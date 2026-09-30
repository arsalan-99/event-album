import uuid
from datetime import datetime, timezone, date
from typing import List, TYPE_CHECKING
from sqlalchemy import Date, DateTime, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

if TYPE_CHECKING:
    from app.models.photo import Photo
    from app.models.guest import Guest


class Event(Base):
    __tablename__ = "events"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    event_date: Mapped[date] = mapped_column(Date, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    owner_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)

    photos: Mapped[List["Photo"]] = relationship(
        "Photo",
        back_populates="event",
        cascade="all, delete-orphan",
    )
    guests: Mapped[List["Guest"]] = relationship(
        "Guest",
        back_populates="event",
        cascade="all, delete-orphan",
    )
