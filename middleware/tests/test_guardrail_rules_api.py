"""Guardrail rule admin API on real SQL Server (PB-26-1 to PB-26-4, REC26-1 to REC26-7).

Only Admin may read or change rules. Tests that change a rule run in the
``db_session`` savepoint, so even a change to a seeded row is rolled back.
"""

from decimal import Decimal
from unittest.mock import Mock

import pytest
from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import create_token
from app.domain.models import AuditLog, GuardrailRule, StaffUser
from app.services.guardrail_rules import active_rules


SECRET = "test-only-secret-with-enough-length-for-hs256"
LIST_URL = "/api/v1/admin/guardrail-rules"
RULE_URL = "/api/v1/admin/guardrail-rules/{rule_id}"
ADMIN = "TEST-gr-admin"
CATEGORY = "TEST-GR-CAT"
ALL_CATEGORY_SEEDS = {"MAX_DISCOUNT": 50.0, "MIN_PRICE": 1000.0, "MIN_SHELF_LIFE": 1.0}


@pytest.fixture(autouse=True)
def jwt_secret(monkeypatch):
    monkeypatch.setattr(settings, "jwt_secret", SecretStr(SECRET))


@pytest.fixture
def admin(db_session: Session) -> StaffUser:
    user = StaffUser(username=ADMIN, full_name="Guardrail admin", role="ADMIN")
    db_session.add(user)
    db_session.flush()
    # Commit the savepoint: a later 403 or 422 rolls the request back, and the
    # account has to survive that.
    db_session.commit()
    return user


@pytest.fixture
def admin_headers(admin: StaffUser) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_token(ADMIN, 'Admin')}"}


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def assert_rejected(response, status: int, code: str) -> dict:
    assert response.status_code == status, response.text
    body = response.json()
    assert set(body) == {"outcome", "code", "message"}
    assert (body["outcome"], body["code"]) == ("REJECTED", code)
    return body


def update(client, headers, rule_id: int, **payload):
    return client.put(RULE_URL.format(rule_id=rule_id), headers=headers, json=payload)


def create_rule(session: Session, rule_type: str, threshold, category: str | None = CATEGORY,
                is_active: bool = True) -> GuardrailRule:
    rule = GuardrailRule(rule_type=rule_type, threshold=Decimal(str(threshold)),
                         category=category, is_active=is_active)
    session.add(rule)
    session.flush()
    # Commit the savepoint so a rejected request cannot roll the rule away.
    session.commit()
    return rule


def all_category_rule(session: Session, rule_type: str) -> GuardrailRule:
    rule = session.scalar(select(GuardrailRule).where(GuardrailRule.rule_type == rule_type,
                                                      GuardrailRule.category.is_(None)))
    assert rule is not None, f"the seeded {rule_type} rule is missing"
    return rule


def stored(session: Session, rule_id: int) -> GuardrailRule:
    session.expire_all()
    rule = session.get(GuardrailRule, rule_id)
    assert rule is not None
    return rule


# REC26-1


def test_rec26_1_seeded_defaults_are_listed(client, admin_headers):
    response = client.get(LIST_URL, headers=admin_headers)

    assert response.status_code == 200
    items = response.json()["items"]
    seeds = {item["rule_type"]: item for item in items if item["category"] is None}
    assert {rule_type: seed["threshold"] for rule_type, seed in seeds.items()
            if rule_type in ALL_CATEGORY_SEEDS} == ALL_CATEGORY_SEEDS
    order = [(item["rule_type"], item["category"] is not None, item["category"] or "",
              item["rule_id"]) for item in items]
    assert order == sorted(order)


# REC26-2


def test_rec26_2_valid_change(client, admin_headers, admin, db_session):
    rule = create_rule(db_session, "MAX_DISCOUNT", 10)
    before = stored(db_session, rule.rule_id).updated_at

    response = update(client, admin_headers, rule.rule_id, threshold=20, is_active=True)

    assert response.status_code == 200, response.text
    assert response.json() == {
        "rule_id": rule.rule_id, "rule_type": "MAX_DISCOUNT", "threshold": 20.0,
        "category": CATEGORY, "is_active": True,
    }
    row = stored(db_session, rule.rule_id)
    assert (float(row.threshold), row.is_active) == (20.0, True)
    assert row.updated_by == admin.user_id
    assert row.updated_at >= before


def test_rec26_2_deactivation(client, admin_headers, db_session):
    rule = create_rule(db_session, "MAX_DISCOUNT", 10)

    response = update(client, admin_headers, rule.rule_id, threshold=10, is_active=False)

    assert response.status_code == 200, response.text
    assert response.json()["is_active"] is False
    assert stored(db_session, rule.rule_id).is_active is False


# REC26-3


@pytest.mark.parametrize("threshold", [101, -1])
def test_rec26_3_max_discount_out_of_range(client, admin_headers, db_session, threshold):
    rule = all_category_rule(db_session, "MAX_DISCOUNT")
    before = rule.threshold

    body = assert_rejected(update(client, admin_headers, rule.rule_id,
                                  threshold=threshold, is_active=True),
                           422, "VALIDATION_ERROR")

    assert "threshold" in body["message"]
    assert stored(db_session, rule.rule_id).threshold == before


# REC26-4


@pytest.mark.parametrize("threshold", [1.5, -1])
def test_rec26_4_min_shelf_life_is_whole_days(client, admin_headers, db_session, threshold):
    rule = all_category_rule(db_session, "MIN_SHELF_LIFE")
    before = rule.threshold

    body = assert_rejected(update(client, admin_headers, rule.rule_id,
                                  threshold=threshold, is_active=True),
                           422, "VALIDATION_ERROR")

    assert "threshold" in body["message"]
    assert stored(db_session, rule.rule_id).threshold == before


# REC26-5


@pytest.mark.parametrize("rule_type", ["MAX_DISCOUNT", "MIN_PRICE", "MIN_SHELF_LIFE"])
def test_rec26_5_three_decimals_are_rejected(client, admin_headers, db_session, rule_type):
    rule = all_category_rule(db_session, rule_type)
    before = rule.threshold

    body = assert_rejected(update(client, admin_headers, rule.rule_id,
                                  threshold=10.001, is_active=True),
                           422, "VALIDATION_ERROR")

    assert "threshold" in body["message"]
    assert stored(db_session, rule.rule_id).threshold == before


def test_rec26_5_extra_field_is_rejected(client, admin_headers, db_session):
    rule = create_rule(db_session, "MAX_DISCOUNT", 10)

    body = assert_rejected(update(client, admin_headers, rule.rule_id, threshold=20,
                                  is_active=True, rule_type="MIN_PRICE"),
                           422, "VALIDATION_ERROR")

    assert "rule_type" in body["message"]
    assert float(stored(db_session, rule.rule_id).threshold) == 10.0


def test_rec26_5_missing_field_is_rejected(client, admin_headers, db_session):
    rule = create_rule(db_session, "MAX_DISCOUNT", 10)

    response = client.put(RULE_URL.format(rule_id=rule.rule_id), headers=admin_headers,
                          json={"threshold": 20})

    body = assert_rejected(response, 422, "VALIDATION_ERROR")
    assert "is_active" in body["message"]


def test_rec26_5_unknown_rule_returns_404(client, admin_headers):
    body = assert_rejected(update(client, admin_headers, 9999, threshold=10, is_active=True),
                           404, "NOT_FOUND")

    assert "9999" in body["message"]


@pytest.mark.parametrize("rule_id", [0, 2_147_483_648])
def test_rec26_5_rule_id_out_of_range_is_422(client, admin_headers, rule_id):
    body = assert_rejected(update(client, admin_headers, rule_id, threshold=10, is_active=True),
                           422, "VALIDATION_ERROR")

    assert "rule_id" in body["message"]


# REC26-6


def test_rec26_6_category_max_discount_may_not_pass_the_all_category_rule(
        client, admin_headers, db_session):
    all_rule = all_category_rule(db_session, "MAX_DISCOUNT")
    category_rule = create_rule(db_session, "MAX_DISCOUNT", Decimal(all_rule.threshold) - 10)

    body = assert_rejected(update(client, admin_headers, category_rule.rule_id,
                                  threshold=float(all_rule.threshold) + 10, is_active=True),
                           422, "VALIDATION_ERROR")

    assert "threshold" in body["message"]
    assert stored(db_session, category_rule.rule_id).threshold == Decimal(all_rule.threshold) - 10


def test_rec26_6_all_category_rule_may_not_drop_below_a_category_rule(
        client, admin_headers, db_session):
    all_rule = all_category_rule(db_session, "MAX_DISCOUNT")
    category_rule = create_rule(db_session, "MAX_DISCOUNT", Decimal(all_rule.threshold) - 10)

    body = assert_rejected(update(client, admin_headers, all_rule.rule_id,
                                  threshold=float(all_rule.threshold) - 20, is_active=True),
                           422, "VALIDATION_ERROR")

    assert "threshold" in body["message"]
    assert stored(db_session, category_rule.rule_id).threshold == Decimal(all_rule.threshold) - 10


def test_rec26_6_a_category_rule_may_equal_the_all_category_rule(client, admin_headers, db_session):
    all_rule = all_category_rule(db_session, "MAX_DISCOUNT")
    category_rule = create_rule(db_session, "MAX_DISCOUNT", Decimal(all_rule.threshold) - 10)

    response = update(client, admin_headers, category_rule.rule_id,
                      threshold=float(all_rule.threshold), is_active=True)

    assert response.status_code == 200, response.text


@pytest.mark.parametrize("rule_type", ["MIN_PRICE", "MIN_SHELF_LIFE"])
def test_rec26_6_category_rule_may_not_go_below_the_all_category_rule(
        client, admin_headers, db_session, rule_type):
    all_rule = all_category_rule(db_session, rule_type)
    category_rule = create_rule(db_session, rule_type, Decimal(all_rule.threshold) + 5)

    below = float(all_rule.threshold) - 1
    body = assert_rejected(update(client, admin_headers, category_rule.rule_id,
                                  threshold=below, is_active=True),
                           422, "VALIDATION_ERROR")

    assert "threshold" in body["message"]


def test_rec26_6_inactive_rules_are_not_tightened(client, admin_headers, db_session):
    all_rule = all_category_rule(db_session, "MAX_DISCOUNT")
    category_rule = create_rule(db_session, "MAX_DISCOUNT", Decimal(all_rule.threshold) - 10)

    response = update(client, admin_headers, category_rule.rule_id,
                      threshold=float(all_rule.threshold) + 10, is_active=False)

    assert response.status_code == 200, response.text


# REC26-7


def test_rec26_7_active_rules_reflect_the_change(client, admin_headers, db_session):
    rule = create_rule(db_session, "MAX_DISCOUNT", 12)

    assert update(client, admin_headers, rule.rule_id, threshold=30, is_active=True).status_code == 200

    values = {item.rule_id: float(item.threshold) for item in active_rules(db_session)}
    assert values[rule.rule_id] == 30.0

    assert update(client, admin_headers, rule.rule_id, threshold=30, is_active=False).status_code == 200
    assert rule.rule_id not in {item.rule_id for item in active_rules(db_session)}


# Audit and authorization.


def test_update_writes_an_audit_row(client, admin_headers, admin, db_session):
    rule = create_rule(db_session, "MAX_DISCOUNT", 10)

    assert update(client, admin_headers, rule.rule_id, threshold=25, is_active=True).status_code == 200

    row = db_session.scalar(select(AuditLog)
                            .where(AuditLog.action == "GUARDRAIL_RULE_UPDATED",
                                   AuditLog.entity_key == str(rule.rule_id)))
    assert row is not None
    assert row.entity_name == "guardrail_rule"
    assert row.user_id == admin.user_id
    assert "threshold 10.00 -> 25" in row.details
    assert "is_active True -> True" in row.details


def test_missing_token_returns_401(client):
    assert_rejected(client.get(LIST_URL), 401, "UNAUTHORIZED")
    assert_rejected(update(client, {}, 1, threshold=10, is_active=True), 401, "UNAUTHORIZED")


@pytest.mark.parametrize("username,api_role", [
    ("TEST-gr-pos", "POS"),
    ("TEST-gr-staff", "Staff"),
    ("TEST-gr-manager", "Manager"),
    ("TEST-gr-hq", "HQ"),
    ("TEST-gr-auditor", "Auditor"),
], ids=["pos", "staff", "manager", "hq", "auditor"])
def test_every_other_role_is_forbidden(client, admin, db_session, username, api_role):
    db_role = {"POS": "POS_SYSTEM", "Staff": "STORE_STAFF", "Manager": "STORE_MANAGER",
               "HQ": "HQ_OPERATOR", "Auditor": "AUDITOR"}[api_role]
    db_session.add(StaffUser(username=username, full_name="Guardrail caller", role=db_role))
    db_session.commit()
    headers = bearer(create_token(username, api_role))

    assert_rejected(client.get(LIST_URL, headers=headers), 403, "FORBIDDEN")
    # The role check runs before the body and path validation.
    assert_rejected(update(client, headers, 0, threshold="bad"), 403, "FORBIDDEN")


def test_the_list_never_commits(client, admin_headers, db_session, monkeypatch):
    rule = create_rule(db_session, "MAX_DISCOUNT", 10)
    commit = Mock()
    monkeypatch.setattr(db_session, "commit", commit)

    assert client.get(LIST_URL, headers=admin_headers).status_code == 200

    commit.assert_not_called()
    assert float(stored(db_session, rule.rule_id).threshold) == 10.0
