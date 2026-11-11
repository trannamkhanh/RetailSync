"""Pick one Commons photo per demo SKU and report it with its licence.

Commons search is noisy: "milk carton" also returns a band called The Milk
Carton Kids. So each SKU names a title fragment that must appear in the file
name, which keeps the choice reviewable instead of trusting rank order.
"""

import json
import time
import urllib.parse
import urllib.request

UA = "RetailSync-demo/0.1 (student project)"
API = "https://commons.wikimedia.org/w/api.php"

# sku -> (search term, must-appear-in-title fragments, prefer snippet)
DESIRED: dict[str, tuple[str, tuple[str, ...]]] = {
    "SKU-0001": ("milk carton", ("milk",)),
    "SKU-0002": ("yogurt", ("yogurt", "yoghurt")),
    "SKU-0003": ("cheese slices", ("cheese",)),
    "SKU-0004": ("sliced bread", ("bread",)),
    "SKU-0005": ("sponge cake", ("sponge", "cake")),
    "SKU-0006": ("butter cookies", ("cookie",)),
    "SKU-0007": ("bag of rice", ("rice",)),
    "SKU-0008": ("instant noodles", ("noodle",)),
    "SKU-0009": ("cooking oil", ("oil",)),
    "SKU-0010": ("water spinach", ("spinach", "convolvulus", "kangkung", "morning glory", "空心菜")),
    "SKU-0011": ("tomato", ("tomato",)),
    "SKU-0012": ("bananas", ("banana",)),
    "SKU-0013": ("beer can", ("beer",)),
    "SKU-0014": ("bottle of soft drink", ("soft drink", "soda", "cola", "coke")),
    "SKU-0015": ("coffee beans", ("coffee",)),
    "SKU-0016": ("laundry detergent", ("detergent", "laundry")),
    "SKU-0017": ("tissue box", ("tissue",)),
    "SKU-0018": ("dishwashing liquid", ("dish", "washing")),
    "SKU-0019": ("chicken eggs", ("egg",)),
    "SKU-0020": ("yogurt drink", ("yogurt", "yoghurt")),
    "SKU-0021": ("sandwich", ("sandwich",)),
}


def get(params: dict, *, attempts: int = 4) -> dict:
    url = f"{API}?{urllib.parse.urlencode(params)}"
    for attempt in range(attempts):
        request = urllib.request.Request(url, headers={"User-Agent": UA})
        try:
            with urllib.request.urlopen(request, timeout=40) as response:
                return json.load(response)
        except urllib.error.HTTPError as error:
            if error.code != 429 or attempt == attempts - 1:
                raise
            time.sleep(5 * (attempt + 1))
    raise RuntimeError("unreachable")


def search(term: str, limit: int = 20) -> list[dict]:
    payload = get(
        {
            "action": "query",
            "format": "json",
            "generator": "search",
            "gsrsearch": f"filetype:bitmap {term}",
            "gsrnamespace": "6",
            "gsrlimit": str(limit),
            "prop": "imageinfo",
            "iiprop": "url|extmetadata|size|mime",
            "iiurlwidth": "800",
        }
    )
    pages = (payload.get("query") or {}).get("pages") or {}
    out = []
    for page in pages.values():
        info = (page.get("imageinfo") or [{}])[0]
        meta = info.get("extmetadata") or {}
        out.append(
            {
                "title": page.get("title", ""),
                "url": info.get("thumburl") or info.get("url"),
                "full": info.get("url"),
                "mime": info.get("mime"),
                "width": info.get("width") or 0,
                "height": info.get("height") or 0,
                "licence": (meta.get("LicenseShortName") or {}).get("value", "?"),
                "author": (meta.get("Artist") or {}).get("value", "?"),
                "page": info.get("descriptionurl"),
            }
        )
    return out


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


def main() -> None:
    chosen: dict[str, dict] = {}
    for sku, (term, fragments) in DESIRED.items():
        try:
            candidates = search(term)
        except Exception as error:  # noqa: BLE001
            print(f"{sku}: SEARCH FAILED {error}")
            time.sleep(3)
            continue

        best = None
        for candidate in candidates:
            if candidate["mime"] not in ("image/jpeg", "image/png"):
                continue
            title = candidate["title"].lower()
            if not any(fragment.lower() in title for fragment in fragments):
                continue
            if min(candidate["width"], candidate["height"]) < 400:
                continue
            if "recalled" in title or "advert" in title:
                continue
            best = candidate
            break

        if best is None:
            print(f"{sku}: NO MATCH for '{term}'")
        else:
            chosen[sku] = best
            print(f"{sku}: {best['title']}")
            print(f"       {best['width']}x{best['height']} {best['licence']} by {clean(best['author'])[:60]}")
        time.sleep(5)

    print("\n--- resolved ---")
    print(json.dumps(chosen, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
