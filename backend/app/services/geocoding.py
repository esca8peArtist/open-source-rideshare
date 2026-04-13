import httpx

from app.config import settings


class GeocodingError(Exception):
    pass


async def geocode(address: str) -> dict:
    """Convert an address string to coordinates using Nominatim."""
    params = {
        "q": address,
        "format": "jsonv2",
        "limit": 1,
        "addressdetails": 1,
    }
    headers = {"User-Agent": f"{settings.app_name}/1.0"}

    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"{settings.nominatim_url}/search",
            params=params,
            headers=headers,
            timeout=10.0,
        )
        if response.status_code != 200:
            raise GeocodingError(f"Nominatim returned status {response.status_code}")
        results = response.json()

    if not results:
        raise GeocodingError(f"No results found for: {address}")

    result = results[0]
    return {
        "lat": float(result["lat"]),
        "lng": float(result["lon"]),
        "display_name": result.get("display_name", address),
    }


async def reverse_geocode(lat: float, lng: float) -> dict:
    """Convert coordinates to a human-readable address using Nominatim."""
    params = {
        "lat": lat,
        "lon": lng,
        "format": "jsonv2",
        "addressdetails": 1,
    }
    headers = {"User-Agent": f"{settings.app_name}/1.0"}

    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"{settings.nominatim_url}/reverse",
            params=params,
            headers=headers,
            timeout=10.0,
        )
        if response.status_code != 200:
            raise GeocodingError(f"Nominatim returned status {response.status_code}")
        data = response.json()

    if "error" in data:
        raise GeocodingError(f"Reverse geocode failed: {data['error']}")

    address_parts = data.get("address", {})
    short_address = _format_short_address(address_parts)

    return {
        "display_name": data.get("display_name", ""),
        "short_address": short_address,
        "address": address_parts,
    }


def _format_short_address(parts: dict) -> str:
    """Build a concise address from Nominatim address components."""
    components = []
    street_number = parts.get("house_number", "")
    street = parts.get("road", "")
    if street:
        components.append(f"{street_number} {street}".strip())
    city = parts.get("city") or parts.get("town") or parts.get("village", "")
    if city:
        components.append(city)
    state = parts.get("state", "")
    if state:
        components.append(state)
    return ", ".join(components) if components else parts.get("display_name", "Unknown")
