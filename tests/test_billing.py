"""
Unit tests for BigCommerce subscription billing.

Verifies the plan ladder (ported verbatim from the TikTok integration) and the
billing route auth/validation behavior.
"""

from decimal import Decimal

from app.services.billing_service import (
    PLANS,
    PLAN_ORDER,
    BillingPlan,
    BillingService,
)


class TestPlanLadder:
    """The plan ladder must match the TikTok integration exactly."""

    def test_four_plans_present(self):
        assert set(PLANS.keys()) == {
            BillingPlan.FREE,
            BillingPlan.STARTER,
            BillingPlan.PRO,
            BillingPlan.ENTERPRISE,
        }

    def test_prices(self):
        assert PLANS[BillingPlan.FREE].price == Decimal("0")
        assert PLANS[BillingPlan.STARTER].price == Decimal("29")
        assert PLANS[BillingPlan.PRO].price == Decimal("99")
        assert PLANS[BillingPlan.ENTERPRISE].price == Decimal("299")

    def test_trial_days(self):
        assert PLANS[BillingPlan.FREE].trial_days == 0
        assert PLANS[BillingPlan.STARTER].trial_days == 7
        assert PLANS[BillingPlan.PRO].trial_days == 7
        assert PLANS[BillingPlan.ENTERPRISE].trial_days == 14

    def test_product_limits(self):
        assert PLANS[BillingPlan.FREE].max_products == 50
        assert PLANS[BillingPlan.STARTER].max_products == 500
        assert PLANS[BillingPlan.PRO].max_products == 5000
        assert PLANS[BillingPlan.ENTERPRISE].max_products == -1

    def test_conversion_limits(self):
        assert PLANS[BillingPlan.FREE].conversion_limit == 100
        assert PLANS[BillingPlan.STARTER].conversion_limit == 1000
        assert PLANS[BillingPlan.PRO].conversion_limit == 10000
        assert PLANS[BillingPlan.ENTERPRISE].conversion_limit == -1

    def test_creator_limits_retained_for_parity(self):
        # max_creators is kept for parity with TikTok even though BigCommerce
        # has no creators concept.
        assert PLANS[BillingPlan.FREE].max_creators == 5
        assert PLANS[BillingPlan.STARTER].max_creators == 25
        assert PLANS[BillingPlan.PRO].max_creators == 100
        assert PLANS[BillingPlan.ENTERPRISE].max_creators == -1

    def test_feature_gates(self):
        assert PLANS[BillingPlan.FREE].export_enabled is False
        assert PLANS[BillingPlan.STARTER].export_enabled is True
        assert PLANS[BillingPlan.PRO].api_access is True
        assert PLANS[BillingPlan.ENTERPRISE].priority_support is True

    def test_plan_order(self):
        assert PLAN_ORDER == [
            BillingPlan.FREE,
            BillingPlan.STARTER,
            BillingPlan.PRO,
            BillingPlan.ENTERPRISE,
        ]


class TestUpgradeDetection:
    """Upgrade/downgrade direction detection."""

    def test_is_upgrade(self):
        svc = BillingService(db=None)
        assert svc._is_upgrade(BillingPlan.FREE, BillingPlan.PRO) is True
        assert svc._is_upgrade(BillingPlan.PRO, BillingPlan.STARTER) is False
        assert svc._is_upgrade(BillingPlan.STARTER, BillingPlan.STARTER) is False


class TestBillingRoutes:
    """Auth + validation behavior on the billing endpoints."""

    def test_plans_requires_auth(self, client):
        response = client.get("/api/billing/plans")
        assert response.status_code in [401, 403]

    def test_plans_returns_ladder_with_api_key(self, client):
        # conftest sets AFFILYNC_API_KEY=test-api-key
        response = client.get(
            "/api/billing/plans",
            headers={"X-API-Key": "test-api-key"},
        )
        assert response.status_code == 200
        plans = response.json()["plans"]
        prices = {p["id"]: p["price"] for p in plans}
        assert prices == {"free": 0.0, "starter": 29.0, "pro": 99.0, "enterprise": 299.0}

    def test_subscribe_rejects_invalid_plan(self, client):
        response = client.post(
            "/api/billing/subscribe",
            headers={"X-API-Key": "test-api-key"},
            json={"plan": "platinum", "store_id": "abc"},
        )
        assert response.status_code == 400

    def test_subscribe_rejects_invalid_store_id(self, client):
        response = client.post(
            "/api/billing/subscribe",
            headers={"X-API-Key": "test-api-key"},
            json={"plan": "pro", "store_id": "not-a-uuid"},
        )
        assert response.status_code == 400
