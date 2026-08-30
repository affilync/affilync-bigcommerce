"""
BigCommerce Subscription model for billing/plan management.

Ported from the TikTok Shop integration (tiktok_subscriptions) so the two
e-commerce integrations share an identical plan ladder and billing mechanism.
Subscriptions are keyed to the BigCommerce store (the same UUID primary key
that products and webhook logs link to), NOT to TikTok's shop id.
"""

from datetime import datetime
from uuid import uuid4

from app.database import Base
from sqlalchemy import Column, DateTime, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import UUID

from app.models._types import JSONB
from sqlalchemy.orm import relationship


class BigCommerceSubscription(Base):
    """Subscription record for a BigCommerce store."""

    __tablename__ = "bigcommerce_subscriptions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)

    # Foreign key to store (UUID PK of bigcommerce_stores, same as products link)
    store_id = Column(
        UUID(as_uuid=True),
        ForeignKey("bigcommerce_stores.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )

    # Plan info
    plan = Column(String(50), nullable=False, default="free")  # free, starter, pro, enterprise
    status = Column(String(50), nullable=False, default="active")  # active, cancelled, grace_period
    previous_plan = Column(String(50), nullable=True)

    # Pricing
    price_cents = Column(Integer, default=0)  # Monthly price in cents
    currency = Column(String(10), default="USD")

    # Trial
    trial_days = Column(Integer, default=0)
    trial_ends_at = Column(DateTime(timezone=True), nullable=True)

    # Billing period
    current_period_start = Column(DateTime(timezone=True), nullable=True)
    current_period_end = Column(DateTime(timezone=True), nullable=True)

    # Grace period
    grace_period_ends = Column(DateTime(timezone=True), nullable=True)
    downgrade_reason = Column(String(100), nullable=True)

    # Usage tracking
    conversions_used = Column(Integer, default=0)
    creators_used = Column(Integer, default=0)
    products_synced = Column(Integer, default=0)

    # Metadata
    cancelled_at = Column(DateTime(timezone=True), nullable=True)
    plan_metadata = Column("metadata", JSONB, default=dict)

    # Timestamps
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at = Column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    store = relationship("BigCommerceStore", backref="subscription")

    def __repr__(self):
        return f"<BigCommerceSubscription {self.plan} ({self.status})>"

    def to_dict(self):
        """Convert to dictionary for API responses."""
        return {
            "id": str(self.id),
            "store_id": str(self.store_id),
            "plan": self.plan,
            "status": self.status,
            "previous_plan": self.previous_plan,
            "price_cents": self.price_cents,
            "currency": self.currency,
            "trial_days": self.trial_days,
            "trial_ends_at": self.trial_ends_at.isoformat() if self.trial_ends_at else None,
            "current_period_start": (
                self.current_period_start.isoformat() if self.current_period_start else None
            ),
            "current_period_end": (
                self.current_period_end.isoformat() if self.current_period_end else None
            ),
            "grace_period_ends": (
                self.grace_period_ends.isoformat() if self.grace_period_ends else None
            ),
            "conversions_used": self.conversions_used,
            "creators_used": self.creators_used,
            "products_synced": self.products_synced,
            "cancelled_at": self.cancelled_at.isoformat() if self.cancelled_at else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
