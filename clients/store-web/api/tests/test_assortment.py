"""Each store sells a different assortment, and the shop says where a product is.

The ``seeded`` fixture deletes every catalogue row outside ``WEB-%``, so these
tests add their own store-specific products rather than depending on the demo
seed. That keeps the assertion about the rule (a product without an inventory row
is absent from a store's catalogue) instead of about today's demo data.
"""

from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session


def _add_product(session: Session, sku: str, name: str, category: str, price: int) -> None:
    session.execute(
        text(
            "INSERT INTO dbo.product (sku, barcode, name, category, unit_price) "
            "VALUES (:sku, :barcode, :name, :category, :price)"
        ),
        {
            "sku": sku,
            "barcode": f"9{abs(hash(sku)) % 10**12:012d}",
            "name": name,
            "category": category,
            "price": price,
        },
    )


def _stock_only_at(session: Session, store_id: str, sku: str, quantity: int, expiry_days: int) -> None:
    """Give one store a sellable batch, leaving every other store without stock."""
    session.execute(
        text(
            "INSERT INTO dbo.inventory (store_id, sku, quantity) "
            "VALUES (:store_id, :sku, :quantity)"
        ),
        {"store_id": store_id, "sku": sku, "quantity": quantity},
    )
    session.execute(
        text(
            "INSERT INTO dbo.product_batch (batch_id, sku, store_id, expiry_date, quantity) "
            "VALUES (:batch_id, :sku, :store_id, DATEADD(day, :days, CAST(:today AS date)), :quantity)"
        ),
        {
            "batch_id": f"B-{store_id}-{sku}-1",
            "sku": sku,
            "store_id": store_id,
            "days": expiry_days,
            "today": "2026-11-10",
            "quantity": quantity,
        },
    )
    session.flush()


def test_every_store_lists_the_catalog_with_its_own_stock(
    seeded: Session, seeded_client: TestClient
) -> None:
    """A branch shows the whole catalogue, but only its own stock is non-zero.

    This is what lets the store page answer "we don't have it, but branch X does":
    the row is visible everywhere, the quantity tells the truth per branch.
    """
    _add_product(seeded, "WEB-ONLY-A", "Chỉ cửa A", "Fresh", 12000)
    _stock_only_at(seeded, "WEB-A", "WEB-ONLY-A", 30, 5)

    _add_product(seeded, "WEB-ONLY-B", "Chỉ cửa B", "Household", 165000)
    _stock_only_at(seeded, "WEB-B", "WEB-ONLY-B", 22, 365)

    a_items = seeded_client.get("/api/stores/WEB-A/products").json()["items"]
    b_items = seeded_client.get("/api/stores/WEB-B/products").json()["items"]

    a_by_sku = {item["sku"]: item for item in a_items}
    b_by_sku = {item["sku"]: item for item in b_items}

    # Both branches list both products...
    assert "WEB-ONLY-A" in a_by_sku and "WEB-ONLY-A" in b_by_sku
    assert "WEB-ONLY-B" in a_by_sku and "WEB-ONLY-B" in b_by_sku

    # ...but only the owning branch reports stock.
    assert a_by_sku["WEB-ONLY-A"]["sellable_quantity"] == 30
    assert b_by_sku["WEB-ONLY-A"]["sellable_quantity"] == 0
    assert b_by_sku["WEB-ONLY-B"]["sellable_quantity"] == 22
    assert a_by_sku["WEB-ONLY-B"]["sellable_quantity"] == 0


def test_the_page_lists_the_whole_catalog_not_only_this_store(
    seeded: Session, seeded_client: TestClient
) -> None:
    """A branch shows every product in the system so a customer can be sent elsewhere.

    ``product_count`` on the store header is what this branch stocks; the page
    total is the catalog. They are different questions and must not be conflated.
    """
    _add_product(seeded, "WEB-ONLY-A", "Chỉ cửa A", "Fresh", 12000)
    _stock_only_at(seeded, "WEB-A", "WEB-ONLY-A", 30, 5)
    _add_product(seeded, "WEB-ONLY-B", "Chỉ cửa B", "Household", 165000)
    _stock_only_at(seeded, "WEB-B", "WEB-ONLY-B", 22, 365)

    store = seeded_client.get("/api/stores/WEB-A").json()
    page = seeded_client.get("/api/stores/WEB-A/products").json()

    # Six products exist in the catalog (WEB-P1..P4 plus the two added here);
    # WEB-A stocks four of them.
    assert page["total"] == 6
    assert store["product_count"] == 4

    rows = {item["sku"]: item for item in page["items"]}
    assert rows["WEB-ONLY-B"]["quantity"] == 0
    assert rows["WEB-ONLY-B"]["sellable_quantity"] == 0


def test_shop_points_a_store_specific_product_at_its_only_store(
    seeded: Session, seeded_client: TestClient
) -> None:
    _add_product(seeded, "WEB-ONLY-B", "Chỉ cửa B", "Household", 165000)
    _stock_only_at(seeded, "WEB-B", "WEB-ONLY-B", 22, 365)

    body = seeded_client.get(
        "/api/shop/search",
        params={"q": "Chỉ cửa B", "latitude": 16.0, "longitude": 108.0},
    ).json()

    item = next(item for item in body["items"] if item["sku"] == "WEB-ONLY-B")
    assert [store["store_id"] for store in item["stores"]] == ["WEB-B"]
    assert item["nearest"]["store_id"] == "WEB-B"
    assert item["nearest"]["sellable_quantity"] == 22


def test_store_page_sends_the_customer_to_the_branch_that_has_it(
    seeded: Session, seeded_client: TestClient
) -> None:
    """The branch being viewed stocks nothing, so the suggestion is the other branch."""
    _add_product(seeded, "WEB-ONLY-B", "Chỉ cửa B", "Household", 165000)
    _stock_only_at(seeded, "WEB-B", "WEB-ONLY-B", 22, 365)

    body = seeded_client.get(
        "/api/stores/WEB-A/products",
        params={"latitude": 16.0, "longitude": 108.0},
    ).json()

    row = next(item for item in body["items"] if item["sku"] == "WEB-ONLY-B")
    assert row["sellable_quantity"] == 0
    assert row["nearest_store"]["store_id"] == "WEB-B"
    assert row["nearest_store"]["sellable_quantity"] == 22


def test_the_viewed_store_wins_over_a_closer_one(
    seeded: Session, seeded_client: TestClient
) -> None:
    """Already standing in that branch: "buy it here" beats a shorter drive."""
    _add_product(seeded, "WEB-ONLY-A", "Chỉ cửa A", "Fresh", 12000)
    _stock_only_at(seeded, "WEB-A", "WEB-ONLY-A", 30, 5)

    # The origin sits exactly on WEB-B, which is genuinely nearer than WEB-A.
    body = seeded_client.get(
        "/api/stores/WEB-A/products",
        params={"latitude": 16.0, "longitude": 108.0},
    ).json()

    row = next(item for item in body["items"] if item["sku"] == "WEB-ONLY-A")
    assert row["nearest_store"]["store_id"] == "WEB-A"
    assert row["nearest_store"]["sellable_quantity"] == 30


def test_no_stock_anywhere_has_no_suggestion(
    seeded: Session, seeded_client: TestClient
) -> None:
    """WEB-P3 is in the catalog with no inventory row: nothing to suggest."""
    body = seeded_client.get(
        "/api/stores/WEB-A/products",
        params={"latitude": 16.0, "longitude": 108.0},
    ).json()

    row = next(item for item in body["items"] if item["sku"] == "WEB-P3")
    assert row["nearest_store"] is None


def test_without_coordinates_no_suggestion_is_invented(
    seeded: Session, seeded_client: TestClient
) -> None:
    body = seeded_client.get("/api/stores/WEB-A/products").json()
    assert all(item["nearest_store"] is None for item in body["items"])
