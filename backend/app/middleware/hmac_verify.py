"""
Bearer-token verification for BigCommerce webhooks.

V58.36 P0 (2026-05-28): the previous HMAC-content-hash scheme
expected a header (X-BC-Api-Content-Hash) that BigCommerce does NOT
emit on outbound webhook deliveries — every order/product/uninstall
webhook silently 401'd at this middleware. Conversion tracking,
product sync, and uninstall teardown were ALL dead end-to-end.

BC's actual outbound-webhook auth model is the `headers` dict
configured at webhook registration time. The app generates a strong
secret, stores it in BIGCOMMERCE_WEBHOOK_SECRET, propagates it as
`Authorization: Bearer <secret>` on register_all_webhooks, and this
middleware compares constant-time.

The function name `verify_webhook_hmac` is retained as a thin
backward-compat alias so existing call sites keep working; semantics
are now bearer-token comparison.
"""

import hmac
import logging
from typing import Callable

from fastapi.responses import JSONResponse
from fastapi import HTTPException, Request, status
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

from app.config import settings

logger = logging.getLogger(__name__)


def _expected_webhook_token() -> str:
    """Return the bearer token BC should be sending on every webhook.

    Falls back to ``bigcommerce_client_secret`` when the dedicated
    ``BIGCOMMERCE_WEBHOOK_SECRET`` env var isn't set, so unit tests +
    dev don't need a separate secret. Production should always set
    the dedicated env var so it can be rotated independently.
    """
    return settings.bigcommerce_webhook_secret or settings.bigcommerce_client_secret


def verify_webhook_bearer(authorization_header: str) -> bool:
    """Verify the `Authorization: Bearer <token>` header sent by BC."""
    if not authorization_header:
        return False
    parts = authorization_header.strip().split(None, 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return False
    return hmac.compare_digest(parts[1], _expected_webhook_token())


# Back-compat alias — old callers passed (payload, signature). New
# semantics: verify the Authorization bearer string only. payload is
# kept in the signature for source compatibility but ignored.
def verify_webhook_hmac(payload: bytes, signature: str) -> bool:  # noqa: D401
    """Deprecated: use verify_webhook_bearer.

    Kept as a thin alias so any out-of-tree callers keep compiling.
    The `payload` argument is no longer used.
    """
    return verify_webhook_bearer(signature)


class WebhookHMACMiddleware(BaseHTTPMiddleware):
    """Middleware that verifies the per-app bearer token on BC webhooks.

    Only applies to /webhooks/bigcommerce. Body is still read once and
    stashed on request.state.raw_body so route handlers don't have to
    re-read it (FastAPI/Starlette doesn't let you re-await body()
    multiple times by default).
    """

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        # Only verify webhooks path
        if not request.url.path.startswith("/webhooks/bigcommerce"):
            return await call_next(request)

        # V58.36 P0 (2026-05-28): bearer-token auth (see module
        # docstring). Header arrives unchanged for replay-protection
        # dedup, so the per-(body+auth) key remains unique per
        # delivery and an attacker who captured one valid request
        # still can't replay it after 24h.
        authorization = request.headers.get("Authorization") or ""

        # Read body and store for later use
        body = await request.body()

        if not verify_webhook_bearer(authorization):
            logger.warning("BC webhook bearer verification failed")
            # Return, don't raise: HTTPException raised inside
            # BaseHTTPMiddleware.dispatch never reaches FastAPI's exception
            # handlers (they wrap the router, INSIDE user middleware), so it
            # surfaced as a raw 500 — and BigCommerce retries 5xx, meaning
            # forged/broken deliveries were retried indefinitely instead of
            # being dropped on a definitive 401.
            return JSONResponse(
                status_code=status.HTTP_401_UNAUTHORIZED,
                content={"detail": "Invalid webhook credentials"},
            )

        # SEC: replay protection. Same logic as before — captured
        # webhooks can be replayed indefinitely without a freshness
        # guard because BC does not include a per-delivery nonce.
        # Dedup on (hash of body + authorization) for 24 h.
        try:
            import hashlib as _hashlib

            from app.services.redis_service import get_redis  # type: ignore

            redis = await get_redis()
            if redis is not None:
                replay_key = (
                    "bc_webhook_replay:"
                    + _hashlib.sha256(body + authorization.encode()).hexdigest()
                )
                # SET NX EX 86400 — atomic dedup with 24 h TTL.
                claimed = await redis.set(replay_key, b"1", nx=True, ex=86400)
                if not claimed:
                    logger.warning(
                        "Replayed BigCommerce webhook rejected: %s", replay_key[:60]
                    )
                    # Same return-don't-raise rule as the 401 above.
                    return JSONResponse(
                        status_code=status.HTTP_409_CONFLICT,
                        content={"detail": "Webhook already processed"},
                    )
        except Exception as redis_err:
            # Redis unreachable — log and allow. Webhooks are idempotent
            # on the application side; HMAC has already validated the
            # payload, so allowing dedup-skipped delivery is preferable
            # to blocking legitimate Connect webhooks during a Redis outage.
            logger.warning("Webhook replay-protection skipped: %s", redis_err)

        # Store body in state for route handler
        request.state.raw_body = body

        return await call_next(request)


async def verify_webhook_signature(request: Request) -> bytes:
    """FastAPI dependency to verify webhook auth and return body.

    Alternative to middleware for more granular control. Uses the same
    bearer-token semantics as the middleware (V58.36).
    """
    authorization = request.headers.get("Authorization") or ""
    body = await request.body()

    if not verify_webhook_bearer(authorization):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid webhook credentials",
        )

    return body
