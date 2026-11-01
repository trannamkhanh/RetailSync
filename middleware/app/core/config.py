"""Settings read from environment variables."""

from pydantic_settings import BaseSettings, SettingsConfigDict


API_PREFIX = "/api/v1"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    hq_url: str = "http://localhost:9000/api/v1"
    sync_interval: int = 3600
    sync_retry_base_seconds: int = 60


settings = Settings()
