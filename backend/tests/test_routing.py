"""Unit tests for the routing service (OSRM integration)."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.routing import RoutingError, get_route


class TestGetRoute:
    """Tests for get_route function with mocked httpx."""

    @pytest.mark.asyncio
    @patch("app.services.routing.httpx.AsyncClient")
    async def test_successful_route(self, mock_client_cls):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "code": "Ok",
            "routes": [
                {
                    "distance": 15000,  # 15 km in meters
                    "duration": 1200,   # 20 min in seconds
                    "geometry": {"type": "LineString", "coordinates": [[0, 0], [1, 1]]},
                }
            ],
        }

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        result = await get_route(40.0, -74.0, 40.1, -74.1)

        assert result["distance_km"] == 15.0
        assert result["duration_min"] == 20.0
        assert result["geometry"]["type"] == "LineString"

    @pytest.mark.asyncio
    @patch("app.services.routing.httpx.AsyncClient")
    async def test_osrm_non_200_raises_routing_error(self, mock_client_cls):
        mock_response = MagicMock()
        mock_response.status_code = 500

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        with pytest.raises(RoutingError, match="status 500"):
            await get_route(40.0, -74.0, 40.1, -74.1)

    @pytest.mark.asyncio
    @patch("app.services.routing.httpx.AsyncClient")
    async def test_osrm_no_route_found(self, mock_client_cls):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"code": "NoRoute", "routes": []}

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        with pytest.raises(RoutingError, match="No route found"):
            await get_route(40.0, -74.0, 40.1, -74.1)

    @pytest.mark.asyncio
    @patch("app.services.routing.httpx.AsyncClient")
    async def test_osrm_empty_routes_list(self, mock_client_cls):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"code": "Ok", "routes": []}

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        with pytest.raises(RoutingError, match="No route found"):
            await get_route(40.0, -74.0, 40.1, -74.1)

    @pytest.mark.asyncio
    @patch("app.services.routing.httpx.AsyncClient")
    async def test_short_route_values(self, mock_client_cls):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "code": "Ok",
            "routes": [
                {
                    "distance": 500,    # 0.5 km
                    "duration": 120,    # 2 min
                    "geometry": {"type": "LineString", "coordinates": [[0, 0]]},
                }
            ],
        }

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        result = await get_route(40.0, -74.0, 40.001, -74.001)

        assert result["distance_km"] == 0.5
        assert result["duration_min"] == 2.0

    @pytest.mark.asyncio
    @patch("app.services.routing.httpx.AsyncClient")
    async def test_osrm_404_raises_routing_error(self, mock_client_cls):
        mock_response = MagicMock()
        mock_response.status_code = 404

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        with pytest.raises(RoutingError, match="status 404"):
            await get_route(40.0, -74.0, 40.1, -74.1)
