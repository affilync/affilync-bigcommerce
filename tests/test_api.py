"""Store API tests — pinned to the REAL surface.

The old suite hit /api/sync/products and /api/conversions (neither exists;
the real routes are /api/products/sync and /api/analytics), accepted
"200 or 401 or 403" so nothing could fail, and patched a parallel
backend.app.* module tree the app never imported.

Auth model exercised for real: require_auth is overridden as a trusted
api_key caller (the gateway shape); get_current_store then runs its actual
store lookup against a real row in the test database — including the
fail-closed cross-store gate.
"""

import uuid

import pytest
import pytest_asyncio
from app.main import app
from app.middleware.auth import require_auth
from app.models.store import BigCommerceStore


@pytest_asyncio.fixture
async def store(db):
    """A real, active store row (unconnected: brand_id=None)."""
    row = BigCommerceStore(
        store_hash="abc123",
        store_name="Test Store",
        access_token="enc-token",
        scope="store_v2_default",
        is_active=True,
    )
    db.add(row)
    await db.commit()
    return row


@pytest.fixture
def authed_client(client):
    """The conftest client plus a trusted service (api_key) identity."""
    app.dependency_overrides[require_auth] = lambda: {"type": "api_key"}
    yield client
    app.dependency_overrides.pop(require_auth, None)


class TestAuthGate:
    def test_products_requires_auth(self, client):
        response = client.get("/api/products", params={"store_hash": "abc123"})
        assert response.status_code in (401, 403)

    def test_sync_requires_auth(self, client):
        response = client.post("/api/products/sync", params={"store_hash": "abc123"})
        assert response.status_code in (401, 403)

    def test_store_hash_is_required(self, authed_client):
        """get_current_store takes store_hash as a required query param."""
        response = authed_client.get("/api/products")
        assert response.status_code == 422

    def test_unknown_store_is_404(self, authed_client):
        response = authed_client.get(
            "/api/products", params={"store_hash": "nosuchstore"}
        )
        assert response.status_code == 404


class TestProductsAPI:
    def test_empty_store_lists_no_products(self, authed_client, store):
        response = authed_client.get("/api/products", params={"store_hash": "abc123"})
        assert response.status_code == 200
        data = response.json()
        assert data["products"] == []
        assert data["total"] == 0

    def test_sync_requires_connected_brand(self, authed_client, store):
        """An unconnected store (brand_id NULL) cannot sync — 400 with an
        actionable message, not a crash."""
        response = authed_client.post(
            "/api/products/sync", params={"store_hash": "abc123"}
        )
        assert response.status_code == 400
        assert "brand" in response.json()["detail"].lower()


class TestAnalyticsAPI:
    def test_analytics_requires_auth(self, client):
        response = client.get("/api/analytics", params={"store_hash": "abc123"})
        assert response.status_code in (401, 403)

    def test_unconnected_store_gets_zeroed_analytics(self, authed_client, store):
        """brand_id NULL => a zeroed AnalyticsResponse, not an error."""
        response = authed_client.get(
            "/api/analytics", params={"store_hash": "abc123"}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["conversions"] == 0
        assert data["revenue"] == 0
        assert data["top_affiliates"] == []


class TestCrossStoreGate:
    """The fail-closed IDOR gate in get_current_store."""

    def test_foreign_brand_jwt_cannot_read_store(self, client, store):
        """A brand JWT with a different brand_id must get 403 — the old
        check failed OPEN for tokens without a store_hash claim."""
        app.dependency_overrides[require_auth] = lambda: {
            "type": "jwt",
            "brand_id": str(uuid.uuid4()),
        }
        try:
            response = client.get(
                "/api/products", params={"store_hash": "abc123"}
            )
        finally:
            app.dependency_overrides.pop(require_auth, None)
        assert response.status_code == 403

    def test_store_bound_jwt_allowed(self, client, store):
        app.dependency_overrides[require_auth] = lambda: {
            "type": "jwt",
            "store_hash": "abc123",
        }
        try:
            response = client.get(
                "/api/products", params={"store_hash": "abc123"}
            )
        finally:
            app.dependency_overrides.pop(require_auth, None)
        assert response.status_code == 200
