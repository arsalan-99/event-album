import uuid
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.celery_app import celery_app
from app.core.database import get_db
from app.models import Event, Photo, ProcessingStatus
from app.schemas.photo import (
    PresignRequest,
    PresignResponse,
    PresignedUploadItem,
    ConfirmPhotoRequest,
    ConfirmResponse,
    ConfirmedPhotoItem,
    PhotoUrlResponse,
)
from app.services.storage import storage_service
from app.worker import process_photo, run_photo_pipeline

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Photos"])


import redis
from app.core.config import settings

def is_celery_worker_active() -> bool:
    """Fast check if Redis broker is reachable to enqueue tasks."""
    try:
        r = redis.from_url(settings.REDIS_URL, socket_connect_timeout=0.5, socket_timeout=0.5)
        return bool(r.ping())
    except Exception:
        return False



@router.post("/events/{event_id}/photos/presign", response_model=PresignResponse)
async def get_presigned_upload_urls(
    event_id: str,
    payload: PresignRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Generate 15-minute presigned PUT URLs for direct-to-R2 upload.
    Photos are never proxied through the FastAPI backend.
    """
    # Verify event exists
    event = await db.scalar(select(Event).where(Event.id == event_id))
    if not event:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Event {event_id} not found",
        )

    print(f"[api:presign] {len(payload.files)} file(s)", flush=True)
    items: List[PresignedUploadItem] = []
    for file_item in payload.files:
        photo_id = str(uuid.uuid4())
        suffix = Path(file_item.filename).suffix.lower() or ".jpg"
        r2_key = f"events/{event_id}/photos/{photo_id}{suffix}"

        upload_url = storage_service.generate_presigned_put_url(
            key=r2_key,
            content_type=file_item.content_type,
            expires_in=900,  # 15 minutes
        )

        items.append(
            PresignedUploadItem(
                photo_id=photo_id,
                filename=file_item.filename,
                r2_object_key=r2_key,
                upload_url=upload_url,
                expires_in_seconds=900,
            )
        )

    return PresignResponse(event_id=event_id, items=items)


@router.post("/events/{event_id}/photos/confirm", response_model=ConfirmResponse)
async def confirm_photos_upload(
    event_id: str,
    payload: ConfirmPhotoRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    """
    Confirm that client finished direct PUT to R2.
    Creates photos row with status=pending and dispatches photo processing pipeline.
    """
    event = await db.scalar(select(Event).where(Event.id == event_id))
    if not event:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Event {event_id} not found",
        )

    print(f"[api:confirm] {len(payload.photos)} photo(s)", flush=True)
    celery_active = is_celery_worker_active()
    confirmed_items: List[ConfirmedPhotoItem] = []

    for item in payload.photos:
        photo_id = item.photo_id or str(uuid.uuid4())

        # Check if photo already exists for idempotency
        existing_photo = await db.scalar(select(Photo).where(Photo.r2_object_key == item.r2_object_key))
        if existing_photo:
            photo = existing_photo
            photo_id = photo.id
            photo.processing_status = ProcessingStatus.PENDING
        else:
            photo = Photo(
                id=photo_id,
                event_id=event_id,
                r2_object_key=item.r2_object_key,
                uploaded_at=datetime.now(timezone.utc),
                processing_status=ProcessingStatus.PENDING,
            )
            db.add(photo)

        await db.commit()
        await db.refresh(photo)

        task_id = None
        if celery_active:
            try:
                task_result = process_photo.delay(photo_id)
                task_id = task_result.id
            except Exception as e:
                logger.warning(f"Failed to dispatch to Celery: {e}")
                task_id = None

        if not task_id:
            logger.warning(
                f"[QUEUE WARNING] CELERY UNREACHABLE — falling back to in-process BackgroundTasks "
                f"for photo {photo_id[:8]}, this photo will NOT be processed via the queue!"
            )
            print(
                f"⚠️  [QUEUE WARNING] CELERY UNREACHABLE — falling back to in-process BackgroundTasks "
                f"for photo {photo_id[:8]}, this photo will NOT be processed via the queue!",
                flush=True,
            )
            background_tasks.add_task(run_photo_pipeline, photo_id)
            task_id = f"local-{photo_id[:8]}"

        confirmed_items.append(
            ConfirmedPhotoItem(
                photo_id=photo_id,
                event_id=event_id,
                r2_object_key=photo.r2_object_key,
                processing_status=photo.processing_status.value,
                task_id=task_id,
            )
        )

    return ConfirmResponse(confirmed=confirmed_items)


@router.get("/photos/{photo_id}/url", response_model=PhotoUrlResponse)
async def get_photo_presigned_url(
    photo_id: str,
    db: AsyncSession = Depends(get_db),
):
    """
    Generate short-lived presigned GET URLs for viewing original and thumbnail photos.
    Keeps the R2 bucket private.
    """
    photo = await db.scalar(select(Photo).where(Photo.id == photo_id))
    if not photo:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Photo {photo_id} not found",
        )

    # Generate 1-hour presigned GET URL for photo
    presigned_photo_url = storage_service.generate_presigned_get_url(
        key=photo.r2_object_key,
        expires_in=3600,
    )

    # Generate presigned GET URL for thumbnail if available
    presigned_thumb_url = None
    if photo.thumbnail_key:
        presigned_thumb_url = storage_service.generate_presigned_get_url(
            key=photo.thumbnail_key,
            expires_in=3600,
        )

    return PhotoUrlResponse(
        photo_id=photo.id,
        url=presigned_photo_url,
        thumbnail_url=presigned_thumb_url,
        expires_in_seconds=3600,
    )


@router.delete("/photos/{photo_id}", status_code=status.HTTP_200_OK)
async def delete_photo(
    photo_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Delete a photo, its R2 objects, and associated database records."""
    photo = await db.scalar(select(Photo).where(Photo.id == photo_id))
    if not photo:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Photo {photo_id} not found",
        )

    # Delete R2 files
    keys = [photo.r2_object_key]
    if photo.thumbnail_key:
        keys.append(photo.thumbnail_key)
    storage_service.delete_files(keys)

    # Delete photo row (cascades to face_embeddings in Postgres)
    await db.delete(photo)
    await db.commit()

    print(f"[photo:delete] id={photo_id[:8]} deleted", flush=True)
    return {"message": "Photo deleted", "photo_id": photo_id}

