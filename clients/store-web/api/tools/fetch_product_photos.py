"""Download the chosen Commons photos and record their attribution.

Each SKU names an exact Commons file, so nothing depends on search ranking. For
every file the script asks the API for the licence and author (not transcribed by
hand), downloads an 800 px render, shrinks it to a card-sized JPEG with Pillow and
writes ``ATTRIBUTION.md`` next to the images. The photos stay local, so the shop
works without internet and no third-party host is called by the browser.
"""

import io
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from PIL import Image

USER_AGENT = "RetailSync-demo/0.1 (student project)"
API = "https://commons.wikimedia.org/w/api.php"

OUT = Path(__file__).resolve().parents[2] / "web" / "public" / "products"

# sku -> (output stem, exact Commons file title)
PHOTOS: dict[str, tuple[str, str]] = {
    "SKU-0001": ("fresh-milk", "File:Plastic bottle of milk.jpg"),
    "SKU-0002": ("yogurt", "File:Creamy yogurt.jpg"),
    "SKU-0003": ("cheese", "File:White cheddar cheese sliced CNE.jpg"),
    "SKU-0004": ("bread", "File:Tin Loaf - one slash in the crust.jpg"),
    "SKU-0005": ("sponge-cake", "File:Zero-sugar sponge cake.jpg"),
    "SKU-0006": ("butter-cookies", "File:Danish-butter-cookies-1032894.jpg"),
    "SKU-0007": ("rice", "File:Bag of rice 20221028 150305.jpg"),
    "SKU-0008": ("instant-noodles", "File:-2022-01-14 Instant noodles & paster packets, Morrisons, Cromer.JPG"),
    "SKU-0009": ("cooking-oil", "File:Oil3.jpg"),
    "SKU-0010": ("water-spinach", "File:空心菜 - 深圳.jpg"),
    "SKU-0011": ("tomato", "File:Red and orange cherry tomatoes, Mercado de Arroios, Lisbon, Portugal julesvernex2.jpg"),
    "SKU-0012": ("banana", "File:At Icod de los Vinos 2023 033 - Bananas at Parque del Drago.jpg"),
    "SKU-0013": ("beer-can", "File:Budweiser Lager.jpg"),
    "SKU-0014": ("soft-drink", "File:Cola bottle aug 21.jpg"),
    "SKU-0015": ("coffee", "File:Amy farms typica hybrid coffee beans.jpg"),
    "SKU-0016": ("laundry", "File:HK SKD TKO Po Yap Road 將軍澳廣場 Tseung Kwan O Plaza K-mart fresh food indoor market shop Kai Bo Food Supermarket Wayway Laundry Liquid plastic bottle July 2021 SS2 01.jpg"),
    "SKU-0017": ("tissues", "File:A tissue box.jpg"),
    "SKU-0018": ("dish-soap", "File:Dish-soap.jpg"),
    "SKU-0019": ("eggs", "File:6-Pack-Chicken-Eggs.jpg"),
    "SKU-0020": ("drinking-yogurt", "File:Yakult drink.jpg"),
    "SKU-0021": ("sandwich", "File:A roast beef sandwich with au jus sauce for dipping, served with a side of fries..jpg"),
}

TARGET_WIDTH = 640
TARGET_HEIGHT = 512


def api(params: dict, *, attempts: int = 5) -> dict:
    url = f"{API}?{urllib.parse.urlencode(params)}"
    for attempt in range(attempts):
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        try:
            with urllib.request.urlopen(request, timeout=45) as response:
                return json.load(response)
        except urllib.error.HTTPError as error:
            if error.code != 429 or attempt == attempts - 1:
                raise
            time.sleep(8 * (attempt + 1))
    raise RuntimeError("unreachable")


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


def info_for(title: str) -> dict:
    payload = api(
        {
            "action": "query",
            "format": "json",
            "titles": title,
            "prop": "imageinfo",
            "iiprop": "url|extmetadata|size|mime",
            "iiurlwidth": "800",
        }
    )
    pages = (payload.get("query") or {}).get("pages") or {}
    page = next(iter(pages.values()))
    if "imageinfo" not in page:
        raise RuntimeError(f"no imageinfo for {title}")
    info = page["imageinfo"][0]
    meta = info.get("extmetadata") or {}
    return {
        "title": title,
        "thumb": info.get("thumburl") or info.get("url"),
        "licence": (meta.get("LicenseShortName") or {}).get("value", "unknown"),
        "author": strip_html((meta.get("Artist") or {}).get("value", "unknown")) or "unknown",
        "page": info.get("descriptionurl", ""),
    }


def download(url: str) -> bytes:
    for attempt in range(5):
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                return response.read()
        except urllib.error.HTTPError as error:
            if error.code != 429 or attempt == 4:
                raise
            time.sleep(8 * (attempt + 1))
    raise RuntimeError("unreachable")


def save_card(raw: bytes, target: Path) -> tuple[int, int]:
    """Crop to 5:4 from the centre, then shrink: cards are a fixed shape."""
    with Image.open(io.BytesIO(raw)) as image:
        image = image.convert("RGB")
        width, height = image.size
        wanted = TARGET_WIDTH / TARGET_HEIGHT
        if width / height > wanted:
            new_width = int(height * wanted)
            left = (width - new_width) // 2
            image = image.crop((left, 0, left + new_width, height))
        else:
            new_height = int(width / wanted)
            top = (height - new_height) // 2
            image = image.crop((0, top, width, top + new_height))
        image = image.resize((TARGET_WIDTH, TARGET_HEIGHT), Image.LANCZOS)
        image.save(target, "JPEG", quality=82, optimize=True)
    return TARGET_WIDTH, TARGET_HEIGHT


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    rows: list[dict] = []

    for sku, (stem, title) in PHOTOS.items():
        target = OUT / f"{stem}.jpg"
        try:
            meta = info_for(title)
            raw = download(meta["thumb"])
            size = save_card(raw, target)
            rows.append({**meta, "sku": sku, "file": target.name, "kb": target.stat().st_size // 1024})
            print(f"{sku}: {target.name}  {size[0]}x{size[1]}  {target.stat().st_size // 1024} kB  {meta['licence']}")
        except Exception as error:  # noqa: BLE001
            print(f"{sku}: FAILED {error}")
        time.sleep(4)

    lines = [
        "# Ảnh sản phẩm — nguồn và giấy phép",
        "",
        "Ảnh thật lấy từ Wikimedia Commons, tải về và thu nhỏ (640×512, cắt giữa) để dùng",
        "làm minh hoạ trong demo. Mỗi ảnh giữ giấy phép riêng của nó; khi dùng lại ngoài",
        "phạm vi bài tập, đọc trang gốc và ghi công tác giả theo đúng giấy phép.",
        "",
        "| SKU | Tệp | Tác giả | Giấy phép | Trang gốc |",
        "|---|---|---|---|---|",
    ]
    for row in rows:
        lines.append(
            f"| {row['sku']} | `{row['file']}` | {row['author']} | {row['licence']} | [Commons]({row['page']}) |"
        )
    (OUT / "ATTRIBUTION.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"\n{len(rows)}/{len(PHOTOS)} photos saved; attribution written.")


if __name__ == "__main__":
    main()
