import io
import logging
import time
import uuid
from datetime import datetime, timezone
from typing import Optional, Tuple
import cv2
import numpy as np
from PIL import Image, UnidentifiedImageError
from sqlalchemy import delete, insert, select, update
from botocore.exceptions import BotoCoreError, ClientError
from celery.signals import worker_process_init

from app.core.celery_app import celery_app
from app.core.config import settings
from app.core.database import get_sync_db, sync_engine
from app.models import FaceEmbedding, Photo, ProcessingStatus
from app.services.face import FaceEmbedder, get_face_embedder
from app.services.storage import storage_service

logger = logging.getLogger(__name__)

_face_embedder: Optional[FaceEmbedder] = None


@worker_process_init.connect
def on_worker_process_init(**kwargs):
    """Load FaceEmbedder once per worker process and cap OpenCV threads."""
    global _face_embedder
    cv2.setNumThreads(settings.OPENCV_NUM_THREADS)
    t0 = time.perf_counter()
    _face_embedder = get_face_embedder()
    elapsed_ms = (time.perf_counter() - t0) * 1000
    # Clean connection pool so forked processes do not share connections
    sync_engine.dispose(close=False)
    print(
        f"[worker:init] FaceEmbedder loaded in worker process ({elapsed_ms:.1f}ms, threads={cv2.getNumThreads()})",
        flush=True,
    )


def get_worker_embedder() -> Tuple[FaceEmbedder, float]:
    """Return cached FaceEmbedder and elapsed initialization time (0.0 if already loaded)."""
    global _face_embedder
    if _face_embedder is None:
        t0 = time.perf_counter()
        _face_embedder = get_face_embedder()
        init_ms = (time.perf_counter() - t0) * 1000
        return _face_embedder, init_ms
    return _face_embedder, 0.0


def generate_thumbnail(
    image_bytes: Optional[bytes] = None,
    cv_image: Optional[np.ndarray] = None,
    max_width: int = 800,
) -> Tuple[bytes, str]:
    """Generate an 800px-wide JPEG thumbnail.
    
    If cv_image is provided, resize directly via OpenCV (avoiding a second decode).
    If raw bytes are provided and the image is JPEG, Pillow's draft() mode is used.
    """
    if cv_image is not None:
        h, w = cv_image.shape[:2]
        if w > max_width:
            target_h = int((max_width / w) * h)
            resized = cv2.resize(cv_image, (max_width, target_h), interpolation=cv2.INTER_AREA)
        else:
            resized = cv_image
        success, enc = cv2.imencode(".jpg", resized, [int(cv2.IMWRITE_JPEG_QUALITY), 85])
        if not success:
            raise ValueError("Failed to encode thumbnail image")
        return enc.tobytes(), "image/jpeg"

    if not image_bytes:
        raise ValueError("Either cv_image or image_bytes must be provided")

    with Image.open(io.BytesIO(image_bytes)) as img:
        orig_w, orig_h = img.size
        target_h = int((max_width / orig_w) * orig_h) if orig_w > max_width else orig_h
        target_w = min(orig_w, max_width)

        if getattr(img, "format", "") == "JPEG":
            img.draft("RGB", (target_w, target_h))

        if img.mode in ("RGBA", "P", "LA"):
            img = img.convert("RGB")
        elif img.mode != "RGB":
            img = img.convert("RGB")

        if img.size[0] > max_width:
            img = img.resize((target_w, target_h), Image.Resampling.BILINEAR)

        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=85)
        return buf.getvalue(), "image/jpeg"


TRANSIENT_EXCEPTIONS = (
    BotoCoreError,
    ClientError,
    ConnectionError,
    TimeoutError,
    OSError,
)


def run_photo_pipeline(photo_id: str, is_celery_task: bool = False, task_instance=None) -> dict:
    """Execute photo pipeline with stage-by-stage timing instrumentation and batch DB writes."""
    pipeline_start = time.perf_counter()
    short_id = photo_id[:8]

    with get_sync_db() as session:
        photo = session.scalar(select(Photo).where(Photo.id == photo_id))
        if not photo:
            print(f"[photo:error] not found id={short_id}", flush=True)
            return {"status": "error", "message": f"Photo {photo_id} not found"}

        photo.processing_status = ProcessingStatus.PROCESSING
        session.commit()
        r2_object_key = photo.r2_object_key
        event_id = photo.event_id

    try:
        # 1. Model init / retrieve
        embedder, model_init_ms = get_worker_embedder()

        # 2. Download from R2
        t0 = time.perf_counter()
        try:
            image_bytes = storage_service.download_file_bytes(r2_object_key)
        except TRANSIENT_EXCEPTIONS as exc:
            retry_count = getattr(task_instance.request, "retries", 0) if (task_instance and hasattr(task_instance, "request")) else 0
            print(f"[photo:retry] download failed ({retry_count}/3): {exc}", flush=True)
            if task_instance and hasattr(task_instance, "retry"):
                raise task_instance.retry(exc=exc, countdown=2 ** retry_count)
            raise
        r2_download_ms = (time.perf_counter() - t0) * 1000

        # 3. Decode image (once)
        t0 = time.perf_counter()
        np_arr = np.frombuffer(image_bytes, np.uint8)
        cv_image = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
        if cv_image is None:
            raise ValueError("corrupt image")
        decode_ms = (time.perf_counter() - t0) * 1000

        # 4. Thumbnail generation (reusing decoded cv_image)
        t0 = time.perf_counter()
        thumbnail_bytes, thumb_mime = generate_thumbnail(cv_image=cv_image, max_width=800)
        thumb_gen_ms = (time.perf_counter() - t0) * 1000

        # 5. Thumbnail upload to R2
        t0 = time.perf_counter()
        thumbnail_key = f"thumbnails/{event_id}/{photo_id}.jpg"
        storage_service.upload_file_bytes(thumbnail_bytes, thumbnail_key, content_type=thumb_mime)
        thumb_upload_ms = (time.perf_counter() - t0) * 1000

        # 6. Face detection (downscaled to <= 1280px, rescaled to original coords)
        t0 = time.perf_counter()
        detections = embedder.detect(cv_image, max_edge=settings.DETECTION_MAX_EDGE)
        yunet_detect_ms = (time.perf_counter() - t0) * 1000

        # 7. SFace embedding on original full-resolution image per face
        t0 = time.perf_counter()
        embeddings = []
        for det in detections:
            embedding_vec = embedder.embed(cv_image, det)
            embeddings.append(embedding_vec)
        sface_embed_total_ms = (time.perf_counter() - t0) * 1000
        sface_embed_per_face_ms = (sface_embed_total_ms / len(detections)) if detections else 0.0

        # 8. Batch Database write
        face_embeddings_data = [
            {
                "id": str(uuid.uuid4()),
                "photo_id": photo_id,
                "embedding": emb_vec.tolist(),
                "bbox_json": {
                    "bbox": list(det.bbox),
                    "landmarks": det.landmarks.tolist(),
                    "confidence": float(det.confidence),
                },
                "model_name": embedder.model_name,
                "model_version": embedder.model_version,
                "is_low_quality": det.low_quality,
                "created_at": datetime.now(timezone.utc),
            }
            for det, emb_vec in zip(detections, embeddings)
        ]

        t0 = time.perf_counter()
        with get_sync_db() as session:
            session.execute(delete(FaceEmbedding).where(FaceEmbedding.photo_id == photo_id))
            if face_embeddings_data:
                session.execute(insert(FaceEmbedding), face_embeddings_data)
            session.execute(
                update(Photo)
                .where(Photo.id == photo_id)
                .values(thumbnail_key=thumbnail_key, processing_status=ProcessingStatus.DONE)
            )
            session.commit()
        db_insert_ms = (time.perf_counter() - t0) * 1000

        total_task_ms = (time.perf_counter() - pipeline_start) * 1000

        # Structured timing log line
        print(
            f"[TIMING:photo] id={short_id} total_ms={total_task_ms:.1f} model_init_ms={model_init_ms:.1f} "
            f"r2_download_ms={r2_download_ms:.1f} decode_ms={decode_ms:.1f} "
            f"yunet_detect_ms={yunet_detect_ms:.1f} sface_embed_total_ms={sface_embed_total_ms:.1f} "
            f"sface_embed_per_face_ms={sface_embed_per_face_ms:.1f} thumb_gen_ms={thumb_gen_ms:.1f} "
            f"thumb_upload_ms={thumb_upload_ms:.1f} db_insert_ms={db_insert_ms:.1f} faces_count={len(detections)}",
            flush=True,
        )

        return {
            "status": "done",
            "photo_id": photo_id,
            "faces_count": len(detections),
            "thumbnail_key": thumbnail_key,
            "elapsed_ms": round(total_task_ms, 2),
        }

    except (UnidentifiedImageError, ValueError) as corrupt_err:
        print(f"[photo:error] corrupt image id={short_id}: {corrupt_err}", flush=True)
        with get_sync_db() as session:
            p = session.scalar(select(Photo).where(Photo.id == photo_id))
            if p:
                p.processing_status = ProcessingStatus.FAILED
                session.commit()
        return {"status": "failed", "error": str(corrupt_err)}

    except Exception as exc:
        retries = getattr(task_instance.request, "retries", 0) if (task_instance and hasattr(task_instance, "request")) else 0
        max_retries = getattr(task_instance, "max_retries", 3) if task_instance else 0
        if retries >= max_retries:
            print(f"[photo:fail] id={short_id} error: {exc}", flush=True)
            with get_sync_db() as session:
                p = session.scalar(select(Photo).where(Photo.id == photo_id))
                if p:
                    p.processing_status = ProcessingStatus.FAILED
                    session.commit()
            return {"status": "failed", "error": str(exc)}
        print(f"[photo:retry] id={short_id} error: {exc}", flush=True)
        raise


@celery_app.task(bind=True, max_retries=3, name="process_photo")
def process_photo(self, photo_id: str):
    return run_photo_pipeline(photo_id, is_celery_task=True, task_instance=self)
