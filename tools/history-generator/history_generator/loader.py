"""Generate repeatable simulated sales and replace only history owned by this tool."""

from collections import defaultdict
from datetime import date, datetime, time, timedelta
from hashlib import sha256
from math import exp
from random import Random

from sqlalchemy import delete, insert, select, text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.domain.models import PosTerminal, PosTransaction, Product, SyncBatch, TransactionItem
from app.services.idempotency import content_hash


DATABASES = {"RTS_DB_DEMO", "RTS_DB_TEST"}
WEEKDAY_FACTORS = (1.0, 1.0, 1.0, 1.0, 1.1, 1.3, 1.2)


def allowed_database(name: str) -> str:
    if name not in DATABASES:
        raise ValueError("History generation requires RTS_DB_DEMO or RTS_DB_TEST.")
    return name


def _poisson(random: Random, mean: float) -> int:
    threshold = exp(-mean)
    product = random.random()
    quantity = 0
    while product > threshold:
        quantity += 1
        product *= random.random()
    return quantity


def _transactions(products: list[Product], terminals: list[str], store: str, store_factor: float,
                  days: int, as_of: date, random: Random, slow_skus: set[str],
                  short_skus: set[str]) -> tuple[list[dict], list[dict], list[dict]]:
    sales, returns, items = [], [], []
    offset = timedelta(hours=settings.business_utc_offset_hours)
    for product in products:
        sku = product.sku
        base = random.uniform(5, 12)
        if sku in slow_skus:
            base *= 0.15
        span = min(days, 14) if sku in short_skus else days
        for age in range(span, 0, -1):
            day = as_of - timedelta(days=age)
            promotion_factor = 1.5 if random.random() < 0.08 else 1.0
            mean = base * WEEKDAY_FACTORS[day.weekday()] * store_factor * promotion_factor
            quantity = _poisson(random, mean)
            if sku in short_skus and age == 1:
                quantity = max(1, quantity)
            if not quantity:
                continue
            timestamp = datetime.combine(day, time(12)) - offset
            pos = random.choice(terminals)
            key = sha256(f"{store}/{sku}/{day}".encode()).hexdigest()[:30]
            sale_id = f"HIST-{key}-S"
            events = [("SALE", sale_id, None, quantity, timestamp, sales)]
            if random.random() < 0.025:
                events.append(("RETURN", f"HIST-{key}-R", sale_id, 1, timestamp + timedelta(hours=1), returns))
            for kind, txn, reference, qty, created, target in events:
                target.append({
                    "txn_id": txn, "store_id": store, "pos_id": pos, "txn_type": kind,
                    "ref_txn_id": reference, "status": "OK", "sync_batch_id": f"SB-HIST-{store}",
                    "payload_hash": content_hash(kind, store, pos, reference, [(sku, qty, product.unit_price)]),
                    "created_at": created,
                })
                items.append({"txn_id": txn, "sku": sku, "qty": qty, "unit_price": product.unit_price})
    return sales, returns, items


def _replace_store_history(session: Session, store: str, sales: list[dict],
                           returns: list[dict], items: list[dict]) -> None:
    batch_id = f"SB-HIST-{store}"
    history = (PosTransaction.sync_batch_id == batch_id, PosTransaction.txn_id.startswith("HIST-"))
    owned_ids = select(PosTransaction.txn_id).where(*history)
    session.execute(delete(TransactionItem).where(TransactionItem.txn_id.in_(owned_ids)))
    session.execute(delete(PosTransaction).where(*history, PosTransaction.txn_type == "RETURN"))
    session.execute(delete(PosTransaction).where(*history))
    session.execute(delete(SyncBatch).where(SyncBatch.sync_batch_id == batch_id))

    if not sales:
        return
    timestamps = [row["created_at"] for row in sales + returns]
    session.execute(insert(SyncBatch), [{
        "sync_batch_id": batch_id, "store_id": store, "status": "ACKED",
        "period_start": min(timestamps), "period_end": max(timestamps),
        "txn_count": len(timestamps), "acked_at": max(timestamps),
    }])
    session.execute(insert(PosTransaction), sales)
    if returns:
        session.execute(insert(PosTransaction), returns)
    session.execute(insert(TransactionItem), items)


def load_history(session: Session, days: int, seed: int, as_of: date, *,
                 store_ids: set[str] | None = None) -> int:
    """Replace synthetic history for the chosen active stores in the caller's transaction."""
    allowed_database(session.scalar(text("SELECT DB_NAME()")))
    if not 1 <= days <= 3650:
        raise ValueError("days must be between 1 and 3650")
    terminals = defaultdict(list)
    terminal_query = select(PosTerminal.store_id, PosTerminal.pos_id).where(
        PosTerminal.status == "ACTIVE",
    ).order_by(PosTerminal.store_id, PosTerminal.pos_id)
    if store_ids is not None:
        terminal_query = terminal_query.where(PosTerminal.store_id.in_(store_ids))
    for store, pos in session.execute(terminal_query):
        terminals[store].append(pos)
    products = list(session.scalars(select(Product).order_by(Product.sku)))
    if not products or not terminals:
        raise ValueError("Load the catalogue and active POS terminals before generating history.")

    random = Random(seed)
    skus = [product.sku for product in products]
    slow_skus = set(random.sample(skus, max(1, round(len(skus) * 0.10))))
    pairs = [(store, sku) for store in terminals for sku in skus]
    short_pairs = set(random.sample(pairs, max(1, round(len(pairs) * 0.05))))
    count = 0
    for store, ids in terminals.items():
        sales, returns, items = _transactions(
            products, ids, store, random.uniform(0.8, 1.2), days, as_of, random,
            slow_skus, {sku for pair_store, sku in short_pairs if pair_store == store},
        )
        _replace_store_history(session, store, sales, returns, items)
        count += len(sales) + len(returns)
    return count
