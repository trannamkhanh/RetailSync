"""ORM models of the customer database.

They live apart from ``app.customer_db`` so routers can import a model without
importing the engine, which imports the settings.

``Unicode`` matters: on SQL Server a plain ``String`` binds as ``VARCHAR``, so a
Vietnamese name would reach the driver as cp1252 and arrive with ``?`` in place
of every character outside that code page. ``Unicode`` binds as ``NVARCHAR`` and
matches the ``nvarchar`` columns the DDL creates.
"""

from datetime import datetime

from sqlalchemy import DateTime, Float, Identity, Index, Integer, String, Unicode
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class CustomerBase(DeclarativeBase):
    pass


class Customer(CustomerBase):
    __tablename__ = "customer"
    __table_args__ = {"schema": "dbo"}

    customer_id: Mapped[int] = mapped_column(Integer, Identity(1, 1), primary_key=True)
    # Emails are stored case-folded ASCII, so varchar is correct and indexed cheaply.
    email: Mapped[str] = mapped_column(String(200), unique=True, nullable=False)
    full_name: Mapped[str] = mapped_column(Unicode(120), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class CustomerSession(CustomerBase):
    __tablename__ = "customer_session"
    __table_args__ = (
        Index("ix_customer_session_customer", "customer_id"),
        {"schema": "dbo"},
    )

    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    customer_id: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class CustomerAddress(CustomerBase):
    __tablename__ = "customer_address"
    __table_args__ = (
        Index("ix_customer_address_customer", "customer_id"),
        {"schema": "dbo"},
    )

    address_id: Mapped[int] = mapped_column(Integer, Identity(1, 1), primary_key=True)
    customer_id: Mapped[int] = mapped_column(Integer, nullable=False)
    label: Mapped[str] = mapped_column(Unicode(60), nullable=False)
    address_text: Mapped[str] = mapped_column(Unicode(300), nullable=False)
    latitude: Mapped[float] = mapped_column(Float, nullable=False)
    longitude: Mapped[float] = mapped_column(Float, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

