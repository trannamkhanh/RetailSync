"""The API is read-only: SELECT-only SQL, no commits, no row changes."""

import re
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session

from app import queries

WRITE_WORDS = re.compile(r"\b(INSERT|UPDATE|DELETE|MERGE|DROP|ALTER|TRUNCATE)\b", re.IGNORECASE)
SELECT_START = re.compile(r"^\s*SELECT\b", re.IGNORECASE)
TABLES = ("dbo.store", "dbo.product", "dbo.inventory", "dbo.product_batch")


def _query_sources() -> list[Path]:
    return sorted(Path(queries.__file__).parent.glob("*.py"))


def _statements() -> list[tuple[str, str]]:
    """Every SQL string handed to ``text(...)`` in ``app/queries``."""
    found: list[tuple[str, str]] = []
    for path in _query_sources():
        source = path.read_text(encoding="utf-8")
        for match in re.finditer(r"text\(\s*[fr]?\"\"\"(.*?)\"\"\"", source, re.S):
            found.append((path.name, match.group(1)))
        # Single-line fragments, including ones concatenated with shared pieces.
        for match in re.finditer(r"text\(\s*\"([^\"]+)\"", source):
            found.append((path.name, match.group(1)))
    return found


def test_queries_contain_only_select_statements() -> None:
    statements = _statements()
    assert statements, "no SQL statement found in app/queries"
    for name, statement in statements:
        assert SELECT_START.match(statement), f"{name} does not start with SELECT:\n{statement[:120]}"
        # __ORDER__ is a placeholder for a fixed ORDER BY fragment, never a filter.
        assert not WRITE_WORDS.search(statement.replace("__ORDER__", "")), (
            f"{name} contains a write keyword:\n{statement[:120]}"
        )


def test_every_module_level_statement_is_a_select() -> None:
    """Catches SQL assembled from constants, which the source scan cannot see."""
    from app.queries import products, stores

    checked = 0
    for module in (stores, products):
        for name, value in vars(module).items():
            if name.startswith("_") or not hasattr(value, "text"):
                continue
            sql = str(value.text)
            assert SELECT_START.match(sql), f"{module.__name__}.{name} is not a SELECT:\n{sql[:120]}"
            assert not WRITE_WORDS.search(sql), f"{module.__name__}.{name} contains a write keyword"
            checked += 1
    assert checked >= 7, "expected the queries modules to expose their statements"


def test_store_queries_and_store_routers_never_commit() -> None:
    """Store catalog/inventory queries and routers are strictly read-only."""
    sources = [path.read_text(encoding="utf-8") for path in _query_sources()]
    api_dir = Path(queries.__file__).parent.parent / "api"
    # auth.py and shop.py (which saves addresses) write to customer DB, but stores/products/meta never commit.
    read_only_routers = ["health.py", "stores.py", "products.py", "meta.py"]
    sources += [(api_dir / name).read_text(encoding="utf-8") for name in read_only_routers]
    joined = "\n".join(sources)
    assert ".commit(" not in joined
    assert ".rollback(" not in joined


def _counts(session: Session) -> dict[str, int]:
    return {
        table: int(session.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar_one())
        for table in TABLES
    }


def test_endpoints_do_not_change_row_counts(seeded_client: TestClient, seeded: Session) -> None:
    before = _counts(seeded)
    for path in (
        "/api/health",
        "/api/stores",
        "/api/stores/WEB-A",
        "/api/stores/WEB-A/products",
        "/api/stores/WEB-A/products/WEB-P1",
        "/api/categories",
    ):
        assert seeded_client.get(path).status_code == 200, path
    assert _counts(seeded) == before
