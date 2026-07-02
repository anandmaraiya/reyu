"""Legal / compliance document registry (F-A15).

Single source of truth for the versioned legal documents users must
accept. Each document has an integer `version` — bump it whenever the
text materially changes, and every user will be re-prompted to accept
the new version (their prior acceptance is retained for audit, the new
one is recorded fresh).

Acceptance is tracked per (user, doc_type, version) in the
`user_legal_acceptance` table. Two gating groups:

  PLATFORM_DOCS  — must be accepted to use the platform at all
                   (surfaced at signup / first login).
  LIVE_DOCS      — must be accepted before a strategy can be deployed
                   to LIVE (real-money) execution, in addition to the
                   platform docs.

IMPORTANT: The body text below is DRAFT placeholder content. It is NOT
legal advice and MUST be replaced with counsel-reviewed copy before
relying on it. The plumbing (versioning, acceptance records, gating,
audit) is production-ready; the words are not.

Reyu is an AI-powered strategy-automation platform. It does NOT provide
investment advice or portfolio management, does not recommend trades,
and does not claim any strategy is profitable. Users build, test,
approve, and deploy their own trading strategies at their own risk.
"""
from __future__ import annotations

from typing import TypedDict

DRAFT_BANNER = (
    "DRAFT — placeholder text pending legal review. Not legal advice. "
    "Replace with counsel-approved copy before production reliance."
)


class LegalDoc(TypedDict):
    doc_type: str
    version: int
    title: str
    effective_date: str      # ISO date the current version took effect
    summary: str             # one-liner shown in lists / checkboxes
    body: str                # full markdown text of the document


# ── Document registry ───────────────────────────────────────────────
# Bump `version` (and `effective_date`) to force re-acceptance.
LEGAL_DOCS: dict[str, LegalDoc] = {
    "terms_of_use": {
        "doc_type": "terms_of_use",
        "version": 1,
        "title": "Terms of Use",
        "effective_date": "2026-07-01",
        "summary": "The rules for using Reyu as a strategy-automation platform.",
        "body": f"""# Terms of Use

> {DRAFT_BANNER}

## 1. What Reyu is
Reyu is an **AI-powered trading-strategy automation platform**. Reyu lets
you build, backtest, forward-test, approve, and deploy **your own**
trading strategies. Reyu is a software tool, not a broker, not an
exchange, and not a registered investment adviser.

## 2. What Reyu is not
Reyu does **not**:
- provide investment, financial, legal, or tax advice;
- manage your portfolio or exercise discretion over your funds;
- recommend specific trades, securities, or strategies;
- guarantee, predict, or claim that any strategy is or will be profitable;
- rank strategies by performance or represent past results as indicative
  of future results.

All decisions to create, test, approve, or deploy a strategy are **yours
alone**. You are solely responsible for every order that your strategies
place.

## 3. Eligibility
You must be legally eligible to trade Indian exchange-traded derivatives
and to enter into this agreement. You are responsible for complying with
all applicable laws and with your broker's terms.

## 4. Your account
You are responsible for safeguarding your credentials and for all
activity under your account. Notify us immediately of any unauthorised
use.

## 5. Strategies you share or sell
If you publish or sell a strategy, you represent that you have the right
to do so and that its description is accurate and not misleading. You may
**not** claim or imply guaranteed returns. Reyu does not endorse, verify,
or rank the performance of any user-published strategy.

## 6. No warranty
The platform is provided "as is" without warranties of any kind. Market
data may be delayed, incomplete, or inaccurate. Backtests and
forward-tests are hypothetical and have inherent limitations.

## 7. Limitation of liability
To the maximum extent permitted by law, Reyu is not liable for trading
losses or for any indirect, incidental, or consequential damages arising
from your use of the platform.

## 8. Changes
We may update these terms. Material changes require you to re-accept
before continuing to use the platform.
""",
    },
    "risk_disclosure": {
        "doc_type": "risk_disclosure",
        "version": 1,
        "title": "Risk Disclosure & Acknowledgement (SEBI / NSE)",
        "effective_date": "2026-07-01",
        "summary": "Derivatives trading is high-risk. Acknowledge you understand.",
        "body": f"""# Risk Disclosure & Acknowledgement

> {DRAFT_BANNER}

## Trading in derivatives is high-risk
Trading in equity derivatives (futures and options) on Indian exchanges
(NSE / BSE), regulated by SEBI, involves a **high degree of risk** and is
**not suitable for every investor**. You can lose your entire capital,
and losses on short-option and leveraged positions can **exceed** your
initial margin.

## SEBI research findings
SEBI studies have found that the **large majority of individual traders
in the equity F&O segment incur net losses**. Costs (brokerage, taxes,
slippage) further reduce net outcomes.

## Automation-specific risks
Deploying an automated strategy adds risk: software bugs, data outages,
connectivity failures, broker-side rejections, unexpected market
conditions, and rapid compounding of a flawed rule can all cause losses
faster than manual trading. Backtested and forward-tested results are
**hypothetical**, may suffer from overfitting, and **do not guarantee**
future performance.

## Your acknowledgement
By accepting, you confirm that you understand:
1. Derivatives trading is high-risk and you may lose more than you invest.
2. Reyu does not provide investment advice and does not manage your money.
3. No strategy on the platform is represented as profitable.
4. You are solely responsible for your trading decisions and outcomes.
5. You are trading with risk capital you can afford to lose.
""",
    },
    "execution_authorization": {
        "doc_type": "execution_authorization",
        "version": 1,
        "title": "Live Execution Authorization",
        "effective_date": "2026-07-01",
        "summary": "Authorize Reyu to place real orders via your broker when you deploy live.",
        "body": f"""# Live Execution Authorization

> {DRAFT_BANNER}

This authorization is required **only** to deploy a strategy to **LIVE**
(real-money) execution. Paper trading and backtesting do not require it.

## What you are authorizing
When you deploy a strategy to LIVE, you instruct Reyu to transmit orders
generated by **your** strategy to **your** connected broker account on
your behalf, according to the rules **you** configured. You may pause or
halt a live strategy at any time.

## What Reyu does not do
- Reyu does not exercise discretion over your funds or decide what to
  trade — your strategy's rules do.
- Reyu does not add, withdraw, or transfer money in your broker account.
- Reyu does not guarantee order execution, fills, or prices; the broker
  and exchange control execution.

## Your responsibilities
- You are responsible for every live order your strategy places.
- You must maintain sufficient margin and monitor your live strategies.
- You accept the risk that automation, connectivity, or data failures may
  cause unintended orders or missed exits.

## Revocation
This authorization ends when you halt the strategy, disconnect your
broker, or revoke it in Settings. Open positions remain yours to manage.
""",
    },
    "privacy_policy": {
        "doc_type": "privacy_policy",
        "version": 1,
        "title": "Privacy Policy",
        "effective_date": "2026-07-01",
        "summary": "How Reyu collects, uses, and protects your data.",
        "body": f"""# Privacy Policy

> {DRAFT_BANNER}

## What we collect
- Account data (email, display name, tier).
- Usage data (strategies, backtests, chat prompts and AI responses,
  approvals, and orders) — retained as a compliance audit trail.
- Broker connection tokens (stored securely; used only to fetch data and,
  when you deploy live, to place your strategy's orders).

## How we use it
- To operate the platform and your strategies.
- To maintain a detailed, tamper-evident log of prompts, AI responses,
  approvals, and executed orders for compliance and dispute resolution.
- To improve the product. We do not sell your personal data.

## Retention
Compliance and audit records are retained for the period required by
applicable law and regulation.

## Your rights
You may request access to or deletion of your personal data, subject to
records we are legally required to retain.

## Security
We use industry-standard safeguards. No system is perfectly secure; you
share information at your own risk.
""",
    },
}

# Gating groups
PLATFORM_DOCS: list[str] = ["terms_of_use", "risk_disclosure", "privacy_policy"]
LIVE_DOCS: list[str] = ["execution_authorization"]


def current_version(doc_type: str) -> int:
    doc = LEGAL_DOCS.get(doc_type)
    if not doc:
        raise KeyError(f"unknown legal doc: {doc_type}")
    return doc["version"]


def doc_meta(doc_type: str) -> dict:
    """Document metadata without the full body — for list views."""
    d = LEGAL_DOCS[doc_type]
    return {
        "doc_type": d["doc_type"],
        "version": d["version"],
        "title": d["title"],
        "effective_date": d["effective_date"],
        "summary": d["summary"],
    }
