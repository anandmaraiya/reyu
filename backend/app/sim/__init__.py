"""Shared simulation engine — Sprint 1.

Both the RL bandit and user-defined strategies decide trades through the
same engine. The only thing that differs is the `decide` callable.

  `engine.simulate_session(candles, decide_fn, ...)` returns a list of
      structured trade dicts; the caller plugs in either a bandit
      `Policy` wrapped as a decider or a condition evaluator.

  `engine.compute_roi(trades, lot_size, ...)` is the unchanged
      capital-sequencing math, now with realistic slippage + tax
      friction so backtest ROI no longer needs the "halve it for
      reality" caveat.
"""
