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

    # Razorpay billing
    razorpay_key_id: str = ""
    razorpay_key_secret: str = ""
    razorpay_webhook_secret: str = ""
    razorpay_plan_pro_monthly: str = ""   # Razorpay plan ID for Pro monthly
    razorpay_plan_pro_yearly: str = ""    # Razorpay plan ID for Pro yearly
    razorpay_plan_algo_monthly: str = ""  # Razorpay plan ID for Algo monthly
    razorpay_plan_algo_yearly: str = ""   # Razorpay plan ID for Algo yearly
    razorpay_callback_url: str = "http://localhost:5173/subscription"

    # OpenRouter LLM (used by the chat agent when set; otherwise the regex
    # router takes over). Get a key at https://openrouter.ai/keys
    openrouter_api_key: str = ""
    openrouter_model: str = "anthropic/claude-3.5-haiku"
    openrouter_referer: str = "https://reyu.ai"      # OpenRouter requires HTTP-Referer
    openrouter_app_name: str = "Reyu.ai Options Co-pilot"

    class Config:
        env_file = ".env"
        case_sensitive = False


settings = Settings()
