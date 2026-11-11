from collections import Counter
import json
from pathlib import Path

import pytest
import requests

from app.api.schemas.pos import PosEvent
from pos_simulator import transport
from pos_simulator.config import Faults, read_config
from pos_simulator.plan import generate


@pytest.fixture
def config():
    config = read_config(Path(__file__).resolve().parents[1] / "config.example.yaml")
    config.event_count = 250
    config.mix = {"SALE": 0.6, "RETURN": 0.25, "CANCELLATION": 0.15}
    return config


def test_pb03_sales_use_the_seeded_catalogue_and_validate(config):
    for event in generate(config):
        payload = PosEvent.model_validate(event.payload)
        if event.resend is not None:
            PosEvent.model_validate(event.resend)
        if payload.event_type == "SALE":
            assert config.items_per_sale.min <= len(payload.items) <= config.items_per_sale.max
            assert all(str(item.unit_price) == config.catalogue[item.sku] for item in payload.items)


def test_ps03_4_reversals_reference_valid_sales_within_limits(config):
    sales = {}
    returned = set()
    kinds = Counter()
    for event in generate(config):
        payload = PosEvent.model_validate(event.payload)
        kinds[payload.event_type] += 1
        if payload.event_type == "SALE":
            sales[payload.transaction_id] = (payload.store_id, {item.sku: item.quantity for item in payload.items})
            continue
        store, remaining = sales[payload.original_transaction_id]
        assert store == payload.store_id
        if payload.event_type == "RETURN":
            for item in payload.items:
                assert item.quantity <= remaining[item.sku]
                remaining[item.sku] -= item.quantity
            returned.add(payload.original_transaction_id)
        else:
            assert payload.original_transaction_id not in returned
            del sales[payload.original_transaction_id]
    assert all(kinds[kind] > 0 for kind in config.mix)


def test_ps03_2_same_seed_and_configuration_generate_same_plan(config):
    assert generate(config) == generate(config)
    assert generate(config) != generate(config.model_copy(update={"seed": config.seed + 1}))


def test_ps03_3_default_event_mix_is_within_two_percentage_points():
    config = read_config(Path(__file__).resolve().parents[1] / "config.example.yaml")
    config.event_count = 5_000
    events = generate(config)
    counts = Counter(event.payload["event_type"] for event in events)

    assert len(events) == 5_000
    for kind, expected in {"SALE": 0.92, "RETURN": 0.05, "CANCELLATION": 0.03}.items():
        assert counts[kind] / len(events) == pytest.approx(expected, abs=0.02)


@pytest.mark.parametrize(("field", "fault"), [
    ("duplicate_rate", "duplicate"), ("conflict_rate", "conflict"), ("timeout_retry_rate", "timeout_retry"),
])
def test_pb03_fault_resends_keep_id_and_change_items_only_for_conflicts(config, field, fault):
    config.fault_injection = Faults(**{field: 1})
    resends = [event for event in generate(config) if event.resend is not None]
    assert resends
    for event in resends:
        assert event.fault == fault
        assert event.resend["transaction_id"] == event.payload["transaction_id"]
        assert (event.resend["items"] != event.payload["items"]) == (fault == "conflict")
        PosEvent.model_validate(event.resend)


def test_pb03_retries_same_payload_on_timeout_and_503(config, monkeypatch):
    sent = []
    replies = iter([requests.Timeout(), 503, 200])

    class Session:
        def post(self, url, *, json, timeout):
            sent.append(json)
            status = next(replies)
            if isinstance(status, Exception):
                raise status
            response = requests.Response()
            response.status_code = status
            response._content = b'{"outcome": "OK", "code": "OK"}'
            return response

    monkeypatch.setattr(transport, "sleep", lambda _: None)
    payload = generate(config)[0].payload
    counts, rejected, latencies = Counter(), Counter(), []
    assert transport._send(Session(), config, payload, latencies, counts, rejected)
    assert sent == [payload, payload, payload]
    assert counts == {"sent": 3, "ok": 1, "timeouts": 1, "service_unavailable": 1}
    assert not rejected and len(latencies) == 3


def test_pb03_skips_reversals_when_the_original_was_rejected(config, monkeypatch, tmp_path):
    events = generate(config)
    config.tokens_file = tmp_path / "tokens.json"
    config.tokens_file.write_text(json.dumps({pos: "test" for _, pos in config.terminals}))
    config.ca_file = tmp_path / "ca.crt"
    config.ca_file.touch()
    config.terminal_cert_dir = tmp_path
    for _, pos in config.terminals:
        (tmp_path / f"{pos}.crt").touch()
        (tmp_path / f"{pos}.key").touch()

    class Session:
        def __init__(self):
            self.headers = {}

        def __enter__(self):
            return self

        def __exit__(self, *_):
            pass

        def post(self, url, *, json, timeout):
            assert json["event_type"] == "SALE"
            assert self.cert[0].endswith(f"{json['pos_id']}.crt")
            assert self.headers["Authorization"] == "Bearer test"
            response = requests.Response()
            response.status_code = 409
            response._content = b'{"outcome": "REJECTED", "code": "INSUFFICIENT_STOCK"}'
            return response

    monkeypatch.setattr(transport.requests, "Session", Session)
    monkeypatch.setattr(transport, "sleep", lambda _: None)
    result = transport.run(config, events)
    sales = sum(event.payload["event_type"] == "SALE" for event in events)
    assert result["sent"] == sales
    assert result["skipped_unaccepted_sale"] == len(events) - sales > 0
    assert result["rejected"] == {"INSUFFICIENT_STOCK": sales}
