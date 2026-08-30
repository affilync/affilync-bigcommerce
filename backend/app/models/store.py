"""
BigCommerceStore Model - Store installation data
"""

from datetime import datetime
from typing import Optional
from uuid import uuid4

from sqlalchemy import Boolean, Column, DateTime, String, Text
from sqlalchemy.dialects.postgresql import UUID

from app.models._types import JSONB
from sqlalchemy.orm import relationship

from app.database import Base


class BigCommerceStore(Base):
    """
    Represents a BigCommerce store that has installed the Affilync app.
    Stores OAuth credentials and links to the Affilync brand account.
    """

    __tablename__ = "bigcommerce_stores"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)

    # BigCommerce identifiers
    store_hash = Column(String(50), unique=True, nullable=False, index=True)
    store_name = Column(String(255))
    store_email = Column(String(255))
    store_domain = Column(String(255))

    # OAuth tokens
    access_token = Column(Text, nullable=False)  # Encrypted
    scope = Column(Text, nullable=False)

    # BigCommerce user who installed
    bc_user_id = Column(String(50), index=True)
    bc_user_email = Column(String(255))

    # Link to Affilync brand account
    brand_id = Column(UUID(as_uuid=True), index=True)

    # Status
    is_active = Column(Boolean, default=True)
    installed_at = Column(DateTime, default=datetime.utcnow)
    uninstalled_at = Column(DateTime, nullable=True)

    # App settings (JSON)
    settings = Column(JSONB, default=dict)

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    products = relationship(
        "BigCommerceProduct",
        back_populates="store",
        cascade="all, delete-orphan",
    )
    webhook_logs = relationship(
        "BigCommerceWebhookLog",
        back_populates="store",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return f"<BigCommerceStore {self.store_hash}>"

    @property
    def is_connected_to_affilync(self) -> bool:
        """Check if store is connected to an Affilync brand account."""
        return self.brand_id is not None

    @property
    def auto_sync_products(self) -> bool:
        """Get auto-sync setting."""
        return (self.settings or {}).get("auto_sync_products", False)

    @property
    def cookie_duration_days(self) -> int:
        """Get attribution cookie duration setting."""
        return (self.settings or {}).get("cookie_duration_days", 30)

    @property
    def attribution_model(self) -> str:
        """Get attribution model setting."""
        return (self.settings or {}).get("attribution_model", "last_click")

    @property
    def api_base_url(self) -> str:
        """Get BigCommerce API base URL for this store."""
        return f"https://api.bigcommerce.com/stores/{self.store_hash}"

    def update_settings(self, **kwargs) -> None:
        """Update settings dictionary."""
        current = self.settings or {}
        current.update(kwargs)
        self.settings = current
