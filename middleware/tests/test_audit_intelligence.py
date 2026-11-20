"""Minor audit regressions for forecasts, demo scripts and inactive stores."""

from datetime import date, timedelta
from importlib.util import module_from_spec, spec_from_file_location
from io import BytesIO
from pathlib import Path
import urllib.error

import pytest
from sqlalchemy import select

from app.core import clock
from app.domain.models import NearExpiryAlert, ProductBatch, Store
from app.jobs import recommendation as job
from app.repositories.forecast import Demand
from app.services.forecast import _features
from tests.pos_test_support import uid
from tests.test_recommendation import recommendation_world, recommendations, set_forecast


ROOT = Path(__file__).resolve().parents[2]


def module(name, relative):
    spec = spec_from_file_location(name, ROOT / relative)
    loaded = module_from_spec(spec)
    spec.loader.exec_module(loaded)
    return loaded


def test_audit15_rolling_mean_uses_available_history():
    demand = Demand("TEST-STORE", "TEST-SKU", "TEST", 10, date(2026, 1, 1), (8,) * 14)
    assert _features(demand, date(2026, 1, 15), demand.values)["mean_28"] == 8


def test_audit09_inactive_source_store_is_skipped(db_session, recommendation_world):
    store, _, _ = recommendation_world
    db_session.get(Store, store).is_active = False
    db_session.commit()
    assert store not in job.run_recommendations()
    assert recommendations(db_session, store) == []


def test_audit09_inactive_redistribution_target_is_skipped(db_session, recommendation_world):
    store, sku, batch = recommendation_world
    db_session.delete(db_session.scalar(select(NearExpiryAlert).where(NearExpiryAlert.batch_id == batch)))
    other = f"TEST-Z{uid(4)}"
    db_session.add(Store(store_id=other, name="Inactive target", latitude=0, longitude=0,
                         region_id="TEST", is_active=False))
    db_session.flush()
    set_forecast(db_session, store, sku, 10, 20)
    set_forecast(db_session, other, sku, 20, -20)
    db_session.commit()
    job.run_recommendations()
    row, = recommendations(db_session, store)
    assert (row.action_type, row.discount_pct) == ("DISCOUNT", 10)


def test_audit15_snapshot_probe_handles_html_error(monkeypatch):
    script = module("audit_snapshot", "scripts/demo/snapshot_during_sales.py")
    error = urllib.error.HTTPError("https://example.invalid", 502, "Bad Gateway", {},
                                   BytesIO(b"<html>upstream unavailable</html>"))

    def fail(*args, **kwargs):
        raise error

    monkeypatch.setattr(script.urllib.request, "urlopen", fail)
    status, body = script.post("https://example.invalid", b"{}", "test", None)
    assert status == 502
    assert "upstream unavailable" in body["message"]


def test_audit15_smoke_handles_html_guardrail_error(monkeypatch, capsys):
    script = module("audit_smoke", "scripts/demo/sprint2_smoke.py")
    monkeypatch.setattr(script, "TOKENS", {key: "test" for key in ("staff_dn1", "admin", "auditor")})
    monkeypatch.setattr(script, "call", lambda *args, **kwargs: (502, "<html>Bad Gateway</html>"))
    monkeypatch.setattr(script, "pos_call", lambda *args, **kwargs: (502, "<html>Bad Gateway</html>"))
    monkeypatch.setattr(script, "stock", lambda *args, **kwargs: 100)
    assert script.run() == 1
    assert "Bad Gateway" in capsys.readouterr().out
