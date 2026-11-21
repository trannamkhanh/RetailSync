from decimal import Decimal
from uuid import uuid4

from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.models import HqSyncBatch
from app.schemas import SalesLine
from app.service import _add_totals, _duplicate
from test_sync18 import _batch


def test_audit_minor_json_precision_is_validated_before_rounding(client, auth):
    import json
    raw = json.dumps(_batch("TEST-JSON")).replace("100.5", "0.10000000000000001")
    response = client.post("/api/v1/sync", content=raw, headers={**auth, "Content-Type": "application/json"})
    assert response.status_code == 422


def test_audit_minor_parallel_duplicate_reads_do_not_lose_increments(test_engine):
    batch = f"TEST-AUDIT-{uuid4().hex[:12]}"
    with Session(test_engine) as session, session.begin():
        session.add(HqSyncBatch(sync_batch_id=batch, store_id="TEST-AUD", txn_count=1, payload_hash="a" * 64))
    try:
        with Session(test_engine) as first, Session(test_engine) as second:
            a = first.get(HqSyncBatch, batch)
            b = second.get(HqSyncBatch, batch)
            _duplicate(first, a, "a" * 64)
            first.commit()
            _duplicate(second, b, "a" * 64)
            second.commit()
        with Session(test_engine) as session:
            assert session.get(HqSyncBatch, batch).duplicate_count == 2
    finally:
        with Session(test_engine) as session, session.begin():
            session.execute(delete(HqSyncBatch).where(HqSyncBatch.sync_batch_id == batch))


def test_audit_minor_hq_total_updates_follow_sku_order():
    observed = []

    class Updated:
        rowcount = 1

    class RecordingSession:
        def execute(self, statement):
            observed.append(statement.compile().params["sku_1"])
            return Updated()

    lines = [SalesLine(sku=sku, sold_qty=1, returned_qty=0, net_revenue=Decimal("1.25"))
             for sku in ("TEST-Z", "TEST-A")]
    _add_totals(RecordingSession(), "TEST-STORE", lines)
    assert observed == ["TEST-A", "TEST-Z"]
