from unittest.mock import AsyncMock, MagicMock

import pytest

from app.api.websocket import (
    ConnectionManager,
    _authenticate_ws,
    notify_admin_sos,
    notify_driver_eta,
    manager as global_manager,
)


@pytest.fixture
def manager():
    return ConnectionManager()


@pytest.fixture
def mock_ws():
    ws = AsyncMock()
    ws.accept = AsyncMock()
    ws.send_json = AsyncMock()
    return ws


@pytest.mark.asyncio
async def test_connect_rider(manager, mock_ws):
    await manager.connect_rider(1, mock_ws)

    mock_ws.accept.assert_called_once()
    assert manager.online_rider_count == 1


@pytest.mark.asyncio
async def test_connect_driver(manager, mock_ws):
    await manager.connect_driver(1, mock_ws)

    mock_ws.accept.assert_called_once()
    assert manager.online_driver_count == 1


@pytest.mark.asyncio
async def test_disconnect_rider(manager, mock_ws):
    await manager.connect_rider(1, mock_ws)
    manager.disconnect_rider(1)

    assert manager.online_rider_count == 0


@pytest.mark.asyncio
async def test_disconnect_driver(manager, mock_ws):
    await manager.connect_driver(1, mock_ws)
    manager.disconnect_driver(1)

    assert manager.online_driver_count == 0


@pytest.mark.asyncio
async def test_send_to_rider(manager, mock_ws):
    await manager.connect_rider(1, mock_ws)

    result = await manager.send_to_rider(1, {"type": "test"})

    assert result is True
    mock_ws.send_json.assert_called_once_with({"type": "test"})


@pytest.mark.asyncio
async def test_send_to_rider_not_connected(manager):
    result = await manager.send_to_rider(999, {"type": "test"})

    assert result is False


@pytest.mark.asyncio
async def test_send_to_driver(manager, mock_ws):
    await manager.connect_driver(1, mock_ws)

    result = await manager.send_to_driver(1, {"type": "ride_offer"})

    assert result is True
    mock_ws.send_json.assert_called_once_with({"type": "ride_offer"})


@pytest.mark.asyncio
async def test_broadcast_to_drivers(manager):
    ws1 = AsyncMock()
    ws1.accept = AsyncMock()
    ws1.send_json = AsyncMock()
    ws2 = AsyncMock()
    ws2.accept = AsyncMock()
    ws2.send_json = AsyncMock()

    await manager.connect_driver(1, ws1)
    await manager.connect_driver(2, ws2)

    sent = await manager.broadcast_to_drivers([1, 2, 3], {"type": "alert"})

    assert sent == 2
    ws1.send_json.assert_called_once()
    ws2.send_json.assert_called_once()


@pytest.mark.asyncio
async def test_connect_admin(manager, mock_ws):
    await manager.connect_admin(1, mock_ws)

    mock_ws.accept.assert_called_once()
    assert manager.online_admin_count == 1


@pytest.mark.asyncio
async def test_disconnect_admin(manager, mock_ws):
    await manager.connect_admin(1, mock_ws)
    manager.disconnect_admin(1)

    assert manager.online_admin_count == 0


@pytest.mark.asyncio
async def test_send_to_admin(manager, mock_ws):
    await manager.connect_admin(1, mock_ws)

    result = await manager.send_to_admin(1, {"type": "sos_alert"})

    assert result is True
    mock_ws.send_json.assert_called_once_with({"type": "sos_alert"})


@pytest.mark.asyncio
async def test_send_to_admin_not_connected(manager):
    result = await manager.send_to_admin(999, {"type": "sos_alert"})

    assert result is False


@pytest.mark.asyncio
async def test_broadcast_to_admins(manager):
    ws1 = AsyncMock()
    ws1.accept = AsyncMock()
    ws1.send_json = AsyncMock()
    ws2 = AsyncMock()
    ws2.accept = AsyncMock()
    ws2.send_json = AsyncMock()

    await manager.connect_admin(1, ws1)
    await manager.connect_admin(2, ws2)

    sent = await manager.broadcast_to_admins({"type": "sos_alert", "alert_id": 7})

    assert sent == 2
    ws1.send_json.assert_called_once()
    ws2.send_json.assert_called_once()


@pytest.mark.asyncio
async def test_broadcast_to_admins_none_connected(manager):
    sent = await manager.broadcast_to_admins({"type": "sos_alert"})

    assert sent == 0


@pytest.mark.asyncio
async def test_notify_admin_sos_broadcasts():
    """notify_admin_sos should broadcast SOS payload to all connected admins."""
    ws1 = AsyncMock()
    ws1.accept = AsyncMock()
    ws1.send_json = AsyncMock()

    await global_manager.connect_admin(100, ws1)
    try:
        sent = await notify_admin_sos(
            alert_id=42, user_id=7, ride_id=99,
            latitude=40.71, longitude=-74.00, message="Help!",
        )
        assert sent == 1
        call_args = ws1.send_json.call_args[0][0]
        assert call_args["type"] == "sos_alert"
        assert call_args["alert_id"] == 42
        assert call_args["user_id"] == 7
        assert call_args["ride_id"] == 99
        assert call_args["message"] == "Help!"
    finally:
        global_manager.disconnect_admin(100)


def test_authenticate_ws_valid():
    from app.services.auth import create_access_token
    token = create_access_token(user_id=42, role="driver")

    payload = _authenticate_ws(token)

    assert payload is not None
    assert payload["sub"] == "42"
    assert payload["role"] == "driver"


def test_authenticate_ws_invalid():
    payload = _authenticate_ws("invalid.token")

    assert payload is None


def test_authenticate_ws_refresh_token_rejected():
    from app.services.auth import create_refresh_token
    token = create_refresh_token(user_id=42)

    payload = _authenticate_ws(token)

    assert payload is None


@pytest.mark.asyncio
async def test_notify_driver_eta_sends_to_rider():
    """notify_driver_eta pushes a driver_eta message to the connected rider."""
    ws = AsyncMock()
    ws.accept = AsyncMock()
    ws.send_json = AsyncMock()

    await global_manager.connect_rider(200, ws)
    try:
        result = await notify_driver_eta(
            rider_user_id=200,
            ride_id=55,
            eta_minutes=4.5,
            distance_km=1.8,
            driver_lat=29.76,
            driver_lng=-95.37,
        )
        assert result is True
        call_args = ws.send_json.call_args[0][0]
        assert call_args["type"] == "driver_eta"
        assert call_args["ride_id"] == 55
        assert call_args["eta_minutes"] == 4.5
        assert call_args["distance_km"] == 1.8
        assert call_args["driver_lat"] == 29.76
        assert call_args["driver_lng"] == -95.37
    finally:
        global_manager.disconnect_rider(200)


@pytest.mark.asyncio
async def test_notify_driver_eta_rider_not_connected():
    """notify_driver_eta returns False when the rider has no active connection."""
    result = await notify_driver_eta(
        rider_user_id=9999,
        ride_id=1,
        eta_minutes=3.0,
        distance_km=1.0,
        driver_lat=0.0,
        driver_lng=0.0,
    )
    assert result is False
