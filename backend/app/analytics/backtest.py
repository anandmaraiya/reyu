"""
Strategy backtesting engine.

Backtests option strategy templates against historical data.
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from datetime import datetime, timedelta, date
from typing import Any

import numpy as np

from app.analytics.greeks import bs_price, greeks
from app.analytics.templates import apply_template
from app.analytics.chain import normalize_chain

RISK_FREE = 0.07


@dataclass
class LegSpec:
    symbol: str
    action: str
    strike: float
    option_type: str
    qty: int
    entry_price: float
    lot_size: int = 50
    iv: float = 0.0
    delta: float = 0.0
    theta: float = 0.0


@dataclass
class StrategyTrade:
    template_key: str
    entry_date: date
    expiry_date: date
    underlying: str
    spot_at_entry: float
    legs: list
    exit_date: date = None
    spot_at_exit: float = 0.0
    pnl: float = 0.0
    pnl_pct: float = 0.0
    max_pnl: float = 0.0
    min_pnl: float = 0.0
    entry_cost: float = 0.0
    exit_value: float = 0.0
    status: str = "OPEN"
    daily_pnl: list = field(default_factory=list)


@dataclass
class BacktestResult:
    template_key: str
    underlying: str
    start_date: str
    end_date: str
    spot_at_start: float = 0.0
    spot_at_end: float = 0.0
    trades: list = field(default_factory=list)
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    total_pnl: float = 0.0
    avg_pnl: float = 0.0
    avg_pnl_pct: float = 0.0
    max_drawdown_pct: float = 0.0
    max_drawdown_abs: float = 0.0
    win_rate: float = 0.0
    sharpe_ratio: float = 0.0
    profit_factor: float = 0.0
    avg_trade_duration_days: float = 0.0
    best_trade_pnl: float = 0.0
    worst_trade_pnl: float = 0.0
    equity_curve: list = field(default_factory=list)


def _trading_days(start_date, end_date):
    days = []
    d = start_date
    while d <= end_date:
        if d.weekday() < 5:
            days.append(d)
        d += timedelta(days=1)
    return days


def _nearest_expiry(d, weekly=True):
    if weekly:
        days_ahead = 3 - d.weekday()
        if days_ahead < 0:
            days_ahead += 7
        return d + timedelta(days=days_ahead)
    else:
        next_month = d.replace(day=28) + timedelta(days=4)
        last_day = next_month - timedelta(days=next_month.day)
        days_back = (last_day.weekday() - 3) % 7
        return last_day - timedelta(days=days_back)


def _years_to_expiry(expiry_date, as_of):
    days = (expiry_date - as_of).days
    return max(days / 365.0, 1.0 / 365.0)


def _generate_synthetic_history(symbol, start_date, end_date, base_spot=0):
    r = random.Random(hash(symbol + str(start_date)) & 0xFFFFFFFF)
    spot = base_spot
    if spot <= 0:
        DEMO_SPOTS = {
            "NIFTY": 24800, "NIFTY50": 24800, "BANKNIFTY": 53200,
            "FINNIFTY": 26500, "MIDCPNIFTY": 13200, "SENSEX": 81100,
            "RELIANCE": 1230, "HDFCBANK": 1690, "INFY": 1820,
            "TCS": 4150, "ICICIBANK": 1340,
        }
        for k, v in DEMO_SPOTS.items():
            if k in symbol.upper():
                spot = v
                break
        if spot <= 0:
            spot = 24800
    mu = 0.10 / 252
    sigma = 0.15 / (252 ** 0.5)
    candles = []
    price = spot
    days_list = _trading_days(start_date, end_date)
    for d in days_list:
        z = r.gauss(0, 1)
        open_p = price
        close_p = price * math.exp((mu - 0.5 * sigma**2) + sigma * z)
        high_p = max(open_p, close_p) * (1 + abs(r.gauss(0, 0.003)))
        low_p = min(open_p, close_p) * (1 - abs(r.gauss(0, 0.003)))
        volume = int(r.uniform(2e6, 8e6))
        candles.append({
            "date": d, "open": round(open_p, 2), "high": round(high_p, 2),
            "low": round(low_p, 2), "close": round(close_p, 2), "volume": volume,
        })
        price = close_p
    return candles


def _generate_synthetic_option_chain(symbol, spot, expiry_date, as_of, strikecount=21):
    r = random.Random(hash(symbol + str(as_of) + str(expiry_date)) & 0xFFFFFFFF)
    if "NIFTY50" in symbol or ("NIFTY" in symbol and "BANK" not in symbol):
        spacing = 50
    elif "BANK" in symbol:
        spacing = 100
    else:
        spacing = max(round(spot * 0.005), 1)
    atm = round(spot / spacing) * spacing
    T = _years_to_expiry(expiry_date, as_of)
    atm_iv = 0.12 + r.uniform(-0.02, 0.04)
    rows = []
    half = strikecount // 2
    for i in range(-half, half + 1):
        K = atm + i * spacing
        moneyness = abs(K - spot) / spot
        iv_ce = atm_iv + moneyness * 0.5 + r.uniform(-0.005, 0.005)
        iv_pe = atm_iv + moneyness * 0.45 + r.uniform(-0.005, 0.005)
        ce_price = bs_price(spot, K, T, RISK_FREE, iv_ce, "CE")
        pe_price = bs_price(spot, K, T, RISK_FREE, iv_pe, "PE")
        ce_oi = int(max(r.gauss(80000 - abs(i) * 4000, 15000), 100))
        pe_oi = int(max(r.gauss(85000 - abs(i) * 4500, 15000), 100))
        ce_oich = int(r.gauss(0, 8000))
        pe_oich = int(r.gauss(0, 8000))
        ce_vol = int(max(r.gauss(40000 - abs(i) * 2000, 10000), 0))
        pe_vol = int(max(r.gauss(42000 - abs(i) * 2000, 10000), 0))
        expiry_dt = datetime.combine(expiry_date, datetime.min.time())
        sym_base = symbol.replace("-INDEX","").replace("-EQ","").replace("NSE:","").replace("BSE:","")
        ce_sym = f"{sym_base}{expiry_dt:%y%b}{int(K)}CE".upper()
        pe_sym = f"{sym_base}{expiry_dt:%y%b}{int(K)}PE".upper()
        rows.append({
            "symbol": ce_sym, "strike_price": K, "option_type": "CE",
            "ltp": round(ce_price, 2), "oi": ce_oi, "oich": ce_oich,
            "volume": ce_vol, "iv": round(iv_ce, 4),
        })
        rows.append({
            "symbol": pe_sym, "strike_price": K, "option_type": "PE",
            "ltp": round(pe_price, 2), "oi": pe_oi, "oich": pe_oich,
            "volume": pe_vol, "iv": round(iv_pe, 4),
        })
    return {
        "s": "ok",
        "data": {
            "symbol": symbol, "ltp": spot,
            "expiry": int(datetime.combine(expiry_date, datetime.min.time()).timestamp()),
            "expiryData": [{"date": expiry_date.strftime("%d-%b-%Y")}],
            "optionsChain": rows,
        },
    }


def _compute_leg_pnl_at_spot(leg, spot, T_remaining):
    if T_remaining <= 0:
        if leg.option_type == "CE":
            intrinsic = max(spot - leg.strike, 0)
        else:
            intrinsic = max(leg.strike - spot, 0)
        price_at = intrinsic
    else:
        iv = max(leg.iv, 0.05)
        price_at = bs_price(spot, leg.strike, T_remaining, RISK_FREE, iv, leg.option_type)
    if leg.action == "BUY":
        return (price_at - leg.entry_price) * leg.qty * leg.lot_size
    else:
        return (leg.entry_price - price_at) * leg.qty * leg.lot_size


def _compute_trade_pnl(trade, spot, as_of):
    T_remaining = _years_to_expiry(trade.expiry_date, as_of)
    total = 0.0
    for leg in trade.legs:
        total += _compute_leg_pnl_at_spot(leg, spot, T_remaining)
    return total


def _build_strategy_legs(template_key, chain_payload, lots=1, width_steps=2, wing_steps=2, lot_size=50):
    chain = normalize_chain(chain_payload)
    raw_legs = apply_template(template_key, chain, lots=lots, width_steps=width_steps, wing_steps=wing_steps)
    specs = []
    for rl in raw_legs:
        specs.append(LegSpec(
            symbol=rl["symbol"], action=rl["action"], strike=rl["strike"],
            option_type=rl["option_type"], qty=rl["qty"], entry_price=rl["price"],
            lot_size=lot_size,
        ))
    return specs


def _parse_fyers_history(hist):
    candles_raw = hist.get("candles", [])
    out = []
    for c in candles_raw:
        if len(c) >= 6:
            ts = datetime.fromtimestamp(c[0]).date()
            out.append({
                "date": ts, "open": c[1], "high": c[2],
                "low": c[3], "close": c[4], "volume": c[5],
            })
    return out
async def run_backtest(
    template_key, underlying, start_date, end_date,
    lots=1, width_steps=2, wing_steps=2, strikecount=21, lot_size=50,
    fyers_history_fn=None, fyers_chain_fn=None, is_demo=True,
):
    result = BacktestResult(
        template_key=template_key, underlying=underlying,
        start_date=start_date.isoformat(), end_date=end_date.isoformat(),
    )

    if is_demo or fyers_history_fn is None:
        candles = _generate_synthetic_history(underlying, start_date, end_date)
    else:
        try:
            hist = await fyers_history_fn(
                underlying, "1D",
                start_date.strftime("%Y-%m-%d"),
                end_date.strftime("%Y-%m-%d"),
            )
            candles = _parse_fyers_history(hist)
        except Exception:
            candles = _generate_synthetic_history(underlying, start_date, end_date)

    if not candles:
        return result

    spot_map = {c["date"]: c["close"] for c in candles}
    result.spot_at_start = candles[0]["close"]
    result.spot_at_end = candles[-1]["close"]

    trading_days_list = _trading_days(start_date, end_date)
    entry_dates = []
    current_week = None
    for d in trading_days_list:
        week = d.isocalendar()[1]
        if week != current_week:
            current_week = week
            entry_dates.append(d)

    trades = []
    for entry_date in entry_dates:
        spot = spot_map.get(entry_date)
        if not spot:
            continue

        expiry_date = _nearest_expiry(entry_date + timedelta(days=1), weekly=True)
        if expiry_date > end_date:
            expiry_date = _nearest_expiry(end_date, weekly=False)

        if is_demo or fyers_chain_fn is None:
            chain_payload = _generate_synthetic_option_chain(
                underlying, spot, expiry_date, entry_date, strikecount
            )
        else:
            try:
                chain_payload = await fyers_chain_fn(underlying, strikecount)
            except Exception:
                chain_payload = _generate_synthetic_option_chain(
                    underlying, spot, expiry_date, entry_date, strikecount
                )

        try:
            legs = _build_strategy_legs(
                template_key, chain_payload, lots=lots,
                width_steps=width_steps, wing_steps=wing_steps, lot_size=lot_size,
            )
        except Exception:
            continue

        if not legs:
            continue

        T = _years_to_expiry(expiry_date, entry_date)
        for leg in legs:
            try:
                g = greeks(spot, leg.strike, T, RISK_FREE, max(leg.iv, 0.15), leg.option_type)
                leg.iv = g.iv or 0.15
                leg.delta = g.delta
                leg.theta = g.theta
            except Exception:
                leg.iv = 0.15

        entry_cost = sum(
            (leg.entry_price * leg.qty * leg.lot_size) if leg.action == "BUY"
            else (-leg.entry_price * leg.qty * leg.lot_size)
            for leg in legs
        )

        trade = StrategyTrade(
            template_key=template_key, entry_date=entry_date, expiry_date=expiry_date,
            underlying=underlying, spot_at_entry=spot, legs=legs, entry_cost=entry_cost,
        )

        daily_pnl = []
        max_pnl = 0.0
        min_pnl = 0.0
        exit_spot = spot
        exit_date = entry_date

        for d in trading_days_list:
            if d <= entry_date:
                continue
            if d > expiry_date:
                break
            day_spot = spot_map.get(d)
            if not day_spot:
                continue
            T_rem = _years_to_expiry(expiry_date, d)
            day_pnl = _compute_trade_pnl(trade, day_spot, d)
            daily_pnl.append({"date": d.isoformat(), "pnl": round(day_pnl, 2), "spot": day_spot})
            if day_pnl > max_pnl:
                max_pnl = day_pnl
            if day_pnl < min_pnl:
                min_pnl = day_pnl
            exit_date = d
            exit_spot = day_spot

        expiry_spot = spot_map.get(expiry_date)
        if expiry_spot is None:
            for d in reversed(trading_days_list):
                if d <= expiry_date and d in spot_map:
                    expiry_spot = spot_map[d]
                    break
        if expiry_spot is None:
            expiry_spot = exit_spot

        final_pnl = _compute_trade_pnl(trade, expiry_spot, expiry_date)
        trade.exit_date = min(expiry_date, exit_date)
        trade.spot_at_exit = expiry_spot
        trade.pnl = round(final_pnl, 2)
        trade.max_pnl = round(max(max_pnl, final_pnl), 2)
        trade.min_pnl = round(min(min_pnl, final_pnl), 2)
        trade.daily_pnl = daily_pnl
        trade.status = "EXPIRED"

        if entry_cost > 0:
            trade.pnl_pct = round((final_pnl / entry_cost) * 100, 2)
        elif entry_cost < 0:
            trade.pnl_pct = round((final_pnl / abs(entry_cost)) * 100, 2)
        else:
            trade.pnl_pct = 0.0

        trade.exit_value = entry_cost + final_pnl if entry_cost > 0 else final_pnl - abs(entry_cost)
        trades.append(trade)

    result.trades = trades
    result.total_trades = len(trades)

    if not trades:
        return result

    pnls = [t.pnl for t in trades]
    pnls_pct = [t.pnl_pct for t in trades]

    result.total_pnl = round(sum(pnls), 2)
    result.avg_pnl = round(sum(pnls) / len(pnls), 2)
    result.avg_pnl_pct = round(sum(pnls_pct) / len(pnls_pct), 2)
    result.winning_trades = sum(1 for p in pnls if p > 0)
    result.losing_trades = sum(1 for p in pnls if p <= 0)
    result.win_rate = round(result.winning_trades / len(pnls) * 100, 1) if pnls else 0
    result.best_trade_pnl = round(max(pnls), 2)
    result.worst_trade_pnl = round(min(pnls), 2)

    gross_profit = sum(p for p in pnls if p > 0)
    gross_loss = abs(sum(p for p in pnls if p < 0))
    result.profit_factor = round(gross_profit / gross_loss, 2) if gross_loss > 0 else 0.0

    durations = []
    for t in trades:
        if t.exit_date and t.entry_date:
            durations.append((t.exit_date - t.entry_date).days)
    result.avg_trade_duration_days = round(sum(durations) / len(durations), 1) if durations else 0

    equity = 0.0
    equity_curve = []
    for t in trades:
        equity += t.pnl
        equity_curve.append({
            "date": t.exit_date.isoformat() if t.exit_date else t.entry_date.isoformat(),
            "equity": round(equity, 2), "pnl": t.pnl, "spot": t.spot_at_exit,
            "trade_num": len(equity_curve) + 1,
        })
    result.equity_curve = equity_curve

    peak = 0.0
    max_dd = 0.0
    max_dd_abs = 0.0
    running = 0.0
    for t in trades:
        running += t.pnl
        if running > peak:
            peak = running
        dd = peak - running
        if dd > max_dd_abs:
            max_dd_abs = dd
            max_dd = (dd / peak * 100) if peak > 0 else 0
    result.max_drawdown_pct = round(max_dd, 2)
    result.max_drawdown_abs = round(max_dd_abs, 2)

    if len(pnls) >= 2:
        returns = np.array(pnls)
        std = np.std(returns)
        if std > 0:
            sharpe = (np.mean(returns) / std) * math.sqrt(252 / max(result.avg_trade_duration_days, 1))
            result.sharpe_ratio = round(float(sharpe), 2)
        else:
            result.sharpe_ratio = 0.0

    return result


def serialize_result(result):
    return {
        "template_key": result.template_key,
        "underlying": result.underlying,
        "start_date": result.start_date,
        "end_date": result.end_date,
        "spot_at_start": result.spot_at_start,
        "spot_at_end": result.spot_at_end,
        "trades": [
            {
                "template_key": t.template_key,
                "entry_date": t.entry_date.isoformat(),
                "expiry_date": t.expiry_date.isoformat(),
                "exit_date": t.exit_date.isoformat() if t.exit_date else None,
                "underlying": t.underlying,
                "spot_at_entry": t.spot_at_entry,
                "spot_at_exit": t.spot_at_exit,
                "pnl": t.pnl, "pnl_pct": t.pnl_pct,
                "max_pnl": t.max_pnl, "min_pnl": t.min_pnl,
                "entry_cost": t.entry_cost, "exit_value": t.exit_value,
                "status": t.status,
                "legs": [
                    {
                        "symbol": l.symbol, "action": l.action, "strike": l.strike,
                        "option_type": l.option_type, "qty": l.qty,
                        "entry_price": l.entry_price, "lot_size": l.lot_size,
                        "iv": round(l.iv, 4), "delta": round(l.delta, 4),
                    }
                    for l in t.legs
                ],
                "daily_pnl": t.daily_pnl,
            }
            for t in result.trades
        ],
        "metrics": {
            "total_trades": result.total_trades,
            "winning_trades": result.winning_trades,
            "losing_trades": result.losing_trades,
            "total_pnl": result.total_pnl,
            "avg_pnl": result.avg_pnl,
            "avg_pnl_pct": result.avg_pnl_pct,
            "max_drawdown_pct": result.max_drawdown_pct,
            "max_drawdown_abs": result.max_drawdown_abs,
            "win_rate": result.win_rate,
            "sharpe_ratio": result.sharpe_ratio,
            "profit_factor": result.profit_factor,
            "avg_trade_duration_days": result.avg_trade_duration_days,
            "best_trade_pnl": result.best_trade_pnl,
            "worst_trade_pnl": result.worst_trade_pnl,
        },
        "equity_curve": result.equity_curve,
    }
