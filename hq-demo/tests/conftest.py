"""SQL Server fixtures for the HQ demo tests. Tables come from database/migrate.sh."""

from collections.abc import Generator
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys

import jwt
import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import modes  # noqa: E402
from app.config import settings  # noqa: E402
from app.db import database_url, get_db  # noqa: E402
from app.main import app  # noqa: E402


SECRET = "hq-test-secret-with-enough-length-for-hs256"


@pytest.fixture(autouse=True)
def jwt_secret(monkeypatch) -> None:
    monkeypatch.setattr(settings, "hq_jwt_secret", SecretStr(SECRET))


@pytest.fixture(autouse=True)
def online_mode() -> Generator[None, None, None]:
    modes.reset()
    yield
    modes.reset()


@pytest.fixture(scope="session")
def test_engine() -> Generator[Engine, None, None]:
    if settings.hq_db_name.casefold() == "rts_hq" \
            or not settings.hq_db_name.upper().endswith("_TEST"):
        pytest.fail(
            "HQ_DB_NAME must end with _TEST and differ from RTS_HQ; use RTS_HQ_TEST.",
            pytrace=False,
        )
    try:
        engine = create_engine(
            database_url(settings.hq_db_name), pool_pre_ping=True,
            connect_args={"timeout": 5}, hide_parameters=True,
        )
        with engine.connect() as connection:
            connection.execute(text("SELECT COUNT(*) FROM dbo.hq_sync_batch"))
    except (SQLAlchemyError, RuntimeError):
        pytest.fail(
            "Cannot reach the HQ test database. Start sqlserver and run "
            "docker compose run --rm -e HQ_DB_NAME=RTS_HQ_TEST migrate. "
            "See README.md, section 'HQ demo service'.",
            pytrace=False,
        )
    try:
        yield engine
    finally:
        engine.dispose()


@pytest.fixture
def db_session(test_engine: Engine) -> Generator[Session, None, None]:
    with test_engine.connect() as connection:
        transaction = connection.begin()
        session = Session(bind=connection, join_transaction_mode="create_savepoint")
        try:
            yield session
        finally:
            session.close()
            transaction.rollback()


@pytest.fixture
def client(db_session: Session) -> Generator[TestClient, None, None]:
    def override_get_db() -> Generator[Session, None, None]:
        try:
            yield db_session
        except BaseException:
            db_session.rollback()
            raise

    previous = app.dependency_overrides.copy()
    app.dependency_overrides[get_db] = override_get_db
    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(previous)


@pytest.fixture
def hq_secret() -> str:
    return SECRET


@pytest.fixture
def auth() -> dict[str, str]:
    token = jwt.encode(
        {"sub": "rts-middleware", "role": "MIDDLEWARE",
         "exp": datetime.now(timezone.utc) + timedelta(hours=1)},
        SECRET, algorithm="HS256",
    )
    return {"Authorization": f"Bearer {token}"}
