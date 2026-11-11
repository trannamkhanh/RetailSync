"""Search Wikimedia Commons for one photo per demo SKU.

Prints candidates so a human can eyeball the match before anything is downloaded;
only the chosen file names go into the download step. Commons content is freely
licensed but each file keeps its own licence, which is why the licence and author
are fetched too and stored next to the images.
"""

import json
import urllib.parse
import urllib.request

UA = "RetailSync-demo/0.1 (student project; contact: local)"
API = "https://commons.wikimedia.org/w/api.php"

QUERIES: dict[str, str] = {
    "SKU-0001": "milk carton",
    "SKU-0002": "yogurt cup",
    "SKU-0003": "cheese slices",
    "SKU-0004": "sliced bread loaf",
    "SKU-0005": "sponge cake",
    "SKU-0006": "butter cookies",
    "SKU-0007": "rice bag",
    "SKU-0008": "instant noodles",
    "SKU-0009": "cooking oil bottle",
    "SKU-0010": "water spinach vegetable",
    "SKU-0011": "tomato",
    "SKU-0012": "banana bunch",
    "SKU-0013": "beer can",
    "SKU-0014": "soft drink bottle",
    "SKU-0015": "roasted coffee beans",
    "SKU-0016": "laundry detergent bottle",
    "SKU-0017": "tissue paper box",
    "SKU-0018": "dishwashing liquid",
    "SKU-0019": "chicken eggs",
    "SKU-0020": "drinking yogurt bottle",
    "SKU-0021": "sandwich",
}


def search(term: str, limit: int = 6) -> list[dict]:
    params = {
        "action": "query",
        "format": "json",
        "generator": "search",
        "gsrsearch": f"filetype:bitmap {term}",
        "gsrnamespace": "6",
        "gsrlimit": str(limit),
        "prop": "imageinfo",
        "iiprop": "url|extmetadata|size|mime",
        "iiurlwidth": "600",
    }
    url = f"{API}?{urllib.parse.urlencode(params)}"
    request = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(request, timeout=30) as response:
        payload = json.load(response)

    pages = (payload.get("query") or {}).get("pages") or {}
    results = []
    for page in pages.values():
        info = (page.get("imageinfo") or [{}])[0]
        meta = info.get("extmetadata") or {}
        results.append(
            {
                "title": page.get("title", ""),
                "url": info.get("thumburl") or info.get("url"),
                "mime": info.get("mime"),
                "width": info.get("width"),
                "height": info.get("height"),
                "licence": (meta.get("LicenseShortName") or {}).get("value", "?"),
                "author": (meta.get("Artist") or {}).get("value", "?"),
                "page": info.get("descriptionurl"),
            }
        )
    return results


def strip_html(text: str) -> str:
    out, depth = [], 0
    for char in text:
        if char == "<":
            depth += 1
        elif char == ">":
            depth = max(0, depth - 1)
        elif depth == 0:
            out.append(char)
    return " ".join("".join(out).split())


if __name__ == "__main__":
    for sku, term in QUERIES.items():
        print(f"\n=== {sku}  ({term}) ===")
        try:
            for candidate in search(term):
                if candidate["mime"] not in ("image/jpeg", "image/png"):
                    continue
                print(f"  {candidate['title']}")
                print(f"     {candidate['width']}x{candidate['height']}  {candidate['licence']}")
                print(f"     author: {strip_html(candidate['author'])[:80]}")
        except Exception as error:  # noqa: BLE001 - a probe, print and continue
            print(f"  FAILED: {error}")
