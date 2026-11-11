"""database/seed/002_demo_catalog.sql is repeatable and fills the demo dataset (PB-08-6)."""

from decimal import Decimal
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.domain.models import GuardrailRule, Inventory, Product, StaffUser


SEED = Path(__file__).resolve().parents[2] / "database" / "seed" / "002_demo_catalog.sql"
STORES = ("STORE-DN1", "STORE-DN2", "STORE-DN3")
PRODUCTS = {
    "SKU-0001": ("8930000000011", "Fresh milk 1L", "Dairy", Decimal("32000")),
    "SKU-0002": ("8930000000028", "Yogurt 100g", "Dairy", Decimal("7000")),
    "SKU-0003": ("8930000000035", "Cheese slices 200g", "Dairy", Decimal("65000")),
    "SKU-0004": ("8930000000042", "Bread 400g", "Bakery", Decimal("25000")),
    "SKU-0005": ("8930000000059", "Sponge cake 300g", "Bakery", Decimal("45000")),
    "SKU-0006": ("8930000000066", "Butter cookies 200g", "Bakery", Decimal("38000")),
    "SKU-0007": ("8930000000073", "Rice 50kg", "Dry goods", Decimal("1250000")),
    "SKU-0008": ("8930000000080", "Instant noodles 75g", "Dry goods", Decimal("4500")),
    "SKU-0009": ("8930000000097", "Cooking oil 1L", "Dry goods", Decimal("58000")),
}
ACCOUNTS = {
    "staff_dn1": ("STORE_STAFF", "STORE-DN1"),
    "staff_dn2": ("STORE_STAFF", "STORE-DN2"),
    "staff_dn3": ("STORE_STAFF", "STORE-DN3"),
    "manager_dn1": ("STORE_MANAGER", "STORE-DN1"),
    "admin": ("ADMIN", None),
    "auditor": ("AUDITOR", None),
    "hq_operator": ("HQ_OPERATOR", None),
    "pos_system": ("POS_SYSTEM", None),
}
RULES = {"MIN_SHELF_LIFE": Decimal("1"), "MAX_DISCOUNT": Decimal("50"), "MIN_PRICE": Decimal("1000")}


def run_seed(session: Session) -> None:
    session.connection().exec_driver_sql(SEED.read_text(encoding="utf-8"))


def count(session: Session, model, *where) -> int:
    session.flush()
    return session.scalar(select(func.count()).select_from(model).where(*where))


def seed_counts(session: Session) -> dict[str, int]:
    """Counts are keyed by the demo ids, so other tests' rows cannot distort them."""
    return {
        "products": count(session, Product, Product.sku.in_(PRODUCTS)),
        "inventory": count(session, Inventory,
                           Inventory.store_id.in_(STORES), Inventory.sku.in_(PRODUCTS)),
        "accounts": count(session, StaffUser, StaffUser.username.in_(ACCOUNTS)),
        "rules": count(session, GuardrailRule,
                       GuardrailRule.rule_type.in_(RULES), GuardrailRule.category.is_(None)),
    }


def test_seed_twice_keeps_the_documented_row_counts(db_session):
    run_seed(db_session)
    first = seed_counts(db_session)
    run_seed(db_session)

    assert first == {"products": 9, "inventory": 27, "accounts": 8, "rules": 3}
    assert seed_counts(db_session) == first


def test_seeded_products_match_the_catalog(db_session):
    run_seed(db_session)

    rows = {product.sku: (product.barcode, product.name, product.category, product.unit_price)
            for product in db_session.scalars(select(Product).where(Product.sku.in_(PRODUCTS)))}
    assert rows == PRODUCTS


def test_seeded_inventory_has_the_demo_quantities(db_session):
    run_seed(db_session)

    for store_id, quantity in (("STORE-DN1", 40), ("STORE-DN2", 25), ("STORE-DN3", 15)):
        stored = db_session.scalars(select(Inventory.quantity).where(
            Inventory.store_id == store_id, Inventory.sku.in_(PRODUCTS))).all()
        assert len(stored) == 9
        assert set(stored) == {quantity}


def test_seed_does_not_overwrite_an_existing_quantity(db_session):
    run_seed(db_session)
    row = db_session.get(Inventory, ("STORE-DN1", "SKU-0001"))
    row.quantity = 99
    db_session.flush()

    run_seed(db_session)

    db_session.expire_all()
    assert db_session.get(Inventory, ("STORE-DN1", "SKU-0001")).quantity == 99
    assert count(db_session, Inventory, Inventory.store_id.in_(STORES),
                 Inventory.sku.in_(PRODUCTS)) == 27


def test_seeded_accounts_are_active_and_bound_to_the_demo_stores(db_session):
    run_seed(db_session)

    users = {user.username: user for user in
             db_session.scalars(select(StaffUser).where(StaffUser.username.in_(ACCOUNTS)))}
    assert {name: (user.role, user.store_id) for name, user in users.items()} == ACCOUNTS
    assert all(user.is_active for user in users.values())
    assert all(user.full_name.strip() for user in users.values())


def test_seeded_guardrail_rules_use_the_ds07_defaults(db_session):
    run_seed(db_session)

    rules = {rule.rule_type: rule for rule in db_session.scalars(
        select(GuardrailRule).where(GuardrailRule.rule_type.in_(RULES),
                                    GuardrailRule.category.is_(None)))}
    assert {rule_type: rule.threshold for rule_type, rule in rules.items()} == RULES
    assert all(rule.is_active for rule in rules.values())
