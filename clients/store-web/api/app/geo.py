"""Distance between two points on the earth, and the sample address list.

Haversine in Python keeps the "nearest store" rule in one readable place; the
candidate set is three stores, so there is nothing to gain from SQL geography.
"""

import math

EARTH_RADIUS_KM = 6371.0088


def distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in kilometres, rounded to 100 m."""
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lon2 - lon1)
    a = (
        math.sin(d_phi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    )
    return round(2 * EARTH_RADIUS_KM * math.asin(math.sqrt(a)), 1)


# Picking one of these is the offline alternative to the browser geolocation prompt.
# Coordinates match the seeded stores' region (Da Nang).
SAMPLE_ADDRESSES = (
    {
        "address_id": "ADR-HAI-CHAU",
        "label": "Hải Châu, Đà Nẵng",
        "address_text": "Đường Bạch Đằng, Hải Châu, Đà Nẵng",
        "latitude": 16.0678,
        "longitude": 108.2208,
    },
    {
        "address_id": "ADR-THANH-KHE",
        "label": "Thanh Khê, Đà Nẵng",
        "address_text": "Đường Nguyễn Văn Linh, Thanh Khê, Đà Nẵng",
        "latitude": 16.0610,
        "longitude": 108.1800,
    },
    {
        "address_id": "ADR-SON-TRA",
        "label": "Sơn Trà, Đà Nẵng",
        "address_text": "Đường Ngô Quyền, Sơn Trà, Đà Nẵng",
        "latitude": 16.0750,
        "longitude": 108.2350,
    },
    {
        "address_id": "ADR-LIEN-CHIEU",
        "label": "Liên Chiểu, Đà Nẵng",
        "address_text": "Đường Nguyễn Lương Bằng, Liên Chiểu, Đà Nẵng",
        "latitude": 16.0748,
        "longitude": 108.1490,
    },
)
