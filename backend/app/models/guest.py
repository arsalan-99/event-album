import uuid
from datetime import datetime, timezone
from typing import List, Optional, TYPE_CHECKING
from pgvector.sqlalchemy import Vector
from sqlalchemy import DateTime, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

if TYPE_CHECKING:
    from app.models.event import Event


class Guest(Base):
    __tablename__ = "guests"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )
    event_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("events.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    # Relationships
    event: Mapped["Event"] = relationship("Event", back_populates="guests")
    embeddings: Mapped[List["GuestEmbedding"]] = relationship(
        "GuestEmbedding",
        back_populates="guest",
        cascade="all, delete-orphan",
    )


class GuestEmbedding(Base):
    """Supports 2-3 selfie embeddings per guest, averaged at query time."""
    __tablename__ = "guest_embeddings"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )
    guest_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("guests.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # 128-dimensional vector embedding for SFace
    embedding = mapped_column(Vector(128), nullable=False)

    # STACK LOCK: model_name and model_version required on all embedding tables
    model_name: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    model_version: Mapped[str] = mapped_column(String(50), nullable=False, index=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    # Relationship
    guest: Mapped["Guest"] = relationship("Guest", back_populates="embeddings")

    __table_args__ = (
        Index(
            "ix_guest_embeddings_embedding_hnsw",
            embedding,
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
        Index(
            "ix_guest_embeddings_model_version",
            "model_name",
            "model_version",
        ),
    )
