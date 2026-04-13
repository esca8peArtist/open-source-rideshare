"""Tests for WebSocket heartbeat, connection health tracking, and graceful failure handling."""

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.api.websocket import ConnectionManager


@pytest.fixture
def mgr():
    """ConnectionManager with fast heartbeat for testing."""
    return ConnectionManager(heartbeat_interval=0.1, heartbeat_timeout=0.1)


@pytest.fixture
def mock_ws():
    ws = AsyncMock()
    ws.accept = AsyncMock()
    ws.send_json = AsyncMock()
    ws.close = AsyncMock()
    return ws


# ------------------------------------------------------------------
# Activity tracking
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_connect_records_activity(mgr, mock_ws):
    """Connecting should record initial activity timestamp."""
    await mgr.connect_rider(1, mock_ws)

    assert mgr.last_activity(1) is not None
    assert mgr.connection_age(1) is not None
    assert mgr.connection_age(1) < 1.0  # just connected


@pytest.mark.asyncio
async def test_record_activity_updates_timestamp(mgr, mock_ws):
    """record_activity should update the last-seen timestamp."""
    await mgr.connect_rider(1, mock_ws)
    first = mgr.last_activity(1)

    # Simulate a small delay then new activity
    mgr.record_activity(1)
    second = mgr.last_activity(1)

    assert second >= first


@pytest.mark.asyncio
async def test_record_activity_clears_awaiting_pong(mgr, mock_ws):
    """Any incoming message should clear the awaiting-pong flag."""
    await mgr.connect_rider(1, mock_ws)
    mgr._awaiting_pong[1] = True

    mgr.record_activity(1)

    assert 1 not in mgr._awaiting_pong


def test_last_activity_unknown_user(mgr):
    """last_activity should return None for unknown users."""
    assert mgr.last_activity(999) is None


def test_connection_age_unknown_user(mgr):
    """connection_age should return None for unknown users."""
    assert mgr.connection_age(999) is None


# ------------------------------------------------------------------
# Disconnect cleanup
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_disconnect_rider_cleans_tracking(mgr, mock_ws):
    """Disconnecting should remove activity and pong tracking."""
    await mgr.connect_rider(1, mock_ws)
    mgr._awaiting_pong[1] = True

    mgr.disconnect_rider(1)

    assert mgr.last_activity(1) is None
    assert 1 not in mgr._awaiting_pong
    assert mgr.online_rider_count == 0


@pytest.mark.asyncio
async def test_disconnect_driver_cleans_tracking(mgr, mock_ws):
    await mgr.connect_driver(1, mock_ws)
    mgr.disconnect_driver(1)

    assert mgr.last_activity(1) is None
    assert mgr.online_driver_count == 0


@pytest.mark.asyncio
async def test_disconnect_admin_cleans_tracking(mgr, mock_ws):
    await mgr.connect_admin(1, mock_ws)
    mgr.disconnect_admin(1)

    assert mgr.last_activity(1) is None
    assert mgr.online_admin_count == 0


# ------------------------------------------------------------------
# Graceful send failure (dead connection pruning)
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_safe_send_success(mgr, mock_ws):
    """Successful send returns True."""
    await mgr.connect_rider(1, mock_ws)

    result = await mgr.send_to_rider(1, {"type": "test"})

    assert result is True
    mock_ws.send_json.assert_called_once_with({"type": "test"})


@pytest.mark.asyncio
async def test_safe_send_failure_prunes_connection(mgr):
    """If send_json raises, the connection should be removed."""
    ws = AsyncMock()
    ws.accept = AsyncMock()
    ws.send_json = AsyncMock(side_effect=RuntimeError("connection reset"))

    await mgr.connect_rider(1, ws)
    assert mgr.online_rider_count == 1

    result = await mgr.send_to_rider(1, {"type": "test"})

    assert result is False
    assert mgr.online_rider_count == 0
    assert mgr.last_activity(1) is None


@pytest.mark.asyncio
async def test_safe_send_failure_prunes_driver(mgr):
    ws = AsyncMock()
    ws.accept = AsyncMock()
    ws.send_json = AsyncMock(side_effect=ConnectionError("broken pipe"))

    await mgr.connect_driver(1, ws)
    result = await mgr.send_to_driver(1, {"type": "test"})

    assert result is False
    assert mgr.online_driver_count == 0


@pytest.mark.asyncio
async def test_safe_send_failure_prunes_admin(mgr):
    ws = AsyncMock()
    ws.accept = AsyncMock()
    ws.send_json = AsyncMock(side_effect=OSError("transport closed"))

    await mgr.connect_admin(1, ws)
    result = await mgr.send_to_admin(1, {"type": "test"})

    assert result is False
    assert mgr.online_admin_count == 0


@pytest.mark.asyncio
async def test_broadcast_to_admins_prunes_dead(mgr):
    """Broadcast should still deliver to healthy connections when some are dead."""
    good_ws = AsyncMock()
    good_ws.accept = AsyncMock()
    good_ws.send_json = AsyncMock()

    bad_ws = AsyncMock()
    bad_ws.accept = AsyncMock()
    bad_ws.send_json = AsyncMock(side_effect=RuntimeError("dead"))

    await mgr.connect_admin(1, good_ws)
    await mgr.connect_admin(2, bad_ws)

    sent = await mgr.broadcast_to_admins({"type": "alert"})

    # One succeeded, one failed and was pruned
    assert sent == 1
    assert mgr.online_admin_count == 1


# ------------------------------------------------------------------
# Heartbeat ping/pong cycle
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_send_pings_marks_awaiting(mgr, mock_ws):
    """_send_pings should mark all connections as awaiting pong."""
    await mgr.connect_rider(1, mock_ws)

    await mgr._send_pings()

    assert mgr._awaiting_pong.get(1) is True
    mock_ws.send_json.assert_called_with({"type": "ping"})


@pytest.mark.asyncio
async def test_send_pings_across_pools(mgr):
    """Pings should be sent to riders, drivers, and admins."""
    rider_ws = AsyncMock()
    rider_ws.accept = AsyncMock()
    rider_ws.send_json = AsyncMock()

    driver_ws = AsyncMock()
    driver_ws.accept = AsyncMock()
    driver_ws.send_json = AsyncMock()

    admin_ws = AsyncMock()
    admin_ws.accept = AsyncMock()
    admin_ws.send_json = AsyncMock()

    await mgr.connect_rider(1, rider_ws)
    await mgr.connect_driver(2, driver_ws)
    await mgr.connect_admin(3, admin_ws)

    await mgr._send_pings()

    rider_ws.send_json.assert_called_with({"type": "ping"})
    driver_ws.send_json.assert_called_with({"type": "ping"})
    admin_ws.send_json.assert_called_with({"type": "ping"})
    assert mgr._awaiting_pong[1] is True
    assert mgr._awaiting_pong[2] is True
    assert mgr._awaiting_pong[3] is True


@pytest.mark.asyncio
async def test_send_pings_handles_failed_send(mgr):
    """If ping send fails, the user should still be marked for pruning."""
    ws = AsyncMock()
    ws.accept = AsyncMock()
    ws.send_json = AsyncMock(side_effect=RuntimeError("broken"))

    await mgr.connect_rider(1, ws)
    await mgr._send_pings()

    # Should be marked for pruning
    assert mgr._awaiting_pong.get(1) is True


@pytest.mark.asyncio
async def test_prune_dead_connections_removes_unresponsive(mgr, mock_ws):
    """Connections still awaiting pong should be pruned."""
    await mgr.connect_rider(1, mock_ws)
    mgr._awaiting_pong[1] = True

    await mgr._prune_dead_connections()

    assert mgr.online_rider_count == 0
    assert 1 not in mgr._awaiting_pong
    mock_ws.close.assert_called_once_with(code=4008, reason="Heartbeat timeout")


@pytest.mark.asyncio
async def test_prune_keeps_responsive_connections(mgr):
    """Connections that responded (pong cleared flag) should NOT be pruned."""
    ws = AsyncMock()
    ws.accept = AsyncMock()
    ws.send_json = AsyncMock()
    ws.close = AsyncMock()

    await mgr.connect_rider(1, ws)
    # Simulate: ping was sent, client responded (record_activity cleared the flag)
    mgr._awaiting_pong[1] = False

    await mgr._prune_dead_connections()

    assert mgr.online_rider_count == 1  # still connected


@pytest.mark.asyncio
async def test_prune_handles_already_closed(mgr):
    """Pruning a connection whose close() raises should not crash."""
    ws = AsyncMock()
    ws.accept = AsyncMock()
    ws.send_json = AsyncMock()
    ws.close = AsyncMock(side_effect=RuntimeError("already closed"))

    await mgr.connect_driver(1, ws)
    mgr._awaiting_pong[1] = True

    # Should not raise
    await mgr._prune_dead_connections()

    assert mgr.online_driver_count == 0


@pytest.mark.asyncio
async def test_force_disconnect_removes_from_all_pools(mgr):
    """_force_disconnect should clean up user from any pool."""
    ws = AsyncMock()
    ws.accept = AsyncMock()
    ws.close = AsyncMock()

    await mgr.connect_admin(5, ws)
    mgr._awaiting_pong[5] = True

    await mgr._force_disconnect(5)

    assert mgr.online_admin_count == 0
    assert mgr.last_activity(5) is None
    assert 5 not in mgr._awaiting_pong


# ------------------------------------------------------------------
# Heartbeat lifecycle (start/stop)
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_start_heartbeat_creates_task(mgr):
    """start_heartbeat should create a background task."""
    mgr.start_heartbeat()

    assert mgr._heartbeat_task is not None
    assert not mgr._heartbeat_task.done()

    mgr.stop_heartbeat()


@pytest.mark.asyncio
async def test_stop_heartbeat_cancels_task(mgr):
    mgr.start_heartbeat()
    task = mgr._heartbeat_task

    mgr.stop_heartbeat()
    # Yield to event loop so the cancellation propagates
    await asyncio.sleep(0)

    assert task.cancelled() or task.done()
    assert mgr._heartbeat_task is None


@pytest.mark.asyncio
async def test_start_heartbeat_is_idempotent(mgr):
    """Calling start_heartbeat twice should not create a second task."""
    mgr.start_heartbeat()
    first_task = mgr._heartbeat_task

    mgr.start_heartbeat()

    assert mgr._heartbeat_task is first_task

    mgr.stop_heartbeat()


# ------------------------------------------------------------------
# Connection health diagnostics
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_connection_health_empty(mgr):
    health = mgr.connection_health()

    assert health["riders"] == 0
    assert health["drivers"] == 0
    assert health["admins"] == 0
    assert health["total"] == 0
    assert health["awaiting_pong"] == 0
    assert health["connections"] == []


@pytest.mark.asyncio
async def test_connection_health_with_connections(mgr):
    ws1 = AsyncMock()
    ws1.accept = AsyncMock()
    ws2 = AsyncMock()
    ws2.accept = AsyncMock()

    await mgr.connect_rider(1, ws1)
    await mgr.connect_driver(2, ws2)

    health = mgr.connection_health()

    assert health["riders"] == 1
    assert health["drivers"] == 1
    assert health["total"] == 2
    assert len(health["connections"]) == 2
    assert health["heartbeat_interval"] == 0.1
    assert health["heartbeat_timeout"] == 0.1


@pytest.mark.asyncio
async def test_connection_health_counts_awaiting_pong(mgr, mock_ws):
    await mgr.connect_rider(1, mock_ws)
    mgr._awaiting_pong[1] = True

    health = mgr.connection_health()

    assert health["awaiting_pong"] == 1


# ------------------------------------------------------------------
# Full heartbeat cycle (integration-style, fast timers)
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_heartbeat_cycle_prunes_unresponsive():
    """Full cycle: start heartbeat → ping → no pong → prune."""
    mgr = ConnectionManager(heartbeat_interval=0.05, heartbeat_timeout=0.05)

    ws = AsyncMock()
    ws.accept = AsyncMock()
    ws.send_json = AsyncMock()  # accepts ping but client never sends pong
    ws.close = AsyncMock()

    await mgr.connect_rider(1, ws)
    assert mgr.online_rider_count == 1

    mgr.start_heartbeat()
    # Wait for one full cycle: interval(0.05) + timeout(0.05) + buffer
    await asyncio.sleep(0.2)
    mgr.stop_heartbeat()

    assert mgr.online_rider_count == 0


@pytest.mark.asyncio
async def test_heartbeat_cycle_keeps_responsive():
    """Full cycle: client responds to ping → connection survives."""
    mgr = ConnectionManager(heartbeat_interval=0.05, heartbeat_timeout=0.05)

    ws = AsyncMock()
    ws.accept = AsyncMock()
    ws.close = AsyncMock()

    # Simulate: when server sends ping, client "responds" by calling record_activity
    async def fake_send_json(msg):
        if msg.get("type") == "ping":
            # Simulate client pong arriving
            mgr.record_activity(1)

    ws.send_json = AsyncMock(side_effect=fake_send_json)

    await mgr.connect_rider(1, ws)
    mgr.start_heartbeat()
    await asyncio.sleep(0.2)
    mgr.stop_heartbeat()

    # Connection should still be alive because pong was "received"
    assert mgr.online_rider_count == 1


# ------------------------------------------------------------------
# _all_connections snapshot
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_all_connections_returns_all_pools(mgr):
    ws1 = AsyncMock()
    ws1.accept = AsyncMock()
    ws2 = AsyncMock()
    ws2.accept = AsyncMock()
    ws3 = AsyncMock()
    ws3.accept = AsyncMock()

    await mgr.connect_rider(1, ws1)
    await mgr.connect_driver(2, ws2)
    await mgr.connect_admin(3, ws3)

    conns = mgr._all_connections()
    user_ids = {uid for uid, _ in conns}

    assert user_ids == {1, 2, 3}
