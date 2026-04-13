import httpx

from app.config import settings


class RoutingError(Exception):
    pass


async def get_route(
    origin_lat: float, origin_lng: float, dest_lat: float, dest_lng: float
) -> dict:
    url = (
        f"{settings.osrm_url}/route/v1/driving/"
        f"{origin_lng},{origin_lat};{dest_lng},{dest_lat}"
        f"?overview=full&geometries=geojson"
    )
    async with httpx.AsyncClient() as client:
        response = await client.get(url, timeout=10.0)
        if response.status_code != 200:
            raise RoutingError(f"OSRM returned status {response.status_code}")
        data = response.json()

    if data.get("code") != "Ok" or not data.get("routes"):
        raise RoutingError("No route found")

    route = data["routes"][0]
    return {
        "distance_km": route["distance"] / 1000,
        "duration_min": route["duration"] / 60,
        "geometry": route["geometry"],
    }


async def get_multi_stop_route(
    origin_lat: float,
    origin_lng: float,
    dest_lat: float,
    dest_lng: float,
    waypoints: list[tuple[float, float]],
) -> dict:
    """Calculate a route through multiple waypoints using OSRM.

    Args:
        origin_lat, origin_lng: Pickup location.
        dest_lat, dest_lng: Final dropoff location.
        waypoints: List of (lat, lng) tuples for intermediate stops, in order.

    Returns:
        dict with total distance_km, duration_min, geometry, and per-leg breakdowns.
    """
    # Build coordinate string: origin;wp1;wp2;...;destination
    coords = [f"{origin_lng},{origin_lat}"]
    for lat, lng in waypoints:
        coords.append(f"{lng},{lat}")
    coords.append(f"{dest_lng},{dest_lat}")
    coord_str = ";".join(coords)

    url = (
        f"{settings.osrm_url}/route/v1/driving/{coord_str}"
        f"?overview=full&geometries=geojson&steps=false"
    )
    async with httpx.AsyncClient() as client:
        response = await client.get(url, timeout=15.0)
        if response.status_code != 200:
            raise RoutingError(f"OSRM returned status {response.status_code}")
        data = response.json()

    if data.get("code") != "Ok" or not data.get("routes"):
        raise RoutingError("No route found for multi-stop trip")

    route = data["routes"][0]
    legs = []
    for leg in route.get("legs", []):
        legs.append({
            "distance_km": leg["distance"] / 1000,
            "duration_min": leg["duration"] / 60,
        })

    return {
        "distance_km": route["distance"] / 1000,
        "duration_min": route["duration"] / 60,
        "geometry": route["geometry"],
        "legs": legs,
    }
