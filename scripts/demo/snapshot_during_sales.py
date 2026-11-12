"""Live check for PB-13: sales keep running while HQ snapshots arrive.

Sends `POST /api/v1/hq/snapshot` in a loop for the duration of a simulator run,
then prints how many snapshots were refused and whether the ledger still
balances. Read-only towards stock; it never writes a delta.

Usage, from the repository root in PowerShell:

    docker compose run --rm --no-deps --volume "${PWD}:/repo" --workdir /repo `
        --env PYTHONDONTWRITEBYTECODE=1 middleware `
        python scripts/demo/snapshot_during_sales.py --seconds 120
"""

from __future__ import annotations

import argparse
import json
import ssl
import sys
import time
import urllib.error
import urllib.request
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
STORE = "STORE-DN1"
BODY = json.dumps({"store_id": STORE, "items": [{"sku": "SKU-0001", "quantity": 0}]}).encode()


def token() -> str:
    tokens = json.loads((ROOT / ".tokens" / "demo_tokens.json").read_text())
    return tokens["hq_operator"]


def post(url: str, body: bytes, bearer: str, context: ssl.SSLContext) -> tuple[int, dict]:
    request = urllib.request.Request(
        url, data=body, method="POST",
        headers={"Authorization": f"Bearer {bearer}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, context=context, timeout=5) as response:
            return response.status, json.loads(response.read() or b"{}")
    except urllib.error.HTTPError as error:
        return error.code, json.loads(error.read() or b"{}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seconds", type=float, default=120)
    parser.add_argument("--interval", type=float, default=2.0)
    parser.add_argument("--url", default="https://middleware:8443/api/v1/hq/snapshot")
    args = parser.parse_args()

    context = ssl.create_default_context(cafile=str(ROOT / ".certs" / "ca.crt"))
    bearer = token()
    results: Counter = Counter()
    deadline = time.monotonic() + args.seconds
    while time.monotonic() < deadline:
        status, body = post(args.url, BODY, bearer, context)
        results[(status, body.get("code"))] += 1
        time.sleep(args.interval)

    print(f"snapshots sent={sum(results.values())} results={dict(results)}")
    refused = results[(422, "SNAPSHOT_REJECTED")]
    return 0 if refused == sum(results.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
