"""Unit tests for BigCommerce OAuth routes — pinned to the REAL surface.

The old suite tested /oauth/install (never existed; the entry point is
/oauth/auth) and patched backend.app.routes.oauth.exchange_code_for_token
(neither the module path nor the function exist). Every assertion accepted
404 as a pass, so the drift was invisible.
"""

from unittest.mock import AsyncMock, patch

from app.middleware import jwt_bc


class TestOAuthAuthStart:
    """GET /oauth/auth — the canonical entry point."""

    def test_initial_auth_redirects_to_bigcommerce(self, client):
        """No code => issue CSRF state and redirect to BC authorize URL."""
        with patch(
            "app.routes.oauth._store_state", new=AsyncMock(return_value=None)
        ):
            response = client.get("/oauth/auth", follow_redirects=False)
        assert response.status_code in (302, 307)
        location = response.headers["location"]
        assert "/oauth2/authorize" in location
        assert "state=" in location
        assert "client_id=test-client-id" in location

    def test_state_storage_down_fails_closed(self, client):
        """Redis down => refuse to issue an auth URL we cannot validate
        (deliberate 503 — do not ship a merchant into an unvalidatable
        OAuth flow)."""
        response = client.get("/oauth/auth", follow_redirects=False)
        assert response.status_code == 503

    def test_callback_via_auth_requires_state(self, client):
        """code without a CSRF state => 400 (V58.6 P0: stripping state must
        not skip validation)."""
        response = client.get(
            "/oauth/auth",
            params={
                "code": "auth-code",
                "scope": "store_v2_default",
                "context": "stores/abc123",
            },
        )
        assert response.status_code == 400
        assert "state" in response.json()["detail"].lower()


class TestOAuthCallback:
    """GET /oauth/callback."""

    def test_callback_without_code_fails_validation(self, client):
        response = client.get("/oauth/callback")
        assert response.status_code == 422

    def test_callback_with_invalid_state_rejected(self, client):
        """State that fails validation => 400, before any token exchange."""
        with patch(
            "app.routes.oauth._validate_state", new=AsyncMock(return_value=False)
        ):
            response = client.get(
                "/oauth/callback",
                params={
                    "code": "auth-code",
                    "scope": "store_v2_default",
                    "context": "stores/abc123",
                    "state": "forged",
                },
            )
        assert response.status_code == 400


class TestOAuthUninstall:
    """GET /oauth/uninstall — signed_payload_jwt, verified sig/iss/aud."""

    def test_uninstall_requires_signed_payload(self, client):
        response = client.get("/oauth/uninstall")
        assert response.status_code == 422

    def test_uninstall_rejects_invalid_jwt(self, client):
        response = client.get(
            "/oauth/uninstall", params={"signed_payload_jwt": "not.a.jwt"}
        )
        assert response.status_code == 401

    def test_uninstall_deactivates_store(self, client):
        """A validly-signed payload deactivates the named store."""
        with patch.object(
            jwt_bc, "decode_bc_jwt", return_value={"sub": "stores/abc123"}
        ), patch(
            "app.routes.oauth.StoreService"
        ) as MockSvc:
            MockSvc.return_value.uninstall_store = AsyncMock(return_value=True)
            response = client.get(
                "/oauth/uninstall", params={"signed_payload_jwt": "signed"}
            )
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}
        MockSvc.return_value.uninstall_store.assert_awaited_once_with("abc123")
