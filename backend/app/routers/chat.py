"""POST /api/chat — conversational interface to the analytics engine.

Endpoints:
  POST /api/chat              Run one turn (with optional session_id for memory)
  GET  /api/chat/tools        List available tools (for transparency / debugging)
  GET  /api/chat/sessions     List active sessions for the current user
  GET  /api/chat/sessions/:id Get full conversation history for a session
  DELETE /api/chat/sessions/:id  Delete a session

Session memory:
  Each session is stored in Redis as a list of {role, content, ts} messages.
  Keys: chat:session:<session_id>
  TTL: 7 days (same as refresh token)
  Index: chat:sessions:<user_id>  (set of active session ids)
"""
from __future__ import annotations

import uuid
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from app.agent import router as intent_router
from app.agent.tools import call_tool, list_tools
from app.agent import llm as agent_llm
from app.routers.user_auth import get_current_user
from app.store import store

router = APIRouter()

SESSION_TTL = 7 * 86400  # 7 days
MAX_HISTORY = 50         # max messages kept per session
MAX_SESSIONS = 20        # max concurrent sessions per user


class ChatMessage(BaseModel):
    role: str           # 'user' | 'assistant'
    content: str


class ChatRequest(BaseModel):
    message: str
    session_id: str | None = None
    history: list[ChatMessage] = []


class ChatResponse(BaseModel):
    session_id: str
    text: str
    tool: str | None = None
    tool_args: dict | None = None
    data: dict | None = None
    chart: str | None = None             # GET URL — embed directly in <img src>
    chart_post: dict | None = None        # POST {url, body} — for payoff (legs in body)
    ts: str


def _session_key(sid: str) -> str:
    return f"chat:session:{sid}"


def _user_sessions_key(uid: str) -> str:
    return f"chat:sessions:{uid}"


async def _save_message(session_id: str, role: str, content: str) -> None:
    """Append a message to the session history in Redis."""
    key = _session_key(session_id)
    msg = {"role": role, "content": content, "ts": datetime.utcnow().isoformat()}
    await store.r.rpush(key, __import__("json").dumps(msg))
    # Trim to MAX_HISTORY
    length = await store.r.llen(key)
    if length > MAX_HISTORY:
        await store.r.ltrim(key, -(MAX_HISTORY), -1)
    # Reset TTL on every write
    await store.r.expire(key, SESSION_TTL)


async def _get_history(session_id: str, limit: int = 20) -> list[dict]:
    """Retrieve recent messages from a session."""
    key = _session_key(session_id)
    raw = await store.r.lrange(key, -limit, -1)
    import json
    return [json.loads(m) for m in raw]


async def _register_session(user_id: str, session_id: str) -> None:
    """Add session to user's active set, evict oldest if over limit."""
    key = _user_sessions_key(user_id)
    await store.r.sadd(key, session_id)
    await store.r.expire(key, SESSION_TTL)
    # Evict oldest sessions if over limit
    members = await store.r.smembers(key)
    if len(members) > MAX_SESSIONS:
        # Remove oldest sessions (we use session id prefix to determine age —
        # session ids are uuid7-like, but we'll just remove arbitrary ones)
        to_remove = list(members)[:len(members) - MAX_SESSIONS]
        for sid in to_remove:
            await store.r.srem(key, sid)
            await store.r.delete(_session_key(sid))


@router.post("", response_model=ChatResponse)
async def chat(req: ChatRequest, user: dict | None = Depends(get_current_user)):
    # Determine user identity for session scoping
    user_id = user.get("sub", "anonymous") if user else "anonymous"

    # Generate or reuse session_id
    sid = req.session_id or str(uuid.uuid4())

    # Save user message to session
    await _save_message(sid, "user", req.message)

    # Build history from Redis if we have a session, else use request history
    if req.session_id:
        redis_history = await _get_history(sid, limit=20)
        # Convert to ChatMessage format for the intent router context
        history_msgs = [ChatMessage(role=m["role"], content=m["content"]) for m in redis_history]
    else:
        history_msgs = req.history

    # Prefer LLM (function-calling) when configured, fall back to regex router
    if agent_llm.is_enabled():
        # Convert recent history into the {role, content} shape the LLM expects
        history_dicts = [{"role": m.role, "content": m.content} for m in history_msgs]
        result = await agent_llm.chat_with_llm(req.message, history=history_dicts, user=user)
        tool_used = "llm"
        tool_args_used: dict | None = None
    else:
        decision = intent_router.route(req.message)
        if "error" in decision:
            error_text = decision["error"]
            await _save_message(sid, "assistant", error_text)
            return ChatResponse(
                session_id=sid,
                text=error_text,
                ts=datetime.utcnow().isoformat(),
            )
        result = await call_tool(decision["tool"], decision["args"], user)
        tool_used = decision["tool"]
        tool_args_used = decision["args"]
    text = result.get("text", "")

    # Save assistant response to session
    await _save_message(sid, "assistant", text)

    # Register session in user's active set (only for authenticated users)
    if user:
        await _register_session(user_id, sid)

    return ChatResponse(
        session_id=sid,
        text=text,
        tool=tool_used,
        tool_args=tool_args_used,
        data=result.get("data"),
        chart=result.get("chart"),
        chart_post=result.get("chart_post"),
        ts=datetime.utcnow().isoformat(),
    )


@router.get("/tools")
async def tools():
    return {"tools": list_tools()}


@router.get("/sessions")
async def list_sessions(user: dict | None = Depends(get_current_user)):
    """List active chat sessions for the current user."""
    if not user:
        raise HTTPException(401, "Authentication required")
    uid = user["sub"]
    key = _user_sessions_key(uid)
    sids = await store.r.smembers(key)
    sessions = []
    for sid in sids:
        history = await _get_history(sid, limit=1)
        if history:
            sessions.append({
                "session_id": sid,
                "last_message": history[-1]["content"][:120],
                "last_ts": history[-1].get("ts"),
                "message_count": await store.r.llen(_session_key(sid)),
            })
    # Sort by last message time descending
    sessions.sort(key=lambda s: s.get("last_ts") or "", reverse=True)
    return {"sessions": sessions}


@router.get("/sessions/{session_id}")
async def get_session(session_id: str, user: dict | None = Depends(get_current_user)):
    """Get full conversation history for a session."""
    if not user:
        raise HTTPException(401, "Authentication required")
    uid = user["sub"]
    key = _user_sessions_key(uid)
    if not await store.r.sismember(key, session_id):
        raise HTTPException(404, "Session not found")
    history = await _get_history(session_id, limit=MAX_HISTORY)
    return {"session_id": session_id, "messages": history}


@router.delete("/sessions/{session_id}")
async def delete_session(session_id: str, user: dict | None = Depends(get_current_user)):
    """Delete a chat session."""
    if not user:
        raise HTTPException(401, "Authentication required")
    uid = user["sub"]
    key = _user_sessions_key(uid)
    if not await store.r.sismember(key, session_id):
        raise HTTPException(404, "Session not found")
    await store.r.srem(key, session_id)
    await store.r.delete(_session_key(session_id))
    return {"ok": True}
