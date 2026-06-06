"""Per-underlying linear contextual-bandit policy.

State `x ∈ R^d` (from features.extract).
Actions `a ∈ {LONG=0, SHORT=1, FLAT=2}`.

Score per action:
    s_LONG  = w_long · x_norm  + b_long
    s_SHORT = w_short · x_norm + b_short
    s_FLAT  = 0                    (baseline)

`x_norm = (x - μ) / σ` using EWMA per-feature running stats.

Action distribution: softmax(scores). With probability ε pick uniformly
random (exploration); otherwise sample from softmax.

Update on terminal reward `r`:
    ∇ log π(a|x) = (1_a - π) ⊗ x_norm           (REINFORCE-style)
    w ← w + α · advantage · ∇
where `advantage = r - baseline` and baseline is an EWMA of recent
rewards (variance reduction).

Tiny by design — interpretable, robust at low data, and trivial to inspect.
"""
from __future__ import annotations

import json
import math
import random
from dataclasses import dataclass, field, asdict

from app.rl.features import FEATURE_DIM, FEATURE_NAMES


ACTIONS = ["LONG", "SHORT", "FLAT"]
N_ACTIONS = 3
LR = 0.05
EWMA_ALPHA = 0.05
BASELINE_ALPHA = 0.10
EPSILON_FLOOR = 0.02
EPSILON_DECAY_AFTER = 200


@dataclass
class Policy:
    """Lightweight per-underlying policy. Persists via .to_json / .from_json."""
    w_long: list[float] = field(default_factory=lambda: [0.0] * FEATURE_DIM)
    w_short: list[float] = field(default_factory=lambda: [0.0] * FEATURE_DIM)
    b_long: float = 0.0
    b_short: float = 0.0
    mu: list[float] = field(default_factory=lambda: [0.0] * FEATURE_DIM)
    sigma: list[float] = field(default_factory=lambda: [1.0] * FEATURE_DIM)
    baseline: float = 0.0
    n_updates: int = 0

    # ── serialisation ──────────────────────────────────────────
    def to_json(self) -> str:
        return json.dumps(asdict(self))

    @classmethod
    def from_json(cls, s: str | None) -> "Policy":
        if not s or s == "{}":
            return cls()
        d = json.loads(s)
        d.setdefault("mu", [0.0] * FEATURE_DIM)
        d.setdefault("sigma", [1.0] * FEATURE_DIM)
        # ── Defensive dim repair ─────────────────────────────────
        # FEATURE_DIM grows when we add features. Old persisted
        # weights / normalisation vectors are shorter; pad with
        # zeros (weights) or neutrals (mu=0, sigma=1) so the policy
        # keeps working and starts learning the new dims online.
        # Truncate if the persisted vector is somehow longer.
        def _resize(v: list[float], target: int, fill: float) -> list[float]:
            if len(v) == target:
                return v
            if len(v) > target:
                return v[:target]
            return v + [fill] * (target - len(v))
        d["w_long"] = _resize(d.get("w_long") or [], FEATURE_DIM, 0.0)
        d["w_short"] = _resize(d.get("w_short") or [], FEATURE_DIM, 0.0)
        d["mu"] = _resize(d["mu"], FEATURE_DIM, 0.0)
        d["sigma"] = _resize(d["sigma"], FEATURE_DIM, 1.0)
        return cls(**d)

    # ── normalisation ──────────────────────────────────────────
    def update_running_stats(self, x: list[float]) -> None:
        """EWMA update of running mean + std for input features."""
        for i, v in enumerate(x):
            d = v - self.mu[i]
            self.mu[i] += EWMA_ALPHA * d
            self.sigma[i] = (1 - EWMA_ALPHA) * self.sigma[i] + EWMA_ALPHA * abs(d)
            if self.sigma[i] < 1e-3:
                self.sigma[i] = 1e-3

    def normalise(self, x: list[float]) -> list[float]:
        return [(x[i] - self.mu[i]) / self.sigma[i] for i in range(len(x))]

    # ── scoring ────────────────────────────────────────────────
    def scores(self, x: list[float]) -> tuple[float, float, float]:
        xn = self.normalise(x)
        s_long = self.b_long + sum(self.w_long[i] * xn[i] for i in range(FEATURE_DIM))
        s_short = self.b_short + sum(self.w_short[i] * xn[i] for i in range(FEATURE_DIM))
        return s_long, s_short, 0.0       # FLAT score fixed at 0

    @staticmethod
    def _softmax(scores: tuple[float, float, float]) -> list[float]:
        m = max(scores)
        exps = [math.exp(s - m) for s in scores]
        z = sum(exps)
        return [e / z for e in exps]

    def act(self, x: list[float], epsilon: float,
            min_conviction: float = 0.0) -> tuple[int, float, list[float]]:
        """Returns (action_idx, log π(a|x), probs).

        `min_conviction` ∈ [0, 1] forces FLAT when the winning directional
        action's probability minus FLAT's probability is below the
        threshold. Critical at 1:1 R/R where you need real edge — and
        useful even at asymmetric brackets to skip the low-conviction tail.
        """
        sc = self.scores(x)
        probs = self._softmax(sc)
        exploring = random.random() < epsilon
        if exploring:
            a = random.randrange(N_ACTIONS)
        else:
            r = random.random()
            cum = 0.0; a = N_ACTIONS - 1
            for i, p in enumerate(probs):
                cum += p
                if r <= cum:
                    a = i
                    break
        # Conviction filter — exploitation only. We want exploration to
        # still generate data; gating it would freeze a randomly-initialised
        # policy at FLAT forever (uniform softmax never beats the threshold).
        if not exploring and min_conviction > 0 and a in (0, 1):
            if probs[a] - probs[2] < min_conviction:
                a = 2  # force FLAT
        return a, math.log(max(probs[a], 1e-9)), probs

    # ── learning ───────────────────────────────────────────────
    def update(self, x: list[float], action: int, reward: float,
               lr: float | None = None) -> dict:
        """Single-trade REINFORCE update with EWMA baseline.
        `lr` overrides the module default — used by the hyperparameter
        tuner so we can A/B different rates without mutating the constant."""
        rate = LR if lr is None else lr
        self.n_updates += 1
        self.update_running_stats(x)
        xn = self.normalise(x)
        probs = self._softmax(self.scores(x))
        advantage = reward - self.baseline
        for a in range(N_ACTIONS):
            grad_coef = (1.0 if a == action else 0.0) - probs[a]
            if a == 0:        # LONG
                for i in range(FEATURE_DIM):
                    self.w_long[i] += rate * advantage * grad_coef * xn[i]
                self.b_long += rate * advantage * grad_coef
            elif a == 1:      # SHORT
                for i in range(FEATURE_DIM):
                    self.w_short[i] += rate * advantage * grad_coef * xn[i]
                self.b_short += rate * advantage * grad_coef
            # FLAT has no weights to update — it's the baseline
        self.baseline += BASELINE_ALPHA * (reward - self.baseline)
        return {"advantage": advantage, "baseline": self.baseline, "probs": probs}


def adjusted_epsilon(base_eps: float, n_trades: int) -> float:
    """Linearly decay exploration once a ticker has enough samples."""
    if n_trades < EPSILON_DECAY_AFTER:
        return base_eps
    decay = max(0.0, 1.0 - (n_trades - EPSILON_DECAY_AFTER) / 1000.0)
    return max(EPSILON_FLOOR, base_eps * decay)
