import argparse
import json
from math import ceil
from pathlib import Path
from time import monotonic, sleep
import requests

parser = argparse.ArgumentParser(description="Sample Staff cross-store lookups during POS traffic.")
parser.add_argument("--stop-file", type=Path, required=True,
                    help="Keep sampling until the POS runner creates this file")
args = parser.parse_args()
tokens = json.loads(Path("/repo/.tokens/demo_tokens.json").read_text())
elapsed = []
statuses = {}
errors = 0
with requests.Session() as session:
    session.verify = "/repo/.certs/ca.crt"
    session.headers["Authorization"] = f"Bearer {tokens['staff_dn1']}"
    while not args.stop_file.exists():
        started = monotonic()
        try:
            response = session.get(
                "https://middleware:8443/api/v1/products/barcode/8930000000011/stock",
                params={"from_store": "STORE-DN1"}, timeout=5,
            )
            statuses[response.status_code] = statuses.get(response.status_code, 0) + 1
            errors += int(not response.ok)
        except requests.RequestException:
            errors += 1
        elapsed.append((monotonic() - started) * 1000)
        sleep(max(0, 1 - (monotonic() - started)))
elapsed.sort()
if not elapsed:
    raise SystemExit("No lookup samples collected")
print(json.dumps({"samples": len(elapsed), "errors": errors, "statuses": statuses,
                  "p95_ms": round(elapsed[ceil(len(elapsed)*0.95)-1], 2),
                  "max_ms": round(max(elapsed), 2)}))
