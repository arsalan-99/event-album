from datetime import date, datetime
from typing import Optional
from pydantic import BaseModel, Field


class EventCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    event_date: date = Field(..., description="Date of the event")
    owner_id: Optional[str] = None


class EventResponse(BaseModel):
    id: str
    name: str
    event_date: date
    owner_id: str
    created_at: datetime
    photos_count: int = 0
    guests_count: int = 0
