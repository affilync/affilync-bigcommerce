"""Webhook auth + dispatch tests — pinned to the REAL surface.

The old suite POSTed /webhooks/orders, /webhooks/products, /webhooks/app
(none exist — everything lands on POST /webhooks/bigcommerce) and patched
backend.app.middleware.hmac_verify.verify_hmac (module path and function
both nonexistent). V58.36 semantics: BigCommerce authenticates webhooks
with an `Authorization: Bearer <token>` header compared against
BIGCOMMERCE_WEBHOOK_SECRET (fallback: the client secret).
"""

from app.middleware.hmac_verify import verify_webhook_bearer

# conftest sets BIGCOMMERCE_CLIENT_SECRET=test-client-secret and no
# dedicated webhook secret, so the fallback token is the client secret.
VALID_AUTH = {"Authorization": "Bearer test-client-secret"}


class TestWebhookBearerVerification:
    def test_valid_bearer_passes(self):
        assert verify_webhook_bearer("Bearer test-client-secret") is True

    def test_wrong_token_fails(self):
        assert verify_webhook_bearer("Bearer wrong-token") is False

    def test_missing_header_fails(self):
        assert verify_webhook_bearer("") is False

    def test_non_bearer_scheme_fails(self):
        assert verify_webhook_bearer("Basic test-client-secret") is False


class TestWebhookEndpoint:
    """POST /webhooks/bigcommerce."""

    def test_rejects_missing_auth(self, client, sample_webhook_payload):
        response = client.post("/webhooks/bigcommerce", json=sample_webhook_payload)
        assert response.status_code == 401

    def test_rejects_wrong_bearer(self, client, sample_webhook_payload):
        response = client.post(
            "/webhooks/bigcommerce",
            json=sample_webhook_payload,
            headers={"Authorization": "Bearer forged"},
        )
        assert response.status_code == 401

    def test_invalid_json_is_400(self, client):
        response = client.post(
            "/webhooks/bigcommerce",
            content=b"not json",
            headers={**VALID_AUTH, "Content-Type": "application/json"},
        )
        assert response.status_code == 400

    def test_missing_producer_is_acknowledged_ignored(self, client):
        """No producer => no store hash; acknowledged as ignored (BC would
        otherwise retry forever)."""
        response = client.post(
            "/webhooks/bigcommerce",
            json={"scope": "store/order/created", "data": {}},
            headers=VALID_AUTH,
        )
        assert response.status_code == 200
        assert response.json() == {"status": "ignored", "reason": "missing_store_hash"}

    def test_unknown_store_is_acknowledged_ignored(self, client, sample_webhook_payload):
        response = client.post(
            "/webhooks/bigcommerce",
            json=sample_webhook_payload,
            headers=VALID_AUTH,
        )
        assert response.status_code == 200
        assert response.json() == {"status": "ignored", "reason": "store_not_found"}
