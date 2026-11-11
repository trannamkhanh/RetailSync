"""Print candidate Commons files for the SKUs whose first match was wrong."""

import json
import time
import urllib.parse
import urllib.request

UA = "RetailSync-demo/0.1 (student project)"
API = "https://commons.wikimedia.org/w/api.php"

TERMS = {
    "milk": "milk bottle glass",
    "cheese": "sliced cheese",
    "bread": "white bread loaf",
    "rice": "rice grains bowl",
    "oil": "cooking oil bottle kitchen",
    "tomato": "tomato fruit red",
    "softdrink": "cola bottle",
}


def get(params: dict, attempts: int = 5) -> dict:
    url = f"{API}?{urllib.parse.urlencode(params)}"
    for attempt in range(attempts):
        request = urllib.request.Request(url, headers={"User-Agent": UA})
        try:
            with urllib.request.urlopen(request, timeout=40) as response:
                return json.load(response)
        except urllib.error.HTTPError as error:
            if error.code != 429 or attempt == attempts - 1:
                raise
            time.sleep(8 * (attempt + 1))
    raise RuntimeError("unreachable")


def clean(html: str) -> str:
    out, depth = [], 0
    for char in html:
        if char == "<":
            depth += 1
        elif char == ">":
            depth = max(0, depth - 1)
        elif depth == 0:
            out.append(char)
    return " ".join("".join(out).split())


for label, term in TERMS.items():
    print(f"\n=== {label}: {term} ===")
    try:
        payload = get(
            {
                "action": "query",
                "format": "json",
                "generator": "search",
                "gsrsearch": f"filetype:bitmap {term}",
                "gsrnamespace": "6",
                "gsrlimit": "12",
                "prop": "imageinfo",
                "iiprop": "url|extmetadata|size|mime",
                "iiurlwidth": "800",
            }
        )
    except Exception as error:  # noqa: BLE001
        print(f"  FAILED {error}")
        time.sleep(10)
        continue

    for page in ((payload.get("query") or {}).get("pages") or {}).values():
        info = (page.get("imageinfo") or [{}])[0]
        if info.get("mime") not in ("image/jpeg", "image/png"):
            continue
        meta = info.get("extmetadata") or {}
        licence = (meta.get("LicenseShortName") or {}).get("value", "?")
        author = clean((meta.get("Artist") or {}).get("value", "?"))[:40]
        print(f"  {page.get('title')}")
        print(f"     {info.get('width')}x{info.get('height')} | {licence} | {author}")
    time.sleep(6)
