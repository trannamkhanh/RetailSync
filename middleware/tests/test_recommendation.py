from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import clock
from app.domain.models import Forecast, GuardrailResult, GuardrailRule, NearExpiryAlert, Product, ProductBatch, Recommendation, StaffDecision, StaffUser, Store
from app.jobs import recommendation as job
from app.repositories.forecast import utc_start
from app.services import guardrail_rules

from tests.pos_test_support import add_stock, uid


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
    monkeypatch.setattr(guardrail_rules, "active_rules", lambda session: [])
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
    store, sku, _ = recommendation_world
    expired_batch = add_stock(db_session, store, sku, 3, expiry_date=clock.today_local() - timedelta(days=1))
    expired = Recommendation(store_id=store, sku=sku, batch_id=expired_batch,
                             action_type="CLEARANCE", proposed_qty=3, reason="Test expiry", status="PENDING")
    db_session.add(expired)
    db_session.commit()

    def unavailable(session):
        raise RuntimeError("forced rule read failure")

    monkeypatch.setattr(guardrail_rules, "active_rules", unavailable)
    assert job.run_recommendations()[store] == 1
    query = select(Recommendation).where(
        Recommendation.store_id == store, Recommendation.batch_id != expired_batch,
    )
    db_session.refresh(expired)
    assert expired.status == "EXPIRED"
    row = db_session.scalars(query).one()
    assert row.status == "GENERATED"
    assert db_session.scalar(select(GuardrailResult).where(GuardrailResult.rec_id == row.rec_id)) is None
    db_session.commit()

    monkeypatch.setattr(guardrail_rules, "active_rules", lambda session: [])
    assert job.run_recommendations()[store] == 0
    assert db_session.scalars(query).one().status == "PENDING"


def test_pb25_store_failure_rolls_back_and_other_store_still_saves(
    db_session, recommendation_world, monkeypatch,
):
    failing_store, sku, _ = recommendation_world
    surviving_store = f"TEST-Z{uid(4)}"
    db_session.add(Store(store_id=surviving_store, name="Other store", latitude=0, longitude=0, region_id="TEST"))
    db_session.flush()
    batch = add_stock(db_session, surviving_store, sku, 10, expiry_date=clock.today_local())
    db_session.add(NearExpiryAlert(batch_id=batch, store_id=surviving_store, sku=sku, days_to_expiry=0,
                                   remaining_qty=10, alert_type="NEAR_EXPIRY", status="OPEN"))
    db_session.commit()
    monkeypatch.setattr(guardrail_rules, "active_rules", lambda session: [])
    apply = job.apply_guardrails

    def fail_one_store(session, recommendation, **kwargs):
        if recommendation.store_id == failing_store:
            session.flush()
            raise RuntimeError("forced store failure")
        return apply(session, recommendation, **kwargs)

    monkeypatch.setattr(job, "apply_guardrails", fail_one_store)
    results = job.run_recommendations()
    assert failing_store not in results
    assert results[surviving_store] == 1
    rows = list(db_session.scalars(select(Recommendation).where(
        Recommendation.store_id.in_((failing_store, surviving_store)),
    )))
    assert [(row.store_id, row.status) for row in rows] == [(surviving_store, "PENDING")]


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

def set_forecast(session, store, sku, demand, balance=0):
    status = "SURPLUS" if balance > 0 else "SHORTAGE" if balance < 0 else "BALANCED"
    session.add(Forecast(store_id=store, sku=sku, horizon_days=7, predicted_demand=demand,
                         surplus_shortage=balance, balance_status=status,
                         model_version="seasonal-naive-v1", created_at=utc_start(clock.today_local())))


def recommendations(session, store):
    return list(session.scalars(select(Recommendation).where(
        Recommendation.store_id == store,
    ).order_by(Recommendation.rec_id).execution_options(populate_existing=True)))


@pytest.mark.parametrize(("days", "discount"), [(1, 50), (3, 30), (5, 15)])
def test_rec25_1_discount_tiers(db_session, recommendation_world, days, discount):
    store, sku, batch = recommendation_world
    db_session.get(ProductBatch, batch).expiry_date = clock.today_local() + timedelta(days=days)
    set_forecast(db_session, store, sku, 14 if days == 1 else 7)
    db_session.commit()
    assert job.run_recommendations()[store] == 1
    row, = recommendations(db_session, store)
    assert (row.action_type, row.discount_pct, row.batch_id) == ("DISCOUNT", discount, batch)


def test_rec25_2_clearance(db_session, recommendation_world):
    store, sku, _ = recommendation_world
    set_forecast(db_session, store, sku, 7)
    db_session.commit()
    assert job.run_recommendations()[store] == 1
    row, = recommendations(db_session, store)
    assert (row.action_type, row.proposed_qty) == ("CLEARANCE", 8)


def test_rec25_3_sales_clear_batch(db_session, recommendation_world):
    store, sku, _ = recommendation_world
    set_forecast(db_session, store, sku, 35)
    db_session.commit()
    assert job.run_recommendations()[store] == 0
    assert recommendations(db_session, store) == []


def test_rec25_4_expired_alert_is_ignored(db_session, recommendation_world):
    store, _, batch = recommendation_world
    alert = db_session.scalar(select(NearExpiryAlert).where(NearExpiryAlert.batch_id == batch))
    alert.alert_type = "EXPIRED"
    db_session.commit()
    assert job.run_recommendations()[store] == 0
    assert recommendations(db_session, store) == []


def remove_alert(session, batch):
    session.delete(session.scalar(select(NearExpiryAlert).where(NearExpiryAlert.batch_id == batch)))


def test_rec25_5_redistribution_takes_priority(db_session, recommendation_world):
    store, sku, batch = recommendation_world
    remove_alert(db_session, batch)
    other = f"TEST-Z{uid(4)}"
    db_session.add(Store(store_id=other, name="Shortage", latitude=0, longitude=0, region_id="TEST"))
    db_session.flush()
    set_forecast(db_session, store, sku, 10, 20)
    set_forecast(db_session, other, sku, 12, -12)
    db_session.commit()
    assert job.run_recommendations()[store] == 1
    row, = recommendations(db_session, store)
    assert (row.action_type, row.proposed_qty, row.batch_id) == ("REDISTRIBUTION", 12, None)


@pytest.mark.parametrize(("surplus", "expected"), [(9, 0), (10, 1)])
def test_rec25_6_surplus_discount_threshold(db_session, recommendation_world, surplus, expected):
    store, sku, batch = recommendation_world
    remove_alert(db_session, batch)
    set_forecast(db_session, store, sku, 10, surplus)
    db_session.commit()
    assert job.run_recommendations()[store] == expected
    rows = recommendations(db_session, store)
    assert len(rows) == expected
    if expected:
        assert (rows[0].action_type, rows[0].discount_pct) == ("DISCOUNT", 10)


def test_rec25_7_reason_contains_actual_values(db_session, recommendation_world):
    store, sku, batch = recommendation_world
    db_session.get(ProductBatch, batch).expiry_date = clock.today_local() + timedelta(days=2)
    set_forecast(db_session, store, sku, Decimal("8.75"))
    db_session.commit()
    assert job.run_recommendations()[store] == 1
    row, = recommendations(db_session, store)
    assert row.reason == f"Batch {batch} expires in 2 day(s); 7 of 10 units may not sell in time."


def decide(session, row, decision, decided_at):
    user = StaffUser(username=f"TEST-{uid(8)}", full_name="Test Staff", role="STORE_STAFF",
                     store_id=row.store_id, is_active=True)
    session.add(user)
    session.flush()
    row.status = {"ACCEPT": "ACCEPTED", "REJECT": "REJECTED"}[decision]
    session.add(StaffDecision(rec_id=row.rec_id, user_id=user.user_id,
                              decision=decision, decided_at=decided_at))
    session.commit()


@pytest.mark.parametrize("state", ["BLOCKED", "ACCEPTED", "REJECTED"])
@pytest.mark.parametrize("days_ago", [0, 1], ids=["today", "yesterday"])
def test_pb25_final_state_suppresses_only_same_business_date(
    db_session, recommendation_world, state, days_ago,
):
    store, _, batch = recommendation_world
    assert job.run_recommendations()[store] == 1
    original, = recommendations(db_session, store)
    business_date = clock.today_local() - timedelta(days=days_ago)
    timestamp = utc_start(business_date) + timedelta(minutes=1)
    # Always create the recommendation yesterday so decisions are checked by
    # decided_at, while BLOCKED uses its own creation timestamp.
    original.created_at = utc_start(clock.today_local() - timedelta(days=1))
    if state == "BLOCKED":
        original.status = state
        original.created_at = timestamp
        rule = GuardrailRule(rule_type="MIN_SHELF_LIFE", threshold=2, category=None, is_active=True)
        db_session.add(rule)
        db_session.flush()
        db_session.add(GuardrailResult(rec_id=original.rec_id, rule_id=rule.rule_id,
                                       outcome="BLOCKED", checked_at=timestamp))
        db_session.commit()
    else:
        decide(db_session, original, "ACCEPT" if state == "ACCEPTED" else "REJECT", timestamp)

    assert job.run_recommendations()[store] == days_ago
    rows = recommendations(db_session, store)
    assert len(rows) == 1 + days_ago
    assert rows[0].rec_id == original.rec_id
    assert rows[0].status == state
    if days_ago:
        assert (rows[1].batch_id, rows[1].status) == (batch, "PENDING")


@pytest.mark.parametrize(("decision", "created_days_ago", "sku_only"), [
    ("ACCEPT", 0, False), ("REJECT", 0, True), ("ACCEPT", 1, False),
])
def test_pb25_decided_today_prevents_recommendation_rerun(
    db_session, recommendation_world, decision, created_days_ago, sku_only,
):
    store, sku, batch = recommendation_world
    if sku_only:
        remove_alert(db_session, batch)
        set_forecast(db_session, store, sku, 10, 10)
        db_session.commit()
    assert job.run_recommendations()[store] == 1
    row, = recommendations(db_session, store)
    today = clock.today_local()
    row.created_at = utc_start(today - timedelta(days=created_days_ago))
    # This UTC timestamp falls on yesterday in UTC and today in business time.
    decide(db_session, row, decision, utc_start(today) + timedelta(minutes=1))
    assert job.run_recommendations()[store] == 0
    assert len(recommendations(db_session, store)) == 1


def test_pb25_rejection_yesterday_allows_higher_discount_today(db_session, recommendation_world, monkeypatch):
    store, sku, batch = recommendation_world
    today = clock.today_local()
    db_session.get(ProductBatch, batch).expiry_date = today + timedelta(days=2)
    # Make the first run N5, then move business time forward to the final two days.
    earlier = today - timedelta(days=2)
    monkeypatch.setattr(clock, "today_local", lambda: earlier)
    set_forecast(db_session, store, sku, 7)
    db_session.commit()
    assert job.run_recommendations()[store] == 1
    first, = recommendations(db_session, store)
    assert first.discount_pct == 15
    first.created_at = utc_start(earlier)
    decide(db_session, first, "REJECT", utc_start(today) - timedelta(seconds=1))

    monkeypatch.setattr(clock, "today_local", lambda: today)
    assert job.run_recommendations()[store] == 1
    first, second = recommendations(db_session, store)
    assert (first.status, second.action_type, second.discount_pct) == ("REJECTED", "DISCOUNT", 30)
