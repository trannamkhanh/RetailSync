"""Original-sale checks shared by RETURN (PB-06) and CANCELLATION (PB-07)."""

from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.core.errors import ApiError
from app.repositories import original_sale as repository


@dataclass(frozen=True)
class OriginalSale:
    txn_id: str
    status: str
    sold: dict[str, int]
    returned: dict[str, int]


def _not_found(txn_id: str) -> ApiError:
    return ApiError(404, "ORIGINAL_SALE_NOT_FOUND", f"Original sale '{txn_id}' was not found.")


def lock_original_sale(session: Session, store_id: str, txn_id: str) -> OriginalSale:
    """Lock the SALE and return its status plus sold and returned quantities.

    This is also the DS-04 not-found check: an unknown sale of this store raises
    404 ``ORIGINAL_SALE_NOT_FOUND`` here, before the caller's
    ``claim_transaction`` inserts the FK-bearing row. RETURN and CANCELLATION
    used to call a separate ``require_original_sale`` for that first, which was
    one unlock read of the same row on every reversal and became dead code once
    this call started coming first (review of PR #78).
    """
    row = repository.lock_sale(session, store_id, txn_id)
    if row is None:
        raise _not_found(txn_id)
    return OriginalSale(
        txn_id=str(row.txn_id),
        status=str(row.status),
        sold=repository.sold_quantities(session, txn_id),
        returned=repository.returned_quantities(session, store_id, txn_id),
    )
