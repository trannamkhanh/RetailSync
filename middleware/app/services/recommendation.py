"""Decision rules for recommendation candidates (DS-06, section 6)."""

from dataclasses import dataclass
from decimal import Decimal
from math import ceil


@dataclass(frozen=True)
class Proposal:
    action_type: str
    reason: str
    proposed_qty: int | None = None
    discount_pct: int | None = None


def near_expiry_proposal(
    batch_id: str, days: int, remaining: int, daily_demand: Decimal = Decimal(0),
) -> Proposal | None:
    if days < 0 or remaining <= 0:
        return None
    at_risk = max(0, ceil(remaining - daily_demand * (days + 1)))
    if at_risk == 0:
        return None
    reason = f"Batch {batch_id} expires in {days} day(s); {at_risk} of {remaining} units may not sell in time."
    if days <= 1 and at_risk * 5 >= remaining * 4:
        return Proposal("CLEARANCE", reason, proposed_qty=at_risk)
    discount = 50 if days <= 1 else 30 if days <= 3 else 15
    return Proposal("DISCOUNT", reason, discount_pct=discount)


def surplus_proposal(
    demand: Decimal, surplus: Decimal, shortage: tuple[str, Decimal] | None,
) -> Proposal | None:
    if surplus <= 0:
        return None
    if shortage is not None:
        other_store, units_short = shortage
        quantity = int(min(surplus, units_short))
        if quantity > 0:
            reason = f"{other_store} is short of {units_short:g} units; this store has {surplus:g} extra."
            return Proposal("REDISTRIBUTION", reason, proposed_qty=quantity)
    if surplus >= demand:
        stock = demand + surplus
        return Proposal("DISCOUNT", f"Forecast demand is {demand:g} units for 7 days; stock is {stock:g}.",
                        discount_pct=10)
    return None
