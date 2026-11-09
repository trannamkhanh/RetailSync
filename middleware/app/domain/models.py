"""The Sprint 2 tables of 001_core.sql plus ``product_batch``; no schema creation."""

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import BigInteger, Boolean, CHAR, Date, ForeignKey, ForeignKeyConstraint, Integer, Numeric, Unicode, String, text
from sqlalchemy.dialects.mssql import DATETIME2
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class Store(Base):
    __tablename__ = "store"
    store_id: Mapped[str] = mapped_column(String(10), primary_key=True)
    name: Mapped[str] = mapped_column(Unicode(100))
    latitude: Mapped[Decimal] = mapped_column(Numeric(9, 6))
    longitude: Mapped[Decimal] = mapped_column(Numeric(9, 6))
    region_id: Mapped[str] = mapped_column(String(10))
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=text("1"))


class PosTerminal(Base):
    __tablename__ = "pos_terminal"
    pos_id: Mapped[str] = mapped_column(String(20), primary_key=True)
    store_id: Mapped[str] = mapped_column(String(10), ForeignKey("store.store_id"))
    status: Mapped[str] = mapped_column(String(10))
    registered_at: Mapped[datetime] = mapped_column(DATETIME2, server_default=text("SYSUTCDATETIME()"))
    cert_fingerprint: Mapped[str | None] = mapped_column(CHAR(64))


class StaffUser(Base):
    __tablename__ = "staff_user"
    user_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(50))
    full_name: Mapped[str] = mapped_column(Unicode(100))
    role: Mapped[str] = mapped_column(String(20))
    store_id: Mapped[str | None] = mapped_column(String(10), ForeignKey("store.store_id"))
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=text("1"))


class AuditLog(Base):
    __tablename__ = "audit_log"
    audit_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("staff_user.user_id"))
    action: Mapped[str] = mapped_column(String(50))
    entity_name: Mapped[str] = mapped_column(String(50))
    entity_key: Mapped[str | None] = mapped_column(String(50))
    details: Mapped[str | None] = mapped_column(Unicode(500))
    created_at: Mapped[datetime] = mapped_column(DATETIME2, server_default=text("SYSUTCDATETIME()"))


class Product(Base):
    __tablename__ = "product"
    sku: Mapped[str] = mapped_column(String(20), primary_key=True)
    barcode: Mapped[str] = mapped_column(String(30))
    name: Mapped[str] = mapped_column(Unicode(150))
    category: Mapped[str] = mapped_column(String(50))
    unit_price: Mapped[Decimal] = mapped_column(Numeric(12, 2))


class Inventory(Base):
    __tablename__ = "inventory"
    store_id: Mapped[str] = mapped_column(String(10), ForeignKey("store.store_id"), primary_key=True)
    sku: Mapped[str] = mapped_column(String(20), ForeignKey("product.sku"), primary_key=True)
    quantity: Mapped[int] = mapped_column(Integer)
    updated_at: Mapped[datetime] = mapped_column(DATETIME2, server_default=text("SYSUTCDATETIME()"))


class ProductBatch(Base):
    """One expiry batch of a SKU in a store (PB-20).

    ``inventory.quantity`` equals the sum of the batches of the same store and
    SKU, expired ones included; both change in the same transaction. A batch is
    sellable while ``expiry_date >= today_local()``.
    """

    __tablename__ = "product_batch"
    batch_id: Mapped[str] = mapped_column(String(30), primary_key=True)
    sku: Mapped[str] = mapped_column(String(20), ForeignKey("product.sku"))
    store_id: Mapped[str] = mapped_column(String(10), ForeignKey("store.store_id"))
    expiry_date: Mapped[date] = mapped_column(Date)
    quantity: Mapped[int] = mapped_column(Integer)
    received_at: Mapped[datetime] = mapped_column(DATETIME2, server_default=text("SYSUTCDATETIME()"))


class SyncBatch(Base):
    __tablename__ = "sync_batch"
    sync_batch_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    store_id: Mapped[str] = mapped_column(String(10), ForeignKey("store.store_id"))
    period_start: Mapped[datetime] = mapped_column(DATETIME2)
    period_end: Mapped[datetime] = mapped_column(DATETIME2)
    txn_count: Mapped[int] = mapped_column(Integer)
    payload_bytes: Mapped[int | None] = mapped_column(Integer)
    raw_bytes: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(10))
    attempts: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    last_error: Mapped[str | None] = mapped_column(Unicode(200))
    next_retry_at: Mapped[datetime | None] = mapped_column(DATETIME2)
    created_at: Mapped[datetime] = mapped_column(DATETIME2, server_default=text("SYSUTCDATETIME()"))
    acked_at: Mapped[datetime | None] = mapped_column(DATETIME2)


class PosTransaction(Base):
    __tablename__ = "pos_transaction"
    txn_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    store_id: Mapped[str] = mapped_column(String(10), ForeignKey("store.store_id"))
    pos_id: Mapped[str] = mapped_column(String(20), ForeignKey("pos_terminal.pos_id"))
    txn_type: Mapped[str] = mapped_column(String(15))
    ref_txn_id: Mapped[str | None] = mapped_column(String(40), ForeignKey("pos_transaction.txn_id"))
    status: Mapped[str] = mapped_column(String(12))
    sync_batch_id: Mapped[str | None] = mapped_column(String(40), ForeignKey("sync_batch.sync_batch_id"))
    payload_hash: Mapped[str] = mapped_column(CHAR(64))
    created_at: Mapped[datetime] = mapped_column(DATETIME2, server_default=text("SYSUTCDATETIME()"))


class TransactionItem(Base):
    __tablename__ = "transaction_item"
    item_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    txn_id: Mapped[str] = mapped_column(String(40), ForeignKey("pos_transaction.txn_id"))
    sku: Mapped[str] = mapped_column(String(20), ForeignKey("product.sku"))
    qty: Mapped[int] = mapped_column(Integer)
    unit_price: Mapped[Decimal] = mapped_column(Numeric(12, 2))


class InventoryMovement(Base):
    __tablename__ = "inventory_movement"
    __table_args__ = (ForeignKeyConstraint(["store_id", "sku"], ["inventory.store_id", "inventory.sku"]),)
    movement_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    store_id: Mapped[str] = mapped_column(String(10))
    sku: Mapped[str] = mapped_column(String(20))
    movement_type: Mapped[str] = mapped_column(String(20))
    quantity: Mapped[int] = mapped_column(Integer)
    txn_id: Mapped[str | None] = mapped_column(String(40), ForeignKey("pos_transaction.txn_id"))
    batch_id: Mapped[str | None] = mapped_column(String(30))
    reason: Mapped[str | None] = mapped_column(Unicode(200))
    created_by: Mapped[int | None] = mapped_column(Integer, ForeignKey("staff_user.user_id"))
    created_at: Mapped[datetime] = mapped_column(DATETIME2, server_default=text("SYSUTCDATETIME()"))


class GuardrailRule(Base):
    __tablename__ = "guardrail_rule"
    rule_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    rule_type: Mapped[str] = mapped_column(String(20))
    threshold: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    category: Mapped[str | None] = mapped_column(String(50))
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=text("1"))
    updated_by: Mapped[int | None] = mapped_column(Integer, ForeignKey("staff_user.user_id"))
    updated_at: Mapped[datetime] = mapped_column(DATETIME2, server_default=text("SYSUTCDATETIME()"))
