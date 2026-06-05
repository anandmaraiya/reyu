"""Server-side chart rendering using matplotlib's Agg backend.

Returns PNG bytes that callers can:
  - serve directly via FastAPI Response(media_type='image/png', content=...)
  - attach to Telegram / WhatsApp / Discord as a photo upload

The dark palette mirrors the web dashboard so the same look carries into
chat replies and screenshots. All charts are 16:9 at 1200x675 (well above
retina + Telegram preview cropping).
"""
from __future__ import annotations

import io
from typing import Any

import matplotlib
matplotlib.use("Agg")          # headless — no GUI backend
import matplotlib.pyplot as plt  # noqa: E402

# ── Dark palette matching the web UI ─────────────────────────
PALETTE = {
    "bg":     "#0a0e17",
    "panel":  "#111827",
    "grid":   "#1f2937",
    "text":   "#e5e7eb",
    "muted":  "#94a3b8",
    "green":  "#16a34a",
    "red":    "#dc2626",
    "amber":  "#f59e0b",
    "accent": "#60a5fa",
}

# Default rcParams: dark, antialiased, generous font
plt.rcParams.update({
    "figure.facecolor": PALETTE["bg"],
    "axes.facecolor":   PALETTE["panel"],
    "axes.edgecolor":   PALETTE["grid"],
    "axes.labelcolor":  PALETTE["muted"],
    "axes.titlecolor":  PALETTE["text"],
    "xtick.color":      PALETTE["muted"],
    "ytick.color":      PALETTE["muted"],
    "text.color":       PALETTE["text"],
    "grid.color":       PALETTE["grid"],
    "grid.linestyle":   "--",
    "grid.alpha":       0.6,
    "font.family":      "DejaVu Sans",   # Inter isn't installed in the container
    "font.size":        11,
    "savefig.facecolor": PALETTE["bg"],
    "savefig.edgecolor": "none",
})


def _save(fig) -> bytes:
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=110, bbox_inches="tight", pad_inches=0.3)
    plt.close(fig)
    return buf.getvalue()


# ── Chart 1: payoff @ expiry ─────────────────────────────────
def render_payoff(payoff: dict, title: str = "Payoff @ expiry") -> bytes:
    """payoff = result of analytics.payoff.compute()"""
    fig, ax = plt.subplots(figsize=(11, 5.5))
    pts = payoff["points"]
    xs = [p["S"] for p in pts]
    ys = [p["pnl"] for p in pts]

    ax.fill_between(xs, ys, 0, where=[y >= 0 for y in ys], color=PALETTE["green"], alpha=0.25)
    ax.fill_between(xs, ys, 0, where=[y < 0 for y in ys], color=PALETTE["red"], alpha=0.25)
    ax.plot(xs, ys, color=PALETTE["text"], linewidth=2.0)

    ax.axhline(0, color=PALETTE["muted"], linewidth=0.8, linestyle=":")
    ax.axvline(payoff["spot"], color=PALETTE["accent"], linewidth=1.0, linestyle="--",
               label=f"Spot {payoff['spot']:,.0f}")
    for be in payoff.get("breakevens", []):
        ax.axvline(be, color=PALETTE["amber"], linewidth=0.8, linestyle="--", alpha=0.7)
        ax.text(be, max(ys) * 0.95, f"BE {be:,.0f}", color=PALETTE["amber"],
                fontsize=9, ha="center", va="top")

    ax.set_title(title, fontsize=14, fontweight="bold", pad=12, loc="left")
    ax.set_xlabel("Underlying price")
    ax.set_ylabel("P&L (₹)")
    ax.grid(True, alpha=0.4)
    ax.legend(loc="upper left", frameon=False, fontsize=10)

    # Annotation: max profit / loss
    txt = (f"Max profit ₹{payoff['max_profit']:,.0f}    "
           f"Max loss ₹{payoff['max_loss']:,.0f}    "
           f"Net {'debit' if payoff['net_debit'] >= 0 else 'credit'} "
           f"₹{abs(payoff['net_debit']):,.0f}")
    fig.text(0.5, 0.02, txt, ha="center", color=PALETTE["muted"], fontsize=10)

    return _save(fig)


# ── Chart 2: OI distribution (CE vs PE bars per strike) ─────
def render_oi_distribution(strikes: list[dict], spot: float, max_pain: float | None,
                           atm: float | None, title: str = "OI distribution") -> bytes:
    """strikes = list of {strike, ce:{oi}, pe:{oi}}"""
    fig, ax = plt.subplots(figsize=(11, 5.5))
    xs = [s["strike"] for s in strikes]
    ce = [(s.get("ce") or {}).get("oi", 0) for s in strikes]
    pe = [(s.get("pe") or {}).get("oi", 0) for s in strikes]
    width = (xs[1] - xs[0]) * 0.4 if len(xs) > 1 else 25

    ax.bar([x - width / 2 for x in xs], ce, width=width, color=PALETTE["red"],   label="CE OI", alpha=0.85)
    ax.bar([x + width / 2 for x in xs], pe, width=width, color=PALETTE["green"], label="PE OI", alpha=0.85)

    if atm:
        ax.axvline(atm, color=PALETTE["accent"], linewidth=1.2, linestyle="--", label=f"ATM {atm:,.0f}")
    if max_pain:
        ax.axvline(max_pain, color=PALETTE["amber"], linewidth=1.0, linestyle=":",
                   label=f"Max-Pain {max_pain:,.0f}")

    ax.set_title(title, fontsize=14, fontweight="bold", pad=12, loc="left")
    ax.set_xlabel("Strike")
    ax.set_ylabel("Open interest (contracts)")
    ax.grid(True, alpha=0.4, axis="y")
    ax.legend(loc="upper right", frameon=False, fontsize=10)

    # K-format y axis
    ax.yaxis.set_major_formatter(plt.FuncFormatter(
        lambda v, _: f"{v/1_000_000:.1f}M" if abs(v) >= 1e6 else f"{v/1_000:.0f}k" if abs(v) >= 1_000 else f"{v:.0f}"
    ))
    return _save(fig)


# ── Chart 3: PCR / OI time-series ────────────────────────────
def render_pcr_timeseries(rows: list[dict], title: str = "PCR & OI delta — today's session") -> bytes:
    """rows = output of /api/ts/snapshots (each has ts, pcr_oi, ce_oi_delta, pe_oi_delta, ltp)"""
    if not rows:
        # Empty-state chart
        fig, ax = plt.subplots(figsize=(11, 5))
        ax.text(0.5, 0.5, "No intraday snapshots yet for this symbol.",
                ha="center", va="center", color=PALETTE["muted"], fontsize=12,
                transform=ax.transAxes)
        ax.set_xticks([]); ax.set_yticks([])
        return _save(fig)

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(11, 6), sharex=True,
                                    gridspec_kw={"height_ratios": [1, 1], "hspace": 0.15})
    ts = list(range(len(rows)))
    labels = [r["ts"][11:16] for r in rows]

    # Top: PCR line + 1.0 reference + spot on twin axis
    ax1.plot(ts, [r["pcr_oi"] for r in rows], color=PALETTE["accent"], linewidth=2, label="PCR (OI)")
    ax1.axhline(1.0, color=PALETTE["muted"], linewidth=0.8, linestyle=":")
    ax1.set_ylabel("PCR")
    ax1.grid(True, alpha=0.4)
    ax1.legend(loc="upper left", frameon=False, fontsize=9)
    ax1b = ax1.twinx()
    ax1b.plot(ts, [r["ltp"] for r in rows], color=PALETTE["muted"], linewidth=1.2,
              linestyle="--", alpha=0.6, label="Spot")
    ax1b.set_ylabel("Spot", color=PALETTE["muted"])

    # Bottom: ΔOI bars CE vs PE
    width = 0.4
    ax2.bar([t - width/2 for t in ts], [r["ce_oi_delta"] for r in rows], width=width, color=PALETTE["red"], label="CE ΔOI")
    ax2.bar([t + width/2 for t in ts], [r["pe_oi_delta"] for r in rows], width=width, color=PALETTE["green"], label="PE ΔOI")
    ax2.axhline(0, color=PALETTE["muted"], linewidth=0.7)
    ax2.set_ylabel("ΔOI per bucket")
    ax2.grid(True, alpha=0.4, axis="y")
    ax2.legend(loc="upper left", frameon=False, fontsize=9)

    # Tick spacing: show every Nth bucket label
    step = max(len(ts) // 12, 1)
    ax2.set_xticks(ts[::step])
    ax2.set_xticklabels(labels[::step], rotation=45, ha="right")

    fig.suptitle(title, fontsize=14, fontweight="bold", x=0.07, y=0.97, ha="left")
    return _save(fig)
