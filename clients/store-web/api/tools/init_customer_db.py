"""Create the customer database and its tables.

Run once after a fresh checkout, or whenever the database was dropped:

    cd clients/store-web/api
    .\\.venv\\Scripts\\python.exe tools/init_customer_db.py

The script only creates objects; it never touches the store database.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import repo_root, settings  # noqa: E402
from app.customer_db import ensure_database, ensure_schema, get_customer_engine  # noqa: E402


def main() -> int:
    print(f"Repository root: {repo_root()}")
    print(f"Customer database: {settings.customer_database_name}")
    ensure_database()
    ensure_schema(get_customer_engine())
    print("Customer database is ready (accounts, sessions, saved addresses).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
