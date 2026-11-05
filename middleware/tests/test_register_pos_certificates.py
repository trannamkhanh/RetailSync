"""scripts/register_pos_certificates.py (PB-48-5), on real SQL Server.

Certificates are made with openssl in a temporary directory; expected
fingerprints come from openssl. The script's session is bound to the test's
connection, so everything is rolled back afterwards.
"""

import importlib.util
from decimal import Decimal
from pathlib import Path
import subprocess
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from app.domain.models import PosTerminal, Store


SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "register_pos_certificates.py"


def _uid(length: int = 6) -> str:
    return uuid4().hex[:length].upper()


@pytest.fixture(scope="module")
def script():
    spec = importlib.util.spec_from_file_location("register_pos_certificates", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def write_certificate(directory: Path, pos_id: str) -> str:
    """Write <pos_id>.crt and .key like generate_dev_certs.sh; return openssl's fingerprint."""
    cert = directory / f"{pos_id}.crt"
    subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "2",
                    "-subj", f"/CN={pos_id}", "-keyout", str(directory / f"{pos_id}.key"),
                    "-out", str(cert)], check=True, capture_output=True)
    printed = subprocess.run(["openssl", "x509", "-in", str(cert), "-noout", "-fingerprint", "-sha256"],
                             check=True, capture_output=True, text=True).stdout
    return printed.strip().split("=", 1)[1].replace(":", "").lower()


@pytest.fixture
def terminals(db_session: Session) -> list[str]:
    store_id = f"TEST-{_uid(5)}"
    db_session.add(Store(store_id=store_id, name="Register cert store", latitude=Decimal("16.000000"),
                         longitude=Decimal("108.000000"), region_id="TEST"))
    db_session.flush()
    pos_ids = [f"TEST-POS-RC-{_uid()}" for _ in range(2)]
    db_session.add_all(PosTerminal(pos_id=pos_id, store_id=store_id, status="ACTIVE") for pos_id in pos_ids)
    db_session.flush()
    return pos_ids


def fingerprint_of(session: Session, pos_id: str) -> str | None:
    session.expire_all()
    return session.get(PosTerminal, pos_id).cert_fingerprint


def test_pb48_5_stores_each_fingerprint(script, db_session, terminals, tmp_path):
    expected = {pos_id: write_certificate(tmp_path, pos_id) for pos_id in terminals}

    registered = script.register(db_session, tmp_path)

    assert dict(registered) == expected
    assert {pos_id: fingerprint_of(db_session, pos_id) for pos_id in terminals} == expected


def test_pb48_5_running_again_keeps_the_fingerprints(script, db_session, terminals, tmp_path):
    expected = {pos_id: write_certificate(tmp_path, pos_id) for pos_id in terminals}
    script.register(db_session, tmp_path)

    script.register(db_session, tmp_path)

    assert {pos_id: fingerprint_of(db_session, pos_id) for pos_id in terminals} == expected


def test_pb48_5_swapped_certificates_do_not_break_the_unique_index(script, db_session, terminals, tmp_path):
    first, second = terminals
    first_dir, second_dir = tmp_path / "first", tmp_path / "second"
    first_dir.mkdir(), second_dir.mkdir()
    write_certificate(first_dir, first)
    write_certificate(first_dir, second)
    script.register(db_session, first_dir)
    for source, target in ((first, second), (second, first)):
        (second_dir / f"{target}.crt").write_text((first_dir / f"{source}.crt").read_text())

    script.register(db_session, second_dir)

    assert fingerprint_of(db_session, first) == script.certificate_fingerprint(
        (first_dir / f"{second}.crt").read_text())


def test_pb48_5_certificate_without_terminal_is_reported(script, db_session, terminals, tmp_path):
    write_certificate(tmp_path, terminals[0])
    write_certificate(tmp_path, "TEST-POS-NOWHERE")

    with pytest.raises(LookupError, match="TEST-POS-NOWHERE"):
        script.register(db_session, tmp_path)


def test_pb48_5_empty_directory_is_reported(script, db_session, tmp_path):
    with pytest.raises(LookupError, match="No certificates"):
        script.register(db_session, tmp_path)


def test_pb48_5_main_prints_names_and_fingerprints_never_keys(script, db_session, terminals, tmp_path,
                                                             monkeypatch, capsys):
    expected = {pos_id: write_certificate(tmp_path, pos_id) for pos_id in terminals}
    keys = [(tmp_path / f"{pos_id}.key").read_text() for pos_id in terminals]
    connection = db_session.connection()
    monkeypatch.setattr(script, "SessionLocal",
                        lambda: Session(bind=connection, join_transaction_mode="create_savepoint"))

    assert script.main(tmp_path) == 0

    printed = capsys.readouterr()
    for pos_id, fingerprint in expected.items():
        assert f"{pos_id} {fingerprint}" in printed.out
    assert "PRIVATE KEY" not in printed.out + printed.err
    assert not any(key.strip().splitlines()[1] in printed.out for key in keys)
    assert {pos_id: fingerprint_of(db_session, pos_id) for pos_id in terminals} == expected


def test_pb48_5_main_fails_and_writes_nothing_for_an_unknown_terminal(script, db_session, terminals, tmp_path,
                                                                     monkeypatch, capsys):
    write_certificate(tmp_path, terminals[0])
    write_certificate(tmp_path, "TEST-POS-NOWHERE")
    connection = db_session.connection()
    monkeypatch.setattr(script, "SessionLocal",
                        lambda: Session(bind=connection, join_transaction_mode="create_savepoint"))

    assert script.main(tmp_path) == 1

    assert "TEST-POS-NOWHERE" in capsys.readouterr().err
    assert fingerprint_of(db_session, terminals[0]) is None
