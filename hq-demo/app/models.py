"""The two HQ tables of database/hq/001_hq_tables.sql (Database Design v1.3)."""

from datetime import datetime
from decimal import Decimal

from sqlalchemy import CHAR, DateTime, Numeric, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class HqSyncBatch(Base):
    __tablename__ = "hq_sync_batch"

    sync_batch_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    store_id: Mapped[str] = mapped_column(String(10))
    txn_count: Mapped[int]
    received_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.sysutcdatetime())
    duplicate_count: Mapped[int] = mapped_column(server_default="0")
    payload_hash: Mapped[str] = mapped_column(CHAR(64))


class HqSalesTotal(Base):
    __tablename__ = "hq_sales_total"

    store_id: Mapped[str] = mapped_column(String(10), primary_key=True)
    sku: Mapped[str] = mapped_column(String(20), primary_key=True)
    sold_qty: Mapped[int]
    returned_qty: Mapped[int]
    net_revenue: Mapped[Decimal] = mapped_column(Numeric(14, 2))
