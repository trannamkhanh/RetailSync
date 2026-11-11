"""Pick the store a customer should visit for one product.

Pure functions over already-read rows so the rule is testable without SQL or
routing: nearest store that has stock beats farther stores, and a store without
stock is never suggested as a place to go.

Distances are computed once per search in ``app.routing`` and passed in, so a
search asks the routing server one question no matter how many products match.
"""


def nearest_stores_for_product(
    stores: list[dict],
    stock_by_store: dict[str, int],
    *,
    distances: dict[str, tuple[float, str]],
) -> list[dict]:
    """Stores that can sell the product, nearest first.

    ``stock_by_store`` holds only stores with sellable stock, so a store missing
    from it is skipped. ``distances`` maps ``store_id`` to ``(km, kind)``.
    The caller decides what to show when the list is empty.
    """
    candidates = []
    for store in stores:
        sellable = stock_by_store.get(store["store_id"], 0)
        if sellable <= 0:
            continue
        km, kind = distances[store["store_id"]]
        candidates.append(
            {
                "store_id": store["store_id"],
                "name": store["name"],
                "region_id": store["region_id"],
                "address_text": store.get("address_text"),
                "sellable_quantity": sellable,
                "distance_km": km,
                "distance_kind": kind,
            }
        )
    candidates.sort(key=lambda entry: (entry["distance_km"], entry["store_id"]))
    return candidates


def best_store(suggestions: list[dict]) -> dict | None:
    """The first suggestion, or ``None`` when no store has the product."""
    return suggestions[0] if suggestions else None


def suggestion(store: dict, quantity: int, distance: tuple[float, str]) -> dict:
    """The wire shape shared by the shop and the store page."""
    km, kind = distance
    return {
        "store_id": store["store_id"],
        "name": store["name"],
        "region_id": store["region_id"],
        "address_text": store.get("address_text"),
        "sellable_quantity": quantity,
        "distance_km": km,
        "distance_kind": kind,
    }


def attach_nearest_stores(
    items: list[dict],
    *,
    view_store_id: str,
    stock_by_sku: dict[str, dict[str, int]],
    stores: list[dict],
    distances: dict[str, tuple[float, str]],
) -> list[dict]:
    """Add ``nearest_store`` to each item of a store page, in place.

    The store being viewed wins whenever it has the product: the customer is
    already looking at that branch, so "buy it here" is the useful answer even if
    another branch is a few hundred metres closer. Only when the viewed store has
    none does the nearest branch with stock become the suggestion. No stock
    anywhere leaves ``None``, which the web shows as "hết hàng".
    """
    by_id = {store["store_id"]: store for store in stores}

    for item in items:
        stock = stock_by_sku.get(item["sku"], {})

        if stock.get(view_store_id, 0) > 0:
            item["nearest_store"] = suggestion(
                by_id[view_store_id], stock[view_store_id], distances[view_store_id]
            )
            continue

        candidates = [
            (distances[store_id][0], store_id, quantity)
            for store_id, quantity in stock.items()
            if quantity > 0 and store_id in by_id and store_id in distances
        ]
        if not candidates:
            item["nearest_store"] = None
            continue

        _, store_id, quantity = min(candidates, key=lambda entry: (entry[0], entry[1]))
        item["nearest_store"] = suggestion(by_id[store_id], quantity, distances[store_id])

    return items
