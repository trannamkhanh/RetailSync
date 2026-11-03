"""SKU lookup and ``transaction_item`` inserts for the POS event flow.

Callers own the transaction; every function takes a session and never commits.
"""

from collections.abc import Iterable, Sequence
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.models import Product, TransactionItem


def find_existing_skus(session: Session, skus: Iterable[str]) -> set[str]:
    """Return the catalogue SKUs that exist among ``skus``."""
    wanted = list(dict.fromkeys(skus))
    if not wanted:
        return set()
    return set(session.scalars(select(Product.sku).where(Product.sku.in_(wanted))))


def add_transaction_items(
    session: Session,
    txn_id: str,
    items: Sequence[tuple[str, int, Decimal]],
) -> None:
    """Store every line as received, including repeated SKUs.

    ``deduct_items`` merges repeated SKUs later; the transaction rows keep the
    basket exactly as the POS sent it.
    """
    session.add_all([
        TransactionItem(txn_id=txn_id, sku=sku, qty=quantity, unit_price=unit_price)
        for sku, quantity, unit_price in items
    ])
    session.flush()
