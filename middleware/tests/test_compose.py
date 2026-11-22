"""Compose security and startup-order checks (Audit #2 and #3)."""

import os
import shutil
import stat
import subprocess
from pathlib import Path

import yaml


REPO = Path(__file__).resolve().parents[2]
COMPOSE_FILE = REPO / "compose.yaml"
MIGRATE_SCRIPT = REPO / "database" / "migrate.sh"
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
            source = vol.split(":", 1)[0].rstrip("/")
            assert source != "./.certs", (
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


def _write_fake_sqlcmd(tmp_path: Path, body: str) -> Path:
    script = tmp_path / "fake_sqlcmd.sh"
    script.write_text("#!/usr/bin/env bash\nset -euo pipefail\n" + body, encoding="utf-8", newline="\n")
    script.chmod(script.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return script


def test_audit03_migrate_waits_for_databases_online(tmp_path: Path):
    script_text = MIGRATE_SCRIPT.read_text(encoding="utf-8")
    assert "state_desc" in script_text and "sys.databases" in script_text
    assert "60" in script_text

    state_dir = tmp_path / "state"
    state_dir.mkdir()
    log_file = tmp_path / "sqlcmd.log"

    fake_sqlcmd = _write_fake_sqlcmd(
        tmp_path,
        f"""
db=""
query=""
input_file=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    -d) db="$2"; shift 2 ;;
    -Q) query="$2"; shift 2 ;;
    -i) input_file="$2"; shift 2 ;;
    *) shift ;;
  esac
done

printf '%s|%s|%s\\n' "$db" "$query" "$input_file" >> "{log_file.as_posix()}"

if [[ "$db" == "master" && "$query" == *"SELECT state_desc FROM sys.databases"* ]]; then
  target=""
  if [[ "$query" == *"RTS_DB_MOCK"* ]]; then target="RTS_DB_MOCK"; fi
  if [[ "$query" == *"RTS_HQ_MOCK"* ]]; then target="RTS_HQ_MOCK"; fi
  count_file="{state_dir.as_posix()}/$target.polls"
  polls=0
  if [[ -f "$count_file" ]]; then polls=$(cat "$count_file"); fi
  polls=$((polls + 1))
  echo "$polls" > "$count_file"
  if (( polls == 1 )); then
    echo "RECOVERING"
  elif (( polls == 2 )); then
    echo "RECOVERY_PENDING"
  else
    echo "ONLINE"
  fi
  exit 0
fi

if [[ "$db" == "RTS_DB_MOCK" || "$db" == "RTS_HQ_MOCK" ]]; then
  count_file="{state_dir.as_posix()}/$db.polls"
  polls=0
  if [[ -f "$count_file" ]]; then polls=$(cat "$count_file"); fi
  if (( polls < 3 )); then
    echo "Cannot open database \\"$db\\" requested by the login. The login failed." >&2
    exit 1
  fi
  if [[ "$query" == *"SELECT 1"* ]]; then
    probe_file="{state_dir.as_posix()}/$db.probe"
    if [[ ! -f "$probe_file" ]]; then
      echo "1" > "$probe_file"
      echo "Cannot open database \\"$db\\" requested by the login. The login failed." >&2
      exit 1
    fi
    echo "1"
    exit 0
  fi
  if [[ "$query" == *"SELECT COUNT(*) FROM dbo.schema_migration"* ]]; then
    echo "1"
    exit 0
  fi
fi

exit 0
""",
    )

    bash = shutil.which("bash") or "/bin/bash"
    env = os.environ.copy()
    env.update(
        {
            "SQLCMDPASSWORD": "test-password",
            "SQLCMD_BIN": str(fake_sqlcmd),
            "DB_NAME": "RTS_DB_MOCK",
            "HQ_DB_NAME": "RTS_HQ_MOCK",
            "MIGRATE_DB_ONLINE_TIMEOUT_SECONDS": "15",
        }
    )
    result = subprocess.run(
        [bash, str(MIGRATE_SCRIPT)],
        capture_output=True,
        text=True,
        env=env,
        timeout=30,
    )
    assert result.returncode == 0, f"migrate.sh failed: {result.stderr}"
    assert "Database is up to date" in result.stdout
    assert "HQ database RTS_HQ_MOCK is up to date" in result.stdout
    assert int((state_dir / "RTS_DB_MOCK.polls").read_text(encoding="utf-8").strip()) >= 4
    assert int((state_dir / "RTS_HQ_MOCK.polls").read_text(encoding="utf-8").strip()) >= 4


def test_audit03_migrate_times_out_when_database_stays_recovering(tmp_path: Path):
    log_file = tmp_path / "sqlcmd_timeout.log"
    fake_sqlcmd = _write_fake_sqlcmd(
        tmp_path,
        f"""
db=""
query=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    -d) db="$2"; shift 2 ;;
    -Q) query="$2"; shift 2 ;;
    *) shift ;;
  esac
done

printf '%s|%s\\n' "$db" "$query" >> "{log_file.as_posix()}"

if [[ "$db" == "master" && "$query" == *"SELECT state_desc FROM sys.databases"* ]]; then
  echo "RECOVERY_PENDING"
  exit 0
fi

if [[ "$db" == "RTS_DB_STUCK" ]]; then
  echo "OPENED_PREMATURELY" >&2
  exit 99
fi

exit 0
""",
    )

    bash = shutil.which("bash") or "/bin/bash"
    env = os.environ.copy()
    env.update(
        {
            "SQLCMDPASSWORD": "test-password",
            "SQLCMD_BIN": str(fake_sqlcmd),
            "DB_NAME": "RTS_DB_STUCK",
            "HQ_DB_NAME": "RTS_HQ_STUCK",
            "MIGRATE_DB_ONLINE_TIMEOUT_SECONDS": "1",
        }
    )
    result = subprocess.run(
        [bash, str(MIGRATE_SCRIPT)],
        capture_output=True,
        text=True,
        env=env,
        timeout=15,
    )
    assert result.returncode != 0
    assert "RTS_DB_STUCK" in result.stderr
    assert "ONLINE" in result.stderr
    assert "OPENED_PREMATURELY" not in result.stderr


def _run_migrate_with_recording_sqlcmd(tmp_path: Path, applied: str) -> list[str]:
    """Run migrate.sh against a fake sqlcmd; return one text per sqlcmd call: db, -Q query, -i file contents."""
    calls = tmp_path / "calls"
    calls.mkdir()
    fake_sqlcmd = _write_fake_sqlcmd(
        tmp_path,
        f"""
n=$(ls "{calls.as_posix()}" | wc -l)
out="{calls.as_posix()}/$(printf '%04d' "$n").txt"
query=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    -d) echo "db=$2" >> "$out"; shift 2 ;;
    -Q) query="$2"; echo "$2" >> "$out"; shift 2 ;;
    -i) IFS=',' read -ra inputs <<< "$2"; for f in "${{inputs[@]}}"; do cat "$f" >> "$out"; echo >> "$out"; done; shift 2 ;;
    *) shift ;;
  esac
done
touch "$out"
if [[ "$query" == *"state_desc"* ]]; then echo "ONLINE"; fi
if [[ "$query" == *"SELECT COUNT(*) FROM dbo.schema_migration"* ]]; then echo "{applied}"; fi
exit 0
""",
    )
    env = os.environ.copy()
    env.update({"SQLCMDPASSWORD": "test-password", "SQLCMD_BIN": str(fake_sqlcmd),
                "DB_NAME": "RTS_DB_MOCK", "HQ_DB_NAME": "RTS_HQ_MOCK",
                "MIGRATE_DB_ONLINE_TIMEOUT_SECONDS": "5"})
    result = subprocess.run([shutil.which("bash") or "/bin/bash", str(MIGRATE_SCRIPT)],
                            capture_output=True, text=True, env=env, timeout=30)
    assert result.returncode == 0, f"migrate.sh failed: {result.stderr}"
    return [path.read_text(encoding="utf-8") for path in sorted(calls.iterdir())]


def test_audit_minor_migration_and_its_schema_migration_row_share_one_transaction(tmp_path: Path):
    calls = _run_migrate_with_recording_sqlcmd(tmp_path, applied="0")

    database = REPO / "database"
    files = sorted((database / "migrations").glob("*.sql")) + sorted((database / "hq").glob("*.sql"))
    assert files
    for path in files:
        record = f"INSERT dbo.schema_migration (version) VALUES ('{path.name}');"
        body = path.read_text(encoding="utf-8").strip()
        [call] = [call for call in calls if record in call]
        assert body in call, f"{path.name} and its schema_migration row run in separate sqlcmd calls"
        begin, ddl, insert = call.index("BEGIN TRANSACTION"), call.index(body), call.index(record)
        assert begin < ddl < insert < call.rindex("COMMIT"), f"{path.name} is not wrapped in one transaction"
        assert call.index("SET XACT_ABORT ON") < begin


def test_audit_minor_rerun_on_an_up_to_date_database_applies_nothing(tmp_path: Path):
    calls = _run_migrate_with_recording_sqlcmd(tmp_path, applied="1")

    assert not [call for call in calls if "INSERT dbo.schema_migration" in call]
    assert not [call for call in calls if "CREATE TABLE dbo.hq_sync_batch" in call]


def test_audit_minor_hq_tables_migration_is_one_transaction():
    text = (REPO / "database" / "hq" / "001_hq_tables.sql").read_text(encoding="utf-8")

    assert text.index("SET XACT_ABORT ON;") < text.index("BEGIN TRANSACTION;") \
        < text.index("CREATE TABLE") < text.rindex("COMMIT;")
