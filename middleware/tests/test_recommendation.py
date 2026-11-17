from decimal import Decimal

import pytest

from app.services.recommendation import near_expiry_proposal, surplus_proposal


def test_rec25_1_expired_batch_has_no_recommendation():
    assert near_expiry_proposal("TEST-B", -1, 10) is None


def test_rec25_2_demand_clears_batch():
    assert near_expiry_proposal("TEST-B", 1, 10, Decimal(5)) is None


def test_rec25_3_clearance_at_eighty_percent_risk():
    proposal = near_expiry_proposal("TEST-B", 1, 10, Decimal(1))
    assert (proposal.action_type, proposal.proposed_qty) == ("CLEARANCE", 8)


@pytest.mark.parametrize(("days", "discount"), [(1, 50), (2, 30), (3, 30), (4, 15)])
def test_rec25_4_discount_tiers(days, discount):
    proposal = near_expiry_proposal("TEST-B", days, 10, Decimal(2 if days <= 3 else 1))
    assert (proposal.action_type, proposal.discount_pct) == ("DISCOUNT", discount)


def test_rec25_5_redistribution_takes_priority():
    proposal = surplus_proposal(Decimal(10), Decimal(20), ("TEST-OTHER", Decimal(12)))
    assert (proposal.action_type, proposal.proposed_qty) == ("REDISTRIBUTION", 12)


def test_rec25_6_discount_requires_surplus_at_least_equal_to_demand():
    assert surplus_proposal(Decimal(10), Decimal(9), None) is None
    assert surplus_proposal(Decimal(10), Decimal(10), None).discount_pct == 10


def test_rec25_7_reason_includes_rounded_risk_and_remaining_quantity():
    proposal = near_expiry_proposal("TEST-B", 2, 10, Decimal("1.25"))
    assert proposal.reason == "Batch TEST-B expires in 2 day(s); 7 of 10 units may not sell in time."
