"""PB-52 demo dataset tests: 30 Vietnamese products, 6 categories, tiers, and S1/S2 scenarios."""

from collections import Counter
from datetime import date, timedelta
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import sys

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import clock
from app.domain.models import (
    Forecast,
    Inventory,
    NearExpiryAlert,
    NearExpiryConfig,
    Product,
    ProductBatch,
    Recommendation,
)
from app.jobs import forecast as forecast_job
from app.jobs import near_expiry as near_expiry_job
from app.jobs import recommendation as recommendation_job
from app.repositories import forecast as forecast_repo
from tests.test_seed_demo_catalog import PRODUCTS as BASE_PRODUCTS, STORES, run_seed as run_base_seed

REPO = Path(__file__).resolve().parents[2]
DEMO_SEED = REPO / "database" / "seed" / "demo" / "001_demo_catalog_30.sql"
HISTORY_ROOT = REPO / "tools" / "history-generator"
if str(HISTORY_ROOT) not in sys.path:
    sys.path.insert(0, str(HISTORY_ROOT))

EXPECTED_CATEGORIES = {"Dairy", "Bakery", "Dry goods", "Beverages", "Snacks", "Frozen"}
EXPECTED_THRESHOLDS = {
    "Dairy": 3,
    "Bakery": 2,
    "Dry goods": 30,
    "Beverages": 7,
    "Snacks": 30,
    "Frozen": 14,
}
TIERS = {(80, 60, 45), (55, 45, 30), (40, 25, 15)}
NEW_SKUS = {f"SKU-{i:04d}" for i in range(10, 31)}
ALL_SKUS = set(BASE_PRODUCTS) | NEW_SKUS
FIXED_TODAY = date(2026, 11, 28)


def _apply_demo_seed(session: Session) -> None:
    assert DEMO_SEED.is_file(), f"Missing demo seed: {DEMO_SEED}"
    run_base_seed(session)
    batches_seed = REPO / "database" / "seed" / "003_demo_batches.sql"
    thresholds_seed = REPO / "database" / "seed" / "004_near_expiry_defaults.sql"
    session.connection().exec_driver_sql(batches_seed.read_text(encoding="utf-8"))
    session.connection().exec_driver_sql(thresholds_seed.read_text(encoding="utf-8"))
    session.connection().exec_driver_sql(DEMO_SEED.read_text(encoding="utf-8"))
    session.expire_all()


def test_pb52_demo_seed_creates_30_vietnamese_products_6_categories_and_tiers(db_session):
    _apply_demo_seed(db_session)
    # Idempotent when run a second time.
    db_session.connection().exec_driver_sql(DEMO_SEED.read_text(encoding="utf-8"))
    db_session.expire_all()

    products = {
        row.sku: row
        for row in db_session.scalars(select(Product).where(Product.sku.in_(ALL_SKUS)))
    }
    assert set(products) == ALL_SKUS
    assert len(products) == 30

    # Categories stay English in DB and cover all 6 categories.
    category_counts = Counter(row.category for row in products.values())
    assert set(category_counts) == EXPECTED_CATEGORIES
    assert sum(category_counts.values()) == 30

    # Old 9 SKUs keep barcodes, categories, prices, and get Vietnamese names.
    for sku, (barcode, english_name, category, unit_price) in BASE_PRODUCTS.items():
        row = products[sku]
        assert row.barcode == barcode
        assert row.category == category
        assert row.unit_price == unit_price
        assert row.name != english_name
        assert row.name.strip()
    assert products["SKU-0001"].name == "Sữa tươi 1L"

    # All 30 products have unique barcodes and Vietnamese/non-empty names.
    assert len({row.barcode for row in products.values()}) == 30
    assert all(row.name.strip() for row in products.values())

    # Near-expiry thresholds include the 3 new English categories.
    configs = {
        row.category: row.threshold_days
        for row in db_session.scalars(
            select(NearExpiryConfig).where(NearExpiryConfig.category.in_(EXPECTED_CATEGORIES))
        )
    }
    assert configs == EXPECTED_THRESHOLDS

    # Stock quantities: old 9 keep 40/25/15; new 21 split across the 3 tiers.
    stock = {
        (row.store_id, row.sku): row.quantity
        for row in db_session.scalars(
            select(Inventory).where(Inventory.store_id.in_(STORES), Inventory.sku.in_(ALL_SKUS))
        )
    }
    assert len(stock) == 90
    for sku in BASE_PRODUCTS:
        assert (stock[("STORE-DN1", sku)], stock[("STORE-DN2", sku)], stock[("STORE-DN3", sku)]) == (40, 25, 15)

    seen_tiers = set()
    for sku in NEW_SKUS:
        triple = (stock[("STORE-DN1", sku)], stock[("STORE-DN2", sku)], stock[("STORE-DN3", sku)])
        assert triple in TIERS, f"{sku} has unexpected tier {triple}"
        seen_tiers.add(triple)
    assert seen_tiers == TIERS


def test_pb52_demo_seed_batches_expire_outside_near_expiry_thresholds(db_session):
    _apply_demo_seed(db_session)

    today = clock.today_local()
    products = {
        row.sku: row
        for row in db_session.scalars(select(Product).where(Product.sku.in_(NEW_SKUS)))
    }
    inventory = {
        (row.store_id, row.sku): row.quantity
        for row in db_session.scalars(
            select(Inventory).where(Inventory.store_id.in_(STORES), Inventory.sku.in_(NEW_SKUS))
        )
    }
    batches = list(
        db_session.scalars(
            select(ProductBatch).where(ProductBatch.store_id.in_(STORES), ProductBatch.sku.in_(NEW_SKUS))
        )
    )
    assert batches

    sums = Counter()
    for batch in batches:
        sums[(batch.store_id, batch.sku)] += batch.quantity
        threshold = EXPECTED_THRESHOLDS[products[batch.sku].category]
        days_left = (batch.expiry_date - today).days
        assert days_left > threshold, (
            f"{batch.batch_id} expires in {days_left}d <= threshold {threshold}d"
        )
        # Keep new Dairy SKUs outside the Act 6 step 2 raised threshold (7 days) too.
        if products[batch.sku].category == "Dairy":
            assert days_left > 7

    assert dict(sums) == inventory


def test_pb52_demo_profile_forecast_and_recommendations_produce_s1_and_s2(db_session, monkeypatch):
    from history_generator.loader import load_history

    _apply_demo_seed(db_session)
    connection = db_session.connection()
    savepoint_factory = lambda: Session(bind=connection, join_transaction_mode="create_savepoint")
    monkeypatch.setattr(clock, "today_local", lambda: FIXED_TODAY)
    monkeypatch.setattr(forecast_job, "session_factory", savepoint_factory)
    monkeypatch.setattr(near_expiry_job, "session_factory", savepoint_factory)
    monkeypatch.setattr(recommendation_job, "session_factory", savepoint_factory)

    # Isolate demand loading to our 3 demo stores and 30 demo SKUs.
    orig_load = forecast_repo.load_demand
    monkeypatch.setattr(
        forecast_repo,
        "load_demand",
        lambda session, end: [
            d for d in orig_load(session, end, history_only=True)
            if d.store in STORES and d.sku in ALL_SKUS
        ],
    )

    txn_count = load_history(db_session, 90, 42, FIXED_TODAY, store_ids=set(STORES), demo_profile=True)
    assert txn_count > 0
    db_session.flush()

    saved = forecast_job.run_forecast()
    assert sum(saved.values()) == 90

    forecasts = list(
        db_session.scalars(
            select(Forecast).where(
                Forecast.store_id.in_(STORES),
                Forecast.sku.in_(ALL_SKUS),
                Forecast.created_at >= forecast_repo.utc_start(FIXED_TODAY),
            )
        )
    )
    assert len(forecasts) == 90
    by_pair = {(row.store_id, row.sku): row for row in forecasts}
    statuses = Counter(row.balance_status for row in forecasts)
    assert statuses["SURPLUS"] > 0
    assert statuses["SHORTAGE"] > 0
    assert statuses["BALANCED"] > 0

    # At least 3 products with SURPLUS at Thanh Khê (STORE-DN2) and SHORTAGE at Hải Châu (STORE-DN1).
    s1_skus = [
        sku for sku in sorted(NEW_SKUS)
        if by_pair[("STORE-DN2", sku)].balance_status == "SURPLUS"
        and by_pair[("STORE-DN1", sku)].balance_status == "SHORTAGE"
    ]
    assert len(s1_skus) >= 3, f"Expected >= 3 S1 SKUs, got {s1_skus}"

    # At least 2 products with SURPLUS at both DN1 and DN2 and surplus >= demand (10% discount S2).
    s2_skus = [
        sku for sku in sorted(NEW_SKUS)
        if by_pair[("STORE-DN1", sku)].balance_status == "SURPLUS"
        and by_pair[("STORE-DN2", sku)].balance_status == "SURPLUS"
        and by_pair[("STORE-DN3", sku)].balance_status != "SHORTAGE"
        and by_pair[("STORE-DN1", sku)].surplus_shortage >= by_pair[("STORE-DN1", sku)].predicted_demand
        and by_pair[("STORE-DN2", sku)].surplus_shortage >= by_pair[("STORE-DN2", sku)].predicted_demand
    ]
    assert len(s2_skus) >= 2, f"Expected >= 2 S2 SKUs, got {s2_skus}"

    # Near-expiry check should flag zero new SKUs.
    near_expiry_job.run_near_expiry_check()
    new_alerts = list(
        db_session.scalars(
            select(NearExpiryAlert).where(
                NearExpiryAlert.store_id.in_(STORES),
                NearExpiryAlert.sku.in_(NEW_SKUS),
                NearExpiryAlert.status == "OPEN",
            )
        )
    )
    assert new_alerts == []

    # Recommendations must include S1 REDISTRIBUTION at STORE-DN2 and S2 10% DISCOUNT at both DN1 & DN2.
    recommendation_job.run_recommendations()
    recs = list(
        db_session.scalars(
            select(Recommendation).where(
                Recommendation.store_id.in_(STORES),
                Recommendation.sku.in_(NEW_SKUS),
                Recommendation.status == "PENDING",
            )
        )
    )
    redist_skus = {
        row.sku for row in recs
        if row.store_id == "STORE-DN2" and row.action_type == "REDISTRIBUTION"
    }
    assert len(redist_skus) >= 3, f"Expected >= 3 REDISTRIBUTION recs at STORE-DN2, got {redist_skus}"

    s2_dn1 = {
        row.sku for row in recs
        if row.store_id == "STORE-DN1" and row.action_type == "DISCOUNT" and row.discount_pct == 10
    }
    s2_dn2 = {
        row.sku for row in recs
        if row.store_id == "STORE-DN2" and row.action_type == "DISCOUNT" and row.discount_pct == 10
    }
    assert len(s2_dn1 & s2_dn2) >= 2, f"Expected >= 2 shared S2 10% DISCOUNT SKUs, got DN1={s2_dn1}, DN2={s2_dn2}"


def test_pb52_smoke_script_accepts_30_skus_in_store_inventory(monkeypatch, capsys):
    spec = spec_from_file_location("pb52_smoke", REPO / "scripts" / "demo" / "sprint2_smoke.py")
    script = module_from_spec(spec)
    spec.loader.exec_module(script)

    monkeypatch.setattr(script, "TOKENS", {k: "tok" for k in ("staff_dn1", "admin", "auditor", "POS-DN1-01")})

    def fake_call(method, url, body=None, token=None, cert_pos=None):
        if method == "GET" and url.endswith("/stores/STORE-DN1/inventory"):
            return 200, {"items": [{"sku": f"SKU-{i:04d}", "quantity": 40} for i in range(1, 31)]}
        return 500, {}

    monkeypatch.setattr(script, "call", fake_call)
    monkeypatch.setattr(script, "pos_call", lambda *args, **kwargs: (500, {}))
    monkeypatch.setattr(script, "stock", lambda *args, **kwargs: 40)

    script.run()
    out = capsys.readouterr().out
    assert "PASS  [10] Staff reads STORE-DN1: 200, 30 SKUs" in out
