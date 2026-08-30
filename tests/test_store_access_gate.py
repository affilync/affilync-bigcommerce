"""Security regression: get_current_store must FAIL CLOSED (cross-store IDOR).

The previous gate was ``type != "api_key" and auth_store_hash and
auth_store_hash != store_hash`` — a JWT with no ``store_hash`` claim (e.g. a
platform/brand token, which carries brand_id not store_hash) skipped the check
entirely and could read/modify ANY store by passing its store_hash. The fix
requires a non-service caller to be bound to the store (matching store_hash, or
owning brand_id, or admin) — otherwise 403.

Driven via asyncio.run so it needs no pytest-asyncio config.
"""
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from app.routes.api import get_current_store


def _run(auth, store_hash="store-A", store_brand_id="brand-1"):
    store = MagicMock()
    store.brand_id = store_brand_id
    store.is_active = True
    with patch("app.routes.api.StoreService") as MockSvc:
        MockSvc.return_value.get_store_by_hash = AsyncMock(return_value=store)
        return asyncio.run(
            get_current_store(store_hash=store_hash, db=AsyncMock(), auth=auth)
        )


def test_jwt_without_store_or_brand_claim_is_denied():
    """The IDOR case: a platform JWT (no store_hash, no matching brand) must 403."""
    with pytest.raises(HTTPException) as exc:
        _run({"type": "jwt", "store_hash": None, "brand_id": None, "is_admin": False})
    assert exc.value.status_code == 403


def test_jwt_with_mismatched_brand_is_denied():
    with pytest.raises(HTTPException) as exc:
        _run({"type": "jwt", "store_hash": None, "brand_id": "other-brand", "is_admin": False})
    assert exc.value.status_code == 403


def test_store_bound_jwt_is_allowed():
    store = _run({"type": "jwt", "store_hash": "store-A", "brand_id": None}, store_hash="store-A")
    assert store is not None


def test_owning_brand_jwt_is_allowed():
    store = _run({"type": "jwt", "store_hash": None, "brand_id": "brand-1"}, store_brand_id="brand-1")
    assert store is not None


def test_admin_is_allowed():
    store = _run({"type": "jwt", "store_hash": None, "brand_id": None, "is_admin": True})
    assert store is not None


def test_api_key_service_is_allowed():
    store = _run({"type": "api_key"})
    assert store is not None
