import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.matching import (
    REDIS_DRIVER_GEO_KEY,
    REDIS_DRIVER_STATUS_PREFIX,
    REDIS_RIDE_OFFERS_PREFIX,
    DriverCandidate,
    MatchingEngine,
)


@pytest.fixture
def mock_redis():
    r = AsyncMock()
    r.geoadd = AsyncMock()
    r.setex = AsyncMock()
    r.zrem = AsyncMock()
    r.delete = AsyncMock()
    r.get = AsyncMock(return_value=None)
    r.geosearch = AsyncMock(return_value=[])
    r.ttl = AsyncMock(return_value=10)
    r.set = AsyncMock()
    return r


@pytest.fixture
def engine(mock_redis):
    return MatchingEngine(mock_redis)


@pytest.mark.asyncio
async def test_update_driver_location(engine, mock_redis):
    await engine.update_driver_location(user_id=1, lat=40.7128, lng=-74.0060)

    mock_redis.geoadd.assert_called_once_with(
        REDIS_DRIVER_GEO_KEY, (-74.0060, 40.7128, "1")
    )
    mock_redis.setex.assert_called_once()
    args = mock_redis.setex.call_args
    assert args[0][0] == f"{REDIS_DRIVER_STATUS_PREFIX}1"
    assert args[0][2] == "available"


@pytest.mark.asyncio
async def test_remove_driver(engine, mock_redis):
    await engine.remove_driver(user_id=5)

    mock_redis.zrem.assert_called_once_with(REDIS_DRIVER_GEO_KEY, "5")
    mock_redis.delete.assert_called_once_with(f"{REDIS_DRIVER_STATUS_PREFIX}5")


@pytest.mark.asyncio
async def test_set_driver_busy(engine, mock_redis):
    await engine.set_driver_busy(user_id=3)

    args = mock_redis.setex.call_args
    assert args[0][2] == "busy"


@pytest.mark.asyncio
async def test_set_driver_available(engine, mock_redis):
    await engine.set_driver_available(user_id=3)

    args = mock_redis.setex.call_args
    assert args[0][2] == "available"


@pytest.mark.asyncio
async def test_find_nearby_drivers(engine, mock_redis):
    mock_redis.geosearch.return_value = [("1", 0.5), ("2", 1.2)]

    results = await engine.find_nearby_drivers(lat=40.7, lng=-74.0, radius_km=5.0)

    assert results == [("1", 0.5), ("2", 1.2)]
    mock_redis.geosearch.assert_called_once_with(
        REDIS_DRIVER_GEO_KEY,
        longitude=-74.0,
        latitude=40.7,
        radius=5.0,
        unit="km",
        sort="ASC",
        count=10,
        withdist=True,
    )


@pytest.mark.asyncio
async def test_filter_available_skips_busy(engine, mock_redis):
    async def mock_get(key):
        if key.endswith("1"):
            return b"available"
        if key.endswith("2"):
            return b"busy"
        return None

    mock_redis.get = AsyncMock(side_effect=mock_get)

    nearby = [("1", 0.5), ("2", 1.0), ("3", 1.5)]
    available = await engine._filter_available(nearby)

    assert available == [(1, 0.5)]


@pytest.mark.asyncio
async def test_accept_offer_success(engine, mock_redis):
    offer = {"ride_id": 10, "driver_user_id": 5, "status": "pending"}
    mock_redis.get.return_value = json.dumps(offer)
    mock_redis.ttl.return_value = 8

    result = await engine.accept_offer(ride_id=10, user_id=5)

    assert result is True
    saved = json.loads(mock_redis.setex.call_args[0][2])
    assert saved["status"] == "accepted"


@pytest.mark.asyncio
async def test_accept_offer_wrong_driver(engine, mock_redis):
    offer = {"ride_id": 10, "driver_user_id": 5, "status": "pending"}
    mock_redis.get.return_value = json.dumps(offer)

    result = await engine.accept_offer(ride_id=10, user_id=99)

    assert result is False


@pytest.mark.asyncio
async def test_accept_offer_already_accepted(engine, mock_redis):
    offer = {"ride_id": 10, "driver_user_id": 5, "status": "accepted"}
    mock_redis.get.return_value = json.dumps(offer)

    result = await engine.accept_offer(ride_id=10, user_id=5)

    assert result is False


@pytest.mark.asyncio
async def test_accept_offer_expired(engine, mock_redis):
    mock_redis.get.return_value = None

    result = await engine.accept_offer(ride_id=10, user_id=5)

    assert result is False
