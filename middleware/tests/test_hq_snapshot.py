"""HQ snapshot refusal on real SQL Server (PB-13-1 to 13-4).

Every test creates its own rows with a ``TEST-`` prefix and never depends on
seed data. The concurrency test commits real rows, so it deletes them again.
"""

from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
import re
from threading import Barrier

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import Engine, delete, func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.db import get_db
from app.core.security import create_token
from app.domain.models import (
    AuditLog, Inventory, InventoryMovement, PosTerminal, PosTransaction,
    Product, ProductBatch, StaffUser, Store, TransactionItem,
)
from app.main import app
from app.services.hq_snapshot import MAX_SNAPSHOT_BYTES
from tests.pos_test_support import add_stock, assert_ledger_balanced, post, uid


SECRET = "test-only-secret-with-enough-length-for-hs256"
URL = "/api/v1/hq/snapshot"
SKU = "TEST-SNAP-SKU"


@pytest.fixture(autouse=True)
def jwt_secret(monkeypatch):
    monkeypatch.setattr(settings, "jwt_secret", SecretStr(SECRET))


def account(session: Session, username: str, role: str,
            store_id: str | None = None) -> StaffUser:
    user = StaffUser(username=username, full_name="Snapshot test account",
                     role=role, store_id=store_id)
    session.add(user)
    session.flush()
    return user


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def assert_rejected(response, status: int, code: str) -> dict:
    assert response.status_code == status, response.text
    body = response.json()
    assert set(body) == {"outcome", "code", "message"}
    assert (body["outcome"], body["code"]) == ("REJECTED", code)
    return body


def audits(session: Session) -> list[AuditLog]:
    session.flush()
    return list(session.scalars(
        select(AuditLog).where(AuditLog.action == "SNAPSHOT_REJECTED")
        .order_by(AuditLog.audit_id)
    ))


@pytest.fixture
def world(db_session: Session) -> dict:
    store_id = f"TEST-{uid(5)}"
    db_session.add(Store(store_id=store_id, name="Snapshot store",
                         latitude=Decimal("16.000000"), longitude=Decimal("108.000000"),
                         region_id="TEST"))
    db_session.add(Product(sku=SKU, barcode=f"BC-{SKU}", name="Snapshot product",
                           category="TEST", unit_price=Decimal("10.00")))
    db_session.flush()
    add_stock(db_session, store_id, SKU, 40)
    hq = account(db_session, f"TEST-hq-{uid(6)}", "HQ_OPERATOR")
    staff = account(db_session, f"TEST-staff-{uid(6)}", "STORE_STAFF", store_id)
    return {
        "store_id": store_id,
        "hq": hq,
        "staff": staff,
        "hq_token": create_token(hq.username, "HQ"),
        "staff_token": create_token(staff.username, "Staff", store_id=store_id),
    }


def stock_of(session: Session, store_id: str) -> int:
    session.expire_all()
    return session.get(Inventory, (store_id, SKU)).quantity


# INV13-1


def test_inv13_1_authorized_snapshot_is_refused_and_changes_no_stock(client, db_session, world):
    before = stock_of(db_session, world["store_id"])

    response = client.post(URL, headers=bearer(world["hq_token"]),
                           json={"store_id": world["store_id"], "items": [{"sku": SKU, "quantity": 0}]})

    assert_rejected(response, 422, "SNAPSHOT_REJECTED")
    assert stock_of(db_session, world["store_id"]) == before
    assert db_session.scalar(select(func.count()).select_from(PosTransaction).where(
        PosTransaction.store_id == world["store_id"])) == 0


def test_inv13_1_snapshot_does_not_touch_batches(client, db_session, world):
    before = db_session.scalar(select(func.sum(ProductBatch.quantity)))

    client.post(URL, headers=bearer(world["hq_token"]), json={"store_id": world["store_id"]})

    assert db_session.scalar(select(func.sum(ProductBatch.quantity))) == before


# INV13-2


def test_inv13_2_the_attempt_is_audited(client, db_session, world):
    body = {"store_id": world["store_id"], "items": []}

    client.post(URL, headers=bearer(world["hq_token"]), json=body)

    rows = audits(db_session)
    assert len(rows) == 1
    row = rows[0]
    assert (row.entity_name, row.entity_key) == ("hq_snapshot", None)
    assert row.user_id == world["hq"].user_id
    assert row.created_at is not None


def test_inv13_2_details_name_the_size_and_the_store(client, db_session, world):
    body = {"store_id": world["store_id"]}

    client.post(URL, headers=bearer(world["hq_token"]), json=body)

    details = audits(db_session)[0].details
    assert re.search(r"\b\d+ bytes\b", details)
    assert world["store_id"] in details


def test_inv13_2_details_omit_a_store_the_body_does_not_name(client, db_session, world):
    client.post(URL, headers=bearer(world["hq_token"]), json={"items": []})

    details = audits(db_session)[0].details
    assert "store" not in details.lower()


def test_inv13_2_every_attempt_writes_its_own_row(client, db_session, world):
    for _ in range(3):
        client.post(URL, headers=bearer(world["hq_token"]), json={"store_id": world["store_id"]})

    assert len(audits(db_session)) == 3


def test_inv13_2_a_hostile_store_value_never_becomes_the_audit_key(client, db_session, world):
    client.post(URL, headers=bearer(world["hq_token"]),
                json={"store_id": "STORE.1; DROP TABLE dbo.store"})

    row = audits(db_session)[0]
    assert row.entity_key is None
    assert "STORE.1; DROP TABLE dbo.store" not in (row.details or "")


# INV13-3


@pytest.mark.parametrize("content", [b"{", b"not json", b"[]", b'"text"', b"null"])
def test_inv13_3_bad_json_from_an_authorized_caller_is_still_snapshot_rejected(
        client, db_session, world, content):
    response = client.post(URL, headers={**bearer(world["hq_token"]),
                                         "Content-Type": "application/json"}, content=content)

    assert_rejected(response, 422, "SNAPSHOT_REJECTED")
    assert len(audits(db_session)) == 1


def test_inv13_3_a_body_over_one_megabyte_is_refused_with_413(client, db_session, world):
    response = client.post(URL, headers={**bearer(world["hq_token"]),
                                         "Content-Type": "application/json"},
                           content=b"x" * (MAX_SNAPSHOT_BYTES + 1))

    assert_rejected(response, 413, "PAYLOAD_TOO_LARGE")
    assert audits(db_session) == []


def test_inv13_3_a_body_of_exactly_one_megabyte_is_still_audited(client, db_session, world):
    body = b"{" + b" " * (MAX_SNAPSHOT_BYTES - 2) + b"}"

    response = client.post(URL, headers={**bearer(world["hq_token"]),
                                         "Content-Type": "application/json"}, content=body)

    assert_rejected(response, 422, "SNAPSHOT_REJECTED")
    assert len(audits(db_session)) == 1


def test_inv13_3_deeply_nested_json_is_refused_and_audited(client, db_session, world):
    before = stock_of(db_session, world["store_id"])
    body = b"[" * 20_000 + b"]" * 20_000

    response = client.post(URL, headers={**bearer(world["hq_token"]),
                                         "Content-Type": "application/json"}, content=body)

    assert_rejected(response, 422, "SNAPSHOT_REJECTED")
    assert len(audits(db_session)) == 1
    assert stock_of(db_session, world["store_id"]) == before


@pytest.mark.parametrize("store_first", [True, False])
def test_inv13_3_deep_object_preserves_store_in_audit(client, db_session, world, store_first):
    before = stock_of(db_session, world["store_id"])
    nested = b'"items":' + b"[" * 20_000 + b"]" * 20_000
    store = b'"store_id":"' + world["store_id"].encode() + b'"'
    body = b"{" + (store + b"," + nested if store_first else nested + b"," + store) + b"}"

    response = client.post(URL, headers=bearer(world["hq_token"]), content=body)

    assert_rejected(response, 422, "SNAPSHOT_REJECTED")
    rows = audits(db_session)
    assert len(rows) == 1
    assert world["store_id"] in rows[0].details
    assert f"{len(body)} bytes" in rows[0].details
    assert stock_of(db_session, world["store_id"]) == before


def test_inv13_3_invalid_deep_object_does_not_name_a_store(client, db_session, world):
    body = (b'{"store_id":"' + world["store_id"].encode() + b'","items":'
            + b"[" * 20_000 + b"]" * 20_000 + b",}")

    response = client.post(URL, headers=bearer(world["hq_token"]), content=body)

    assert_rejected(response, 422, "SNAPSHOT_REJECTED")
    rows = audits(db_session)
    assert len(rows) == 1
    assert world["store_id"] not in rows[0].details


def test_inv13_3_the_limit_is_the_one_ds04_names():
    assert MAX_SNAPSHOT_BYTES == 1_048_576


# INV13-5


def test_inv13_5_missing_token_gets_401_and_writes_nothing(client, db_session, world):
    response = client.post(URL, json={"store_id": world["store_id"]})

    assert_rejected(response, 401, "UNAUTHORIZED")
    assert audits(db_session) == []


@pytest.mark.parametrize(("db_role", "api_role"), [
    ("POS_SYSTEM", "POS"), ("STORE_STAFF", "Staff"), ("STORE_MANAGER", "Manager"),
    ("ADMIN", "Admin"), ("AUDITOR", "Auditor"),
])
def test_inv13_5_only_the_hq_role_may_call_it(client, db_session, world, db_role, api_role):
    username = f"TEST-{api_role.lower()}-{uid(6)}"
    account(db_session, username, db_role, world["store_id"] if api_role != "Admin" else None)

    response = client.post(URL, headers=bearer(create_token(username, api_role)),
                           json={"store_id": world["store_id"]})

    assert_rejected(response, 403, "FORBIDDEN")
    assert audits(db_session) == []


def test_inv13_5_an_inactive_hq_account_is_refused(client, db_session, world):
    world["hq"].is_active = False
    db_session.flush()

    response = client.post(URL, headers=bearer(world["hq_token"]), json={})

    assert_rejected(response, 403, "FORBIDDEN")
    assert audits(db_session) == []


# INV13-4: sales keep running while snapshots arrive


def _seed(engine: Engine, store: str, pos_id: str, username: str, hq_username: str,
          opening: dict[str, int]) -> tuple[int, int]:
    with Session(engine) as session:
        session.add(Store(store_id=store, name="Snapshot traffic", latitude=0,
                          longitude=0, region_id="TEST"))
        session.add_all(Product(sku=sku, barcode=sku, name="Snapshot traffic product",
                                category="TEST", unit_price=10) for sku in opening)
        session.flush()
        session.add(PosTerminal(pos_id=pos_id, store_id=store, status="ACTIVE"))
        for sku, quantity in opening.items():
            add_stock(session, store, sku, quantity)
        pos_user = StaffUser(username=username, full_name="Snapshot traffic POS",
                             role="POS_SYSTEM")
        hq_user = StaffUser(username=hq_username, full_name="Snapshot traffic HQ",
                            role="HQ_OPERATOR")
        session.add_all([pos_user, hq_user])
        session.flush()
        ids = (pos_user.user_id, hq_user.user_id)
        session.commit()
        return ids


def _cleanup(engine: Engine, store: str, user_ids: tuple[int, int], opening: dict[str, int]) -> None:
    with Session(engine) as session:
        txns = select(PosTransaction.txn_id).where(PosTransaction.store_id == store)
        session.execute(delete(AuditLog).where(AuditLog.user_id.in_(user_ids)))
        session.execute(delete(InventoryMovement).where(InventoryMovement.store_id == store))
        session.execute(delete(TransactionItem).where(TransactionItem.txn_id.in_(txns)))
        session.execute(delete(PosTransaction).where(
            PosTransaction.store_id == store, PosTransaction.ref_txn_id.is_not(None)))
        session.execute(delete(PosTransaction).where(PosTransaction.store_id == store))
        session.execute(delete(Inventory).where(Inventory.store_id == store))
        session.execute(delete(ProductBatch).where(ProductBatch.store_id == store))
        session.execute(delete(PosTerminal).where(PosTerminal.store_id == store))
        session.execute(delete(Product).where(Product.sku.in_(opening)))
        session.execute(delete(StaffUser).where(StaffUser.user_id.in_(user_ids)))
        session.execute(delete(Store).where(Store.store_id == store))
        session.commit()


def test_inv13_4_sales_and_snapshots_do_not_interfere(test_engine, monkeypatch):
    suffix = uid(5)
    store = f"TEST-{suffix}"
    pos_id = f"TEST-POS-{suffix}"
    username = f"TEST-SNAP-POS-{suffix}"
    hq_username = f"TEST-SNAP-HQ-{suffix}"
    opening = {f"TEST-SKU-{suffix}-{i}": qty for i, qty in enumerate((200, 200))}
    user_ids = _seed(test_engine, store, pos_id, username, hq_username, opening)
    skus = list(opening)
    pos_token = create_token(username, "POS", store_id=store, pos_id=pos_id)
    hq_token = create_token(hq_username, "HQ")
    barrier = Barrier(4)

    def request_session() -> Iterator[Session]:
        with Session(test_engine) as session:
            try:
                yield session
            except BaseException:
                session.rollback()
                raise

    def event(kind: str, txn: str, items: list[dict], original: str | None = None) -> dict:
        return {
            "event_type": kind, "transaction_id": txn, "store_id": store, "pos_id": pos_id,
            "timestamp": "2026-11-14T03:15:00Z", "items": items,
            "original_transaction_id": original,
        }

    def line(sku: str, quantity: int) -> dict:
        return {"sku": sku, "quantity": quantity, "unit_price": "10.00"}

    try:
        monkeypatch.setitem(app.dependency_overrides, get_db, request_session)
        with TestClient(app, raise_server_exceptions=False) as client:
            sales = []
            for index in range(4):
                txn = f"{store}-S{index}"
                sales.append(txn)
                response = post(client, event("SALE", txn, [line(skus[index % 2], 2)]), pos_token)
                assert response.status_code == 200, response.text

            def send_sale(index: int):
                return post(client, event("SALE", f"{store}-N{index}",
                                          [line(skus[index % 2], 1)]), pos_token)

            def send_return(index: int):
                return post(client, event("RETURN", f"{store}-R{index}",
                                          [line(skus[index % 2], 1)], sales[index]), pos_token)

            def send_cancellation(index: int):
                return post(client, event("CANCELLATION", f"{store}-C{index}", [],
                                          sales[index]), pos_token)

            def send_snapshot(index: int):
                barrier.wait(timeout=20)
                return client.post(URL, headers=bearer(hq_token),
                                   json={"store_id": store, "items": [{"sku": skus[0], "quantity": 0}]})

            work = [
                lambda: send_sale(0), lambda: send_sale(1),
                lambda: send_return(2), lambda: send_return(3),
                lambda: send_cancellation(0), lambda: send_cancellation(1),
            ]
            snapshot_work = [lambda index=index: send_snapshot(index) for index in range(4)]
            with ThreadPoolExecutor(max_workers=len(work) + len(snapshot_work)) as pool:
                futures = [pool.submit(run) for run in work + snapshot_work]
                responses = [future.result() for future in futures]
        events = responses[:len(work)]
        snapshots = responses[len(work):]

        for response in snapshots:
            assert_rejected(response, 422, "SNAPSHOT_REJECTED")
        for response in events:
            assert response.status_code == 200, response.text
            assert response.json()["outcome"] == "OK"

        with Session(test_engine) as session:
            assert_ledger_balanced(session, store, skus, opening)
            assert session.scalar(select(func.count()).select_from(AuditLog).where(
                AuditLog.action == "SNAPSHOT_REJECTED",
                AuditLog.user_id == user_ids[1])) == len(snapshots)
    finally:
        monkeypatch.undo()
        _cleanup(test_engine, store, user_ids, opening)
