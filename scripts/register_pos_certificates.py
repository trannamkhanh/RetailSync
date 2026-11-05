"""Store the fingerprint of each POS client certificate in pos_terminal (PB-48-5).

Reads .certs/pos/<pos_id>.crt, computes the SHA-256 of the certificate in DER
form, and writes it to pos_terminal.cert_fingerprint of that pos_id in DB_NAME.
Prints names and fingerprints, never keys. Run it in the middleware container,
from the repository root, after scripts/generate_dev_certs.sh:

    docker compose run --rm --no-deps --volume "${PWD}:/repo:ro" --workdir /repo middleware python scripts/register_pos_certificates.py
"""

from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "middleware"))

from sqlalchemy.orm import Session  # noqa: E402

from app.core.client_cert import certificate_fingerprint  # noqa: E402
from app.core.config import settings  # noqa: E402
from app.core.db import SessionLocal  # noqa: E402
from app.domain.models import PosTerminal  # noqa: E402


CERT_DIR = ROOT / ".certs" / "pos"


def register(session: Session, cert_dir: Path) -> list[tuple[str, str]]:
    """Set the fingerprints in the caller's transaction; the caller commits."""
    fingerprints = {path.stem: certificate_fingerprint(path.read_text(encoding="ascii"))
                    for path in sorted(cert_dir.glob("*.crt"))}
    if not fingerprints:
        raise LookupError(f"No certificates in {cert_dir}.")
    terminals = {pos_id: session.get(PosTerminal, pos_id) for pos_id in fingerprints}
    missing = [pos_id for pos_id, terminal in terminals.items() if terminal is None]
    if missing:
        raise LookupError(f"No terminal for: {', '.join(missing)}.")
    # Clear first: fingerprints are unique, and two terminals may swap theirs.
    for terminal in terminals.values():
        terminal.cert_fingerprint = None
    session.flush()
    for pos_id, terminal in terminals.items():
        terminal.cert_fingerprint = fingerprints[pos_id]
    session.flush()
    return list(fingerprints.items())


def main(cert_dir: Path = CERT_DIR) -> int:
    with SessionLocal() as session:
        try:
            registered = register(session, cert_dir)
        except LookupError as error:
            print(error, file=sys.stderr)
            return 1
        session.commit()
    print(f"Registered {len(registered)} certificates in {settings.db_name}:")
    for pos_id, fingerprint in registered:
        print(f"{pos_id} {fingerprint}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
