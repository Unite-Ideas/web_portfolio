"""Photos from the business's Google listing, via the Google Places API (New)."""

from __future__ import annotations

from dataclasses import dataclass, field

import httpx

from .dropbox_local import split_city, tokens

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


def in_city(address: str, city: str) -> bool:
    """True when a Google address is in the requested city (and state, if given)."""
    city_words, state = split_city(city)
    address_words = set(tokens(address))
    return all(w in address_words for w in city_words) and (state is None or state in address_words)


def find_place(api_key: str, business: str, city: str) -> Place | None:
    """The business's listing in this city. Google returns the closest match it has, which
    can be another location of the same brand (e.g. Little Rock for Hot Springs), so results
    outside the city are ignored."""
    resp = httpx.post(
        SEARCH_URL,
        headers={"X-Goog-Api-Key": api_key, "X-Goog-FieldMask": FIELDS},
        json={"textQuery": f"{business} {city}", "pageSize": 5},
        timeout=30,
    )
    resp.raise_for_status()
    places = [p for p in resp.json().get("places", []) if in_city(p.get("formattedAddress", ""), city)]
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
