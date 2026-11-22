"""Settings read from environment variables."""

from pathlib import Path

from pydantic import SecretStr
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


API_PREFIX = "/api/v1"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    model_config.update(env_file=(Path(__file__).resolve().parents[3] / ".env", ".env"))

    hq_url: str = "http://localhost:9000/api/v1"
    sync_interval: int = 3600
    sync_retry_base_seconds: int = 60
    # DS-05 section 6: sync-send runs every min(sync_interval, this), so retries go out on time.
    sync_send_poll_seconds: int = Field(default=30, ge=5, le=3600)
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
    hq_ca_file: str | None = None
    hq_jwt_secret: SecretStr | None = None
    hq_timeout_seconds: float = Field(default=3, gt=0)
    # The alert window of a product category that has no near_expiry_config row.
    near_expiry_default_days: int = Field(default=3, ge=0, le=3650)

    @field_validator("pos_gateway_secret")
    @classmethod
    def _gateway_secret_fits_nginx(cls, value: SecretStr | None) -> SecretStr | None:
        # pos-gateway pastes the secret inside "..." in its nginx config (deploy/nginx/pos-gateway.conf.template).
        if value is not None and any(c in '$"\\;' or c.isspace() for c in value.get_secret_value()):
            raise ValueError('POS_GATEWAY_SECRET must not contain $, ", \\, ; or whitespace; use a hex value.')
        return value


settings = Settings()
