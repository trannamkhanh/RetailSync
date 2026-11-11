"""Road distance with a straight-line fallback.

The routing server is never contacted for real: a local ``httpx.MockTransport``
stands in, so the tests are offline and fast while still exercising the exact
request the API builds and the fallback paths.
"""

import httpx

from app.geo import distance_km
from app.routing import ROAD, STRAIGHT, store_distances

STORES = [
    {"store_id": "S-A", "latitude": 16.0, "longitude": 108.0},
    {"store_id": "S-B", "latitude": 16.1, "longitude": 108.1},
]


def _client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_road_distance_comes_from_the_routing_server() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"code": "Ok", "distances": [[2756.9, 12034.5]]})

    result = store_distances(
        STORES,
        latitude=16.05,
        longitude=108.05,
        base_url="https://router.test",
        client=_client(handler),
    )

    assert [(entry.store_id, entry.km, entry.kind) for entry in result] == [
        ("S-A", 2.8, ROAD),
        ("S-B", 12.0, ROAD),
    ]

    # One request for every store, origin first, destinations as indices.
    assert len(seen) == 1
    request = seen[0]
    assert request.url.path == "/table/v1/driving/108.050000,16.050000;108.000000,16.000000;108.100000,16.100000"
    assert request.url.params["sources"] == "0"
    assert request.url.params["destinations"] == "1;2"
    assert request.url.params["annotations"] == "distance"


def test_unreachable_store_falls_back_to_straight_line() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"code": "Ok", "distances": [[2756.9, None]]})

    result = store_distances(
        STORES,
        latitude=16.05,
        longitude=108.05,
        base_url="https://router.test",
        client=_client(handler),
    )

    assert (result[0].km, result[0].kind) == (2.8, ROAD)
    expected = distance_km(16.05, 108.05, 16.1, 108.1)
    assert (result[1].km, result[1].kind) == (expected, STRAIGHT)


def test_server_error_falls_back_for_every_store() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500)

    result = store_distances(
        STORES,
        latitude=16.05,
        longitude=108.05,
        base_url="https://router.test",
        client=_client(handler),
    )

    assert [entry.kind for entry in result] == [STRAIGHT, STRAIGHT]
    assert [entry.km for entry in result] == [
        distance_km(16.05, 108.05, 16.0, 108.0),
        distance_km(16.05, 108.05, 16.1, 108.1),
    ]


def test_timeout_falls_back_instead_of_failing_the_request() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("too slow", request=request)

    result = store_distances(
        STORES,
        latitude=16.05,
        longitude=108.05,
        base_url="https://router.test",
        client=_client(handler),
    )

    assert [entry.kind for entry in result] == [STRAIGHT, STRAIGHT]


def test_error_payload_falls_back() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"code": "NoRoute", "message": "no route"})

    result = store_distances(
        STORES,
        latitude=16.05,
        longitude=108.05,
        base_url="https://router.test",
        client=_client(handler),
    )

    assert [entry.kind for entry in result] == [STRAIGHT, STRAIGHT]


def test_mismatched_destination_count_falls_back() -> None:
    """A payload that does not cover every store is treated as no answer."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"code": "Ok", "distances": [[2756.9]]})

    result = store_distances(
        STORES,
        latitude=16.05,
        longitude=108.05,
        base_url="https://router.test",
        client=_client(handler),
    )

    assert [entry.kind for entry in result] == [STRAIGHT, STRAIGHT]


def test_empty_base_url_never_calls_out() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("routing must not be contacted when the URL is empty")

    result = store_distances(
        STORES,
        latitude=16.05,
        longitude=108.05,
        base_url="",
        client=_client(handler),
    )

    assert [entry.kind for entry in result] == [STRAIGHT, STRAIGHT]
    assert result[0].km == distance_km(16.05, 108.05, 16.0, 108.0)


def test_no_stores_needs_no_request() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("no stores means no routing call")

    assert (
        store_distances(
            [], latitude=16.05, longitude=108.05, base_url="https://router.test", client=_client(handler)
        )
        == []
    )


def test_distances_keep_store_order() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"code": "Ok", "distances": [[999.0, 111.0]]})

    result = store_distances(
        STORES,
        latitude=16.05,
        longitude=108.05,
        base_url="https://router.test",
        client=_client(handler),
    )

    assert [entry.store_id for entry in result] == ["S-A", "S-B"]
    assert [entry.km for entry in result] == [1.0, 0.1]
