import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Dict, Any, List
from pgvector.sqlalchemy import Vector
from sqlalchemy import Boolean, DateTime, ForeignKey, Index, JSON, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

if TYPE_CHECKING:
    from app.models.photo import Photo


class FaceEmbedding(Base):
    __tablename__ = "face_embeddings"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )
    photo_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("photos.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # 128-dimensional vector embedding for SFace
    embedding = mapped_column(Vector(128), nullable=False)

    # Bounding box & landmark metadata JSON (e.g., {"x": ..., "y": ..., "w": ..., "h": ..., "landmarks": ...})
    bbox_json: Mapped[Dict[str, Any]] = mapped_column(JSON, nullable=False)

    # STACK LOCK: Every embedding row stored in DB MUST record model_name and model_version
    model_name: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    model_version: Mapped[str] = mapped_column(String(50), nullable=False, index=True)

    is_low_quality: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    # Relationship
    photo: Mapped["Photo"] = relationship("Photo", back_populates="faces")

    __table_args__ = (
        Index(
            "ix_face_embeddings_embedding_hnsw",
            embedding,
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
        Index(
            "ix_face_embeddings_model_version",
            "model_name",
            "model_version",
        ),
    )
