import asyncio
import json
import logging
import time
from collections import defaultdict

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from jose import jwt
from starlette.websockets import WebSocketState

from app.config import settings

logger = logging.getLogger(__name__)

router = APIRouter()


class ConnectionManager:
    """Manages WebSocket connections with server-side heartbeat and health tracking.

    The heartbeat loop periodically sends ``{"type": "ping"}`` to every
    connected client.  If a client does not respond with ``{"type": "pong"}``
    within ``heartbeat_timeout`` seconds the connection is considered dead and
    is pruned automatically.

    Callers of ``send_*`` methods are protected against stale connections: if a
    send raises, the connection is silently removed.
    """

    def __init__(
        self,
        heartbeat_interval: float | None = None,
        heartbeat_timeout: float | None = None,
    ):
        self._rider_connections: dict[int, WebSocket] = {}
        self._driver_connections: dict[int, WebSocket] = {}
        self._admin_connections: dict[int, WebSocket] = {}

        # last time we received *any* message (including pong) from each connection
        self._last_activity: dict[int, float] = {}

        # whether a pong is pending (True = we sent a ping, awaiting pong)
        self._awaiting_pong: dict[int, bool] = {}

        self._heartbeat_interval = (
            heartbeat_interval
            if heartbeat_interval is not None
            else settings.ws_heartbeat_interval_seconds
        )
        self._heartbeat_timeout = (
            heartbeat_timeout
            if heartbeat_timeout is not None
            else settings.ws_heartbeat_timeout_seconds
        )

        self._heartbeat_task: asyncio.Task | None = None

    # ------------------------------------------------------------------
    # Heartbeat lifecycle
    # ------------------------------------------------------------------

    def start_heartbeat(self) -> None:
        """Start the background heartbeat loop (idempotent)."""
        if self._heartbeat_task is None or self._heartbeat_task.done():
            self._heartbeat_task = asyncio.ensure_future(self._heartbeat_loop())

    def stop_heartbeat(self) -> None:
        """Cancel the heartbeat background task."""
        if self._heartbeat_task and not self._heartbeat_task.done():
            self._heartbeat_task.cancel()
            self._heartbeat_task = None

    async def _heartbeat_loop(self) -> None:
        """Periodically ping all connections and prune unresponsive ones."""
        while True:
            await asyncio.sleep(self._heartbeat_interval)
            await self._send_pings()
            # Wait for the timeout window, then prune anything still awaiting pong
            await asyncio.sleep(self._heartbeat_timeout)
            await self._prune_dead_connections()

    async def _send_pings(self) -> None:
        """Send a ping message to every connected client."""
        ping_msg = {"type": "ping"}
        all_connections = self._all_connections()
        for user_id, ws in all_connections:
            # Mark awaiting *before* send so that a pong arriving during (or
            # immediately after) the send can properly clear the flag.
            self._awaiting_pong[user_id] = True
            try:
                await ws.send_json(ping_msg)
            except Exception:
                logger.warning("Failed to send ping to user %d — will prune", user_id)

    async def _prune_dead_connections(self) -> None:
        """Close and remove connections that did not respond to the last ping."""
        dead_ids = [
            uid for uid, awaiting in self._awaiting_pong.items() if awaiting
        ]
        for user_id in dead_ids:
            logger.info("Pruning unresponsive connection for user %d", user_id)
            await self._force_disconnect(user_id)

    async def _force_disconnect(self, user_id: int) -> None:
        """Close a connection and clean up all bookkeeping for *user_id*."""
        ws = (
            self._rider_connections.get(user_id)
            or self._driver_connections.get(user_id)
            or self._admin_connections.get(user_id)
        )
        if ws:
            try:
                await ws.close(code=4008, reason="Heartbeat timeout")
            except Exception:
                pass  # already closed

        # Remove from whichever pool it belongs to
        self._rider_connections.pop(user_id, None)
        self._driver_connections.pop(user_id, None)
        self._admin_connections.pop(user_id, None)
        self._last_activity.pop(user_id, None)
        self._awaiting_pong.pop(user_id, None)

    def _all_connections(self) -> list[tuple[int, WebSocket]]:
        """Return a snapshot of all (user_id, ws) pairs across pools."""
        conns: list[tuple[int, WebSocket]] = []
        conns.extend(self._rider_connections.items())
        conns.extend(self._driver_connections.items())
        conns.extend(self._admin_connections.items())
        return conns

    # ------------------------------------------------------------------
    # Activity tracking
    # ------------------------------------------------------------------

    def record_activity(self, user_id: int) -> None:
        """Record that we received a message from *user_id*."""
        self._last_activity[user_id] = time.monotonic()
        self._awaiting_pong.pop(user_id, None)  # pong received (or any message)

    def last_activity(self, user_id: int) -> float | None:
        """Return monotonic timestamp of last activity, or None if unknown."""
        return self._last_activity.get(user_id)

    def connection_age(self, user_id: int) -> float | None:
        """Seconds since last activity for *user_id*, or None if not tracked."""
        ts = self._last_activity.get(user_id)
        if ts is None:
            return None
        return time.monotonic() - ts

    # ------------------------------------------------------------------
    # Connection management (existing API preserved)
    # ------------------------------------------------------------------

    async def connect_rider(self, user_id: int, websocket: WebSocket) -> None:
        await websocket.accept()
        self._rider_connections[user_id] = websocket
        self.record_activity(user_id)
        logger.info("Rider %d connected via WebSocket", user_id)

    async def connect_driver(self, user_id: int, websocket: WebSocket) -> None:
        await websocket.accept()
        self._driver_connections[user_id] = websocket
        self.record_activity(user_id)
        logger.info("Driver %d connected via WebSocket", user_id)

    async def connect_admin(self, user_id: int, websocket: WebSocket) -> None:
        await websocket.accept()
        self._admin_connections[user_id] = websocket
        self.record_activity(user_id)
        logger.info("Admin %d connected via WebSocket", user_id)

    def disconnect_rider(self, user_id: int) -> None:
        self._rider_connections.pop(user_id, None)
        self._last_activity.pop(user_id, None)
        self._awaiting_pong.pop(user_id, None)
        logger.info("Rider %d disconnected", user_id)

    def disconnect_driver(self, user_id: int) -> None:
        self._driver_connections.pop(user_id, None)
        self._last_activity.pop(user_id, None)
        self._awaiting_pong.pop(user_id, None)
        logger.info("Driver %d disconnected", user_id)

    def disconnect_admin(self, user_id: int) -> None:
        self._admin_connections.pop(user_id, None)
        self._last_activity.pop(user_id, None)
        self._awaiting_pong.pop(user_id, None)
        logger.info("Admin %d disconnected", user_id)

    # ------------------------------------------------------------------
    # Sending (with graceful failure handling)
    # ------------------------------------------------------------------

    async def _safe_send(self, user_id: int, ws: WebSocket, message: dict) -> bool:
        """Send JSON to *ws*, returning False and disconnecting on failure."""
        try:
            await ws.send_json(message)
            return True
        except Exception:
            logger.warning("Send to user %d failed — removing stale connection", user_id)
            # Clean up — the connection is dead
            self._rider_connections.pop(user_id, None)
            self._driver_connections.pop(user_id, None)
            self._admin_connections.pop(user_id, None)
            self._last_activity.pop(user_id, None)
            self._awaiting_pong.pop(user_id, None)
            return False

    async def send_to_rider(self, user_id: int, message: dict) -> bool:
        ws = self._rider_connections.get(user_id)
        if ws:
            return await self._safe_send(user_id, ws, message)
        return False

    async def send_to_driver(self, user_id: int, message: dict) -> bool:
        ws = self._driver_connections.get(user_id)
        if ws:
            return await self._safe_send(user_id, ws, message)
        return False

    async def broadcast_to_drivers(self, user_ids: list[int], message: dict) -> int:
        sent = 0
        for uid in user_ids:
            if await self.send_to_driver(uid, message):
                sent += 1
        return sent

    async def send_to_admin(self, user_id: int, message: dict) -> bool:
        ws = self._admin_connections.get(user_id)
        if ws:
            return await self._safe_send(user_id, ws, message)
        return False

    async def broadcast_to_admins(self, message: dict) -> int:
        sent = 0
        for uid in list(self._admin_connections):
            if await self.send_to_admin(uid, message):
                sent += 1
        return sent

    @property
    def online_rider_count(self) -> int:
        return len(self._rider_connections)

    @property
    def online_driver_count(self) -> int:
        return len(self._driver_connections)

    @property
    def online_admin_count(self) -> int:
        return len(self._admin_connections)

    # ------------------------------------------------------------------
    # Health / diagnostics
    # ------------------------------------------------------------------

    def connection_health(self) -> dict:
        """Return a snapshot of connection health for monitoring/admin endpoints."""
        now = time.monotonic()
        return {
            "riders": self.online_rider_count,
            "drivers": self.online_driver_count,
            "admins": self.online_admin_count,
            "total": self.online_rider_count + self.online_driver_count + self.online_admin_count,
            "heartbeat_interval": self._heartbeat_interval,
            "heartbeat_timeout": self._heartbeat_timeout,
            "awaiting_pong": sum(1 for v in self._awaiting_pong.values() if v),
            "connections": [
                {
                    "user_id": uid,
                    "idle_seconds": round(now - ts, 1),
                }
                for uid, ts in self._last_activity.items()
            ],
        }


manager = ConnectionManager()


def _authenticate_ws(token: str) -> dict | None:
    try:
        payload = jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
        if payload.get("type") != "access":
            return None
        return payload
    except Exception:
        return None


@router.websocket("/ws/rider")
async def rider_ws(websocket: WebSocket):
    token = websocket.query_params.get("token")
    if not token:
        await websocket.close(code=4001, reason="Missing token")
        return

    payload = _authenticate_ws(token)
    if not payload:
        await websocket.close(code=4001, reason="Invalid token")
        return

    user_id = int(payload["sub"])
    await manager.connect_rider(user_id, websocket)

    try:
        while True:
            data = await websocket.receive_json()
            msg_type = data.get("type")
            manager.record_activity(user_id)

            if msg_type == "ping":
                await websocket.send_json({"type": "pong"})
            elif msg_type == "pong":
                pass  # activity already recorded above
            elif msg_type == "chat_message":
                await _handle_chat_message(user_id, data, websocket)
    except WebSocketDisconnect:
        manager.disconnect_rider(user_id)


@router.websocket("/ws/driver")
async def driver_ws(websocket: WebSocket):
    token = websocket.query_params.get("token")
    if not token:
        await websocket.close(code=4001, reason="Missing token")
        return

    payload = _authenticate_ws(token)
    if not payload:
        await websocket.close(code=4001, reason="Invalid token")
        return

    user_id = int(payload["sub"])
    role = payload.get("role", "")
    if role != "driver":
        await websocket.close(code=4003, reason="Driver role required")
        return

    await manager.connect_driver(user_id, websocket)

    try:
        while True:
            data = await websocket.receive_json()
            msg_type = data.get("type")
            manager.record_activity(user_id)

            if msg_type == "ping":
                await websocket.send_json({"type": "pong"})

            elif msg_type == "pong":
                pass  # activity already recorded above

            elif msg_type == "location_update":
                from app.services.matching import get_matching_engine
                engine = await get_matching_engine()
                await engine.update_driver_location(
                    user_id, data["lat"], data["lng"]
                )
                await websocket.send_json({"type": "location_ack"})

                # Push live ETA to rider if driver has an active ride
                active_ride_id = data.get("active_ride_id")
                active_rider_id = data.get("active_rider_id")
                pickup_lat = data.get("pickup_lat")
                pickup_lng = data.get("pickup_lng")
                if active_ride_id and active_rider_id and pickup_lat and pickup_lng:
                    try:
                        from app.services.eta import estimate_driver_eta
                        eta = await estimate_driver_eta(
                            engine.redis, user_id, pickup_lat, pickup_lng
                        )
                        if eta:
                            await notify_driver_eta(
                                active_rider_id,
                                active_ride_id,
                                eta.eta_minutes,
                                eta.distance_km,
                                eta.driver_lat,
                                eta.driver_lng,
                            )
                    except Exception:
                        pass  # ETA push is best-effort

            elif msg_type == "accept_ride":
                ride_id = data.get("ride_id")
                if ride_id:
                    from app.services.matching import get_matching_engine
                    engine = await get_matching_engine()
                    accepted = await engine.accept_offer(ride_id, user_id)
                    await websocket.send_json({
                        "type": "accept_ack",
                        "ride_id": ride_id,
                        "accepted": accepted,
                    })

            elif msg_type == "chat_message":
                await _handle_chat_message(user_id, data, websocket)

    except WebSocketDisconnect:
        manager.disconnect_driver(user_id)
        from app.services.matching import get_matching_engine
        engine = await get_matching_engine()
        await engine.remove_driver(user_id)


@router.websocket("/ws/admin")
async def admin_ws(websocket: WebSocket):
    token = websocket.query_params.get("token")
    if not token:
        await websocket.close(code=4001, reason="Missing token")
        return

    payload = _authenticate_ws(token)
    if not payload:
        await websocket.close(code=4001, reason="Invalid token")
        return

    if payload.get("role") != "admin":
        await websocket.close(code=4003, reason="Admin role required")
        return

    user_id = int(payload["sub"])
    await manager.connect_admin(user_id, websocket)

    try:
        while True:
            data = await websocket.receive_json()
            msg_type = data.get("type")
            manager.record_activity(user_id)

            if msg_type == "ping":
                await websocket.send_json({"type": "pong"})
            elif msg_type == "pong":
                pass  # activity already recorded above
    except WebSocketDisconnect:
        manager.disconnect_admin(user_id)


async def _handle_chat_message(sender_id: int, data: dict, websocket: WebSocket) -> None:
    """Validate, persist, and relay a chat message between ride participants."""
    ride_id = data.get("ride_id")
    message_text = data.get("message", "").strip()

    if not ride_id or not message_text:
        await websocket.send_json({
            "type": "chat_error",
            "error": "ride_id and message are required",
        })
        return

    if len(message_text) > 2000:
        await websocket.send_json({
            "type": "chat_error",
            "error": "Message cannot exceed 2000 characters",
        })
        return

    from app.db.database import async_session
    from app.services.chat import get_recipient_id, save_message, validate_chat_participant

    async with async_session() as db:
        ride, error = await validate_chat_participant(db, ride_id, sender_id)
        if error:
            await websocket.send_json({"type": "chat_error", "error": error})
            return

        recipient_id = get_recipient_id(ride, sender_id)
        chat_msg = await save_message(db, ride_id, sender_id, recipient_id, message_text)

    payload = {
        "type": "chat_message",
        "message_id": chat_msg.id,
        "ride_id": ride_id,
        "sender_id": sender_id,
        "message": message_text,
        "created_at": chat_msg.created_at.isoformat(),
    }

    # Send acknowledgement to sender
    await websocket.send_json({"type": "chat_ack", "message_id": chat_msg.id, "ride_id": ride_id})

    # Relay to recipient (try both rider and driver pools — we don't know their role here)
    delivered = await manager.send_to_rider(recipient_id, payload)
    if not delivered:
        delivered = await manager.send_to_driver(recipient_id, payload)


async def relay_chat_message(
    recipient_id: int, message_id: int, ride_id: int, sender_id: int,
    message_text: str, created_at: str,
) -> bool:
    """Relay a chat message to a connected user (called from REST fallback)."""
    payload = {
        "type": "chat_message",
        "message_id": message_id,
        "ride_id": ride_id,
        "sender_id": sender_id,
        "message": message_text,
        "created_at": created_at,
    }
    delivered = await manager.send_to_rider(recipient_id, payload)
    if not delivered:
        delivered = await manager.send_to_driver(recipient_id, payload)
    return delivered


async def notify_admin_sos(
    alert_id: int,
    user_id: int,
    ride_id: int | None,
    latitude: float | None,
    longitude: float | None,
    message: str | None,
) -> int:
    """Push an SOS alert to all connected admin WebSocket clients.

    Returns the number of admins who received the notification.
    """
    payload = {
        "type": "sos_alert",
        "alert_id": alert_id,
        "user_id": user_id,
        "ride_id": ride_id,
        "latitude": latitude,
        "longitude": longitude,
        "message": message,
    }
    return await manager.broadcast_to_admins(payload)


async def notify_driver_eta(
    rider_user_id: int,
    ride_id: int,
    eta_minutes: float,
    distance_km: float,
    driver_lat: float,
    driver_lng: float,
) -> bool:
    """Push a live ETA update to the rider."""
    message = {
        "type": "driver_eta",
        "ride_id": ride_id,
        "eta_minutes": eta_minutes,
        "distance_km": distance_km,
        "driver_lat": driver_lat,
        "driver_lng": driver_lng,
    }
    return await manager.send_to_rider(rider_user_id, message)


async def notify_ride_status(rider_user_id: int, ride_id: int, status: str, **extra) -> bool:
    message = {"type": "ride_status", "ride_id": ride_id, "status": status, **extra}
    return await manager.send_to_rider(rider_user_id, message)


async def send_ride_offer(driver_user_id: int, ride_id: int, pickup_address: str,
                          dropoff_address: str, estimated_fare: float,
                          distance_km: float) -> bool:
    message = {
        "type": "ride_offer",
        "ride_id": ride_id,
        "pickup_address": pickup_address,
        "dropoff_address": dropoff_address,
        "estimated_fare": estimated_fare,
        "pickup_distance_km": round(distance_km, 2),
        "timeout_seconds": settings.ride_offer_timeout_seconds,
    }
    return await manager.send_to_driver(driver_user_id, message)
