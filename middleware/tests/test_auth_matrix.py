"""Authorization against the real app (PB-02-5, PS02-1 to PS02-8).

Every protected route is called by all six roles and without a token. Each
request is otherwise valid, so a 401 or 403 can only come from authorization.
A route walk makes sure a new route cannot be left without a role check.
"""

from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import jwt
import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import create_token, require_role
from app.domain.models import Inventory, PosTerminal, Product, StaffUser, Store
from app.main import app


SECRET = "test-only-secret-with-enough-length-for-hs256"
STORE_ID = "TEST-AM1"
NEW_STORE_ID = "TEST-AM2"
POS_ID = "TEST-AM-POS1"
NEW_POS_ID = "TEST-AM-POS2"
SKU = "TEST-AM-SKU"
ROLES = ["POS", "Staff", "Manager", "HQ", "Admin", "Auditor"]
ACCOUNTS = {
    "POS": ("TEST-am-pos", "POS_SYSTEM", None),
    "Staff": ("TEST-am-staff", "STORE_STAFF", STORE_ID),
    "Manager": ("TEST-am-manager", "STORE_MANAGER", STORE_ID),
    "HQ": ("TEST-am-hq", "HQ_OPERATOR", None),
    "Admin": ("TEST-am-admin", "ADMIN", None),
    "Auditor": ("TEST-am-auditor", "AUDITOR", None),
}

STORES = ("POST", "/api/v1/admin/stores")
TERMINALS = ("POST", "/api/v1/admin/pos-terminals")
AUDIT_LOGS = ("GET", "/api/v1/audit-logs")
INVENTORY = ("GET", "/api/v1/stores/{store_id}/inventory")
POS_EVENTS = ("POST", "/api/v1/pos/events")

# Expected status for every protected route on main, by caller.
#                  POS  Staff  Manager  HQ   Admin  Auditor  no token
MATRIX = {
    STORES:       (403, 403,   403,     403, 201,   403,     401),
    TERMINALS:    (403, 403,   403,     403, 201,   403,     401),
    AUDIT_LOGS:   (403, 403,   403,     403, 403,   200,     401),
    INVENTORY:    (403, 200,   200,     403, 403,   403,     401),
    POS_EVENTS:   (200, 403,   403,     403, 403,   403,     401),
}
CALLERS = [*ROLES, None]

PUBLIC = {("GET", "/api/v1/health")}
# FastAPI's own documentation routes: public by design, not API operations.
DOCUMENTATION = {"/openapi.json", "/docs", "/docs/oauth2-redirect", "/redoc"}


@pytest.fixture(autouse=True)
def jwt_secret(monkeypatch):
    monkeypatch.setattr(settings, "jwt_secret", SecretStr(SECRET))


@pytest.fixture
def world(db_session: Session) -> None:
    db_session.add(Store(store_id=STORE_ID, name="Auth matrix store", latitude=Decimal("16.000000"),
                         longitude=Decimal("108.000000"), region_id="TEST"))
    db_session.add(Product(sku=SKU, barcode=f"BC-{SKU}", name="Auth matrix product",
                           category="TEST", unit_price=Decimal("10.00")))
    db_session.flush()
    db_session.add(PosTerminal(pos_id=POS_ID, store_id=STORE_ID, status="ACTIVE"))
    db_session.add(Inventory(store_id=STORE_ID, sku=SKU, quantity=10))
    for username, db_role, store_id in ACCOUNTS.values():
        db_session.add(StaffUser(username=username, full_name="Auth matrix account",
                                 role=db_role, store_id=store_id))
    # The fixture's outer transaction still rolls this back after the test.
    db_session.commit()


def token_for(role: str, **overrides) -> str:
    username, _, store_id = ACCOUNTS[role]
    pos_id = POS_ID if role == "POS" else None
    if role == "POS":
        store_id = STORE_ID
    return create_token(username, role, store_id=store_id, pos_id=pos_id, **overrides)


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def sale() -> dict:
    return {
        "event_type": "SALE", "transaction_id": "TEST-AM-TXN1", "store_id": STORE_ID,
        "pos_id": POS_ID, "timestamp": "2026-11-14T03:15:00Z",
        "items": [{"sku": SKU, "quantity": 1, "unit_price": "10.00"}],
    }


REQUESTS: dict[tuple[str, str], Callable[[TestClient, dict], object]] = {
    STORES: lambda client, headers: client.post(STORES[1], headers=headers, json={
        "store_id": NEW_STORE_ID, "name": "New store", "latitude": 16.1,
        "longitude": 108.1, "region_id": "TEST",
    }),
    TERMINALS: lambda client, headers: client.post(TERMINALS[1], headers=headers, json={
        "pos_id": NEW_POS_ID, "store_id": STORE_ID,
    }),
    AUDIT_LOGS: lambda client, headers: client.get(AUDIT_LOGS[1], headers=headers),
    INVENTORY: lambda client, headers: client.get(INVENTORY[1].format(store_id=STORE_ID), headers=headers),
    POS_EVENTS: lambda client, headers: client.post(POS_EVENTS[1], headers=headers, json=sale()),
}


def assert_rejected(response, status: int, code: str) -> None:
    assert response.status_code == status, response.text
    body = response.json()
    assert set(body) == {"outcome", "code", "message"}
    assert (body["outcome"], body["code"]) == ("REJECTED", code)


def has_role_check(dependant) -> bool:
    """True when require_role guards the route, directly or through another dependency."""
    for dependency in dependant.dependencies:
        if getattr(dependency.call, "__qualname__", "") == f"{require_role.__name__}.<locals>.dependency":
            return True
        if has_role_check(dependency):
            return True
    return False


def api_operations() -> set[tuple[str, str]]:
    return {(method, route.path) for route in app.routes if isinstance(route, APIRoute)
            for method in route.methods}


# PS02-1 to PS02-6 and PS02-8


def test_ps02_1_request_without_token_is_refused(client, world):
    response = client.get(INVENTORY[1].format(store_id=STORE_ID))

    assert_rejected(response, 401, "UNAUTHORIZED")


def test_ps02_2_token_with_another_signature_is_refused(client, world):
    claims = jwt.decode(token_for("Staff"), SECRET, algorithms=["HS256"])
    tampered = jwt.encode(claims, "another-secret-with-enough-length-for-hs256", algorithm="HS256")

    response = client.get(INVENTORY[1].format(store_id=STORE_ID), headers=bearer(tampered))

    assert_rejected(response, 401, "UNAUTHORIZED")


def test_ps02_3_expired_token_is_refused(client, world):
    response = client.get(INVENTORY[1].format(store_id=STORE_ID),
                          headers=bearer(token_for("Staff", expires_in_days=-1)))

    assert_rejected(response, 401, "UNAUTHORIZED")


def test_ps02_4_wrong_role_is_refused_and_creates_nothing(client, db_session, world):
    response = REQUESTS[STORES](client, bearer(token_for("Staff")))

    assert_rejected(response, 403, "FORBIDDEN")
    assert db_session.scalar(select(func.count()).select_from(Store)
                             .where(Store.store_id == NEW_STORE_ID)) == 0


def test_ps02_5_allowed_role_reads_its_store_stock(client, world):
    response = client.get(INVENTORY[1].format(store_id=STORE_ID), headers=bearer(token_for("Staff")))

    assert response.status_code == 200, response.text
    assert response.json() == {"store_id": STORE_ID, "items": [{"sku": SKU, "quantity": 10}]}


def test_ps02_6_inactive_account_is_refused(client, db_session, world):
    staff = db_session.scalar(select(StaffUser).where(StaffUser.username == ACCOUNTS["Staff"][0]))
    staff.is_active = False
    db_session.commit()

    response = client.get(INVENTORY[1].format(store_id=STORE_ID), headers=bearer(token_for("Staff")))

    assert_rejected(response, 403, "FORBIDDEN")


def test_ps02_8_there_is_no_login_api(client):
    response = client.post("/api/v1/auth/login", json={"username": "admin", "password": "x"})

    assert_rejected(response, 404, "NOT_FOUND")


# PS02-7: the role matrix


@pytest.mark.parametrize("caller", CALLERS, ids=lambda caller: caller or "no-token")
@pytest.mark.parametrize("operation", list(MATRIX), ids=lambda operation: " ".join(operation))
def test_ps02_7_role_matrix(client, world, operation, caller):
    expected = MATRIX[operation][CALLERS.index(caller)]
    headers = bearer(token_for(caller)) if caller else {}

    response = REQUESTS[operation](client, headers)

    assert response.status_code == expected, response.text
    if expected == 401:
        assert response.json()["code"] == "UNAUTHORIZED"
    if expected == 403:
        assert response.json()["code"] == "FORBIDDEN"


def test_matrix_allows_exactly_the_ds04_roles():
    """x-roles in DS-04: Admin, Admin, Auditor, Staff and Manager, POS."""
    allowed = {operation: {role for role, status in zip(ROLES, statuses) if status < 400}
               for operation, statuses in MATRIX.items()}

    assert allowed == {
        STORES: {"Admin"}, TERMINALS: {"Admin"}, AUDIT_LOGS: {"Auditor"},
        INVENTORY: {"Staff", "Manager"}, POS_EVENTS: {"POS"},
    }


# Route walk


def test_matrix_covers_every_protected_route():
    assert api_operations() - PUBLIC == set(MATRIX)


def test_every_api_route_except_health_has_a_role_check():
    unguarded = {(sorted(route.methods)[0], route.path) for route in app.routes
                 if isinstance(route, APIRoute) and not has_role_check(route.dependant)}

    assert unguarded == PUBLIC


def test_only_documentation_routes_live_outside_the_api():
    others = {route.path for route in app.routes if not isinstance(route, APIRoute)}

    assert others == DOCUMENTATION


def test_role_check_detection_sees_through_nested_dependencies():
    inventory = next(route for route in app.routes
                     if isinstance(route, APIRoute) and route.path == INVENTORY[1])

    assert not any(getattr(d.call, "__qualname__", "").startswith("require_role")
                   for d in inventory.dependant.dependencies)
    assert has_role_check(inventory.dependant)


def test_health_stays_public(client):
    assert client.get("/api/v1/health").status_code == 200
