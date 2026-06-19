"""
Seed test users for browser testing.
Run: cd backend && python seed_test_users.py

Creates:
  anon  - no account (just use the app without logging in)
  free@reyu.ai / Test1234! - free tier (15-day trial)
  paid@reyu.ai / Test1234! - paid tier
  algo@reyu.ai / Test1234! - algo tier
"""
import asyncio
import sys
sys.path.insert(0, ".")

from passlib.context import CryptContext
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy import select
from app.db import User, Base
from app.config import settings
from datetime import datetime, timedelta

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

TEST_USERS = [
    {"email": "free@reyu.ai",  "display_name": "Free Trader",  "tier": "free",  "trial_days": 15},
    {"email": "paid@reyu.ai",  "display_name": "Pro Trader",   "tier": "paid",  "trial_days": None},
    {"email": "algo@reyu.ai",  "display_name": "Algo Trader",  "tier": "algo",  "trial_days": None},
]

PASSWORD = "Test1234!"

async def seed():
    engine = create_async_engine(settings.database_url.replace("postgresql://", "postgresql+asyncpg://"), echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    Session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    hashed = pwd_context.hash(PASSWORD)

    async with Session() as sess:
        for u in TEST_USERS:
            existing = (await sess.execute(select(User).where(User.email == u["email"]))).scalar_one_or_none()
            if existing:
                existing.tier = u["tier"]
                if u["trial_days"]:
                    existing.trial_expires_at = datetime.utcnow() + timedelta(days=u["trial_days"])
                print(f"  Updated: {u['email']} → tier={u['tier']}")
            else:
                user = User(
                    email=u["email"],
                    display_name=u["display_name"],
                    hashed_password=hashed,
                    tier=u["tier"],
                    trial_expires_at=datetime.utcnow() + timedelta(days=u["trial_days"]) if u["trial_days"] else None,
                )
                sess.add(user)
                print(f"  Created: {u['email']} → tier={u['tier']}")
        await sess.commit()
    
    print("\n✓ Done. Test accounts:")
    print(f"  Anonymous : just browse — no login needed")
    for u in TEST_USERS:
        print(f"  {u['email']} / {PASSWORD}  [{u['tier']}]")

asyncio.run(seed())
