import uuid
from datetime import datetime, timezone
from typing import List, TYPE_CHECKING, Optional
from sqlalchemy import DateTime, ForeignKey, Index, String, Enum as SQLEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.enums import ProcessingStatus

if TYPE_CHECKING:
    from app.models.event import Event
    from app.models.face import FaceEmbedding


class Photo(Base):
    __tablename__ = "photos"

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
    r2_object_key: Mapped[str] = mapped_column(String(512), nullable=False, unique=True)
    thumbnail_key: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    uploaded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    processing_status: Mapped[ProcessingStatus] = mapped_column(
        SQLEnum(
            ProcessingStatus,
            name="processing_status_enum",
            native_enum=True,
            values_callable=lambda enum_cls: [e.value for e in enum_cls],
        ),
        default=ProcessingStatus.PENDING,
        nullable=False,
        index=True,
    )

    # Relationships
    event: Mapped["Event"] = relationship("Event", back_populates="photos")
    faces: Mapped[List["FaceEmbedding"]] = relationship(
        "FaceEmbedding",
        back_populates="photo",
        cascade="all, delete-orphan",
    )
