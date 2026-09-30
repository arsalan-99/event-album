import os
import time
import uuid
import logging
from typing import List, Optional
import cv2
import numpy as np
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.models import Event, FaceEmbedding, Guest, GuestEmbedding, Photo
from app.schemas.guest import GuestEnrollResponse, GuestMatchResponse, PhotoMatchItem
from app.services.face import get_face_embedder
from app.services.storage import storage_service

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Guests"])

# Shared face embedder instance
_embedder = None


def get_embedder():
    global _embedder
    if _embedder is None:
        _embedder = get_face_embedder()
    return _embedder


@router.post("/events/{event_id}/guests/enroll", response_model=GuestEnrollResponse)
async def enroll_guest(
    event_id: str,
    files: List[UploadFile] = File(..., description="1-3 selfie images for enrollment"),
    name: Optional[str] = Form(None, description="Optional guest name"),
    guest_id: Optional[str] = Form(None, description="Optional existing guest ID"),
    db: AsyncSession = Depends(get_db),
):
    """
    Enroll a guest by uploading 1-3 selfie images.
    - Embeds each selfie via YuNet (detection) + SFace (recognition).
    - Stores 128-d vector embeddings in guest_embeddings.
    - PRIVACY REQUIREMENT: Raw selfie bytes are processed strictly in-memory and
      IMMEDIATELY discarded. Never stored in R2, DB, or disk.
    """
    if not (1 <= len(files) <= 3):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Must provide between 1 and 3 selfie images for enrollment.",
        )

    # 1. Verify Event exists
    event = await db.scalar(select(Event).where(Event.id == event_id))
    if not event:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Event {event_id} not found",
        )

    # 2. Get or create Guest
    if guest_id:
        guest = await db.scalar(select(Guest).where(Guest.id == guest_id, Guest.event_id == event_id))
        if not guest:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Guest {guest_id} not found in this event",
            )
        if name and not guest.name:
            guest.name = name
    else:
        guest_id = str(uuid.uuid4())
        guest = Guest(
            id=guest_id,
            event_id=event_id,
            name=name,
        )
        db.add(guest)

    embedder = get_embedder()
    embeddings_to_save: List[List[float]] = []

    # 3. Process each selfie strictly in memory
    for idx, upload_file in enumerate(files):
        raw_bytes = await upload_file.read()
        if not raw_bytes:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"File {upload_file.filename} is empty",
            )

        # Decode image from memory
        np_arr = np.frombuffer(raw_bytes, np.uint8)
        # Immediately dereference raw byte string
        del raw_bytes

        cv_image = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
        del np_arr

        if cv_image is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Selfie {upload_file.filename} is corrupt or an unsupported image format.",
            )

        try:
            detections = embedder.detect(cv_image)
            if not detections:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"No face detected in selfie #{idx+1} ({upload_file.filename}). Please provide a clear, front-facing selfie.",
                )

            # Pick highest confidence detection
            best_det = max(detections, key=lambda d: d.confidence)
            embedding_vec = embedder.embed(cv_image, best_det)

            # Normalize to unit vector
            norm = np.linalg.norm(embedding_vec)
            if norm > 0:
                embedding_vec = embedding_vec / norm

            embeddings_to_save.append(embedding_vec.tolist())
        finally:
            # Hard privacy guarantee: explicitly dereference and delete raw image array from memory
            del cv_image

    # 4. Save embeddings into DB
    for emb_vec in embeddings_to_save:
        g_emb = GuestEmbedding(
            id=str(uuid.uuid4()),
            guest_id=guest_id,
            embedding=emb_vec,
            model_name=embedder.model_name,
            model_version=embedder.model_version,
        )
        db.add(g_emb)

    await db.commit()
    await db.refresh(guest)

    logger.info(f"Enrolled guest {guest_id} with {len(embeddings_to_save)} embeddings for event {event_id}")

    return GuestEnrollResponse(
        guest_id=guest.id,
        event_id=event_id,
        name=guest.name,
        embeddings_count=len(embeddings_to_save),
        message="Guest enrolled successfully. Raw selfies discarded per privacy policy.",
    )


@router.post("/events/{event_id}/guests/{guest_id}/match", response_model=GuestMatchResponse)
async def match_guest_photos(
    event_id: str,
    guest_id: str,
    top_n: Optional[int] = None,
    db: AsyncSession = Depends(get_db),
):
    """
    Match photos containing the guest:
    1. Averages guest's stored embeddings into a single query vector.
    2. Runs pgvector cosine distance (<=>) search against event face_embeddings.
    3. Groups by photo, filters by MATCH_THRESHOLD (dynamic env var), and ranks by similarity.
    4. Limits to top N results (default settings.TOP_N_MATCHES).
    5. Generates short-lived presigned GET URLs for matched photos and thumbnails.
    """
    match_start = time.perf_counter()

    # 1. Verify Event and Guest
    event = await db.scalar(select(Event).where(Event.id == event_id))
    if not event:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Event {event_id} not found",
        )

    guest = await db.scalar(select(Guest).where(Guest.id == guest_id, Guest.event_id == event_id))
    if not guest:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Guest {guest_id} not found in event {event_id}",
        )

    # 2. Fetch all embeddings for guest
    guest_embeddings_rows = (
        await db.scalars(select(GuestEmbedding).where(GuestEmbedding.guest_id == guest_id))
    ).all()

    if not guest_embeddings_rows:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Guest {guest_id} has no enrolled face embeddings.",
        )

    # 3. Average guest embeddings and re-normalize to unit vector
    t_mod0 = time.perf_counter()
    embedder = get_embedder()
    model_init_ms = (time.perf_counter() - t_mod0) * 1000

    t_emb0 = time.perf_counter()
    target_model = embedder.model_name
    target_version = embedder.model_version

    vectors = [
        np.array(ge.embedding, dtype=np.float32)
        for ge in guest_embeddings_rows
        if ge.model_name == target_model and ge.model_version == target_version
    ]
    if not vectors:
        # Fallback to all vectors if model version changed
        vectors = [np.array(ge.embedding, dtype=np.float32) for ge in guest_embeddings_rows]

    avg_vec = np.mean(vectors, axis=0)
    norm = np.linalg.norm(avg_vec)
    if norm > 0:
        avg_vec = avg_vec / norm
    avg_vec_list = avg_vec.tolist()
    embed_ms = (time.perf_counter() - t_emb0) * 1000

    # 4. Dynamic MATCH_THRESHOLD from environment
    threshold_str = os.getenv("MATCH_THRESHOLD", str(settings.MATCH_THRESHOLD))
    try:
        match_threshold = float(threshold_str)
    except ValueError:
        match_threshold = 0.50

    # Max cosine distance = 1.0 - match_threshold
    max_distance = 1.0 - match_threshold

    # 5. Query event photos using pgvector <=> cosine distance operator
    limit_count = top_n or settings.TOP_N_MATCHES or 50
    t_db0 = time.perf_counter()
    cosine_dist_expr = FaceEmbedding.embedding.cosine_distance(avg_vec_list)

    query = (
        select(
            Photo.id.label("photo_id"),
            Photo.r2_object_key,
            Photo.thumbnail_key,
            func.min(cosine_dist_expr).label("min_dist"),
        )
        .join(FaceEmbedding, FaceEmbedding.photo_id == Photo.id)
        .where(Photo.event_id == event_id)
        .where(FaceEmbedding.model_name == target_model)
        .where(FaceEmbedding.model_version == target_version)
        .group_by(Photo.id, Photo.r2_object_key, Photo.thumbnail_key)
        .having(func.min(cosine_dist_expr) <= max_distance)
        .order_by(func.min(cosine_dist_expr).asc())
        .limit(limit_count)
    )

    result = await db.execute(query)
    rows = result.all()
    db_query_ms = (time.perf_counter() - t_db0) * 1000

    # 6. Build response with presigned URLs and similarity scores
    matches: List[PhotoMatchItem] = []
    for r in rows:
        # Cosine similarity = 1.0 - cosine_distance for normalized vectors
        similarity = float(np.clip(1.0 - r.min_dist, 0.0, 1.0))

        # Generate private presigned GET URLs
        photo_url = storage_service.generate_presigned_get_url(r.r2_object_key, expires_in=3600)
        thumb_url = None
        if r.thumbnail_key:
            thumb_url = storage_service.generate_presigned_get_url(r.thumbnail_key, expires_in=3600)

        matches.append(
            PhotoMatchItem(
                photo_id=r.photo_id,
                similarity=round(similarity, 4),
                r2_object_key=r.r2_object_key,
                thumbnail_url=thumb_url,
                photo_url=photo_url,
            )
        )

    total_ms = (time.perf_counter() - match_start) * 1000

    # Structured timing log line
    print(
        f"[TIMING:match] guest_id={guest_id[:8]} event_id={event_id[:8]} total_ms={total_ms:.1f} "
        f"model_init_ms={model_init_ms:.1f} embed_ms={embed_ms:.1f} "
        f"db_query_ms={db_query_ms:.1f} matches_count={len(matches)}",
        flush=True,
    )

    return GuestMatchResponse(
        guest_id=guest_id,
        event_id=event_id,
        match_threshold=match_threshold,
        matches_count=len(matches),
        matches=matches,
    )
