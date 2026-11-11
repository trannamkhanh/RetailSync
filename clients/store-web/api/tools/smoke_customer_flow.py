"""End-to-end check of the customer flow over HTTP, using UTF-8 on both sides.

Run it against a live API:

    .\\.venv\\Scripts\\python.exe tools\\smoke_customer_flow.py

It creates one throwaway account, saves an address, searches, and deletes nothing
except its own session. Not part of pytest: it needs a running server.
"""

import json
import sys
import urllib.error
import urllib.request
from uuid import uuid4


BASE = "http://127.0.0.1:5180"


def call(method: str, path: str, body: dict | None = None, cookie: str | None = None):
    data = json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None
    request = urllib.request.Request(
        BASE + path, data=data, method=method,
        headers={"Content-Type": "application/json; charset=utf-8", "Accept": "application/json"},
    )
    if cookie:
        request.add_header("Cookie", cookie)
    try:
        with urllib.request.urlopen(request) as response:
            raw = response.read().decode("utf-8")
            return response.status, (json.loads(raw) if raw else None), response.headers.get_all("Set-Cookie")
    except urllib.error.HTTPError as error:
        raw = error.read().decode("utf-8")
        return error.code, (json.loads(raw) if raw else None), error.headers.get_all("Set-Cookie")


def main() -> int:
    failures: list[str] = []

    def check(name: str, condition: bool, detail: str = "") -> None:
        print(("PASS  " if condition else "FAIL  ") + name + (f"  [{detail}]" if detail and not condition else ""))
        if not condition:
            failures.append(name)

    email = f"khach-{uuid4().hex[:10]}@example.test"
    status, body, cookies = call("POST", "/api/auth/register", {
        "email": email, "full_name": "Nguyễn Thị Khách", "password": "matkhau123",
    })
    check("register 201", status == 201, str(status))
    cookie = (cookies or [""])[0].split(";")[0]
    check("cookie set and httpOnly", "httponly" in (cookies or [""])[0].lower(), (cookies or [""])[0])
    check("name keeps Vietnamese", (body or {}).get("customer", {}).get("full_name") == "Nguyễn Thị Khách", str(body))

    status, body, _ = call("GET", "/api/auth/me", cookie=cookie)
    check("me 200", status == 200 and (body or {}).get("customer", {}).get("email") == email, str(body))

    status, body, _ = call("POST", "/api/shop/addresses/mine", {
        "label": "Nhà riêng",
        "address_text": "123 Bạch Đằng, Hải Châu, Đà Nẵng",
        "latitude": 16.0678, "longitude": 108.2208,
    }, cookie=cookie)
    check("save address 201", status == 201, str(status))
    check(
        "address text keeps Vietnamese",
        (body or {}).get("address_text") == "123 Bạch Đằng, Hải Châu, Đà Nẵng",
        str((body or {}).get("address_text")),
    )

    status, body, _ = call("GET", "/api/shop/addresses/mine", cookie=cookie)
    check("saved address listed", status == 200 and len((body or {}).get("addresses", [])) == 1, str(body))

    status, body, _ = call("GET", "/api/shop/search?q=milk&latitude=16.0678&longitude=108.2208")
    items = (body or {}).get("items", [])
    check("search finds the milk", status == 200 and len(items) == 1, str(status))
    if items:
        nearest = items[0].get("nearest") or {}
        check("nearest store is DN1", nearest.get("store_id") == "STORE-DN1", str(nearest))
        check("nearest has stock", nearest.get("sellable_quantity") == 40, str(nearest))
        check("all three stores offered", len(items[0].get("stores", [])) == 3, str(len(items[0].get("stores", []))))

    status, body, _ = call("GET", "/api/shop/search?q=milk&latitude=16.0750&longitude=108.2350")
    items = (body or {}).get("items", [])
    if items:
        nearest = items[0].get("nearest") or {}
        check("from Son Tra the nearest is DN3", nearest.get("store_id") == "STORE-DN3", str(nearest))

    status, body, _ = call("GET", "/api/shop/search?q=milk")
    check("missing coordinates rejected", status == 422, str(status))

    status, body, _ = call("POST", "/api/auth/login", {"email": email, "password": "wrong-password"})
    check("wrong password 401", status == 401, str(status))

    status, body, _ = call("POST", "/api/auth/login", {"email": email, "password": "matkhau123"})
    check("login 200", status == 200, str(status))
    login_cookie = (body is not None, (cookies or [""])[0].split(";")[0])

    status, _, _ = call("POST", "/api/auth/logout", cookie=login_cookie[1])
    check("logout 204", status == 204, str(status))

    status, _, _ = call("GET", "/api/auth/me", cookie=login_cookie[1])
    check("me after logout 401", status == 401, str(status))

    status, _, _ = call("GET", "/api/shop/addresses/mine")
    check("saved addresses need login", status == 401, str(status))

    print()
    if failures:
        print(f"{len(failures)} check(s) failed: {', '.join(failures)}")
        return 1
    print("All customer flow checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
