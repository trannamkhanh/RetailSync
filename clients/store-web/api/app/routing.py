"""Road distance from a customer to the stores, with a straight-line fallback.

The shop suggests "the nearest store that still has the product". Driving
distance is what a customer actually travels, so the ranking asks an OSRM
routing server (``STORE_WEB_OSRM_URL``) for one ``table`` request per search:
one origin, every candidate store at once.

Routing is best-effort. A timeout, a connection error, a non-``Ok`` payload or a
disabled URL all fall back to the haversine distance in ``app.geo``, so the shop
keeps answering with a usable (if slightly optimistic) number instead of failing.
Every result records which kind of distance it is; the web shows that flag, so a
fallback is never silently presented as a road distance.
"""

from dataclasses import dataclass
from typing import Literal

import httpx

from app.geo import distance_km

DistanceKind = Literal["road", "straight"]

ROAD = "road"
STRAIGHT = "straight"


@dataclass(frozen=True)
class StoreDistance:
    """One store's distance from the customer, in kilometres."""

    store_id: str
    km: float
    kind: DistanceKind


def _coords(latitude: float, longitude: float) -> str:
    """OSRM wants ``longitude,latitude``, six decimals is ~10 cm."""
    return f"{longitude:.6f},{latitude:.6f}"


def _table_request(
    origin: tuple[float, float],
    stores: list[dict],
    *,
    base_url: str,
    timeout: float,
    client: httpx.Client | None = None,
) -> list[float] | None:
    """Drive distances in store order, or ``None`` when routing is unavailable."""
    if not base_url or not stores:
        return None

    points = [_coords(*origin)] + [_coords(store["latitude"], store["longitude"]) for store in stores]
    destinations = ";".join(str(index) for index in range(1, len(points)))
    url = f"{base_url}/table/v1/driving/{';'.join(points)}"

    try:
        owned = client is None
        session = client or httpx.Client(timeout=timeout)
        try:
            response = session.get(
                url,
                params={
                    "sources": "0",
                    "destinations": destinations,
                    "annotations": "distance",
                },
                timeout=timeout,
            )
            response.raise_for_status()
            payload = response.json()
        finally:
            if owned:
                session.close()
    except (httpx.HTTPError, ValueError):
        return None

    if payload.get("code") != "Ok":
        return None
    rows = payload.get("distances") or []
    if not rows or not rows[0]:
        return None

    metres = rows[0]
    if len(metres) != len(stores):
        return None
    # A store unreachable by road comes back as null; fall back per store instead
    # of dropping it, or a missing route would look like "no stock".
    return [None if value is None else float(value) / 1000 for value in metres]


def store_distances(
    stores: list[dict],
    *,
    latitude: float,
    longitude: float,
    base_url: str,
    timeout: float = 2.0,
    client: httpx.Client | None = None,
) -> list[StoreDistance]:
    """Distance from one origin to each store, rounded to 100 m like ``geo``.

    Returns one entry per input store, in the same order, so the caller can zip
    them back onto its own rows without matching by id.
    """
    road = _table_request(
        (latitude, longitude),
        stores,
        base_url=base_url,
        timeout=timeout,
        client=client,
    )

    distances: list[StoreDistance] = []
    for index, store in enumerate(stores):
        value = road[index] if road is not None else None
        if value is None:
            distances.append(
                StoreDistance(
                    store_id=store["store_id"],
                    km=distance_km(
                        latitude, longitude, store["latitude"], store["longitude"]
                    ),
                    kind=STRAIGHT,
                )
            )
        else:
            distances.append(
                StoreDistance(store_id=store["store_id"], km=round(value, 1), kind=ROAD)
            )
    return distances
