from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    USE_KAFKA: bool = False
    KAFKA_BOOTSTRAP: str = "localhost:9092"
    USE_REDIS: bool = False
    REDIS_URL: str = "redis://localhost:6379/0"
    FREEZE_THRESHOLD: float = 0.8
    WINDOW_SECONDS: float = 10.0
    ZSCORE_THRESHOLD: float = 4.0
    NEW_MERCHANT_BURST: int = 3
    MIN_WARMUP_EVENTS: int = 15
    MAX_WINDOW_SECONDS: float = 60.0
    API_PORT: int = 8000
    NUM_AGENTS: int = 6
    ACTIONS_PER_SECOND: float = 5.0

    # Auth
    JWT_SECRET_KEY: str = "sentinel-dev-secret-do-not-use-in-prod"
    JWT_EXPIRE_MINUTES: int = 60
    AUTH_REQUIRED: bool = False  # Set True in production to enforce JWT/API-key

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

settings = Settings()
