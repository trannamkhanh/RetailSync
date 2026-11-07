"""Sprint 2 demo smoke check: 14 steps, one PASS/FAIL line each.

Run it in the middleware container, against the running demo stack, from the
repository root:

    docker compose run --rm --volume "${PWD}:/repo" --workdir /repo ^
        middleware python scripts/demo/sprint2_smoke.py

It talks to the real ports: Staff, Admin and Auditor through the middleware on
8443, POS events through the POS gateway on 9443 with the terminal certificate.
The container mounts the repository at /repo and the certificates at /certs, so
the defaults are the compose service names. Set RTS_MIDDLEWARE_URL and
RTS_GATEWAY_URL to point it somewhere else; on the host it falls back to
127.0.0.1.

Every run registers a new store and terminal and uses fresh transaction ids, so
it can run again on the same database. It exits 1 if any check fails.
"""

import http.client
import json
import os
import random
import socket
import ssl
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit


REPO = Path(__file__).resolve().parents[2]
TOKENS_FILE = REPO / ".tokens" / "demo_tokens.json"
TOKENS = json.loads(TOKENS_FILE.read_text(encoding="utf-8")) if TOKENS_FILE.is_file() else {}

CONTAINER_CA = Path("/certs/ca.crt")
if CONTAINER_CA.is_file():
    CA = CONTAINER_CA
    CERT_DIR = Path("/certs/pos")
    default_middleware = "https://middleware:8443/api/v1"
    default_gateway = "https://pos-gateway:9443/api/v1/pos/events"
else:
    CA = REPO / ".certs" / "ca.crt"
    CERT_DIR = REPO / ".certs" / "pos"
    default_middleware = "https://127.0.0.1:8443/api/v1"
    default_gateway = "https://127.0.0.1:9443/api/v1/pos/events"

MIDDLEWARE = os.environ.get("RTS_MIDDLEWARE_URL", default_middleware).rstrip("/")
GATEWAY = os.environ.get("RTS_GATEWAY_URL", default_gateway)

# The development certificate names localhost, 127.0.0.1 and middleware; the
# gateway container answers to the service name "pos-gateway" on the compose
# network. Dial the service but verify the certificate for a name it carries.
GATEWAY_URL = urlsplit(GATEWAY)
GATEWAY_SERVER_NAME = os.environ.get("RTS_GATEWAY_SERVER_NAME", "localhost")

STOCK = "SKU-0001"
BARCODE = "8930000000011"
STORE_DN1 = "STORE-DN1"
POS_DN1 = "POS-DN1-01"

RUN = datetime.now(timezone.utc).strftime("%H%M%S") + str(random.randrange(10))
STORE = f"SM{RUN}"
POS = f"SM-POS-{RUN}"
TXN_SALE = f"TXN-SMK-{RUN}-A"
TXN_RETURN = f"TXN-SMK-{RUN}-R"
TXN_SALE_B = f"TXN-SMK-{RUN}-B"
TXN_CANCEL_B = f"TXN-SMK-{RUN}-C"
TXN_RETURN_A = f"TXN-SMK-{RUN}-R2"
TXN_BIG = f"TXN-SMK-{RUN}-BIG"

failures = 0


def context(cert_pos: str | None = None) -> ssl.SSLContext:
    ctx = ssl.create_default_context(cafile=str(CA))
    if cert_pos:
        ctx.load_cert_chain(str(CERT_DIR / f"{cert_pos}.crt"),
                            str(CERT_DIR / f"{cert_pos}.key"))
    return ctx


def _parse_body(raw: str):
    try:
        return json.loads(raw)
    except ValueError:
        return raw[:200]


def call(method: str, url: str, body=None, token: str | None = None,
         cert_pos: str | None = None):
    """Return (status, parsed body) and never raise for an HTTP error."""
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(request, context=context(cert_pos), timeout=20) as response:
            raw = response.read().decode(errors="replace")
            status = response.status
    except urllib.error.HTTPError as error:
        raw = error.read().decode(errors="replace")
        status = error.code
    except Exception as error:  # noqa: BLE001 - a missing stack is a FAIL, not a crash
        return 0, {"code": f"CONNECTION_ERROR: {error}"}
    try:
        return status, _parse_body(raw)
    except ValueError:
        return status, raw[:200]


def check(number: int, label: str, ok: bool, detail: str) -> None:
    global failures
    failures += 0 if ok else 1
    print(f"  {'PASS' if ok else 'FAIL'}  [{number:02d}] {label}: {detail}")


def code_of(body) -> str:
    return body.get("code", "") if isinstance(body, dict) else ""


def message_of(body) -> str:
    return body.get("message", "") if isinstance(body, dict) else str(body)


def stock(sku: str = STOCK, store: str = STORE_DN1, token_name: str = "staff_dn1") -> int:
    status, body = call("GET", f"{MIDDLEWARE}/stores/{store}/inventory?sku={sku}",
                        token=TOKENS[token_name])
    if status != 200:
        raise RuntimeError(f"cannot read stock {sku}: {status} {body}")
    return body["items"][0]["quantity"]


def event(kind: str, txn: str, items=None, original: str | None = None,
          store: str = STORE_DN1, pos: str = POS_DN1) -> dict:
    body = {
        "event_type": kind,
        "transaction_id": txn,
        "store_id": store,
        "pos_id": pos,
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    if items is not None:
        body["items"] = [{"sku": sku, "quantity": qty, "unit_price": price}
                         for sku, qty, price in items]
    if original:
        body["original_transaction_id"] = original
    return body


class _GatewayConnection(http.client.HTTPSConnection):
    """Dial the gateway service but verify the certificate against its own name."""

    def __init__(self, host: str, port: int, context: ssl.SSLContext,
                 server_name: str) -> None:
        super().__init__(host, port, context=context, timeout=20)
        self._server_name = server_name

    def connect(self) -> None:
        sock = socket.create_connection((self.host, self.port), self.timeout)
        try:
            self.sock = self._context.wrap_socket(sock, server_hostname=self._server_name)
        except Exception:
            sock.close()
            raise


def pos_call(body: dict, cert_pos: str | None = POS_DN1, token_name: str = POS_DN1):
    connection = _GatewayConnection(GATEWAY_URL.hostname, GATEWAY_URL.port or 443,
                                    context(cert_pos), GATEWAY_SERVER_NAME)
    try:
        payload = json.dumps(body).encode()
        connection.request("POST", GATEWAY_URL.path, body=payload,
                           headers={"Content-Type": "application/json",
                                    "Authorization": f"Bearer {TOKENS[token_name]}"})
        response = connection.getresponse()
        raw = response.read().decode(errors="replace")
        return response.status, _parse_body(raw)
    except Exception as error:  # noqa: BLE001 - a missing stack is a FAIL, not a crash
        return 0, {"code": f"CONNECTION_ERROR: {error}"}
    finally:
        connection.close()


def run() -> int:
    print(f"RetailSync Sprint 2 smoke check {RUN} at "
          f"{datetime.now().isoformat(timespec='seconds')}")
    print(f"  middleware: {MIDDLEWARE}\n  gateway:    {GATEWAY}")

    # 1. Health over HTTPS (PB-02-1).
    status, body = call("GET", f"{MIDDLEWARE}/health")
    check(1, "GET /health", status == 200 and body == {"status": "ok"}, f"{status} {body}")

    # 2. Authentication and roles (PB-02).
    status, body = call("GET", f"{MIDDLEWARE}/stores/{STORE_DN1}/inventory")
    check(2, "no token", status == 401 and code_of(body) == "UNAUTHORIZED",
          f"{status} {code_of(body)}")
    status, body = call("GET", f"{MIDDLEWARE}/admin/guardrail-rules",
                        token=TOKENS["staff_dn1"])
    check(2, "Staff on an Admin route", status == 403 and code_of(body) == "FORBIDDEN",
          f"{status} {code_of(body)}")

    # 3. Store and POS registration (PB-08).
    store_body = {"store_id": STORE, "name": "Cua hang smoke", "latitude": 16.0678,
                  "longitude": 108.2208, "region_id": "TEST"}
    status, body = call("POST", f"{MIDDLEWARE}/admin/stores", store_body,
                        token=TOKENS["admin"])
    check(3, "Admin registers a store", status == 201,
          f"{status} {body.get('store_id') if isinstance(body, dict) else body}")
    status, body = call("POST", f"{MIDDLEWARE}/admin/pos-terminals",
                        {"pos_id": POS, "store_id": STORE}, token=TOKENS["admin"])
    check(3, "Admin registers a terminal", status == 201,
          f"{status} {body.get('pos_id') if isinstance(body, dict) else body}")
    status, body = call("POST", f"{MIDDLEWARE}/admin/stores", store_body,
                        token=TOKENS["admin"])
    check(3, "the same store again", status == 409 and code_of(body) == "ALREADY_EXISTS",
          f"{status} {code_of(body)}")

    # 4. SALE through the POS gateway (PB-05, PB-10, PB-48).
    before = stock()
    sale = event("SALE", TXN_SALE, [(STOCK, 2, 32000.00)])
    status, body = pos_call(sale)
    after = stock()
    check(4, "POS sells 2 x SKU-0001",
          status == 200 and code_of(body) == "OK" and after == before - 2,
          f"{status} {code_of(body)}, stock {before} -> {after}")

    # 5. The same event again (PB-09).
    status, body = pos_call(sale)
    check(5, "duplicate", status == 200 and code_of(body) == "DUPLICATE_IGNORED"
          and stock() == after, f"{status} {code_of(body)}, stock {stock()}")

    # 6. Same id, different content (PB-09).
    conflict = event("SALE", TXN_SALE, [(STOCK, 3, 32000.00)])
    status, body = pos_call(conflict)
    check(6, "same id, other quantity", status == 409 and code_of(body) == "CONFLICT",
          f"{status} {code_of(body)}")

    # 7. A sale above the stock (PB-10).
    big = event("SALE", TXN_BIG, [(STOCK, 999, 32000.00)])
    status, body = pos_call(big)
    check(7, "sale above stock", status == 409 and code_of(body) == "INSUFFICIENT_STOCK"
          and stock() == after, f"{status} {code_of(body)}, stock {stock()}")

    # 8. RETURN and CANCELLATION (PB-06, PB-07).
    returned = event("RETURN", TXN_RETURN, [(STOCK, 1, 32000.00)], original=TXN_SALE)
    status, body = pos_call(returned)
    check(8, "RETURN one unit", status == 200 and code_of(body) == "OK"
          and stock() == after + 1, f"{status} {code_of(body)}, stock {after} -> {stock()}")

    sku2_before = stock("SKU-0002")
    sale_b = event("SALE", TXN_SALE_B, [("SKU-0002", 3, 45000.00)])
    status, _ = pos_call(sale_b)
    sku2_after_sale = stock("SKU-0002")
    cancel_b = event("CANCELLATION", TXN_CANCEL_B, original=TXN_SALE_B)
    status, body = pos_call(cancel_b)
    check(8, "CANCELLATION restores the stock",
          status == 200 and code_of(body) == "OK" and sku2_after_sale == sku2_before - 3
          and stock("SKU-0002") == sku2_before,
          f"{status} {code_of(body)}, SKU-0002 {sku2_before} -> {sku2_after_sale} -> "
          f"{stock('SKU-0002')}")

    # 9. A sale that has a return cannot be cancelled (PB-07).
    cancel_a = event("CANCELLATION", TXN_RETURN_A, original=TXN_SALE)
    status, body = pos_call(cancel_a)
    check(9, "sale with a return", status == 409 and code_of(body) == "SALE_HAS_RETURNS",
          f"{status} {code_of(body)}")

    # 10. Stock query limited to the own store (PB-12).
    status, body = call("GET", f"{MIDDLEWARE}/stores/{STORE_DN1}/inventory",
                        token=TOKENS["staff_dn1"])
    check(10, "Staff reads STORE-DN1",
          status == 200 and isinstance(body, dict) and len(body.get("items", [])) == 9,
          f"{status}, {len(body.get('items', [])) if isinstance(body, dict) else '?'} SKUs")
    status, body = call("GET", f"{MIDDLEWARE}/stores/STORE-DN2/inventory",
                        token=TOKENS["staff_dn1"])
    check(10, "Staff reads STORE-DN2", status == 403 and code_of(body) == "FORBIDDEN",
          f"{status} {code_of(body)}")

    # 11. Barcode lookup (PB-31).
    status, body = call("GET", f"{MIDDLEWARE}/products/barcode/{BARCODE}",
                        token=TOKENS["staff_dn1"])
    check(11, f"barcode {BARCODE}",
          status == 200 and isinstance(body, dict) and body.get("sku") == STOCK,
          f"{status} {body.get('sku') if isinstance(body, dict) else body}")

    # 12. Guardrail rules (PB-26). Restore the threshold even if a check fails.
    status, body = call("GET", f"{MIDDLEWARE}/admin/guardrail-rules", token=TOKENS["admin"])
    rule = next((item for item in body.get("items", [])
                 if item["rule_type"] == "MAX_DISCOUNT" and item["category"] is None), None)
    if rule is None:
        check(12, "the seeded MAX_DISCOUNT rule", False, f"{status} {body}")
    else:
        rule_id = rule["rule_id"]
        try:
            status, body = call("PUT", f"{MIDDLEWARE}/admin/guardrail-rules/{rule_id}",
                                {"threshold": 150, "is_active": True}, token=TOKENS["admin"])
            check(12, "MAX_DISCOUNT 150", status == 422 and "threshold" in message_of(body),
                  f"{status} {code_of(body)} {message_of(body)[:60]}")
            status, body = call("PUT", f"{MIDDLEWARE}/admin/guardrail-rules/{rule_id}",
                                {"threshold": 40, "is_active": True}, token=TOKENS["admin"])
            check(12, "MAX_DISCOUNT 40", status == 200 and body.get("threshold") == 40.0,
                  f"{status} threshold {body.get('threshold')}")
        finally:
            status, body = call("PUT", f"{MIDDLEWARE}/admin/guardrail-rules/{rule_id}",
                                {"threshold": 50, "is_active": True}, token=TOKENS["admin"])
            check(12, "back to 50", status == 200 and body.get("threshold") == 50.0,
                  f"{status} threshold {body.get('threshold')}")

    # 13. Mutual TLS on the POS gateway (PB-48).
    no_cert = event("SALE", f"TXN-SMK-{RUN}-NC", [(STOCK, 1, 32000.00)])
    status, body = pos_call(no_cert, cert_pos=None)
    check(13, "no client certificate", status == 400, f"{status} from the gateway")
    wrong_cert = event("SALE", f"TXN-SMK-{RUN}-WC", [(STOCK, 1, 32000.00)])
    status, body = pos_call(wrong_cert, cert_pos="POS-DN2-01")
    check(13, "certificate of another terminal",
          status == 403 and code_of(body) == "FORBIDDEN", f"{status} {code_of(body)}")

    # 14. Audit log (PB-04).
    status, body = call("GET", f"{MIDDLEWARE}/audit-logs?limit=200", token=TOKENS["auditor"])
    keys = {STORE, POS, TXN_SALE, TXN_RETURN, TXN_SALE_B, TXN_CANCEL_B, TXN_RETURN_A,
            TXN_BIG}
    if rule is not None:
        keys.add(str(rule["rule_id"]))
    entries = [item for item in body.get("items", []) if item.get("entity_key") in keys] \
        if isinstance(body, dict) else []
    actions = {item["action"] for item in entries}
    wanted = {"STOCK_CHANGE", "DUPLICATE_EVENT", "EVENT_REJECTED", "STORE_REGISTERED",
              "POS_REGISTERED", "GUARDRAIL_RULE_UPDATED"}
    check(14, "Auditor sees this run",
          status == 200 and wanted <= actions,
          f"{status}, {len(entries)} entries: {', '.join(sorted(actions))}")
    status, body = call("GET", f"{MIDDLEWARE}/audit-logs", token=TOKENS["staff_dn1"])
    check(14, "Staff reads the audit log", status == 403 and code_of(body) == "FORBIDDEN",
          f"{status} {code_of(body)}")

    print()
    if failures:
        print(f"{failures} CHECK(S) FAILED")
        return 1
    print("ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    if not TOKENS_FILE.is_file():
        print(f"Missing {TOKENS_FILE}. Run scripts/issue_demo_tokens.py first.")
        sys.exit(1)
    sys.exit(run())
