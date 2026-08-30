"""
BigCommerceWebhookLog Model - Webhook event logging
"""

from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import Column, DateTime, ForeignKey, Index, Integer, String, Text, text
from sqlalchemy.dialects.postgresql import UUID

from app.models._types import JSONB
from sqlalchemy.orm import relationship

from app.database import Base


class BigCommerceWebhookLog(Base):
    """
    Logs incoming webhooks from BigCommerce for debugging and auditing.
    """

    __tablename__ = "bigcommerce_webhook_logs"
    # Atomic dedup (migration 002): a partial unique index over (store_id, hash)
    # makes duplicate-webhook rejection race-proof and Redis-outage-proof. Only
    # non-null hashes are constrained (legacy/un-hashed rows are exempt).
    __table_args__ = (
        Index(
            "uq_bc_webhook_logs_store_hash",
            "store_id",
            "hash",
            unique=True,
            postgresql_where=text("hash IS NOT NULL"),
        ),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)

    # Store relationship
    store_id = Column(
        UUID(as_uuid=True),
        ForeignKey("bigcommerce_stores.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Webhook details
    scope = Column(String(100), nullable=False, index=True)  # e.g., "store/order/created"
    webhook_id = Column(String(255), index=True)  # BigCommerce webhook ID
    hash = Column(String(64), index=True)  # Event hash for deduplication

    # Payload
    payload = Column(JSONB, nullable=False)

    # Processing status
    status = Column(String(50), default="received", index=True)
    result = Column(JSONB)
    error = Column(Text)
    processing_time_ms = Column(Integer)

    # Timestamps
    received_at = Column(DateTime, default=lambda: datetime.now(UTC))
    processed_at = Column(DateTime)

    # Relationships
    store = relationship("BigCommerceStore", back_populates="webhook_logs")

    def __repr__(self) -> str:
        return f"<BigCommerceWebhookLog {self.scope} - {self.status}>"

    def mark_processed(self, result: dict = None) -> None:
        """Mark webhook as successfully processed."""
        self.status = "success"
        self.result = result
        self.processed_at = datetime.now(UTC)

    def mark_failed(self, error: str) -> None:
        """Mark webhook as failed."""
        self.status = "failed"
        self.error = error
        self.processed_at = datetime.now(UTC)

    def set_processing_time(self, start_time: datetime) -> None:
        """Calculate and set processing time."""
        if start_time:
            delta = datetime.now(UTC) - start_time
            self.processing_time_ms = int(delta.total_seconds() * 1000)
