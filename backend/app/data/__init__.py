"""Data-lake layer — historical sources for strategy backtests + RL training.

L1 forward intraday  → option_strike_snapshot (scheduler-fed, 2026-06-06+)
L2 historical EOD    → option_eod (NSE F&O Bhavcopy ingester, this module)
L3 paid intraday     → reserved slot, not implemented
L4 BS-synthesized    → fallback, tagged as such in run data_quality

Use `app/fyers/cache.py` (Sprint 0.2b) to route reads through priority.
"""
