"""Mixed POS traffic against SQL Server (DS-09 duplicate storm)."""

from collections import Counter
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from random import Random
from re import findall
from threading import Barrier
from time import monotonic, sleep

from fastapi.testclient import TestClient
from sqlalchemy import Engine, delete, select
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.security import create_token
from app.domain.models import (
    AuditLog, Inventory, InventoryMovement, PosTerminal, PosTransaction,
    Product, ProductBatch, StaffUser, Store, TransactionItem,
)
from app.main import app
from tests.pos_test_support import add_stock, assert_ledger_balanced, post, uid


SEED = 73107
WORKERS = 8
TIME_LIMIT = 60
REJECTIONS = {"INSUFFICIENT_STOCK", "RETURN_QTY_EXCEEDED", "SALE_ALREADY_CANCELLED", "SALE_HAS_RETURNS"}


def _seed(engine: Engine, store: str, terminals: list[str], username: str,
          opening: dict[str, int]) -> int:
    with Session(engine) as session:
        session.add(Store(store_id=store, name="Traffic test", latitude=0, longitude=0, region_id="TEST"))
        session.add_all(Product(sku=sku, barcode=sku, name="Traffic product", category="TEST", unit_price=10)
                        for sku in opening)
        session.flush()
        session.add_all(PosTerminal(pos_id=pos, store_id=store, status="ACTIVE") for pos in terminals)
        for sku, quantity in opening.items():
            add_stock(session, store, sku, quantity)
        user = StaffUser(username=username, full_name="Traffic POS", role="POS_SYSTEM")
        session.add(user)
        session.flush()
        user_id = user.user_id
        session.commit()
        return user_id


def _cleanup(engine: Engine, store: str, user_id: int, opening: dict[str, int]) -> None:
    with Session(engine) as session:
        txns = select(PosTransaction.txn_id).where(PosTransaction.store_id == store)
        session.execute(delete(AuditLog).where(AuditLog.user_id == user_id))
        session.execute(delete(InventoryMovement).where(InventoryMovement.store_id == store))
        session.execute(delete(TransactionItem).where(TransactionItem.txn_id.in_(txns)))
        session.execute(delete(PosTransaction).where(
            PosTransaction.store_id == store, PosTransaction.ref_txn_id.is_not(None),
        ))
        session.execute(delete(PosTransaction).where(PosTransaction.store_id == store))
        session.execute(delete(Inventory).where(Inventory.store_id == store))
        session.execute(delete(ProductBatch).where(ProductBatch.store_id == store))
        session.execute(delete(PosTerminal).where(PosTerminal.store_id == store))
        session.execute(delete(Product).where(Product.sku.in_(opening)))
        session.execute(delete(StaffUser).where(StaffUser.user_id == user_id))
        session.execute(delete(Store).where(Store.store_id == store))
        session.commit()


def _traffic(store: str, terminals: list[str], skus: list[str]) -> tuple[list[dict], list[dict], list[dict]]:
    rng = Random(SEED)
    serial = 0

    def event(kind: str, items: list[dict], original: str | None = None) -> dict:
        nonlocal serial
        serial += 1
        return {
            "transaction_id": f"{store}-TX-{serial}", "event_type": kind,
            "store_id": store, "pos_id": terminals[(serial - 1) % len(terminals)],
            "timestamp": "2026-11-07T00:00:00Z", "items": items,
            "original_transaction_id": original,
        }

    def line(sku: str, quantity: int) -> dict:
        return {"sku": sku, "quantity": quantity, "unit_price": "10.00"}

    initial = [event("SALE", [line(rng.choice(skus), 2)]) for _ in range(40)]
    races = []
    for index, sale in enumerate(initial[:4]):
        sku = sale["items"][0]["sku"]
        txn = sale["transaction_id"]
        races.extend([
            event("RETURN", [line(sku, 2)], txn),
            event("RETURN", [line(sku, 2)], txn) if index % 2 == 0 else event("CANCELLATION", [], txn),
        ])
    mixed = [event("SALE", [line(sku, rng.randint(1, 3)) for sku in rng.sample(skus, rng.randint(1, 3))])
             for _ in range(52)]
    for index in range(32):
        sale = rng.choice(initial[4:])
        txn = sale["transaction_id"]
        sku = sale["items"][0]["sku"]
        mixed.append(event("RETURN", [line(sku, 1)], txn) if index % 3 else event("CANCELLATION", [], txn))
    # Replay 60 payloads unchanged, including reversals that may race their first attempt.
    mixed.extend(rng.sample(initial + races + mixed, 60))
    mixed.extend(event("SALE", [line(rng.choice(skus), 10000)]) for _ in range(8))
    rng.shuffle(mixed)
    assert sum(map(len, (initial, races, mixed))) == 200
    return initial, races, mixed


def _assert_persisted(engine: Engine, store: str, opening: dict[str, int], applied: Counter) -> None:
    with Session(engine) as session:
        assert_ledger_balanced(session, store, list(opening), opening)
        rows = list(session.scalars(select(PosTransaction).where(PosTransaction.store_id == store)))
        assert Counter(row.txn_id for row in rows) == applied
        audit_keys = session.scalars(select(AuditLog.entity_key).where(
            AuditLog.action == "STOCK_CHANGE", AuditLog.entity_key.in_(applied),
        ))
        assert Counter(audit_keys) == applied
        quantities = Counter()
        for txn, sku, qty in session.execute(select(
            TransactionItem.txn_id, TransactionItem.sku, TransactionItem.qty,
        ).join(PosTransaction, PosTransaction.txn_id == TransactionItem.txn_id)
          .where(PosTransaction.store_id == store)):
            quantities[txn, sku] += qty
        sales = {row.txn_id: row for row in rows if row.txn_type == "SALE"}
        returned = Counter()
        cancelled = set()
        for row in rows:
            if row.txn_type == "RETURN":
                assert row.ref_txn_id in sales
                for sku in opening:
                    returned[row.ref_txn_id, sku] += quantities[row.txn_id, sku]
            elif row.txn_type == "CANCELLATION":
                assert row.ref_txn_id in sales and row.ref_txn_id not in cancelled
                cancelled.add(row.ref_txn_id)
        assert cancelled == {txn for txn, sale in sales.items() if sale.status == "CANCELLED"}
        for (txn, sku), qty in returned.items():
            assert qty <= quantities[txn, sku]
            assert not qty or txn not in cancelled


def test_concurrency_mixed_traffic(test_engine, monkeypatch, caplog) -> None:
    suffix = uid(5)
    store = f"TEST-{suffix}"
    terminals = [f"TEST-POS-{suffix}-{i}" for i in range(3)]
    opening = {f"TEST-SKU-{suffix}-{i}": qty for i, qty in enumerate((600, 650, 700))}
    username = f"TEST-TRAFFIC-{suffix}"
    user_id = _seed(test_engine, store, terminals, username, opening)
    print(f"POS traffic seed={SEED}, events=200, workers={WORKERS}, scheduled replays=60", flush=True)
    try:
        tokens = {pos: create_token(username, "POS", store_id=store, pos_id=pos) for pos in terminals}
        initial, races, mixed = _traffic(store, terminals, list(opening))

        def request_session() -> Iterator[Session]:
            with Session(test_engine) as session:
                try:
                    yield session
                except BaseException:
                    session.rollback()
                    raise

        monkeypatch.setitem(app.dependency_overrides, get_db, request_session)
        started = monotonic()
        barrier = Barrier(WORKERS)
        with TestClient(app, raise_server_exceptions=False) as client, ThreadPoolExecutor(max_workers=WORKERS) as pool:
            def send(event: dict, *, race: bool = False) -> tuple[int, dict, int, float]:
                if race:
                    barrier.wait(timeout=10)
                retries = 0
                longest = 0.0
                while True:
                    attempt = monotonic()
                    response = post(client, event, tokens[event["pos_id"]])
                    longest = max(longest, monotonic() - attempt)
                    body = response.json()
                    if response.status_code != 503:
                        return response.status_code, body, retries, longest
                    assert (body["outcome"], body["code"]) == ("ERROR", "SERVICE_UNAVAILABLE")
                    retries += 1
                    assert monotonic() - started < TIME_LIMIT, (event["transaction_id"], retries)
                    sleep(0.05)

            initial_results = list(pool.map(send, initial))
            assert all(status == 200 and body["outcome"] == "OK" for status, body, _, _ in initial_results)
            race_results = list(pool.map(lambda event: send(event, race=True), races))
            mixed_results = list(pool.map(send, mixed))
        elapsed = monotonic() - started
        results = initial_results + race_results + mixed_results
        retries = sum(result[2] for result in results)
        deadlocks = sum("(1205)" in str(record.exc_info[1]) for record in caplog.records if record.exc_info)
        lock_timeouts = sum(
            record.name == "app.api.pos" and record.levelname == "WARNING"
            and "(SQL 1222)" in record.getMessage()
            for record in caplog.records
        )
        lock_errors = deadlocks + lock_timeouts
        outcomes = Counter(body["code"] for _, body, _, _ in results)
        print(f"POS traffic seed={SEED}, final={len(results)}, 503={retries}, SQL 1205={deadlocks}, "
              f"SQL 1222={lock_timeouts}, lock-related 503={lock_errors}, other 503={retries - lock_errors}, "
              f"elapsed={elapsed:.2f}s, "
              f"longest response={max(result[3] for result in results):.2f}s, codes={dict(outcomes)}", flush=True)
        sql_errors = Counter()
        for record in caplog.records:
            if record.exc_info:
                error = record.exc_info[1]
                numbers = findall(r"\((\d+)\)", str(getattr(error, "orig", error)))
                statement = " ".join((getattr(error, "statement", None) or "").split())
                sql_errors[(record.name, ",".join(numbers) or type(error).__name__, statement)] += 1
        for (logger, error, statement), occurrences in sql_errors.items():
            print(f"SQL diagnostic count={occurrences}, logger={logger}, error={error}, statement={statement}", flush=True)
        assert lock_errors <= retries
        assert len(results) == 200 and elapsed < TIME_LIMIT
        assert outcomes["DUPLICATE_IGNORED"] > 0 and outcomes["INSUFFICIENT_STOCK"] == 8
        for index in range(0, len(race_results), 2):
            assert sorted(result[0] for result in race_results[index:index + 2]) == [200, 409]
        applied = Counter()
        duplicates = set()
        for event, (status, body, _, _) in zip(initial + races + mixed, results, strict=True):
            txn = event["transaction_id"]
            if status == 200:
                if body["outcome"] == "OK":
                    assert body["code"] == "OK"
                    applied[txn] += 1
                else:
                    assert (body["outcome"], body["code"]) == ("DUPLICATE", "DUPLICATE_IGNORED")
                    duplicates.add(txn)
            else:
                assert status == 409 and body["outcome"] == "REJECTED" and body["code"] in REJECTIONS, (status, body)
        assert all(value == 1 for value in applied.values())
        assert duplicates <= applied.keys()
        _assert_persisted(test_engine, store, opening, applied)
    finally:
        _cleanup(test_engine, store, user_id, opening)
