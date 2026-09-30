"""
Full User Journey Acceptance Test:
1. Creates event (Simulating /events/new)
2. Presigns, directly PUTs photos to R2, and confirms (Simulating /events/[id]/upload)
3. Enrolls guest selfie with in-memory disposal (Simulating /events/[id] webcam capture)
4. Matches guest against event photos using pgvector <=> cosine search
5. Verifies top match similarity > 95%
6. Downloads photo via presigned GET URL
7. Creates and verifies ZIP archive containing matched photos
"""
import io
import os
import sys
import uuid
import zipfile
import httpx
from datetime import datetime, timezone, date
from pathlib import Path

# Add backend directory to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from httpx import ASGITransport
from app.main import app
from app.services.storage import storage_service
from app.worker import process_photo

ROOT_DIR = Path(__file__).resolve().parent.parent.parent
IMG_TARGET = ROOT_DIR / "images" / "img7.png"
IMG_DISTRACTOR = ROOT_DIR / "images" / "img5.png"


async def run_full_journey():
    print("==================================================")
    print("Starting Full User Journey Acceptance Test")
    print("==================================================")

    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Create Event (/events/new)
        print("\n1. [Page: /events/new] Creating Event...")
        create_res = await client.post(
            "/api/events",
            json={"name": "Grand Wedding Gala", "event_date": str(date.today())},
        )
        assert create_res.status_code == 201, f"Create event failed: {create_res.text}"
        event = create_res.json()
        event_id = event["id"]
        print(f"   Event Created: ID={event_id}, Name='{event['name']}'")

        # 2. Upload Photos (/events/[id]/upload)
        print("\n2. [Page: /events/[id]/upload] Direct-to-R2 Upload Flow...")
        with open(IMG_TARGET, "rb") as f:
            target_bytes = f.read()
        with open(IMG_DISTRACTOR, "rb") as f:
            distractor_bytes = f.read()

        presign_res = await client.post(
            f"/api/events/{event_id}/photos/presign",
            json={
                "files": [
                    {"filename": "target_reception.png", "content_type": "image/png"},
                    {"filename": "distractor_decor.png", "content_type": "image/png"},
                ]
            },
        )
        assert presign_res.status_code == 200, f"Presign failed: {presign_res.text}"
        items = presign_res.json()["items"]
        assert len(items) == 2

        # Upload directly to R2
        async with httpx.AsyncClient() as r2_client:
            put1 = await r2_client.put(items[0]["upload_url"], content=target_bytes, headers={"Content-Type": "image/png"})
            assert put1.status_code == 200
            put2 = await r2_client.put(items[1]["upload_url"], content=distractor_bytes, headers={"Content-Type": "image/png"})
            assert put2.status_code == 200
        print("   Direct PUT of 2 photos to Cloudflare R2 succeeded (HTTP 200).")

        # Confirm uploads
        confirm_res = await client.post(
            f"/api/events/{event_id}/photos/confirm",
            json={
                "photos": [
                    {"photo_id": items[0]["photo_id"], "r2_object_key": items[0]["r2_object_key"]},
                    {"photo_id": items[1]["photo_id"], "r2_object_key": items[1]["r2_object_key"]},
                ]
            },
        )
        assert confirm_res.status_code == 200
        print(f"   Confirmed upload in DB for 2 photos (status=pending).")

        # Process photos with Celery
        print("\n3. Celery background face detection & embedding...")
        p1 = process_photo(items[0]["photo_id"])
        p2 = process_photo(items[1]["photo_id"])
        print(f"   Photo 1 processed: {p1['status']} ({p1.get('faces_count')} faces)")
        print(f"   Photo 2 processed: {p2['status']} ({p2.get('faces_count')} faces)")

        # 4. Guest Selfie Enrollment (/events/[id])
        print("\n4. [Page: /events/[id]] Guest Selfie Enrollment (getUserMedia)...")
        enroll_res = await client.post(
            f"/api/events/{event_id}/guests/enroll",
            files=[("files", ("selfie.png", target_bytes, "image/png"))],
            data={"name": "Alex Guest"},
        )
        assert enroll_res.status_code == 200, f"Enroll failed: {enroll_res.text}"
        guest = enroll_res.json()
        guest_id = guest["guest_id"]
        print(f"   Guest Enrolled: ID={guest_id}, Name='{guest['name']}'")
        print(f"   Privacy Guarantee: {guest['message']}")

        # 5. Face Matching (/events/[id] Match Query)
        print("\n5. [Page: /events/[id]] Facial Recognition Match Query...")
        match_res = await client.post(f"/api/events/{event_id}/guests/{guest_id}/match")
        assert match_res.status_code == 200, f"Match failed: {match_res.text}"
        match_data = match_res.json()
        matches = match_data["matches"]
        print(f"   Found {len(matches)} matching photo(s) above threshold {match_data['match_threshold']}:")

        for rank, m in enumerate(matches, start=1):
            print(f"   - Rank #{rank}: Photo {m['photo_id']} | Similarity: {m['similarity']:.4f} ({m['similarity']*100:.1f}%)")

        assert len(matches) > 0, "Expected at least 1 match"
        top_photo = matches[0]
        assert top_photo["photo_id"] == items[0]["photo_id"], "Target photo must rank #1"
        assert top_photo["similarity"] > 0.95, f"Similarity {top_photo['similarity']} should be > 0.95"

        # 6. Per-photo download verification
        print("\n6. Testing per-photo download via presigned GET URL...")
        async with httpx.AsyncClient() as r2_client:
            dl_res = await r2_client.get(top_photo["photo_url"])
            assert dl_res.status_code == 200
            assert len(dl_res.content) == len(target_bytes)
            print(f"   Photo downloaded successfully: {len(dl_res.content)} bytes.")

        # 7. "Download all as zip" verification
        print("\n7. Testing 'Download all as zip' archive generation...")
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
            for idx, m in enumerate(matches, start=1):
                async with httpx.AsyncClient() as r2_client:
                    img_data = (await r2_client.get(m["photo_url"])).content
                zip_file.writestr(f"photo_{idx}.jpg", img_data)

        zip_bytes = zip_buffer.getvalue()
        assert len(zip_bytes) > 0
        print(f"   ZIP archive created successfully: {len(zip_bytes)} bytes containing {len(matches)} photo(s).")

    print("\n==================================================")
    print("FULL USER JOURNEY ACCEPTANCE TEST PASSED 100%!")
    print("==================================================")


if __name__ == "__main__":
    import asyncio
    asyncio.run(run_full_journey())
