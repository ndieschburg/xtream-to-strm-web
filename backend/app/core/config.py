from pydantic_settings import BaseSettings
from typing import List, Optional

class Settings(BaseSettings):
    PROJECT_NAME: str = "Xtream to STRM"
    VERSION: str = "3.7.0"
    API_V1_STR: str = "/api/v1"
    
    # Database
    DATABASE_URL: str = "sqlite:////db/xtream.db"
    
    # Redis / Celery
    REDIS_URL: str = "redis://localhost:6379/0"
    TIMEZONE: str = "Europe/Paris"
    
    # Xtream Defaults (can be overridden by DB config)
    XC_URL: Optional[str] = None
    XC_USER: Optional[str] = None
    XC_PASS: Optional[str] = None
    
    # Xtream API throttling (see services/xtream.py) - DB setting
    # SYNC_RATE_LIMIT_RPS overrides the rate per install
    XTREAM_RATE_LIMIT_RPS: float = 5.0
    XTREAM_MAX_CONNECTIONS: int = 10
    XTREAM_MAX_RETRIES: int = 4
    XTREAM_BACKOFF_BASE: float = 2.0
    XTREAM_BACKOFF_MAX: float = 60.0

    # Output directories
    OUTPUT_DIR: str = "/output"
    MOVIES_DIR: str = "/output/movies"
    SERIES_DIR: str = "/output/series"

    # Security
    SECRET_KEY: str = "changethis_to_a_secure_random_string_in_production"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24 * 8 # 8 days
    ADMIN_USER: str = "admin"
    ADMIN_PASS: str = "admin"

    # Logging - set to DEBUG to trace HLS segment requests
    LOG_LEVEL: str = "INFO"

    class Config:
        env_file = ".env"

settings = Settings()
