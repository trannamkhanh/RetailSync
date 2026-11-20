"""Compose security and startup-order checks (Audit #2 and #3)."""

from pathlib import Path

import yaml


REPO = Path(__file__).resolve().parents[2]
COMPOSE_FILE = REPO / "compose.yaml"
SMOKE_SCRIPT = REPO / "scripts" / "demo" / "sprint2_smoke.py"


def _compose_services() -> dict:
    data = yaml.safe_load(COMPOSE_FILE.read_text(encoding="utf-8"))
    return data["services"]


def _cert_mounts(service: dict) -> set[str]:
    return {vol for vol in service.get("volumes", []) if "/certs" in vol}


def test_audit02_compose_mounts_only_needed_certificate_files():
    services = _compose_services()

    for name, service in services.items():
        for vol in service.get("volumes", []):
            assert not vol.startswith("./.certs:/certs"), (
                f"Service '{name}' mounts the entire .certs directory: {vol}"
            )
            assert "ca.key" not in vol, f"Service '{name}' must not mount ca.key: {vol}"
            assert ".certs/pos" not in vol, f"Service '{name}' must not mount POS keys: {vol}"

    assert _cert_mounts(services["middleware"]) == {
        "./.certs/ca.crt:/certs/ca.crt:ro",
        "./.certs/server.crt:/certs/server.crt:ro",
        "./.certs/server.key:/certs/server.key:ro",
    }
    assert _cert_mounts(services["hq-demo"]) == {
        "./.certs/server.crt:/certs/server.crt:ro",
        "./.certs/server.key:/certs/server.key:ro",
    }
    assert _cert_mounts(services["pos-gateway"]) == {
        "./.certs/ca.crt:/certs/ca.crt:ro",
        "./.certs/server.crt:/certs/server.crt:ro",
        "./.certs/server.key:/certs/server.key:ro",
    }


def test_audit02_smoke_script_reads_pos_certs_from_repo():
    text = SMOKE_SCRIPT.read_text(encoding="utf-8")
    assert 'Path("/certs/pos")' not in text
    assert 'REPO / ".certs" / "pos"' in text


def test_audit03_compose_waits_for_migrate_and_defines_middleware_healthcheck():
    services = _compose_services()

    for name in ("middleware", "hq-demo"):
        depends = services[name].get("depends_on", {})
        assert isinstance(depends, dict), f"Service '{name}' depends_on must use conditions"
        assert depends.get("sqlserver", {}).get("condition") == "service_healthy"
        assert depends.get("migrate", {}).get("condition") == "service_completed_successfully"

    healthcheck = services["middleware"].get("healthcheck")
    assert isinstance(healthcheck, dict), "middleware must define a healthcheck"
    test_cmd = " ".join(healthcheck.get("test", []))
    assert "https://localhost:8443/api/v1/health" in test_cmd
    assert "/certs/ca.crt" in test_cmd
    assert " -k" not in test_cmd and "--insecure" not in test_cmd

    gateway_deps = services["pos-gateway"].get("depends_on", {})
    assert isinstance(gateway_deps, dict)
    assert gateway_deps.get("middleware", {}).get("condition") == "service_healthy"
