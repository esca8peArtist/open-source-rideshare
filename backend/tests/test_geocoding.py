from unittest.mock import AsyncMock, patch

import pytest

from app.services.geocoding import (
    GeocodingError,
    _format_short_address,
    geocode,
    reverse_geocode,
)


class FakeResponse:
    def __init__(self, status_code, data):
        self.status_code = status_code
        self._data = data

    def json(self):
        return self._data


@pytest.fixture
def nominatim_search_result():
    return [
        {
            "lat": "40.7128",
            "lon": "-74.0060",
            "display_name": "New York, NY, USA",
            "address": {
                "city": "New York",
                "state": "New York",
                "country": "United States",
            },
        }
    ]


@pytest.fixture
def nominatim_reverse_result():
    return {
        "display_name": "123 Main St, Springfield, Illinois, USA",
        "address": {
            "house_number": "123",
            "road": "Main St",
            "city": "Springfield",
            "state": "Illinois",
            "country": "United States",
        },
    }


@pytest.mark.asyncio
async def test_geocode_success(nominatim_search_result):
    fake_client = AsyncMock()
    fake_client.__aenter__ = AsyncMock(return_value=fake_client)
    fake_client.__aexit__ = AsyncMock(return_value=False)
    fake_client.get = AsyncMock(
        return_value=FakeResponse(200, nominatim_search_result)
    )

    with patch("app.services.geocoding.httpx.AsyncClient", return_value=fake_client):
        result = await geocode("New York, NY")

    assert result["lat"] == 40.7128
    assert result["lng"] == -74.0060
    assert result["display_name"] == "New York, NY, USA"


@pytest.mark.asyncio
async def test_geocode_no_results():
    fake_client = AsyncMock()
    fake_client.__aenter__ = AsyncMock(return_value=fake_client)
    fake_client.__aexit__ = AsyncMock(return_value=False)
    fake_client.get = AsyncMock(return_value=FakeResponse(200, []))

    with patch("app.services.geocoding.httpx.AsyncClient", return_value=fake_client):
        with pytest.raises(GeocodingError, match="No results found"):
            await geocode("xyznonexistent12345")


@pytest.mark.asyncio
async def test_geocode_api_error():
    fake_client = AsyncMock()
    fake_client.__aenter__ = AsyncMock(return_value=fake_client)
    fake_client.__aexit__ = AsyncMock(return_value=False)
    fake_client.get = AsyncMock(return_value=FakeResponse(500, {}))

    with patch("app.services.geocoding.httpx.AsyncClient", return_value=fake_client):
        with pytest.raises(GeocodingError, match="status 500"):
            await geocode("New York")


@pytest.mark.asyncio
async def test_reverse_geocode_success(nominatim_reverse_result):
    fake_client = AsyncMock()
    fake_client.__aenter__ = AsyncMock(return_value=fake_client)
    fake_client.__aexit__ = AsyncMock(return_value=False)
    fake_client.get = AsyncMock(
        return_value=FakeResponse(200, nominatim_reverse_result)
    )

    with patch("app.services.geocoding.httpx.AsyncClient", return_value=fake_client):
        result = await reverse_geocode(39.7817, -89.6501)

    assert result["display_name"] == "123 Main St, Springfield, Illinois, USA"
    assert result["short_address"] == "123 Main St, Springfield, Illinois"


@pytest.mark.asyncio
async def test_reverse_geocode_error_response():
    fake_client = AsyncMock()
    fake_client.__aenter__ = AsyncMock(return_value=fake_client)
    fake_client.__aexit__ = AsyncMock(return_value=False)
    fake_client.get = AsyncMock(
        return_value=FakeResponse(200, {"error": "Unable to geocode"})
    )

    with patch("app.services.geocoding.httpx.AsyncClient", return_value=fake_client):
        with pytest.raises(GeocodingError, match="Unable to geocode"):
            await reverse_geocode(0.0, 0.0)


@pytest.mark.asyncio
async def test_reverse_geocode_api_error():
    fake_client = AsyncMock()
    fake_client.__aenter__ = AsyncMock(return_value=fake_client)
    fake_client.__aexit__ = AsyncMock(return_value=False)
    fake_client.get = AsyncMock(return_value=FakeResponse(503, {}))

    with patch("app.services.geocoding.httpx.AsyncClient", return_value=fake_client):
        with pytest.raises(GeocodingError, match="status 503"):
            await reverse_geocode(40.0, -74.0)


def test_format_short_address_full():
    parts = {
        "house_number": "42",
        "road": "Elm Street",
        "city": "Portland",
        "state": "Oregon",
    }
    assert _format_short_address(parts) == "42 Elm Street, Portland, Oregon"


def test_format_short_address_no_house_number():
    parts = {"road": "Broadway", "city": "New York", "state": "New York"}
    assert _format_short_address(parts) == "Broadway, New York, New York"


def test_format_short_address_town_instead_of_city():
    parts = {"road": "Main St", "town": "Smallville", "state": "Kansas"}
    assert _format_short_address(parts) == "Main St, Smallville, Kansas"


def test_format_short_address_village():
    parts = {"village": "Hobbiton", "state": "The Shire"}
    assert _format_short_address(parts) == "Hobbiton, The Shire"


def test_format_short_address_empty():
    parts = {"display_name": "Somewhere"}
    assert _format_short_address(parts) == "Somewhere"


def test_format_short_address_completely_empty():
    assert _format_short_address({}) == "Unknown"
