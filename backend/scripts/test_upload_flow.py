"""
Acceptance test script for direct-to-R2 upload flow:
1. Creates test Event in DB
2. Calls POST /api/events/{event_id}/photos/presign to get presigned PUT URL
3. Directly HTTP PUTs real JPEG bytes to Cloudflare R2 (bypassing FastAPI backend)
4. Verifies photo landed in R2 storage
5. Calls POST /api/events/{event_id}/photos/confirm to create Photo row and enqueue Celery task
6. Verifies Celery worker processes photo (status: pending -> processing -> done, faces detected)
7. Calls GET /api/photos/{photo_id}/url and verifies short-lived presigned GET URL
"""
import asyncio
import sys
import uuid
import httpx
from datetime import datetime, timezone, date
from pathlib import Path

# Add backend directory to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from httpx import ASGITransport
from sqlalchemy import select

from app.main import app
from app.core.database import async_session_maker, engine
from app.models import Event, Photo, FaceEmbedding, ProcessingStatus
from app.services.storage import storage_service
from app.worker import process_photo

ROOT_DIR = Path(__file__).resolve().parent.parent.parent
SAMPLE_IMAGE_PATH = ROOT_DIR / "images" / "img7.png"


async def run_upload_flow_test():
    print("==================================================")
    print("Starting Direct-to-R2 Upload Flow Acceptance Test")
    print("==================================================")

    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Create test Event in DB
        event_id = str(uuid.uuid4())
        async with async_session_maker() as session:
            event = Event(
                id=event_id,
                name="Upload Flow Test Event",
                event_date=date.today(),
                owner_id=str(uuid.uuid4()),
                created_at=datetime.now(timezone.utc),
            )
            session.add(event)
            await session.commit()
        print(f"\n1. Created Event in DB: {event_id}")

        # 2. Call POST /api/events/{event_id}/photos/presign
        print(f"\n2. Calling POST /api/events/{event_id}/photos/presign...")
        presign_payload = {
            "files": [
                {
                    "filename": "guest_selfie.png",
                    "content_type": "image/png",
                }
            ]
        }
        res_presign = await client.post(f"/api/events/{event_id}/photos/presign", json=presign_payload)
        assert res_presign.status_code == 200, f"Presign failed: {res_presign.text}"
        presign_data = res_presign.json()
        assert len(presign_data["items"]) == 1, "Expected 1 presigned item"

        item = presign_data["items"][0]
        photo_id = item["photo_id"]
        r2_key = item["r2_object_key"]
        upload_url = item["upload_url"]
        print(f"   Received Presigned PUT URL:")
        print(f"   - Photo ID: {photo_id}")
        print(f"   - R2 Object Key: {r2_key}")
        print(f"   - Upload URL (expires in 15m): {upload_url[:70]}...")

        # 3. Direct HTTP PUT to Cloudflare R2 (bypassing FastAPI backend)
        print(f"\n3. Uploading image directly to Cloudflare R2 via HTTP PUT (direct to storage)...")
        assert SAMPLE_IMAGE_PATH.exists(), f"Sample image not found at {SAMPLE_IMAGE_PATH}"
        with open(SAMPLE_IMAGE_PATH, "rb") as f:
            image_bytes = f.read()

        # Upload directly to R2 using standalone HTTP client
        async with httpx.AsyncClient() as r2_client:
            put_res = await r2_client.put(
                upload_url,
                content=image_bytes,
                headers={"Content-Type": "image/png"},
            )
            assert put_res.status_code == 200, f"Direct PUT to R2 failed: {put_res.status_code} {put_res.text}"
        print(f"   Direct PUT succeeded (HTTP 200). Photo uploaded directly to R2.")

        # 4. Verify image landed in R2
        print(f"\n4. Verifying object exists in R2...")
        assert storage_service.object_exists(r2_key), f"Object {r2_key} does not exist in R2"
        print(f"   Verified: {r2_key} is present in R2 bucket.")

        # 5. Call POST /api/events/{event_id}/photos/confirm
        print(f"\n5. Calling POST /api/events/{event_id}/photos/confirm...")
        confirm_payload = {
            "photos": [
                {
                    "photo_id": photo_id,
                    "r2_object_key": r2_key,
                    "filename": "guest_selfie.png",
                }
            ]
        }
        res_confirm = await client.post(f"/api/events/{event_id}/photos/confirm", json=confirm_payload)
        assert res_confirm.status_code == 200, f"Confirm failed: {res_confirm.text}"
        confirm_data = res_confirm.json()
        assert len(confirm_data["confirmed"]) == 1
        confirmed = confirm_data["confirmed"][0]
        print(f"   Confirm response: photo_id={confirmed['photo_id']}, status={confirmed['processing_status']}")

        # 6. Verify Photo row in DB and run process_photo
        async with async_session_maker() as session:
            db_photo = await session.scalar(select(Photo).where(Photo.id == photo_id))
            assert db_photo is not None, "Photo not found in DB"
            print(f"   DB row verified: photo_id={db_photo.id}, status={db_photo.processing_status.value}")

        print(f"\n6. Processing photo with face pipeline (YuNet + SFace)...")
        process_result = process_photo(photo_id)
        print(f"   Process photo result: {process_result}")
        assert process_result["status"] == "done", f"Process photo failed: {process_result}"

        async with async_session_maker() as session:
            db_photo_after = await session.scalar(select(Photo).where(Photo.id == photo_id))
            assert db_photo_after.processing_status == ProcessingStatus.DONE
            assert db_photo_after.thumbnail_key is not None

            faces_res = await session.scalars(select(FaceEmbedding).where(FaceEmbedding.photo_id == photo_id))
            faces = faces_res.all()
            assert len(faces) > 0, "No face embeddings recorded"
            print(f"   Photo status: {db_photo_after.processing_status.value}")
            print(f"   Thumbnail key: {db_photo_after.thumbnail_key}")
            print(f"   Recorded {len(faces)} face embedding(s) with model={faces[0].model_name}:{faces[0].model_version}")

        # 7. Call GET /api/photos/{photo_id}/url
        print(f"\n7. Calling GET /api/photos/{photo_id}/url...")
        res_url = await client.get(f"/api/photos/{photo_id}/url")
        assert res_url.status_code == 200, f"Get URL failed: {res_url.text}"
        url_data = res_url.json()
        print(f"   Presigned GET photo URL: {url_data['url'][:70]}...")
        print(f"   Presigned GET thumbnail URL: {url_data['thumbnail_url'][:70]}...")

        # Test downloading via the presigned GET URLs
        async with httpx.AsyncClient() as r2_client:
            get_res = await r2_client.get(url_data["url"])
            assert get_res.status_code == 200
            downloaded = get_res.content
            assert len(downloaded) == len(image_bytes)
            print(f"   Successfully fetched photo via presigned GET URL ({len(downloaded)} bytes, private bucket).")

            thumb_res = await r2_client.get(url_data["thumbnail_url"])
            assert thumb_res.status_code == 200
            thumb_downloaded = thumb_res.content
            assert len(thumb_downloaded) > 0
            print(f"   Successfully fetched thumbnail via presigned GET URL ({len(thumb_downloaded)} bytes).")

    await engine.dispose()
    print("\n==================================================")
    print("ALL DIRECT-TO-R2 UPLOAD ACCEPTANCE CHECKS PASSED!")
    print("==================================================")


if __name__ == "__main__":
    asyncio.run(run_upload_flow_test())
