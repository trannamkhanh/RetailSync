"""The SyncBatchMessage sent to HQ and its hash (PB-15-2; DS-04, DS-05 section 2).

The message is built from what PB-14 stored, so a resend of the same batch
builds the same message and the same hash.
"""

from decimal import Decimal
import hashlib
import json

from sqlalchemy.orm import Session

from app.repositories import sync_batches as repository


CENT = Decimal("0.01")


def build_message(session: Session, sync_batch_id: str) -> dict:
    batch = repository.find_batch(session, sync_batch_id)
    if batch is None:
        raise LookupError(f"Sync batch '{sync_batch_id}' does not exist.")
    return {
        "batch_id": batch.sync_batch_id,
        "store_id": batch.store_id,
        "created_at": f"{batch.created_at.isoformat()}Z",
        "txn_count": batch.txn_count,
        "lines": [
            {
                "sku": line.sku,
                "sold_qty": int(line.sold_qty),
                "returned_qty": int(line.returned_qty),
                "net_revenue": Decimal(line.net_revenue).quantize(CENT),
            }
            for line in sorted(repository.summary_lines(session, sync_batch_id), key=lambda row: row.sku)
        ],
    }


def batch_hash(message: dict) -> str:
    """SHA-256 of compact, key-sorted JSON over batch_id, store_id, txn_count and
    the lines sorted by sku, with net_revenue as a two-decimal string.
    created_at is left out, so a resend keeps the hash."""
    canonical = {
        "batch_id": message["batch_id"],
        "store_id": message["store_id"],
        "txn_count": message["txn_count"],
        "lines": [
            {
                "sku": line["sku"],
                "sold_qty": line["sold_qty"],
                "returned_qty": line["returned_qty"],
                "net_revenue": format(Decimal(str(line["net_revenue"])), ".2f"),
            }
            for line in sorted(message["lines"], key=lambda item: item["sku"])
        ],
    }
    text = json.dumps(canonical, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
