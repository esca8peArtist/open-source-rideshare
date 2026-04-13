import os
from collections.abc import AsyncGenerator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.db.database import Base, get_db
from app.models.user import User, UserRole
from app.models.driver import DriverProfile
from app.models.ride import Ride, RideStatus
from app.models.payment import Payment, PaymentStatus
from app.services.auth import create_access_token, hash_password

TEST_DATABASE_URL = os.environ.get(
    "OPENRIDE_TEST_DATABASE_URL",
    "postgresql+asyncpg://openride_test:openride_test@localhost:5433/openride_test",
)

engine = create_async_engine(TEST_DATABASE_URL, echo=False)
TestSessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


@pytest.fixture(scope="session")
def anyio_backend():
    return "asyncio"


@pytest.fixture(scope="session")
async def setup_database():
    try:
        async with engine.begin() as conn:
            await conn.execute(
                __import__("sqlalchemy").text("CREATE EXTENSION IF NOT EXISTS postgis")
            )
            await conn.run_sync(Base.metadata.create_all)
    except Exception as exc:
        pytest.skip(f"Test database not available: {exc}")
    yield
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
        await engine.dispose()
    except Exception:
        pass


@pytest.fixture
async def db(setup_database) -> AsyncGenerator[AsyncSession, None]:
    async with TestSessionLocal() as session:
        async with session.begin():
            yield session
            await session.rollback()


@pytest.fixture
async def app(db: AsyncSession):
    from app.main import app as fastapi_app

    async def override_get_db():
        yield db

    fastapi_app.dependency_overrides[get_db] = override_get_db

    mock_engine = AsyncMock()
    mock_engine.find_candidates = AsyncMock(return_value=[])
    mock_engine.match_ride = AsyncMock(return_value=None)
    mock_engine.update_driver_location = AsyncMock()
    mock_engine.set_driver_busy = AsyncMock()
    mock_engine.set_driver_available = AsyncMock()
    mock_engine.remove_driver = AsyncMock()

    with patch("app.services.matching.get_matching_engine", return_value=mock_engine), \
         patch("app.api.websocket.notify_ride_status", new_callable=AsyncMock), \
         patch("app.api.websocket.send_ride_offer", new_callable=AsyncMock), \
         patch("app.api.websocket.notify_admin_sos", new_callable=AsyncMock):
        yield fastapi_app

    fastapi_app.dependency_overrides.clear()


@pytest.fixture
async def client(app) -> AsyncGenerator[AsyncClient, None]:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.fixture
async def rider(db: AsyncSession) -> User:
    user = User(
        phone="+15551000001",
        name="Test Rider",
        email="rider@test.com",
        password_hash=hash_password("testpass123"),
        role=UserRole.RIDER,
        is_active=True,
    )
    db.add(user)
    await db.flush()
    return user


@pytest.fixture
async def driver_user(db: AsyncSession) -> User:
    user = User(
        phone="+15551000002",
        name="Test Driver",
        email="driver@test.com",
        password_hash=hash_password("testpass123"),
        role=UserRole.DRIVER,
        is_active=True,
    )
    db.add(user)
    await db.flush()
    return user


@pytest.fixture
async def admin_user(db: AsyncSession) -> User:
    user = User(
        phone="+15551000003",
        name="Test Admin",
        email="admin@test.com",
        password_hash=hash_password("testpass123"),
        role=UserRole.ADMIN,
        is_active=True,
    )
    db.add(user)
    await db.flush()
    return user


@pytest.fixture
async def driver_profile(db: AsyncSession, driver_user: User) -> DriverProfile:
    profile = DriverProfile(
        user_id=driver_user.id,
        vehicle_type="sedan",
        vehicle_make="Toyota",
        vehicle_model="Camry",
        vehicle_year=2022,
        vehicle_color="Silver",
        license_plate="TEST-123",
        license_number="DL-TEST-456",
        insurance_policy="INS-789",
        is_approved=True,
        is_online=False,
        rating_avg=4.8,
        total_trips=50,
    )
    db.add(profile)
    await db.flush()
    return profile


@pytest.fixture
def rider_token(rider: User) -> str:
    return create_access_token(rider.id, rider.role.value)


@pytest.fixture
def driver_token(driver_user: User) -> str:
    return create_access_token(driver_user.id, driver_user.role.value)


@pytest.fixture
def admin_token(admin_user: User) -> str:
    return create_access_token(admin_user.id, admin_user.role.value)


def auth_header(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}
