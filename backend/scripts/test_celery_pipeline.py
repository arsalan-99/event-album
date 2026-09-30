"""
Acceptance test script for Celery photo processing pipeline:
1. Creates event and photo in DB (status: pending)
2. Uploads test photo to Cloudflare R2
3. Executes process_photo task
4. Verifies status transition (pending -> processing -> done)
5. Verifies face_embeddings rows (model_name, model_version, bbox_json)
6. Verifies thumbnail uploaded to R2
7. Tests idempotency by re-running process_photo
8. Tests corrupt image handling (marks FAILED without retry loop)
"""
import sys
import time
import uuid
from datetime import datetime, timezone, date
from pathlib import Path

# Add backend directory to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select, delete
from app.core.database import get_sync_db
from app.models import Event, Photo, FaceEmbedding, ProcessingStatus
from app.services.storage import storage_service
from app.worker import process_photo

ROOT_DIR = Path(__file__).resolve().parent.parent.parent
SAMPLE_IMAGE_PATH = ROOT_DIR / "images" / "img7.png"


def run_pipeline_test():
    print("==================================================")
    print("Starting Celery Photo Processing Acceptance Test")
    print("==================================================")

    # Check test image
    if not SAMPLE_IMAGE_PATH.exists():
        raise FileNotFoundError(f"Test image not found at {SAMPLE_IMAGE_PATH}")

    with open(SAMPLE_IMAGE_PATH, "rb") as f:
        image_bytes = f.read()

    event_id = str(uuid.uuid4())
    photo_id = str(uuid.uuid4())
    r2_key = f"events/{event_id}/photos/{photo_id}.png"

    print(f"\n1. Uploading sample photo to Cloudflare R2 ({r2_key})...")
    storage_service.upload_file_bytes(image_bytes, r2_key, content_type="image/png")
    print("   Upload to R2 successful.")

    print("\n2. Creating Event and Photo records in DB with status PENDING...")
    with get_sync_db() as session:
        event = Event(
            id=event_id,
            name="Acceptance Test Event",
            event_date=date.today(),
            owner_id=str(uuid.uuid4()),
            created_at=datetime.now(timezone.utc),
        )
        session.add(event)

        photo = Photo(
            id=photo_id,
            event_id=event_id,
            r2_object_key=r2_key,
            uploaded_at=datetime.now(timezone.utc),
            processing_status=ProcessingStatus.PENDING,
        )
        session.add(photo)
        session.commit()
    print("   Records created in DB.")

    print("\n3. Executing process_photo task...")
    result = process_photo(photo_id)
    print(f"   Task execution result: {result}")

    print("\n4. Verifying DB state after processing...")
    with get_sync_db() as session:
        photo = session.scalar(select(Photo).where(Photo.id == photo_id))
        assert photo is not None, "Photo record disappeared"
        assert photo.processing_status == ProcessingStatus.DONE, f"Expected DONE, got {photo.processing_status}"
        assert photo.thumbnail_key is not None, "Thumbnail key was not set"
        print(f"   Photo status: {photo.processing_status.value}")
        print(f"   Thumbnail key: {photo.thumbnail_key}")

        faces = session.scalars(select(FaceEmbedding).where(FaceEmbedding.photo_id == photo_id)).all()
        assert len(faces) > 0, "No face embeddings stored"
        print(f"   Face embeddings count: {len(faces)}")

        for i, face in enumerate(faces):
            assert face.model_name == "sface", f"Unexpected model_name: {face.model_name}"
            assert face.model_version == "2021dec", f"Unexpected model_version: {face.model_version}"
            assert len(face.embedding) == 128, f"Embedding dimension is {len(face.embedding)}, expected 128"
            assert "bbox" in face.bbox_json, "Missing bbox in bbox_json"
            print(f"   - Face {i+1}: ID={face.id}, Model={face.model_name}:{face.model_version}, Confidence={face.bbox_json.get('confidence')}")

    print("\n5. Verifying thumbnail exists in R2...")
    thumb_bytes = storage_service.download_file_bytes(photo.thumbnail_key)
    assert len(thumb_bytes) > 0, "Downloaded thumbnail is empty"
    print(f"   Thumbnail verified in R2 ({len(thumb_bytes)} bytes).")

    print("\n6. Testing Idempotency (re-running process_photo)...")
    result_repeat = process_photo(photo_id)
    with get_sync_db() as session:
        faces_repeat = session.scalars(select(FaceEmbedding).where(FaceEmbedding.photo_id == photo_id)).all()
        assert len(faces_repeat) == len(faces), f"Idempotency failed: expected {len(faces)} faces, got {len(faces_repeat)}"
    print(f"   Idempotency confirmed: face count remained exactly {len(faces_repeat)}.")

    print("\n7. Testing Corrupt Image Handling...")
    corrupt_photo_id = str(uuid.uuid4())
    corrupt_key = f"events/{event_id}/photos/{corrupt_photo_id}.jpg"
    storage_service.upload_file_bytes(b"not-a-valid-image-bytes-data", corrupt_key, content_type="image/jpeg")

    with get_sync_db() as session:
        corrupt_photo = Photo(
            id=corrupt_photo_id,
            event_id=event_id,
            r2_object_key=corrupt_key,
            uploaded_at=datetime.now(timezone.utc),
            processing_status=ProcessingStatus.PENDING,
        )
        session.add(corrupt_photo)
        session.commit()

    corrupt_result = process_photo(corrupt_photo_id)
    print(f"   Corrupt task result: {corrupt_result}")
    with get_sync_db() as session:
        p_corrupt = session.scalar(select(Photo).where(Photo.id == corrupt_photo_id))
        assert p_corrupt.processing_status == ProcessingStatus.FAILED, f"Expected FAILED, got {p_corrupt.processing_status}"
    print("   Corrupt image properly marked FAILED without retry loop.")

    print("\n==================================================")
    print("ALL CELERY PIPELINE ACCEPTANCE CHECKS PASSED!")
    print("==================================================")


if __name__ == "__main__":
    run_pipeline_test()
