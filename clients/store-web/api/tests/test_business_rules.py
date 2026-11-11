"""Business rules that are easiest to get wrong: the business date and batches."""

from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from app import clock
from app.config import repo_root, settings


def test_batch_expiring_today_is_still_sellable(seeded_client: TestClient) -> None:
    """The boundary: ``expiry_date == today`` is sellable, as in the middleware."""
    item = seeded_client.get("/api/stores/WEB-A/products/WEB-P1").json()["item"]
    today_batch = next(
        batch for batch in item["batches"] if batch["batch_id"] == "WEB-B-P1-TODAY"
    )
    assert today_batch["sellable"] is True
    assert item["sellable_quantity"] == 40


def test_expired_batches_count_as_expired_not_sellable(seeded_client: TestClient) -> None:
    item = seeded_client.get("/api/stores/WEB-A/products/WEB-P1").json()["item"]
    expired = next(
        batch for batch in item["batches"] if batch["batch_id"] == "WEB-B-P1-EXPIRED"
    )
    assert expired["sellable"] is False
    assert item["expired_quantity"] == 20


def test_expired_quantity_is_summed_not_derived(seeded_client: TestClient) -> None:
    """WEB-P4 has 5 in inventory but a single batch with quantity 0.

    ``quantity - sellable_quantity`` would report 5 expired units; the SUM of
    expired batches is the correct 0.
    """
    item = seeded_client.get("/api/stores/WEB-A/products/WEB-P4").json()["item"]
    assert item["quantity"] == 5
    assert item["sellable_quantity"] == 0
    assert item["expired_quantity"] == 0
    assert item["quantity"] - item["sellable_quantity"] != item["expired_quantity"]


def test_quantity_is_the_sum_of_batches(seeded_client: TestClient) -> None:
    item = seeded_client.get("/api/stores/WEB-A/products/WEB-P1").json()["item"]
    assert item["quantity"] == 60
    assert item["quantity"] == 20 + 15 + 25


def test_nearest_expiry_ignores_expired_and_empty_batches(seeded_client: TestClient) -> None:
    item = seeded_client.get("/api/stores/WEB-A/products/WEB-P1").json()["item"]
    assert item["nearest_expiry"] == "2026-11-10"

    zero = seeded_client.get("/api/stores/WEB-A/products/WEB-P4").json()["item"]
    assert zero["nearest_expiry"] is None


def test_today_local_uses_the_business_utc_offset(monkeypatch) -> None:
    monkeypatch.setattr(settings, "business_utc_offset_hours", 7)
    expected = (datetime.now(timezone.utc) + timedelta(hours=7)).date()
    assert clock.today_local() == expected


def test_repo_root_is_the_directory_with_compose_yaml() -> None:
    root = repo_root()
    assert (root / "compose.yaml").is_file()
    assert (root / "database").is_dir()
    assert (root / "clients" / "store-web").is_dir()
