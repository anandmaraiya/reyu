from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    fyers_app_id: str = ""
    fyers_secret_key: str = ""
    fyers_redirect_uri: str = "http://localhost:8000/api/auth/callback"
    jwt_secret: str = "dev-secret"
    redis_url: str = "redis://redis:6379/0"
    database_url: str = "postgresql+asyncpg://reyu:reyu@postgres:5432/reyu"
    data_dir: str = "/app/data"
    risk_per_trade_pct: float = 1.0
    portfolio_max_delta: float = 500
    portfolio_max_vega: float = 2000
    tracked_symbols: str = "NSE:NIFTY50-INDEX,NSE:NIFTYBANK-INDEX"
    snapshot_interval_sec: int = 60

    class Config:
        env_file = ".env"
        case_sensitive = False


settings = Settings()
