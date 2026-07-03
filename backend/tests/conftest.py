"""Shared test config (F-B4 money-path suite).

These tests target PURE LOGIC in the money path — spec validation,
condition evaluation, feature computation, friction/metrics math, token
derivation. No DB, no Redis, no broker: anything needing infra belongs in
tests/integration/ (gated by the CI docker services).
"""
import os
import warnings

# Deterministic secrets/URLs so imports of app.config never depend on a
# developer's .env. Set BEFORE any app import.
os.environ.setdefault("JWT_SECRET", "test-secret-for-unit-tests")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://reyu:reyu@localhost:5432/reyu")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379")

warnings.filterwarnings("ignore")
