from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import clock
from app.domain.models import Forecast, GuardrailResult, NearExpiryAlert, Product, Recommendation, Store
from app.jobs import recommendation as job
from app.repositories.forecast import utc_start
from app.services import guardrail_rules
from app.services.recommendation import near_expiry_proposal, surplus_proposal
from tests.pos_test_support import add_stock, uid


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


@pytest.fixture
def recommendation_world(db_session, monkeypatch):
    today = date(2026, 11, 23)
    suffix = uid(5)
    store, sku = f"TEST-{suffix}", f"TEST-SKU-{suffix}"
    db_session.add_all([
        Store(store_id=store, name="Recommendation", latitude=0, longitude=0, region_id="TEST"),
        Product(sku=sku, barcode=sku, name="Recommendation SKU", category="TEST", unit_price=10),
    ])
    db_session.flush()
    batch = add_stock(db_session, store, sku, 10, expiry_date=today + timedelta(days=1))
    db_session.add(NearExpiryAlert(batch_id=batch, store_id=store, sku=sku, days_to_expiry=7,
                                   remaining_qty=10, alert_type="NEAR_EXPIRY", status="OPEN"))
    connection = db_session.connection()
    db_session.commit()
    monkeypatch.setattr(clock, "today_local", lambda: today)
    monkeypatch.setattr(job, "session_factory",
                        lambda: Session(bind=connection, join_transaction_mode="create_savepoint"))
    return store, sku, batch


def test_rec25_8_second_run_does_not_duplicate_pending_recommendation(
    db_session, recommendation_world, monkeypatch,
):
    store, _, batch = recommendation_world
    monkeypatch.setattr(guardrail_rules, "active_rules", lambda session: [])
    assert job.run_recommendations()[store] == 1
    assert job.run_recommendations()[store] == 0
    row = db_session.scalars(select(Recommendation).where(Recommendation.store_id == store)).one()
    assert (row.status, row.batch_id, row.proposed_qty) == ("PENDING", batch, 10)
    assert row.alert_id is not None


def test_pb25_rules_unavailable_keeps_generated_and_recovers(
    db_session, recommendation_world, monkeypatch,
):
    store, _, _ = recommendation_world

    def unavailable(session):
        raise RuntimeError("forced rule read failure")

    monkeypatch.setattr(guardrail_rules, "active_rules", unavailable)
    assert job.run_recommendations()[store] == 1
    query = select(Recommendation).where(Recommendation.store_id == store)
    row = db_session.scalars(query).one()
    assert row.status == "GENERATED"
    assert db_session.scalar(select(GuardrailResult).where(GuardrailResult.rec_id == row.rec_id)) is None
    db_session.commit()

    monkeypatch.setattr(guardrail_rules, "active_rules", lambda session: [])
    assert job.run_recommendations()[store] == 0
    assert db_session.scalars(query).one().status == "PENDING"


def test_pb25_forecast_older_than_two_days_is_ignored(db_session, recommendation_world, monkeypatch):
    store, sku, _ = recommendation_world
    db_session.add(Forecast(
        store_id=store, sku=sku, horizon_days=7, predicted_demand=70, surplus_shortage=-60,
        balance_status="SHORTAGE", model_version="seasonal-naive-v1",
        created_at=utc_start(clock.today_local() - timedelta(days=3)),
    ))
    db_session.commit()
    monkeypatch.setattr(guardrail_rules, "active_rules", lambda session: [])
    assert job.run_recommendations()[store] == 1
    row = db_session.scalars(select(Recommendation).where(Recommendation.store_id == store)).one()
    assert (row.action_type, row.proposed_qty) == ("CLEARANCE", 10)
