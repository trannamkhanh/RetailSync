"""Settings read from environment variables."""

from pathlib import Path

from pydantic import SecretStr
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


API_PREFIX = "/api/v1"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    model_config.update(env_file=(Path(__file__).resolve().parents[3] / ".env", ".env"))

    hq_url: str = "http://localhost:9000/api/v1"
    sync_interval: int = 3600
    sync_retry_base_seconds: int = 60
    db_host: str = "127.0.0.1"
    sqlserver_port: int = 14333
    db_name: str = "RTS_DB"
    mssql_sa_password: SecretStr | None = None
    test_db_name: str = "RTS_DB_TEST"
    jwt_secret: SecretStr | None = None
    mtls_required: bool = False
    pos_gateway_secret: SecretStr | None = None
    # Longest wait for each single lock on the POS path. A request that meets
    # several held locks can wait longer in total. 0 or -1 would mean no wait
    # or no limit, so only a positive value is accepted.
    pos_lock_timeout_ms: int = Field(default=2000, gt=0)
    scheduler_enabled: bool = False
    business_utc_offset_hours: int = Field(default=7, ge=-12, le=14)


settings = Settings()
