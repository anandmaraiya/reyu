from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    fyers_app_id: str = ""
    fyers_secret_key: str = ""
    fyers_redirect_uri: str = "http://localhost:8000/api/auth/callback"
    base_url: str = "http://localhost:8000"
    jwt_secret: str = "dev-secret"
    redis_url: str = "redis://redis:6379"
    database_url: str = "postgresql+asyncpg://reyu:reyu@postgres:5432/reyu"
    data_dir: str = "/app/data"
    risk_per_trade_pct: float = 1.0
    portfolio_max_delta: float = 500
    portfolio_max_vega: float = 2000
    tracked_symbols: str = "NSE:NIFTY50-INDEX,NSE:NIFTYBANK-INDEX"
    snapshot_interval_sec: int = 60
    # Comma-separated list of allowed CORS origins. Override per-deployment
    # in .env, e.g. CORS_ORIGINS=http://34.93.12.45:5173,https://reyu.example.com
    cors_origins: str = "http://localhost:5173,http://localhost:3000"

    # SEBI retail-algo framework (F-B1). When True, LIVE promotion
    # requires an exchange-REGISTERED algo ID for the strategy. Default
    # off until the broker-side registration process is confirmed with
    # Fyers + counsel — the rails exist so flipping this is a one-line
    # .env change, not a retrofit.
    enforce_algo_registration: bool = False

    # Razorpay billing
    razorpay_key_id: str = ""
    razorpay_key_secret: str = ""
    razorpay_webhook_secret: str = ""
    razorpay_plan_pro_monthly: str = ""   # Razorpay plan ID for Pro monthly
    razorpay_plan_pro_yearly: str = ""    # Razorpay plan ID for Pro yearly
    razorpay_plan_algo_monthly: str = ""  # Razorpay plan ID for Algo monthly
    razorpay_plan_algo_yearly: str = ""   # Razorpay plan ID for Algo yearly
    razorpay_callback_url: str = "http://localhost:5173/subscription"

    # LLM providers — preference order at call time:
    #   1. ANTHROPIC_API_KEY (direct Claude API, cleanest + cheapest)
    #   2. OPENROUTER_API_KEY (routes to Claude/GPT/etc.)
    #   3. Regex intent router (no LLM required)
    # Get a Claude key at https://console.anthropic.com/settings/keys
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-opus-4-7"
    # OpenRouter — fallback / multi-provider gateway
    openrouter_api_key: str = ""
    openrouter_model: str = "anthropic/claude-3.5-haiku"
    openrouter_referer: str = "https://reyu.ai"      # OpenRouter requires HTTP-Referer
    openrouter_app_name: str = "Reyu.ai Options Co-pilot"

    # Resend transactional email — https://resend.com/api-keys
    # Used for password reset, onboarding welcome, TP/SL notifications.
    resend_api_key: str = ""
    resend_from_email: str = "Reyu <no-reply@reyu.ai>"
    frontend_url: str = "http://localhost:5173"     # base for links in emails

    # PostHog analytics — https://posthog.com/project/settings
    # Used server-side for critical events (login, upgrade, order).
    # Frontend also uses this key (public write-only).
    posthog_api_key: str = ""
    posthog_host: str = "https://us.i.posthog.com"

    # Zerodha Kite Connect — https://developers.kite.trade
    # Kite uses per-day access tokens (~06:00 IST expiry). Users re-auth
    # daily; scheduler + auto-backfill patterns from Fyers apply.
    zerodha_api_key: str = ""
    zerodha_api_secret: str = ""
    zerodha_redirect_uri: str = "http://localhost:8000/api/brokers/zerodha/callback"

    class Config:
        env_file = ".env"
        case_sensitive = False


settings = Settings()
