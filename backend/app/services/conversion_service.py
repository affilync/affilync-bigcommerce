"""
Conversion Attribution Service
Handles order to conversion tracking
"""

import logging
from datetime import datetime
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from affilync_integrations import AffilyncAPIClient, ConversionData, AdjustmentData

from app.config import settings
from app.models import BigCommerceStore
from app.utils.attribution import (
    extract_tracking_code,
    extract_order_line_items,
    get_order_total,
    get_order_subtotal,
)

logger = logging.getLogger(__name__)


class ConversionService:
    """Service for tracking affiliate conversions from BigCommerce orders."""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.api_client = AffilyncAPIClient(
            api_url=settings.affilync_api_url,
            api_key=settings.affilync_api_key,
            source="bigcommerce-app",
        )

    async def process_order(
        self,
        store: BigCommerceStore,
        order_data: dict,
        scope: str = "store/order/created",
    ) -> dict:
        """
        Process an order for affiliate conversion tracking.

        Args:
            store: Store that received the order
            order_data: BigCommerce order webhook payload
            scope: Webhook scope

        Returns:
            dict: Processing result with status and conversion_id if tracked
        """
        order_id = order_data.get("id")
        logger.info(f"Processing order {order_id} from {store.store_hash}")

        # Extract tracking code
        tracking_code = extract_tracking_code(order_data)

        if not tracking_code:
            logger.info(f"No affiliate attribution for order {order_id}")
            return {
                "status": "no_attribution",
                "order_id": order_id,
                "message": "No tracking code found",
            }

        # Check if store is connected to Affilync brand
        if not store.brand_id:
            logger.warning(f"Store {store.store_hash} not connected to Affilync brand")
            return {
                "status": "not_connected",
                "order_id": order_id,
                "tracking_code": tracking_code,
                "message": "Store not connected to Affilync",
            }

        # Build conversion data
        conversion_data = self._build_conversion_data(
            store=store,
            order_data=order_data,
            tracking_code=tracking_code,
        )

        # Send to Affilync API
        try:
            result = await self.api_client.track_conversion(conversion_data)
            logger.info(f"Conversion tracked for order {order_id}: {result.get('conversion_id')}")
            return {
                "status": "tracked",
                "order_id": order_id,
                "tracking_code": tracking_code,
                "conversion_id": result.get("conversion_id"),
            }
        except Exception as e:
            logger.error(f"Failed to track conversion for order {order_id}: {e}")
            return {
                "status": "error",
                "order_id": order_id,
                "tracking_code": tracking_code,
                "error": str(e),
            }

    def _build_conversion_data(
        self,
        store: BigCommerceStore,
        order_data: dict,
        tracking_code: str,
    ) -> ConversionData:
        """
        Build conversion data payload for Affilync API.

        Args:
            store: Store record
            order_data: BigCommerce order data
            tracking_code: Extracted affiliate tracking code

        Returns:
            ConversionData for API
        """
        order_id = order_data.get("id")
        total_value = get_order_total(order_data)
        subtotal = get_order_subtotal(order_data)
        currency = order_data.get("currency_code", "USD")

        # Customer info
        billing = order_data.get("billing_address", {})
        customer_email = billing.get("email") or order_data.get("email")
        customer_id = order_data.get("customer_id")

        # Extract line items
        line_items = extract_order_line_items(order_data)

        # Get order status
        status_id = order_data.get("status_id", 0)
        status = order_data.get("status", "")

        # conversion_type MUST be one of the Affilync ConversionCreate enum values
        # (sale/lead/signup/download/subscription/custom) — "purchase"/"refund"
        # aren't valid values (same fix already applied to Shopify's equivalent).
        # An order that arrives already-refunded (rare: refunded before this
        # webhook fired) still records as "sale" here; process_refund below is
        # the real refund path for orders that transition to refunded later.
        conversion_type = "sale"

        return ConversionData(
            tracking_code=tracking_code,
            brand_id=str(store.brand_id),
            order_id=f"bigcommerce_{order_id}",
            order_value=subtotal,
            total_value=total_value,
            currency=currency,
            conversion_type=conversion_type,
            customer_email=customer_email,
            customer_id=str(customer_id) if customer_id else None,
            metadata={
                "source": "bigcommerce",
                "store_hash": store.store_hash,
                "bc_order_id": order_id,
                "status_id": status_id,
                "status": status,
                "payment_method": order_data.get("payment_method"),
                "line_items": line_items,
                "discount_amount": float(order_data.get("discount_amount", 0)),
                "coupon_discount": float(order_data.get("coupon_discount", 0)),
                "order_created_at": order_data.get("date_created"),
            },
        )

    async def process_refund(
        self,
        store: BigCommerceStore,
        order_data: dict,
    ) -> dict:
        """
        Process a refund for conversion adjustment.

        BigCommerce doesn't have separate refund webhooks - refunds are
        detected via order status changes.

        Args:
            store: Store record
            order_data: BigCommerce order webhook payload

        Returns:
            dict: Processing result
        """
        order_id = order_data.get("id")
        logger.info(f"Processing refund for order {order_id}")

        if not store.brand_id:
            return {
                "status": "not_connected",
                "order_id": order_id,
            }

        # Calculate refund amount from order data
        # In BigCommerce, we'd need to compare original total with refund data
        refund_amount = float(order_data.get("refunded_amount", 0))

        if refund_amount <= 0:
            return {
                "status": "no_refund",
                "order_id": order_id,
            }

        # Send refund adjustment to Affilync
        try:
            adjustment_data = AdjustmentData(
                brand_id=str(store.brand_id),
                original_order_id=f"bigcommerce_{order_id}",
                adjustment_type="refund",
                adjustment_amount=refund_amount,
                refund_id=f"bigcommerce_refund_{order_id}",
                metadata={
                    "source": "bigcommerce",
                    "store_hash": store.store_hash,
                    "order_status": order_data.get("status"),
                },
            )

            result = await self.api_client.track_adjustment(adjustment_data)
            return {
                "status": "adjusted",
                "order_id": order_id,
                "adjustment_id": result.get("adjustment_id"),
                "refund_amount": refund_amount,
            }

        except Exception as e:
            logger.error(f"Failed to process refund for order {order_id}: {e}")
            return {
                "status": "error",
                "order_id": order_id,
                "error": str(e),
            }

    async def get_order_attribution(
        self,
        store: BigCommerceStore,
        order_id: int,
    ) -> Optional[dict]:
        """
        Check if an order has affiliate attribution.

        Args:
            store: Store record
            order_id: BigCommerce order ID

        Returns:
            dict: Attribution info if found
        """
        if not store.brand_id:
            return None

        return await self.api_client.lookup_conversion(
            brand_id=str(store.brand_id),
            external_order_id=f"bigcommerce_{order_id}",
        )
