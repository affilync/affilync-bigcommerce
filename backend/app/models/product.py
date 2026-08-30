"""
BigCommerceProduct Model - Synced product data
"""

from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.dialects.postgresql import UUID

from app.models._types import JSONB
from sqlalchemy.orm import relationship

from app.database import Base


class BigCommerceProduct(Base):
    """
    Represents a product synced from BigCommerce to Affilync.
    """

    __tablename__ = "bigcommerce_products"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)

    # Store relationship
    store_id = Column(
        UUID(as_uuid=True),
        ForeignKey("bigcommerce_stores.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # BigCommerce product identifiers
    bc_product_id = Column(Integer, nullable=False, index=True)
    sku = Column(String(255), index=True)

    # Product details
    title = Column(String(500), nullable=False)
    description = Column(Text)
    handle = Column(String(255), index=True)  # URL slug

    # Pricing
    price = Column(Numeric(12, 2))
    compare_at_price = Column(Numeric(12, 2))  # sale_price in BC
    cost_price = Column(Numeric(12, 2))
    currency = Column(String(3), default="USD")

    # Images
    image_url = Column(Text)
    images = Column(JSONB, default=list)

    # Categorization
    categories = Column(JSONB, default=list)  # Category IDs
    brand_name = Column(String(255))

    # Inventory
    inventory_level = Column(Integer)
    inventory_tracking = Column(String(50))  # none, simple, variant

    # Status
    is_visible = Column(Boolean, default=True)
    availability = Column(String(50), default="available")

    # Link to Affilync
    affilync_product_id = Column(UUID(as_uuid=True), index=True)

    # Sync status
    is_synced = Column(Boolean, default=False)
    last_synced_at = Column(DateTime)
    sync_error = Column(Text)

    # Metadata. NOTE: `metadata` is reserved by SQLAlchemy's declarative Base
    # (raises InvalidRequestError at class definition). Map to the existing
    # "metadata" DB column under a non-reserved attribute name.
    product_metadata = Column("metadata", JSONB, default=dict)

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    store = relationship("BigCommerceStore", back_populates="products")

    def __repr__(self) -> str:
        return f"<BigCommerceProduct {self.bc_product_id}: {self.title}>"

    @property
    def product_url(self) -> str:
        """Get product URL on BigCommerce store."""
        if self.store and self.store.store_domain and self.handle:
            return f"https://{self.store.store_domain}/{self.handle}"
        return ""

    def mark_synced(self, affilync_product_id: str = None) -> None:
        """Mark product as successfully synced."""
        self.is_synced = True
        self.last_synced_at = datetime.now(UTC)
        self.sync_error = None
        if affilync_product_id:
            self.affilync_product_id = affilync_product_id

    def mark_sync_error(self, error: str) -> None:
        """Mark product sync as failed."""
        self.is_synced = False
        self.sync_error = error
        self.last_synced_at = datetime.now(UTC)

    @classmethod
    def from_bigcommerce_data(cls, store_id, bc_data: dict) -> "BigCommerceProduct":
        """
        Create a product from BigCommerce API data.

        Args:
            store_id: Store UUID
            bc_data: BigCommerce product data

        Returns:
            BigCommerceProduct instance
        """
        # Get primary image
        images = bc_data.get("images", [])
        primary_image = None
        for img in images:
            if img.get("is_thumbnail"):
                primary_image = img.get("url_standard")
                break
        if not primary_image and images:
            primary_image = images[0].get("url_standard")

        return cls(
            store_id=store_id,
            bc_product_id=bc_data.get("id"),
            sku=bc_data.get("sku"),
            title=bc_data.get("name"),
            description=bc_data.get("description"),
            handle=bc_data.get("custom_url", {}).get("url", "").strip("/"),
            price=bc_data.get("price"),
            compare_at_price=bc_data.get("sale_price"),
            cost_price=bc_data.get("cost_price"),
            image_url=primary_image,
            images=[{"url": img.get("url_standard"), "is_thumbnail": img.get("is_thumbnail")}
                    for img in images],
            categories=bc_data.get("categories", []),
            brand_name=bc_data.get("brand_name"),
            inventory_level=bc_data.get("inventory_level"),
            inventory_tracking=bc_data.get("inventory_tracking"),
            is_visible=bc_data.get("is_visible", True),
            availability=bc_data.get("availability"),
            product_metadata={
                "type": bc_data.get("type"),
                "weight": bc_data.get("weight"),
                "condition": bc_data.get("condition"),
            },
        )
