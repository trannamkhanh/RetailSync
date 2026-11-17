import json
from math import ceil
from pathlib import Path
from time import monotonic, sleep
import requests

tokens = json.loads(Path("/repo/.tokens/demo_tokens.json").read_text())
elapsed = []
with requests.Session() as session:
    session.verify = "/repo/.certs/ca.crt"
    session.headers["Authorization"] = f"Bearer {tokens['staff_dn1']}"
    for _ in range(24):
        started = monotonic()
        response = session.get(
            "https://middleware:8443/api/v1/products/barcode/8930000000011/stock",
            params={"from_store": "STORE-DN1"}, timeout=5,
        )
        response.raise_for_status()
        elapsed.append((monotonic() - started) * 1000)
        sleep(max(0, 1 - (monotonic() - started)))
elapsed.sort()
print(json.dumps({"samples": len(elapsed), "p95_ms": round(elapsed[ceil(len(elapsed)*0.95)-1], 2),
                  "max_ms": round(max(elapsed), 2)}))
