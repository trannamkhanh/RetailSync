"""Generate one flat-illustration SVG per demo SKU.

Run once; the SVGs are committed as static assets under ``web/public/products``,
so the browser loads them from the same origin with no network dependency and no
third-party image host. Re-running overwrites the files, which keeps the palette
and framing identical across the catalogue.

Each drawing is deliberately simple: a rounded background, one or two shapes that
read as the product, and the product's initial as a fallback cue. Nothing here
tries to be a photograph.
"""

from pathlib import Path

OUT = Path(__file__).resolve().parents[2] / "web" / "public" / "products"

# sku -> (file stem, background colour, accent colour, inner markup)
ART: dict[str, tuple[str, str, str, str]] = {
    # --- Dairy -------------------------------------------------------------
    "SKU-0001": (
        "fresh-milk",
        "#e0f2fe",
        "#0369a1",
        """
        <rect x="52" y="30" width="46" height="70" rx="8" fill="#fff" stroke="#0369a1" stroke-width="4"/>
        <path d="M62 30 L70 14 L80 14 L88 30 Z" fill="#0369a1"/>
        <rect x="62" y="52" width="26" height="26" rx="4" fill="#bae6fd"/>
        <rect x="52" y="88" width="46" height="12" fill="#bae6fd"/>
        """,
    ),
    "SKU-0002": (
        "yogurt",
        "#fce7f3",
        "#9d174d",
        """
        <path d="M56 40 L94 40 L88 96 L62 96 Z" fill="#fff" stroke="#9d174d" stroke-width="4"/>
        <rect x="52" y="32" width="46" height="10" rx="4" fill="#9d174d"/>
        <circle cx="75" cy="68" r="12" fill="#fbcfe8"/>
        """,
    ),
    "SKU-0003": (
        "cheese",
        "#fef3c7",
        "#b45309",
        """
        <path d="M48 92 L48 52 L102 40 L102 92 Z" fill="#fde68a" stroke="#b45309" stroke-width="4"/>
        <circle cx="66" cy="72" r="5" fill="#b45309"/>
        <circle cx="86" cy="64" r="4" fill="#b45309"/>
        <circle cx="76" cy="84" r="3" fill="#b45309"/>
        """,
    ),
    "SKU-0020": (
        "drinking-yogurt",
        "#ede9fe",
        "#5b21b6",
        """
        <rect x="58" y="34" width="34" height="70" rx="6" fill="#fff" stroke="#5b21b6" stroke-width="4"/>
        <rect x="62" y="58" width="26" height="20" rx="4" fill="#ddd6fe"/>
        <rect x="68" y="20" width="14" height="16" rx="3" fill="#5b21b6"/>
        """,
    ),
    # --- Bakery ------------------------------------------------------------
    "SKU-0004": (
        "bread",
        "#fef3c7",
        "#92400e",
        """
        <path d="M46 74 Q46 42 75 42 Q104 42 104 74 L104 90 Q104 96 98 96 L52 96 Q46 96 46 90 Z"
              fill="#fcd34d" stroke="#92400e" stroke-width="4"/>
        <path d="M60 52 Q66 60 62 70" stroke="#92400e" stroke-width="3" fill="none" stroke-linecap="round"/>
        <path d="M75 50 Q81 58 77 68" stroke="#92400e" stroke-width="3" fill="none" stroke-linecap="round"/>
        <path d="M90 52 Q96 60 92 70" stroke="#92400e" stroke-width="3" fill="none" stroke-linecap="round"/>
        """,
    ),
    "SKU-0005": (
        "sponge-cake",
        "#fef9c3",
        "#a16207",
        """
        <rect x="50" y="52" width="50" height="44" rx="6" fill="#fef08a" stroke="#a16207" stroke-width="4"/>
        <rect x="50" y="52" width="50" height="16" rx="6" fill="#fff"/>
        <circle cx="75" cy="42" r="7" fill="#ef4444"/>
        <path d="M62 76 L88 76" stroke="#a16207" stroke-width="3"/>
        """,
    ),
    "SKU-0006": (
        "butter-cookies",
        "#fed7aa",
        "#9a3412",
        """
        <circle cx="60" cy="66" r="17" fill="#fdba74" stroke="#9a3412" stroke-width="4"/>
        <circle cx="90" cy="80" r="15" fill="#fdba74" stroke="#9a3412" stroke-width="4"/>
        <circle cx="55" cy="60" r="3" fill="#9a3412"/>
        <circle cx="66" cy="72" r="3" fill="#9a3412"/>
        <circle cx="86" cy="75" r="3" fill="#9a3412"/>
        <circle cx="95" cy="86" r="3" fill="#9a3412"/>
        """,
    ),
    "SKU-0021": (
        "sandwich",
        "#ffedd5",
        "#c2410c",
        """
        <path d="M46 58 L104 58 L96 48 L54 48 Z" fill="#fcd34d" stroke="#c2410c" stroke-width="4"/>
        <rect x="46" y="58" width="58" height="10" fill="#86efac"/>
        <rect x="46" y="68" width="58" height="8" fill="#fca5a5"/>
        <path d="M46 76 L104 76 L96 90 L54 90 Z" fill="#fcd34d" stroke="#c2410c" stroke-width="4"/>
        """,
    ),
    # --- Dry goods ---------------------------------------------------------
    "SKU-0007": (
        "rice",
        "#f5f5f4",
        "#57534e",
        """
        <path d="M54 44 L96 44 L100 96 L50 96 Z" fill="#fff" stroke="#57534e" stroke-width="4"/>
        <path d="M52 44 Q75 28 98 44 Z" fill="#e7e5e4" stroke="#57534e" stroke-width="4"/>
        <ellipse cx="75" cy="70" rx="14" ry="10" fill="#fafaf9" stroke="#57534e" stroke-width="3"/>
        """,
    ),
    "SKU-0008": (
        "instant-noodles",
        "#fecaca",
        "#991b1b",
        """
        <rect x="54" y="46" width="42" height="52" rx="6" fill="#fff" stroke="#991b1b" stroke-width="4"/>
        <ellipse cx="75" cy="46" rx="21" ry="8" fill="#fca5a5" stroke="#991b1b" stroke-width="4"/>
        <path d="M60 66 Q75 58 90 66" stroke="#f59e0b" stroke-width="5" fill="none" stroke-linecap="round"/>
        <path d="M60 78 Q75 70 90 78" stroke="#f59e0b" stroke-width="5" fill="none" stroke-linecap="round"/>
        """,
    ),
    "SKU-0009": (
        "cooking-oil",
        "#ecfccb",
        "#4d7c0f",
        """
        <rect x="58" y="38" width="34" height="60" rx="6" fill="#fde68a" stroke="#4d7c0f" stroke-width="4"/>
        <rect x="68" y="22" width="14" height="18" rx="3" fill="#4d7c0f"/>
        <rect x="62" y="58" width="26" height="18" rx="4" fill="#fff"/>
        """,
    ),
    # --- Fresh -------------------------------------------------------------
    "SKU-0010": (
        "water-spinach",
        "#dcfce7",
        "#15803d",
        """
        <path d="M75 96 L75 56" stroke="#15803d" stroke-width="5" stroke-linecap="round"/>
        <path d="M75 70 Q50 64 48 42 Q70 44 75 70 Z" fill="#4ade80" stroke="#15803d" stroke-width="3"/>
        <path d="M75 62 Q100 56 102 34 Q80 36 75 62 Z" fill="#22c55e" stroke="#15803d" stroke-width="3"/>
        <path d="M75 82 Q54 78 52 60 Q72 62 75 82 Z" fill="#22c55e" stroke="#15803d" stroke-width="3"/>
        """,
    ),
    "SKU-0011": (
        "tomato",
        "#fee2e2",
        "#b91c1c",
        """
        <circle cx="75" cy="66" r="26" fill="#ef4444" stroke="#b91c1c" stroke-width="4"/>
        <path d="M75 40 L63 30 M75 40 L87 30 M75 40 L75 26" stroke="#15803d" stroke-width="4" stroke-linecap="round"/>
        <path d="M60 60 Q75 52 90 60" stroke="#b91c1c" stroke-width="3" fill="none"/>
        """,
    ),
    "SKU-0012": (
        "banana",
        "#fef9c3",
        "#a16207",
        """
        <path d="M46 40 Q44 86 96 88" stroke="#a16207" stroke-width="4" fill="none" stroke-linecap="round"/>
        <path d="M46 40 Q50 84 96 88 Q88 62 66 48 Q54 42 46 40 Z" fill="#fde047" stroke="#a16207" stroke-width="3"/>
        <path d="M50 42 Q56 40 60 42" stroke="#a16207" stroke-width="3" fill="none"/>
        """,
    ),
    "SKU-0019": (
        "eggs",
        "#fef3c7",
        "#b45309",
        """
        <ellipse cx="62" cy="72" rx="17" ry="22" fill="#fff" stroke="#b45309" stroke-width="4"/>
        <ellipse cx="90" cy="76" rx="15" ry="19" fill="#fff" stroke="#b45309" stroke-width="4"/>
        <ellipse cx="62" cy="70" rx="6" ry="9" fill="#fde68a"/>
        """,
    ),
    # --- Beverages ---------------------------------------------------------
    "SKU-0013": (
        "beer-can",
        "#fef3c7",
        "#78350f",
        """
        <rect x="60" y="30" width="30" height="70" rx="6" fill="#fbbf24" stroke="#78350f" stroke-width="4"/>
        <ellipse cx="75" cy="30" rx="15" ry="6" fill="#fde68a" stroke="#78350f" stroke-width="4"/>
        <rect x="60" y="54" width="30" height="18" fill="#fff"/>
        <circle cx="75" cy="63" r="5" fill="#78350f"/>
        """,
    ),
    "SKU-0014": (
        "soft-drink",
        "#dbeafe",
        "#1d4ed8",
        """
        <path d="M62 32 L88 32 L84 96 L66 96 Z" fill="#bfdbfe" stroke="#1d4ed8" stroke-width="4"/>
        <rect x="60" y="24" width="30" height="10" rx="3" fill="#1d4ed8"/>
        <rect x="64" y="58" width="22" height="20" rx="4" fill="#fff"/>
        """,
    ),
    "SKU-0015": (
        "coffee",
        "#ede9fe",
        "#4c1d95",
        """
        <path d="M56 44 L94 44 L90 96 L60 96 Z" fill="#f5f5f4" stroke="#4c1d95" stroke-width="4"/>
        <rect x="52" y="34" width="46" height="12" rx="4" fill="#4c1d95"/>
        <ellipse cx="75" cy="70" rx="13" ry="11" fill="#78350f"/>
        <path d="M75 59 Q82 52 88 56" stroke="#78350f" stroke-width="3" fill="none"/>
        """,
    ),
    # --- Household ---------------------------------------------------------
    "SKU-0016": (
        "laundry",
        "#e0e7ff",
        "#3730a3",
        """
        <path d="M54 40 L96 40 L100 94 L50 94 Z" fill="#fff" stroke="#3730a3" stroke-width="4"/>
        <rect x="50" y="62" width="50" height="14" fill="#a5b4fc"/>
        <rect x="66" y="26" width="18" height="14" rx="3" fill="#3730a3"/>
        <circle cx="75" cy="80" r="7" fill="#c7d2fe"/>
        """,
    ),
    "SKU-0017": (
        "tissues",
        "#f5f3ff",
        "#6d28d9",
        """
        <rect x="46" y="52" width="58" height="44" rx="6" fill="#fff" stroke="#6d28d9" stroke-width="4"/>
        <ellipse cx="75" cy="52" rx="20" ry="7" fill="#ddd6fe" stroke="#6d28d9" stroke-width="3"/>
        <rect x="62" y="42" width="26" height="14" rx="3" fill="#fff" stroke="#6d28d9" stroke-width="3"/>
        """,
    ),
    "SKU-0018": (
        "dish-soap",
        "#cffafe",
        "#155e75",
        """
        <path d="M58 48 L92 48 L88 96 L62 96 Z" fill="#fff" stroke="#155e75" stroke-width="4"/>
        <rect x="68" y="30" width="14" height="18" rx="3" fill="#155e75"/>
        <path d="M72 30 Q72 20 84 20" stroke="#155e75" stroke-width="4" fill="none" stroke-linecap="round"/>
        <rect x="62" y="66" width="26" height="18" rx="4" fill="#a5f3fc"/>
        """,
    ),
}

TEMPLATE = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 150 120" width="150" height="120"
     role="img" aria-label="{label}">
  <rect width="150" height="120" fill="{bg}"/>
  <g>{art}</g>
</svg>
"""


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for sku, (stem, bg, _accent, art) in ART.items():
        label = stem.replace("-", " ")
        svg = TEMPLATE.format(bg=bg, art=art.strip(), label=label)
        (OUT / f"{stem}.svg").write_text(svg, encoding="utf-8")
        print(f"{sku:10} -> products/{stem}.svg")
    print(f"{len(ART)} images written to {OUT}")


if __name__ == "__main__":
    main()
