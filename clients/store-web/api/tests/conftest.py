"""SQL Server fixtures for the store web API.

The test database is ``STORE_WEB_TEST_DB_NAME`` (``RTS_WEB_TEST`` by default),
never the team's ``RTS_DB_TEST`` and never the application database. The guard
below fails hard rather than skipping, so a misconfigured run cannot write to
application data.
"""

from collections.abc import Generator
from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app import clock
from app.config import settings
from app.customer_db import ensure_database, ensure_schema, get_customer_db
from app.db import database_url, get_db
from app.main import app

FIXED_TODAY = date(2026, 11, 10)


@pytest.fixture(autouse=True)
def offline_routing(monkeypatch: pytest.MonkeyPatch) -> None:
    """The suite never talks to a routing server.

    Pointing at a closed port makes every search take the straight-line fallback,
    which is the documented degraded path. Tests that need road answers use
    ``httpx.MockTransport`` against ``app.routing`` directly.
    """
    monkeypatch.setattr(settings, "store_web_osrm_url", "http://127.0.0.1:1")
    monkeypatch.setattr(settings, "store_web_osrm_timeout_seconds", 0.2)


def _guard() -> None:
    name = settings.store_web_test_db_name
    if name.casefold() == settings.database_name.casefold():
        pytest.fail(
            "STORE_WEB_TEST_DB_NAME must differ from the application database "
            f"({settings.database_name}).",
            pytrace=False,
        )
    if not name.upper().endswith("_TEST"):
        pytest.fail(
            "STORE_WEB_TEST_DB_NAME must end with _TEST to protect application data.",
            pytrace=False,
        )


@pytest.fixture(scope="session")
def test_engine() -> Generator[Engine, None, None]:
    _guard()
    try:
        engine = create_engine(
            database_url(settings.store_web_test_db_name),
            pool_pre_ping=True,
            hide_parameters=True,
            connect_args={"timeout": 5},
        )
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except (SQLAlchemyError, RuntimeError):
        pytest.fail(
            "Cannot connect to the SQL Server test database. Start sqlserver, migrate "
            "RTS_WEB_TEST, install ODBC Driver 18, and check DB_HOST, SQLSERVER_PORT, "
            "STORE_WEB_TEST_DB_NAME and MSSQL_SA_PASSWORD. See clients/store-web/README.md.",
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
def today(monkeypatch: pytest.MonkeyPatch) -> date:
    """Freeze the business date so the expiry boundary is stable."""
    monkeypatch.setattr(clock, "today_local", lambda: FIXED_TODAY)
    return FIXED_TODAY


def _customer_guard() -> None:
    name = settings.store_web_test_customer_db_name
    if name.casefold() == settings.customer_database_name.casefold():
        pytest.fail(
            "STORE_WEB_TEST_CUSTOMER_DB_NAME must differ from the customer database "
            f"({settings.customer_database_name}).",
            pytrace=False,
        )
    if not name.upper().endswith("_TEST"):
        pytest.fail(
            "STORE_WEB_TEST_CUSTOMER_DB_NAME must end with _TEST to protect real accounts.",
            pytrace=False,
        )


@pytest.fixture(scope="session")
def customer_engine() -> Generator[Engine, None, None]:
    """A disposable customer database, created once per run."""
    _customer_guard()
    try:
        ensure_database(settings.store_web_test_customer_db_name)
        engine = create_engine(
            database_url(settings.store_web_test_customer_db_name),
            pool_pre_ping=True,
            hide_parameters=True,
            connect_args={"timeout": 5},
        )
        ensure_schema(engine)
    except (SQLAlchemyError, RuntimeError) as error:
        pytest.fail(
            "Cannot prepare the customer test database. Start sqlserver, install ODBC "
            "Driver 18, and check DB_HOST, SQLSERVER_PORT, STORE_WEB_TEST_CUSTOMER_DB_NAME "
            f"and MSSQL_SA_PASSWORD. Underlying error: {error}",
            pytrace=False,
        )
    try:
        yield engine
    finally:
        engine.dispose()


@pytest.fixture
def customer_session(customer_engine: Engine) -> Generator[Session, None, None]:
    """An empty customer database: every test starts from no accounts.

    Unlike the store database, this one is small and fully controlled by the
    tests, so tables are cleared instead of using a rolled-back transaction. The
    API commits its own sessions, which a savepoint would not contain.
    """
    with customer_engine.begin() as connection:
        connection.execute(text("DELETE FROM dbo.customer_address"))
        connection.execute(text("DELETE FROM dbo.customer_session"))
        connection.execute(text("DELETE FROM dbo.customer"))

    session = Session(bind=customer_engine, join_transaction_mode="create_savepoint")
    try:
        yield session
    finally:
        session.close()


def _client(db_session: Session, customer_session: Session) -> Generator[TestClient, None, None]:
    def override_get_db() -> Generator[Session, None, None]:
        try:
            yield db_session
        except BaseException:
            db_session.rollback()
            raise

    def override_get_customer_db() -> Generator[Session, None, None]:
        try:
            yield customer_session
        except BaseException:
            customer_session.rollback()
            raise

    previous = app.dependency_overrides.copy()
    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_customer_db] = override_get_customer_db
    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(previous)


@pytest.fixture
def client(db_session: Session, customer_session: Session) -> Generator[TestClient, None, None]:
    """A client with both databases overridden onto their test databases."""
    yield from _client(db_session, customer_session)


@pytest.fixture
def seeded(db_session: Session, today: date) -> Session:
    """Three stores and five products covering every expiry and filter case.

    ``WEB-A`` active, ``WEB-B`` active, ``WEB-C`` inactive.
    ``WEB-P1``: batch expired yesterday, one expiring today (still sellable), one +30.
    ``WEB-P2``: only an expired batch, so nothing is sellable.
    ``WEB-P3``: in the catalog with no inventory row at all.
    ``WEB-P4``: an inventory row and a batch with quantity 0.
    """
    # The migrated test database also holds the demo seed. Removing the catalog
    # rows inside this transaction makes the expected totals exact; the rollback
    # at teardown restores everything.
    db_session.execute(text("DELETE FROM dbo.product_batch WHERE sku NOT LIKE 'WEB-%'"))
    db_session.execute(text("DELETE FROM dbo.inventory WHERE sku NOT LIKE 'WEB-%'"))
    db_session.execute(text("DELETE FROM dbo.product WHERE sku NOT LIKE 'WEB-%'"))

    rows = [
        # store_id, name, region_id, is_active
        ("WEB-A", "Cửa hàng Test A", "DN", 1),
        ("WEB-B", "Cửa hàng Test B", "DN", 1),
        ("WEB-C", "Cửa hàng Test C", "DN", 0),
    ]
    for store_id, name, region_id, is_active in rows:
        db_session.execute(
            text(
                "INSERT INTO dbo.store (store_id, name, latitude, longitude, region_id, is_active) "
                "VALUES (:store_id, :name, 16.0, 108.0, :region_id, :is_active)"
            ),
            {"store_id": store_id, "name": name, "region_id": region_id, "is_active": is_active},
        )

    products = [
        ("WEB-P1", "8930000000001", "Sản phẩm Một", "Dairy", 32000),
        ("WEB-P2", "8930000000002", "Sản phẩm Hai", "Dairy", 7000),
        ("WEB-P3", "8930000000003", "Sản phẩm Ba", "Bakery", 65000),
        ("WEB-P4", "8930000000004", "Sản phẩm Bốn", "Dry goods", 120000),
    ]
    for sku, barcode, name, category, price in products:
        db_session.execute(
            text(
                "INSERT INTO dbo.product (sku, barcode, name, category, unit_price) "
                "VALUES (:sku, :barcode, :name, :category, :price)"
            ),
            {"sku": sku, "barcode": barcode, "name": name, "category": category, "price": price},
        )

    inventory = [
        ("WEB-A", "WEB-P1", 60),
        ("WEB-A", "WEB-P2", 10),
        ("WEB-A", "WEB-P4", 5),
        ("WEB-B", "WEB-P1", 20),
    ]
    for store_id, sku, quantity in inventory:
        db_session.execute(
            text(
                "INSERT INTO dbo.inventory (store_id, sku, quantity) "
                "VALUES (:store_id, :sku, :quantity)"
            ),
            {"store_id": store_id, "sku": sku, "quantity": quantity},
        )

    batches = [
        # batch_id, sku, store_id, days offset, quantity
        ("WEB-B-P1-EXPIRED", "WEB-P1", "WEB-A", -1, 20),
        ("WEB-B-P1-TODAY", "WEB-P1", "WEB-A", 0, 15),
        ("WEB-B-P1-LATER", "WEB-P1", "WEB-A", 30, 25),
        ("WEB-B-P2-EXPIRED", "WEB-P2", "WEB-A", -5, 10),
        ("WEB-B-P4-ZERO", "WEB-P4", "WEB-A", 10, 0),
        ("WEB-B-B-P1-LATER", "WEB-P1", "WEB-B", 20, 20),
    ]
    for batch_id, sku, store_id, offset, quantity in batches:
        db_session.execute(
            text(
                "INSERT INTO dbo.product_batch (batch_id, sku, store_id, expiry_date, quantity) "
                "VALUES (:batch_id, :sku, :store_id, DATEADD(day, :offset, CAST(:today AS date)), :quantity)"
            ),
            {
                "batch_id": batch_id,
                "sku": sku,
                "store_id": store_id,
                "offset": offset,
                "today": today,
                "quantity": quantity,
            },
        )

    db_session.flush()
    return db_session


@pytest.fixture
def seeded_client(seeded: Session, customer_session: Session) -> Generator[TestClient, None, None]:
    """A client over the seeded store data and an empty customer database."""
    yield from _client(seeded, customer_session)
