from typing import List, Optional
from pydantic import BaseModel, Field


class PresignPhotoItem(BaseModel):
    filename: str = Field(..., description="Original filename with extension (e.g. photo.jpg)")
    content_type: str = Field(default="image/jpeg", description="MIME type of the photo")


class PresignRequest(BaseModel):
    files: List[PresignPhotoItem] = Field(..., min_length=1, description="List of files to get presigned upload URLs for")


class PresignedUploadItem(BaseModel):
    photo_id: str
    filename: str
    r2_object_key: str
    upload_url: str
    expires_in_seconds: int = 900


class PresignResponse(BaseModel):
    event_id: str
    items: List[PresignedUploadItem]


class ConfirmPhotoItem(BaseModel):
    photo_id: Optional[str] = None
    r2_object_key: str
    filename: Optional[str] = None


class ConfirmPhotoRequest(BaseModel):
    photos: List[ConfirmPhotoItem] = Field(..., min_length=1, description="List of photos uploaded to confirm and process")


class ConfirmedPhotoItem(BaseModel):
    photo_id: str
    event_id: str
    r2_object_key: str
    processing_status: str
    task_id: Optional[str] = None


class ConfirmResponse(BaseModel):
    confirmed: List[ConfirmedPhotoItem]


class PhotoUrlResponse(BaseModel):
    photo_id: str
    url: str
    thumbnail_url: Optional[str] = None
    expires_in_seconds: int = 3600
