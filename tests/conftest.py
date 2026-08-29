"""Pytest fixtures for Async Webhook Engine testing."""

from collections.abc import AsyncGenerator
from unittest.mock import MagicMock, patch
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app
from app.models.user import User
from app.utils.security import create_access_token, get_password_hash

# In-memory SQLite async test database
TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"

test_engine = create_async_engine(
    TEST_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)

TestingAsyncSessionLocal = async_sessionmaker(
    bind=test_engine,
    class_=AsyncSession,
    autocommit=False,
    autoflush=False,
    expire_on_commit=False,
)


@pytest_asyncio.fixture(scope="function", autouse=True)
async def setup_test_database():
    """Create all tables before each test and drop them after."""
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest_asyncio.fixture
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    """Provide a transactional test database session."""
    async with TestingAsyncSessionLocal() as session:
        yield session


@pytest_asyncio.fixture
async def async_client(db_session: AsyncSession) -> AsyncGenerator[AsyncClient, None]:
    """Provide an HTTPX AsyncClient with overridden database session dependency."""

    async def override_get_db() -> AsyncGenerator[AsyncSession, None]:
        yield db_session

    app.dependency_overrides[get_db] = override_get_db

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client

    app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def test_user(db_session: AsyncSession) -> User:
    """Create and return a standard test user."""
    user = User(
        email="testuser@example.com",
        hashed_password=get_password_hash("StrongPassword123!"),
        is_active=True,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest_asyncio.fixture
def auth_headers(test_user: User) -> dict[str, str]:
    """Generate authorization headers for test_user."""
    token = create_access_token(data={"sub": str(test_user.id)})
    return {"Authorization": f"Bearer {token}"}


@pytest_asyncio.fixture
async def second_user(db_session: AsyncSession) -> User:
    """Create and return a second test user for cross-user isolation tests."""
    user = User(
        email="seconduser@example.com",
        hashed_password=get_password_hash("AnotherPassword123!"),
        is_active=True,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest_asyncio.fixture
def second_auth_headers(second_user: User) -> dict[str, str]:
    """Generate authorization headers for second_user."""
    token = create_access_token(data={"sub": str(second_user.id)})
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def mock_celery_task():
    """Mock Celery dispatch_webhook_task.delay."""
    with patch("app.api.webhooks.dispatch_webhook_task.delay") as mock_delay:
        mock_result = MagicMock()
        mock_result.id = "mock-task-uuid-12345"
        mock_delay.return_value = mock_result
        yield mock_delay
