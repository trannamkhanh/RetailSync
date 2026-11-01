"""SQL Server fixtures. No seed data or schema creation is performed here."""

from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.db import database_url, get_db
from app.main import app


@pytest.fixture(scope="session")
def test_engine() -> Generator[Engine, None, None]:
    if settings.test_db_name.casefold() == settings.db_name.casefold():
        pytest.fail("TEST_DB_NAME must differ from DB_NAME; use RTS_DB_TEST.", pytrace=False)
    if not settings.test_db_name.upper().endswith("_TEST"):
        pytest.fail("TEST_DB_NAME must end with _TEST to protect application data.", pytrace=False)
    try:
        engine = create_engine(
            database_url(settings.test_db_name), pool_pre_ping=True,
            connect_args={"timeout": 5}, hide_parameters=True,
        )
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except (SQLAlchemyError, RuntimeError):
        pytest.fail(
            "Cannot connect to SQL Server test database. Start sqlserver, migrate "
            "RTS_DB_TEST, install ODBC Driver 18, and check DB_HOST, SQLSERVER_PORT, "
            "TEST_DB_NAME and MSSQL_SA_PASSWORD. See README.md.", pytrace=False,
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
