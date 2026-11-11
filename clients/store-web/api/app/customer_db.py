"""The customer database: accounts, sessions and saved addresses.

This is the only writable database of the app. It is separate from the store
database, which stays read-only, so a customer feature can never corrupt
inventory data.

Tables are created by :func:`ensure_schema` (idempotent) and the database itself
by ``tools/init_customer_db.py``. No migration runner is involved.
"""

import logging
from collections.abc import Generator

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from app.config import settings
from app.db import database_url

logger = logging.getLogger(__name__)

SCHEMA_STATEMENTS = (
    """
    IF OBJECT_ID(N'dbo.customer', N'U') IS NULL
    CREATE TABLE dbo.customer (
        customer_id int IDENTITY(1,1) NOT NULL CONSTRAINT pk_customer PRIMARY KEY,
        email varchar(200) NOT NULL CONSTRAINT uq_customer_email UNIQUE,
        full_name nvarchar(120) NOT NULL,
        password_hash varchar(255) NOT NULL,
        created_at datetime2 NOT NULL CONSTRAINT df_customer_created DEFAULT SYSUTCDATETIME()
    );
    """,
    """
    IF OBJECT_ID(N'dbo.customer_session', N'U') IS NULL
    BEGIN
        CREATE TABLE dbo.customer_session (
            token_hash char(64) NOT NULL CONSTRAINT pk_customer_session PRIMARY KEY,
            customer_id int NOT NULL CONSTRAINT fk_customer_session_customer
                REFERENCES dbo.customer(customer_id) ON DELETE CASCADE,
            created_at datetime2 NOT NULL CONSTRAINT df_customer_session_created DEFAULT SYSUTCDATETIME(),
            expires_at datetime2 NOT NULL
        );
        CREATE INDEX ix_customer_session_customer ON dbo.customer_session(customer_id);
    END
    """,
    """
    IF OBJECT_ID(N'dbo.customer_address', N'U') IS NULL
    BEGIN
        CREATE TABLE dbo.customer_address (
            address_id int IDENTITY(1,1) NOT NULL CONSTRAINT pk_customer_address PRIMARY KEY,
            customer_id int NOT NULL CONSTRAINT fk_customer_address_customer
                REFERENCES dbo.customer(customer_id) ON DELETE CASCADE,
            label nvarchar(60) NOT NULL,
            address_text nvarchar(300) NOT NULL,
            latitude float NOT NULL,
            longitude float NOT NULL,
            created_at datetime2 NOT NULL CONSTRAINT df_customer_address_created DEFAULT SYSUTCDATETIME()
        );
        CREATE INDEX ix_customer_address_customer ON dbo.customer_address(customer_id);
    END
    """,
)


def ensure_database(database_name: str | None = None) -> None:
    """Create the customer database when it is missing.

    ``CREATE DATABASE`` cannot run inside a transaction, so this uses the
    DB-API connection in autocommit mode instead of ``Engine.begin()``.
    """
    name = database_name or settings.customer_database_name
    master = create_engine(
        database_url("master"),
        pool_pre_ping=True,
        hide_parameters=True,
        connect_args={"timeout": 5},
    )
    try:
        with master.connect() as connection:
            raw = connection.connection.driver_connection
            raw.autocommit = True
            raw.execute(
                "IF DB_ID(N'%s') IS NULL CREATE DATABASE [%s];" % (name, name)
            )
    finally:
        master.dispose()


def ensure_schema(engine: Engine) -> None:
    """Create the customer tables when they are missing. Safe to call repeatedly."""
    with engine.begin() as connection:
        for statement in SCHEMA_STATEMENTS:
            connection.execute(text(statement))


_engine: Engine | None = None


def get_customer_engine() -> Engine:
    """One engine per process, created and prepared on first use."""
    global _engine
    if _engine is None:
        engine = create_engine(
            database_url(settings.customer_database_name),
            pool_pre_ping=True,
            hide_parameters=True,
            connect_args={"timeout": 5},
        )
        ensure_schema(engine)
        _engine = engine
    return _engine


def prepare_customer_database() -> None:
    """Create the database and its tables; log a warning instead of crashing startup."""
    try:
        ensure_database()
        ensure_schema(get_customer_engine())
    except Exception:  # noqa: BLE001 - a missing customer DB must not stop the catalog
        logger.warning(
            "Customer database '%s' is not ready; login and saved addresses are "
            "unavailable until it exists. Run: python tools/init_customer_db.py",
            settings.customer_database_name,
            exc_info=True,
        )


_session_factory = sessionmaker(class_=Session)


def CustomerSessionLocal() -> Session:
    return _session_factory(bind=get_customer_engine())


def get_customer_db() -> Generator[Session, None, None]:
    """A session for the customer database; routers own the commit."""
    session = CustomerSessionLocal()
    try:
        yield session
    except BaseException:
        session.rollback()
        raise
    finally:
        session.close()
