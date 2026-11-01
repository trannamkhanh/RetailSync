"""Write the 13 demo JWTs to .tokens/demo_tokens.json. Prints token names only.

JWT_SECRET comes from the environment or the repository .env. Run it in the
middleware image, or with Python and middleware/requirements.txt installed:

    docker compose run --rm --volume "${PWD}:/repo" --workdir /repo middleware python scripts/issue_demo_tokens.py
"""

import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "middleware"))

from app.core.security import create_token  # noqa: E402


OUTPUT = ROOT / ".tokens" / "demo_tokens.json"
POS_ACCOUNT = "pos_system"
ACCOUNTS = [
    ("staff_dn1", "Staff", "STORE-DN1"),
    ("staff_dn2", "Staff", "STORE-DN2"),
    ("staff_dn3", "Staff", "STORE-DN3"),
    ("manager_dn1", "Manager", "STORE-DN1"),
    ("admin", "Admin", None),
    ("auditor", "Auditor", None),
    ("hq_operator", "HQ", None),
]
TERMINALS = [
    ("POS-DN1-01", "STORE-DN1"),
    ("POS-DN1-02", "STORE-DN1"),
    ("POS-DN2-01", "STORE-DN2"),
    ("POS-DN2-02", "STORE-DN2"),
    ("POS-DN3-01", "STORE-DN3"),
    ("POS-DN3-02", "STORE-DN3"),
]


def issue_tokens() -> dict[str, str]:
    tokens = {name: create_token(name, role, store_id=store_id) for name, role, store_id in ACCOUNTS}
    for pos_id, store_id in TERMINALS:
        tokens[pos_id] = create_token(POS_ACCOUNT, "POS", store_id=store_id, pos_id=pos_id)
    return tokens


def main(output: Path = OUTPUT) -> int:
    try:
        tokens = issue_tokens()
    except RuntimeError as error:
        print(error, file=sys.stderr)
        return 1
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(tokens, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {len(tokens)} tokens: {', '.join(tokens)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
