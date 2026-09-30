import uuid
from datetime import datetime, timezone
from typing import List
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models import Event, Photo, Guest
from app.schemas.event import EventCreate, EventResponse
from app.services.storage import storage_service

router = APIRouter(tags=["Events"])


@router.post("/events", response_model=EventResponse, status_code=status.HTTP_201_CREATED)
async def create_event(
    payload: EventCreate,
    db: AsyncSession = Depends(get_db),
):
    """Create a new event."""
    event_id = str(uuid.uuid4())
    owner_id = payload.owner_id or str(uuid.uuid4())

    event = Event(
        id=event_id,
        name=payload.name,
        event_date=payload.event_date,
        owner_id=owner_id,
        created_at=datetime.now(timezone.utc),
    )
    db.add(event)
    await db.commit()
    await db.refresh(event)

    return EventResponse(
        id=event.id,
        name=event.name,
        event_date=event.event_date,
        owner_id=event.owner_id,
        created_at=event.created_at,
        photos_count=0,
        guests_count=0,
    )


@router.get("/events", response_model=List[EventResponse])
async def list_events(
    db: AsyncSession = Depends(get_db),
):
    """List all events ordered by creation date."""
    events = (
        await db.scalars(select(Event).order_by(Event.created_at.desc()))
    ).all()

    items: List[EventResponse] = []
    for ev in events:
        p_count = await db.scalar(
            select(func.count(Photo.id)).where(Photo.event_id == ev.id)
        ) or 0
        g_count = await db.scalar(
            select(func.count(Guest.id)).where(Guest.event_id == ev.id)
        ) or 0
        items.append(
            EventResponse(
                id=ev.id,
                name=ev.name,
                event_date=ev.event_date,
                owner_id=ev.owner_id,
                created_at=ev.created_at,
                photos_count=p_count,
                guests_count=g_count,
            )
        )
    return items


@router.delete("/events/{event_id}", status_code=status.HTTP_200_OK)
async def delete_event(
    event_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Delete event and delete all its photos from R2 and database."""
    event = await db.scalar(select(Event).where(Event.id == event_id))
    if not event:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Event {event_id} not found",
        )

    # Collect all photo keys to delete from R2
    photos = (
        await db.scalars(select(Photo).where(Photo.event_id == event_id))
    ).all()
    keys_to_delete = []
    for p in photos:
        if p.r2_object_key:
            keys_to_delete.append(p.r2_object_key)
        if p.thumbnail_key:
            keys_to_delete.append(p.thumbnail_key)

    if keys_to_delete:
        storage_service.delete_files(keys_to_delete)

    # Deleting event cascades to photos, face_embeddings, guests, guest_embeddings
    await db.delete(event)
    await db.commit()

    print(f"[event:delete] id={event_id[:8]} deleted ({len(photos)} photos removed)", flush=True)
    return {"message": "Event deleted", "event_id": event_id}


@router.get("/events/{event_id}", response_model=EventResponse)
async def get_event(
    event_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Fetch event metadata including photos and guest count."""
    event = await db.scalar(select(Event).where(Event.id == event_id))
    if not event:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Event {event_id} not found",
        )

    photos_count = await db.scalar(
        select(func.count(Photo.id)).where(Photo.event_id == event_id)
    ) or 0

    guests_count = await db.scalar(
        select(func.count(Guest.id)).where(Guest.event_id == event_id)
    ) or 0

    return EventResponse(
        id=event.id,
        name=event.name,
        event_date=event.event_date,
        owner_id=event.owner_id,
        created_at=event.created_at,
        photos_count=photos_count,
        guests_count=guests_count,
    )


@router.get("/events/{event_id}/photos")
async def list_event_photos(
    event_id: str,
    db: AsyncSession = Depends(get_db),
):
    """List photos for event with processing status and presigned URLs."""
    event = await db.scalar(select(Event).where(Event.id == event_id))
    if not event:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Event {event_id} not found",
        )

    photos = (
        await db.scalars(
            select(Photo).where(Photo.event_id == event_id).order_by(Photo.uploaded_at.desc())
        )
    ).all()

    items = []
    for p in photos:
        url = storage_service.generate_presigned_get_url(p.r2_object_key, expires_in=3600)
        thumb_url = (
            storage_service.generate_presigned_get_url(p.thumbnail_key, expires_in=3600)
            if p.thumbnail_key
            else url
        )
        items.append({
            "id": p.id,
            "r2_object_key": p.r2_object_key,
            "processing_status": p.processing_status.value,
            "uploaded_at": p.uploaded_at.isoformat(),
            "url": url,
            "thumbnail_url": thumb_url,
        })

    return {"event_id": event_id, "photos": items}
