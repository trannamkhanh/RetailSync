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

# PB-52 demo profile: per-store daily mean sales (STORE-DN1, STORE-DN2, STORE-DN3) tuned to the
# 30-SKU demo catalogue so the forecast shows SURPLUS, SHORTAGE and BALANCED, near-expiry batches
# keep at_risk > 0, and recommendations include 3 S1 redistributions (DN2 surplus -> DN1 shortage)
# and 2 S2 10% discounts (surplus >= demand at both DN1 and DN2 with no shortage at DN3).
DEMO_PROFILE_DAILY_MEANS: dict[str, tuple[float, float, float]] = {
    # 9 existing SKUs (stock 40 / 25 / 15)
    "SKU-0001": (3.0, 2.0, 1.5),   # near-expiry 2d at DN1/DN2 -> DISCOUNT 30%
    "SKU-0002": (2.2, 1.4, 1.2),   # near-expiry 3d at DN1/DN2 -> DISCOUNT 30%
    "SKU-0003": (3.5, 2.5, 1.8),
    "SKU-0004": (2.5, 1.5, 1.2),   # near-expiry 1d at DN1/DN2 -> CLEARANCE / 50%
    "SKU-0005": (2.8, 2.0, 1.4),   # expired -1d at DN1/DN2
    "SKU-0006": (4.2, 2.8, 1.8),
    "SKU-0007": (3.8, 2.6, 1.7),
    "SKU-0008": (7.5, 5.0, 3.2),   # fast dry-goods -> SHORTAGE
    "SKU-0009": (4.0, 2.6, 1.7),
    # 7 slow SKUs (stock 80 / 60 / 45); SKU-0025 and SKU-0030 are S2 (10% discount at DN1 & DN2)
    "SKU-0010": (7.2, 5.5, 4.2),
    "SKU-0014": (7.0, 5.4, 4.1),
    "SKU-0023": (7.4, 5.6, 4.2),
    "SKU-0025": (2.5, 2.0, 3.6),   # S2 #1: DN1/DN2 surplus >= demand, DN3 mild surplus
    "SKU-0028": (7.3, 5.5, 4.1),
    "SKU-0029": (7.1, 5.4, 4.0),
    "SKU-0030": (2.4, 1.9, 3.5),   # S2 #2: DN1/DN2 surplus >= demand, DN3 mild surplus
    # 7 medium SKUs (stock 55 / 45 / 30); SKU-0017, SKU-0020, SKU-0022 are S1 (DN2 -> DN1)
    "SKU-0013": (5.5, 4.5, 3.0),
    "SKU-0017": (11.5, 2.2, 4.8),  # S1 #1: DN1 shortage, DN2 surplus, DN3 small shortage
    "SKU-0020": (11.2, 2.3, 4.7),  # S1 #2: DN1 shortage, DN2 surplus, DN3 small shortage
    "SKU-0022": (11.0, 2.1, 4.6),  # S1 #3: DN1 shortage, DN2 surplus, DN3 small shortage
    "SKU-0027": (5.6, 4.4, 3.1),
    # 7 fast SKUs (stock 40 / 25 / 15): clear SHORTAGE and top-selling items
    "SKU-0011": (8.5, 6.0, 3.8),
    "SKU-0012": (8.2, 5.8, 3.6),
    "SKU-0016": (13.0, 8.5, 5.5),
    "SKU-0018": (10.5, 7.2, 4.6),
    "SKU-0019": (9.5, 6.5, 4.2),
    "SKU-0021": (9.0, 6.2, 4.0),
    "SKU-0026": (7.8, 5.4, 3.5),
}

# Exact 7-day weekly patterns matching Medium stock (55 / 45 / 30) so BALANCED rows are guaranteed.
DEMO_BALANCED_WEEKLY: dict[str, dict[str, tuple[int, int, int, int, int, int, int]]] = {
    "SKU-0015": {
        "STORE-DN1": (7, 8, 8, 8, 8, 8, 8),  # sum = 55
        "STORE-DN2": (6, 6, 6, 6, 7, 7, 7),  # sum = 45
        "STORE-DN3": (4, 4, 4, 4, 4, 5, 5),  # sum = 30
    },
    "SKU-0024": {
        "STORE-DN1": (7, 8, 8, 8, 8, 8, 8),  # sum = 55
        "STORE-DN2": (6, 6, 6, 6, 7, 7, 7),  # sum = 45
        "STORE-DN3": (4, 4, 4, 4, 4, 5, 5),  # sum = 30
    },
}
STORE_INDEX = {"STORE-DN1": 0, "STORE-DN2": 1, "STORE-DN3": 2}


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
                  short_skus: set[str], *, demo_profile: bool = False) -> tuple[list[dict], list[dict], list[dict]]:
    sales, returns, items = [], [], []
    offset = timedelta(hours=settings.business_utc_offset_hours)
    store_slot = STORE_INDEX.get(store)
    for product in products:
        sku = product.sku
        balanced_week = DEMO_BALANCED_WEEKLY.get(sku, {}).get(store) if demo_profile else None
        profile_means = DEMO_PROFILE_DAILY_MEANS.get(sku) if demo_profile else None
        base = random.uniform(5, 12)
        if sku in slow_skus:
            base *= 0.15
        span = min(days, 14) if sku in short_skus else days
        for age in range(span, 0, -1):
            day = as_of - timedelta(days=age)
            if balanced_week is not None:
                quantity = balanced_week[day.weekday()]
                add_return = False
            elif profile_means is not None and store_slot is not None:
                promotion_factor = 1.35 if random.random() < 0.06 else 1.0
                mean = profile_means[store_slot] * WEEKDAY_FACTORS[day.weekday()] * promotion_factor
                quantity = _poisson(random, mean)
                add_return = random.random() < 0.025
            else:
                promotion_factor = 1.5 if random.random() < 0.08 else 1.0
                mean = base * WEEKDAY_FACTORS[day.weekday()] * store_factor * promotion_factor
                quantity = _poisson(random, mean)
                add_return = random.random() < 0.025
            if sku in short_skus and age == 1:
                quantity = max(1, quantity)
            if not quantity:
                continue
            timestamp = datetime.combine(day, time(12)) - offset
            pos = random.choice(terminals)
            key = sha256(f"{store}/{sku}/{day}".encode()).hexdigest()[:30]
            sale_id = f"HIST-{key}-S"
            events = [("SALE", sale_id, None, quantity, timestamp, sales)]
            if add_return:
                events.append(("RETURN", f"HIST-{key}-R", sale_id, 1, timestamp + timedelta(hours=1), returns))
            for kind, txn, reference, qty, created, target in events:
                target.append({
                    "txn_id": txn, "store_id": store, "pos_id": pos, "txn_type": kind,
                    "ref_txn_id": reference, "status": "OK", "sync_batch_id": f"SB-HIST-{store}",
                    "payload_hash": content_hash(kind, store, pos, reference, [(sku, qty, product.unit_price)]),
                    # The simulated moment the sale happened, and the moment the
                    # Middleware would have received it. A generated line is
                    # received at once, so it is ON_TIME and not BACKFILL, and
                    # created_at keeps the value it had before migration 004.
                    "occurred_at": created,
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
    # The generated rows carry both moments, so the batch's received-time window
    # stays the one DS-05 describes while the Dashboard can still read the
    # simulated moment the sale happened.
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
                 store_ids: set[str] | None = None, demo_profile: bool = False) -> int:
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
    slow_skus = set() if demo_profile else set(random.sample(skus, max(1, round(len(skus) * 0.10))))
    pairs = [(store, sku) for store in terminals for sku in skus]
    short_pairs = set() if demo_profile else set(random.sample(pairs, max(1, round(len(pairs) * 0.05))))
    count = 0
    for store, ids in terminals.items():
        sales, returns, items = _transactions(
            products, ids, store, random.uniform(0.8, 1.2), days, as_of, random,
            slow_skus, {sku for pair_store, sku in short_pairs if pair_store == store},
            demo_profile=demo_profile,
        )
        _replace_store_history(session, store, sales, returns, items)
        count += len(sales) + len(returns)
    return count
