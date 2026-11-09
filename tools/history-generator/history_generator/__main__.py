"""Command line for loading simulated history into a demo or test database."""

import argparse
from datetime import date

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core import clock
from app.core.db import database_url

from .loader import allowed_database, load_history


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", required=True, type=allowed_database)
    parser.add_argument("--days", type=int, default=90)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--as-of", type=date.fromisoformat, help="Exclusive business date (default: today)")
    args = parser.parse_args()
    if not 1 <= args.days <= 3650:
        parser.error("--days must be between 1 and 3650")
    engine = create_engine(database_url(args.database), hide_parameters=True)
    try:
        with Session(engine) as session, session.begin():
            count = load_history(session, args.days, args.seed, args.as_of or clock.today_local())
    finally:
        engine.dispose()
    print(f"Loaded {count} simulated transactions into {args.database}")


if __name__ == "__main__":
    main()
