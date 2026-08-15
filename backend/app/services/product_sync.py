"""
Product Sync Service
Handles synchronization of products between BigCommerce and Affilync
"""

import logging
from datetime import datetime
from typing import List, Optional
from uuid import UUID

from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from affilync_integrations import AffilyncAPIClient, ProductSyncData

from app.config import settings
from app.models import BigCommerceStore, BigCommerceProduct
from app.services.bigcommerce_client import BigCommerceClient
from app.utils.encryption import decrypt_token

logger = logging.getLogger(__name__)


class ProductSyncService:
    """Service for synchronizing products with Affilync."""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.api_client = AffilyncAPIClient(
            api_url=settings.affilync_api_url,
            api_key=settings.affilync_api_key,
            source="bigcommerce-app",
        )

    async def sync_product_from_webhook(
        self,
        store: BigCommerceStore,
        payload: dict,
    ) -> BigCommerceProduct:
        """
        Sync a product from a webhook payload.

        Args:
            store: Store record
            payload: BigCommerce webhook payload

        Returns:
            BigCommerceProduct: Synced product
        """
        # Webhook payload contains product data
        product_data = payload.get("data", payload)
        product_id = product_data.get("id")

        # Check if product exists
        existing = await self._get_product_by_bc_id(store.id, product_id)

        if existing:
            # Update existing product
            existing = await self._update_product_from_data(existing, product_data)
        else:
            # Create new product
            existing = BigCommerceProduct.from_bigcommerce_data(store.id, product_data)
            self.db.add(existing)

        await self.db.commit()
        await self.db.refresh(existing)

        # Sync to Affilync if store is connected and auto-sync is enabled
        if store.brand_id and store.auto_sync_products:
            await self._sync_to_affilync(store, existing)

        return existing

    async def delete_product_from_webhook(
        self,
        store: BigCommerceStore,
        payload: dict,
    ) -> bool:
        """
        Delete a product from a webhook payload.

        Args:
            store: Store record
            payload: BigCommerce webhook payload

        Returns:
            bool: True if product was deleted
        """
        product_data = payload.get("data", payload)
        product_id = product_data.get("id")

        product = await self._get_product_by_bc_id(store.id, product_id)

        if not product:
            logger.warning(f"Product not found for deletion: {product_id}")
            return False

        # Delete from Affilync if synced
        if product.affilync_product_id and store.brand_id:
            try:
                await self.api_client.delete_product(
                    brand_id=str(store.brand_id),
                    product_id=str(product.affilync_product_id),
                )
            except Exception as e:
                logger.warning(f"Failed to delete product from Affilync: {e}")

        # Delete from local database
        await self.db.delete(product)
        await self.db.commit()

        logger.info(f"Product deleted: {product_id}")
        return True

    async def sync_all_products(
        self,
        store: BigCommerceStore,
        force: bool = False,
    ) -> dict:
        """
        Sync all products from BigCommerce to local database and Affilync.

        Args:
            store: Store record
            force: Force re-sync all products

        Returns:
            dict: Sync statistics
        """
        logger.info(f"Starting full product sync for store {store.store_hash}")

        access_token = decrypt_token(store.access_token)

        async with BigCommerceClient(store.store_hash, access_token) as client:
            # Fetch all products from BigCommerce
            bc_products = await client.get_all_products(
                include=["images", "custom_fields"],
                is_visible=True,
            )

        stats = {
            "total": len(bc_products),
            "created": 0,
            "updated": 0,
            "synced_to_affilync": 0,
            "errors": [],
        }

        for bc_product in bc_products:
            try:
                product_id = bc_product.get("id")
                existing = await self._get_product_by_bc_id(store.id, product_id)

                if existing:
                    existing = await self._update_product_from_data(existing, bc_product)
                    stats["updated"] += 1
                else:
                    existing = BigCommerceProduct.from_bigcommerce_data(store.id, bc_product)
                    self.db.add(existing)
                    stats["created"] += 1

                await self.db.commit()
                await self.db.refresh(existing)

                # Sync to Affilync if connected
                if store.brand_id:
                    try:
                        await self._sync_to_affilync(store, existing)
                        stats["synced_to_affilync"] += 1
                    except Exception as e:
                        stats["errors"].append({
                            "product_id": product_id,
                            "error": str(e),
                        })

            except Exception as e:
                logger.error(f"Error syncing product {bc_product.get('id')}: {e}")
                stats["errors"].append({
                    "product_id": bc_product.get("id"),
                    "error": str(e),
                })

        logger.info(f"Product sync complete: {stats}")
        return stats

    async def _get_product_by_bc_id(
        self,
        store_id: UUID,
        bc_product_id: int,
    ) -> Optional[BigCommerceProduct]:
        """Get product by BigCommerce product ID."""
        result = await self.db.execute(
            select(BigCommerceProduct).where(
                BigCommerceProduct.store_id == store_id,
                BigCommerceProduct.bc_product_id == bc_product_id,
            )
        )
        return result.scalar_one_or_none()

    async def _update_product_from_data(
        self,
        product: BigCommerceProduct,
        bc_data: dict,
    ) -> BigCommerceProduct:
        """Update existing product from BigCommerce data."""
        # Get primary image
        images = bc_data.get("images", [])
        primary_image = None
        for img in images:
            if img.get("is_thumbnail"):
                primary_image = img.get("url_standard")
                break
        if not primary_image and images:
            primary_image = images[0].get("url_standard")

        product.sku = bc_data.get("sku")
        product.title = bc_data.get("name")
        product.description = bc_data.get("description")
        product.handle = bc_data.get("custom_url", {}).get("url", "").strip("/")
        product.price = bc_data.get("price")
        product.compare_at_price = bc_data.get("sale_price")
        product.cost_price = bc_data.get("cost_price")
        product.image_url = primary_image
        product.images = [{"url": img.get("url_standard"), "is_thumbnail": img.get("is_thumbnail")}
                         for img in images]
        product.categories = bc_data.get("categories", [])
        product.brand_name = bc_data.get("brand_name")
        product.inventory_level = bc_data.get("inventory_level")
        product.is_visible = bc_data.get("is_visible", True)
        product.updated_at = datetime.utcnow()

        return product

    async def _sync_to_affilync(
        self,
        store: BigCommerceStore,
        product: BigCommerceProduct,
    ) -> None:
        """
        Sync a product to Affilync.

        Args:
            store: Store record
            product: Product to sync
        """
        try:
            sync_data = ProductSyncData(
                brand_id=str(store.brand_id),
                external_product_id=f"bigcommerce_{product.bc_product_id}",
                source="bigcommerce",
                title=product.title,
                description=product.description,
                price=product.price,
                currency=product.currency,
                image_url=product.image_url,
                product_url=product.product_url,
                metadata={
                    "store_hash": store.store_hash,
                    "sku": product.sku,
                    "categories": product.categories,
                    "brand_name": product.brand_name,
                },
            )

            result = await self.api_client.sync_product(sync_data)
            product.mark_synced(result.get("affilync_product_id"))

            await self.db.commit()
            logger.debug(f"Product synced to Affilync: {product.bc_product_id}")

        except Exception as e:
            product.mark_sync_error(str(e))
            await self.db.commit()
            logger.error(f"Failed to sync product to Affilync: {e}")
            raise

    async def get_store_products(
        self,
        store_id: UUID,
        limit: int = 50,
        offset: int = 0,
        synced_only: bool = False,
    ) -> tuple[List[BigCommerceProduct], int]:
        """
        Get products for a store.

        Args:
            store_id: Store ID
            limit: Max products to return
            offset: Pagination offset
            synced_only: Only return synced products

        Returns:
            Tuple of (products, total_count)
        """
        query = select(BigCommerceProduct).where(
            BigCommerceProduct.store_id == store_id
        )

        if synced_only:
            query = query.where(BigCommerceProduct.is_synced == True)

        # Get total count
        from sqlalchemy import func

        count_result = await self.db.execute(
            select(func.count(BigCommerceProduct.id)).where(
                BigCommerceProduct.store_id == store_id,
                BigCommerceProduct.is_synced == True if synced_only else True,
            )
        )
        total = count_result.scalar() or 0

        # Get paginated results
        query = query.order_by(BigCommerceProduct.title).limit(limit).offset(offset)
        result = await self.db.execute(query)
        products = result.scalars().all()

        return products, total
