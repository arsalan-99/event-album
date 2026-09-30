from typing import List, Optional
from pydantic import BaseModel, Field


class GuestEnrollResponse(BaseModel):
    guest_id: str
    event_id: str
    name: Optional[str] = None
    embeddings_count: int
    message: str = "Guest enrolled successfully. Raw selfies discarded per privacy policy."


class PhotoMatchItem(BaseModel):
    photo_id: str
    similarity: float = Field(..., description="Cosine similarity score (0.0 to 1.0)")
    r2_object_key: Optional[str] = None
    thumbnail_url: Optional[str] = None
    photo_url: Optional[str] = None


class GuestMatchResponse(BaseModel):
    guest_id: str
    event_id: str
    match_threshold: float
    matches_count: int
    matches: List[PhotoMatchItem]
