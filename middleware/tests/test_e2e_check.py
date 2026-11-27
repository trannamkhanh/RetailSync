"""Pure PB-37 checks; live transport is exercised by the e2e script, not mocked PASSes."""
from decimal import Decimal
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from types import SimpleNamespace

import pytest

spec = spec_from_file_location("e2e_check", Path(__file__).resolve().parents[2] / "scripts/e2e/e2e_check.py")
e2e = module_from_spec(spec)
spec.loader.exec_module(e2e)


def test_pb37_stock_and_hq_delta_helpers():
    assert e2e.stock_expectations(40) == [37, 38, 36, 38]
    before = {"totals": [{"store_id": "STORE-DN1", "sku": "SKU-0001",
                          "sold_qty": 7, "returned_qty": 2, "net_revenue": 160000}]}
    after = {"totals": [{"store_id": "STORE-DN1", "sku": "SKU-0001",
                         "sold_qty": 12, "returned_qty": 5, "net_revenue": 224000}]}
    assert e2e.delta(e2e.hq_totals(after, "STORE-DN1", "SKU-0001"),
                     e2e.hq_totals(before, "STORE-DN1", "SKU-0001")) == (5, 3, Decimal(64000))
    assert e2e.hq_totals(before, "STORE-DN2", "SKU-0001") == (0, 0, Decimal(0))
    with pytest.raises(ValueError, match="Duplicate"):
        e2e.hq_totals({"totals": after["totals"] * 2}, "STORE-DN1", "SKU-0001")


@pytest.mark.parametrize(("environment", "arguments", "expected"), [
    (None, [], "RTS_HQ"),
    ("RTS_HQ_REVIEW", [], "RTS_HQ_REVIEW"),
    ("RTS_HQ_REVIEW", ["--hq-db", "RTS_HQ_EXPLICIT"], "RTS_HQ_EXPLICIT"),
])
def test_pb37_hq_database_default_and_override(monkeypatch, environment, arguments, expected):
    monkeypatch.setattr(e2e.settings, "db_name", "RTS_DB_DEMO")
    if environment is None:
        monkeypatch.delenv("HQ_DB_NAME", raising=False)
    else:
        monkeypatch.setenv("HQ_DB_NAME", environment)
    assert e2e.parse_args(arguments).hq_db == expected


@pytest.mark.parametrize(("arguments", "message"), [
    (["--db", "RTS_DB"], "invalid choice"),
    (["--hq-db", "RTS_DB"], "safe database name"),
    (["--hq-db", "bad/name"], "safe database name"),
    (["--opening", "STORE-DN1=-1"], "STORE=nonnegative_integer"),
    (["--opening", "STORE-DN1"], "STORE=nonnegative_integer"),
    (["--opening", "BAD*=2"], "STORE=nonnegative_integer"),
])
def test_pb37_parse_args_refuses_unsafe_inputs(monkeypatch, capsys, arguments, message):
    monkeypatch.setattr(e2e.settings, "db_name", "RTS_DB_DEMO")
    monkeypatch.setenv("HQ_DB_NAME", "RTS_HQ")
    with pytest.raises(SystemExit) as error:
        e2e.parse_args(arguments)
    assert error.value.code == 2
    assert message in capsys.readouterr().err


def test_pb37_parse_args_refuses_mismatched_database(monkeypatch, capsys):
    monkeypatch.setattr(e2e.settings, "db_name", "RTS_DB_NOWRITE")
    with pytest.raises(SystemExit):
        e2e.parse_args([])
    assert "DB_NAME must match" in capsys.readouterr().err


def test_pb37_waits_for_zero_pending_before_hq_baseline(monkeypatch, tmp_path):
    tokens = tmp_path / "tokens.json"
    tokens.write_text('{"admin":"test"}')
    args = SimpleNamespace(tokens=tokens, hq_url="https://hq.test/api/v1")
    answers = iter([{"batches_pending": 3}, {"batches_pending": 1}, {"batches_pending": 0}])
    requests = []

    class BaselineReached(Exception):
        pass

    def request(method, url, **kwargs):
        requests.append(method)
        if method == "GET":
            assert requests == ["POST", "POST", "POST", "GET"]
            raise BaselineReached
        return next(answers)

    monkeypatch.setattr(e2e, "request", request)
    monkeypatch.setattr(e2e.time, "sleep", lambda seconds: None)
    monkeypatch.setattr(e2e.api, "TOKENS", {})
    with pytest.raises(BaselineReached):
        e2e.run(args)


def test_pb37_undrained_queue_fails_before_baseline_or_pos(monkeypatch, tmp_path):
    tokens = tmp_path / "tokens.json"
    tokens.write_text('{"admin":"test"}')
    args = SimpleNamespace(tokens=tokens, hq_url="https://hq.test/api/v1")
    requests = []

    def request(method, url, **kwargs):
        assert method == "POST", "HQ baseline must not be taken while older batches are pending"
        requests.append(method)
        return {"batches_pending": 1}

    monkeypatch.setattr(e2e, "request", request)
    monkeypatch.setattr(e2e.time, "sleep", lambda seconds: None)
    monkeypatch.setattr(e2e.api, "TOKENS", {})
    monkeypatch.setattr(e2e.api, "pos_call", lambda *a, **kw: pytest.fail("POS called before sync was idle"))
    with pytest.raises(RuntimeError, match="older sync traffic drained"):
        e2e.run(args)
    assert len(requests) == 30


def test_pb37_hq_delta_refuses_mismatched_shapes():
    with pytest.raises(ValueError):
        e2e.delta((1, 2, Decimal(3)), (1, 2))
