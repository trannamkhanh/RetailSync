"""Lazy SQL Server access. Routers own commits; migrations own the schema."""

from collections.abc import Generator
from functools import lru_cache

from sqlalchemy import URL, Engine, create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import settings


class Base(DeclarativeBase):
    pass


def database_url(database: str | None = None) -> URL:
    password = settings.mssql_sa_password
    if password is None or not password.get_secret_value():
        raise RuntimeError("Set MSSQL_SA_PASSWORD before using the database.")
    return URL.create(
        "mssql+pyodbc",
        username="sa",
        password=password.get_secret_value(),
        host=settings.db_host,
        port=settings.sqlserver_port,
        database=database or settings.db_name,
        query={"driver": "ODBC Driver 18 for SQL Server", "TrustServerCertificate": "yes"},
    )


@lru_cache(maxsize=1)
def get_engine() -> Engine:
    return create_engine(database_url(), pool_pre_ping=True, connect_args={"timeout": 5})


_session_factory = sessionmaker(class_=Session)


def SessionLocal() -> Session:
    """Create a session without connecting until its first database operation."""
    return _session_factory(bind=get_engine())


def get_db() -> Generator[Session, None, None]:
    session = SessionLocal()
    try:
        yield session
    except BaseException:
        session.rollback()
        raise
    finally:
        session.close()
