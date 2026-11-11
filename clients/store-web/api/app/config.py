"""Settings for the read-only store web API.

The repository root is found by walking up to the directory that holds
``compose.yaml`` (the same idea as ``clients/demo-pos``). Counting
``Path.parents`` does not work here: ``app/config.py`` sits deeper than
``middleware/app/core/config.py``, so a fixed index would read the wrong
``.env`` and silently fall back to a default database name.
"""

from functools import lru_cache
from pathlib import Path

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


def repo_root() -> Path:
    """Nearest ancestor holding ``compose.yaml``."""
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "compose.yaml").is_file():
            return parent
    raise RuntimeError(
        "Repository root not found: no compose.yaml above clients/store-web/api/app/config.py."
    )


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(repo_root() / ".env", ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    store_web_db_name: str | None = None
    store_web_test_db_name: str = "RTS_WEB_TEST"
    store_web_cors_origins: str = ""

    # Road distance between the customer and a store. The public OSRM demo server
    # answers without a key; an empty value turns routing off and the API falls
    # back to the straight-line haversine distance.
    store_web_osrm_url: str = "https://router.project-osrm.org"
    store_web_osrm_timeout_seconds: float = Field(default=2.0, gt=0, le=15)

    # The customer tier owns its own database, so the store database stays read-only.
    store_web_customer_db_name: str = "RTS_CUSTOMER"
    store_web_test_customer_db_name: str = "RTS_CUSTOMER_TEST"
    store_web_session_hours: int = Field(default=24 * 7, ge=1, le=24 * 30)

    db_name: str = "RTS_DB"
    db_host: str = "127.0.0.1"
    sqlserver_port: int = 14333
    mssql_sa_password: SecretStr | None = None
    business_utc_offset_hours: int = Field(default=7, ge=-12, le=14)

    @property
    def database_name(self) -> str:
        """The database this app reads: ``STORE_WEB_DB_NAME`` or ``DB_NAME``."""
        return self.store_web_db_name or self.db_name

    @property
    def customer_database_name(self) -> str:
        """The database that owns customer accounts and sessions."""
        return self.store_web_customer_db_name

    @property
    def cors_origins(self) -> list[str]:
        """Origins allowed in development, split on commas, empties dropped."""
        return [part.strip() for part in self.store_web_cors_origins.split(",") if part.strip()]

    @property
    def osrm_url(self) -> str:
        """Routing base URL without a trailing slash; empty disables routing."""
        return self.store_web_osrm_url.strip().rstrip("/")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
