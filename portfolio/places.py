"""Photos from the business's Google listing, via the Google Places API (New)."""

from __future__ import annotations

from dataclasses import dataclass, field

import httpx

SEARCH_URL = "https://places.googleapis.com/v1/places:searchText"
FIELDS = ",".join(
    [
        "places.id",
        "places.displayName",
        "places.formattedAddress",
        "places.websiteUri",
        "places.googleMapsUri",
        "places.photos",
    ]
)


@dataclass
class PlacePhoto:
    url: str  # media URL (includes the API key; never store or show it)
    name: str
    credit: str
    maps_uri: str


@dataclass
class Place:
    id: str
    name: str
    address: str
    website: str
    maps_uri: str
    photos: list[PlacePhoto] = field(default_factory=list)


def find_place(api_key: str, business: str, city: str) -> Place | None:
    resp = httpx.post(
        SEARCH_URL,
        headers={"X-Goog-Api-Key": api_key, "X-Goog-FieldMask": FIELDS},
        json={"textQuery": f"{business} {city}", "pageSize": 1},
        timeout=30,
    )
    resp.raise_for_status()
    places = resp.json().get("places", [])
    if not places:
        return None
    p = places[0]
    place = Place(
        id=p["id"],
        name=p.get("displayName", {}).get("text", ""),
        address=p.get("formattedAddress", ""),
        website=p.get("websiteUri", ""),
        maps_uri=p.get("googleMapsUri", ""),
    )
    for photo in p.get("photos", []):
        authors = [a.get("displayName", "") for a in photo.get("authorAttributions", [])]
        place.photos.append(
            PlacePhoto(
                url=f"https://places.googleapis.com/v1/{photo['name']}/media?maxWidthPx=4800&key={api_key}",
                name=photo["name"],
                credit=", ".join(a for a in authors if a),
                maps_uri=place.maps_uri,
            )
        )
    return place
