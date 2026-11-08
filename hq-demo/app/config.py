"""Settings read from environment variables."""

from pathlib import Path

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    model_config.update(env_file=(Path(__file__).resolve().parents[2] / ".env", ".env"))

    hq_db_name: str = "RTS_HQ"
    db_host: str = "127.0.0.1"
    sqlserver_port: int = 14333
    mssql_sa_password: SecretStr | None = None
    # HS256 key the middleware signs its service token with; the same value in .env.
    hq_jwt_secret: SecretStr | None = None


settings = Settings()
