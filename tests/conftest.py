"""Pytest configuration and fixtures for BigCommerce integration tests.

Everything imports the service as ``app.*`` — the same module tree
``backend/app/main.py`` itself uses (``pythonpath = backend`` in pytest.ini).
The previous harness imported ``backend.app.*``, which built a PARALLEL copy
of every module: its ``get_db`` override keyed on a function object no route
depended on, and every ``@patch("backend.app...")`` patched modules the
running app never imported. Tests "passed" only where they needed neither.
"""

import os

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

# Set test environment variables before importing app
os.environ.setdefault("BIGCOMMERCE_CLIENT_ID", "test-client-id")
os.environ.setdefault("BIGCOMMERCE_CLIENT_SECRET", "test-client-secret")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("ENCRYPTION_KEY", "test-encryption-key-32chars-long!")
os.environ.setdefault("AFFILYNC_API_URL", "https://api.affilync.com")
os.environ.setdefault("AFFILYNC_API_KEY", "test-api-key")
os.environ.setdefault("JWT_SECRET_KEY", "test-jwt-secret")

from app.database import Base, get_db  # noqa: E402
from app.main import app  # noqa: E402

# One shared in-memory database per test (StaticPool keeps the single
# connection alive across sessions).
_test_engine = create_async_engine(
    "sqlite+aiosqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
_TestSession = async_sessionmaker(_test_engine, expire_on_commit=False)


@pytest_asyncio.fixture(scope="function")
async def db():
    """Create a fresh schema for each test and yield an AsyncSession."""
    async with _test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with _TestSession() as session:
        yield session
    async with _test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest.fixture(scope="function")
def client(db):
    """Test client whose get_db override targets the REAL dependency object."""

    async def override_get_db():
        yield db

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture
def sample_webhook_payload():
    """A BigCommerce order webhook payload in the documented shape."""
    return {
        "scope": "store/order/created",
        "store_id": "1234567",
        "data": {"type": "order", "id": 12345},
        "hash": "unique_hash",
        "created_at": 1234567890,
        "producer": "stores/abc123",
    }
