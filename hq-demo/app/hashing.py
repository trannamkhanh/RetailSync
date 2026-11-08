"""DS-05 section 2: the SHA-256 of a compact, key-sorted batch message.

The middleware computes the same hash with ``batch_hash(message)`` before it
sends the batch. The canonical form is compact JSON with sorted keys over
``batch_id``, ``store_id``, ``txn_count`` and ``lines`` sorted by ``sku``, each
line with ``sku``, ``sold_qty``, ``returned_qty`` and ``net_revenue`` formatted
as a string with exactly two decimals, like the POS ``unit_price`` hash.
``created_at`` is excluded so a resend of the same batch keeps the hash.
"""

import hashlib
import json

from app.schemas import SyncBatchMessage


def batch_hash(message: SyncBatchMessage) -> str:
    payload = {
        "batch_id": message.batch_id,
        "store_id": message.store_id,
        "txn_count": message.txn_count,
        "lines": [
            {
                "sku": line.sku,
                "sold_qty": line.sold_qty,
                "returned_qty": line.returned_qty,
                "net_revenue": format(line.net_revenue, ".2f"),
            }
            for line in sorted(message.lines, key=lambda item: item.sku)
        ],
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
