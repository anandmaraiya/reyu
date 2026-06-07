"""Strategy framework — recipes, runs, trades.

Sprint 0 building blocks:
  - `spec.py`: Pydantic models that validate a strategy JSON before it ever
    touches the DB.

Sprint 1+ will add:
  - `conditions.py`: feature-against-conditions evaluator
  - `runner.py`: orchestrates a run through the shared simulator
"""
