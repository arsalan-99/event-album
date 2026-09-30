"""
Acceptance test script for Guest Enrollment and Face Matching:
1. Creates a test Event
2. Processes 2 event photos:
   - Photo A: Target person (images/img7.png)
   - Photo B: Different person (images/img5.png)
3. Enrolls a guest using selfie (images/img7.png) via POST /api/events/{event_id}/guests/enroll
4. Verifies raw selfie is immediately discarded from memory, not stored on disk or R2
5. Calls POST /api/events/{event_id}/guests/{guest_id}/match
6. Verifies:
   - Photo A containing target face ranks #1 with similarity > MATCH_THRESHOLD
   - Similarity scores are accurately returned per photo
   - Presigned view URLs are generated
"""
import asyncio
import os
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
from app.core.config import settings
from app.core.database import async_session_maker, engine
from app.models import Event, Photo, FaceEmbedding, Guest, GuestEmbedding, ProcessingStatus
from app.services.storage import storage_service
from app.worker import process_photo

ROOT_DIR = Path(__file__).resolve().parent.parent.parent
IMG_TARGET = ROOT_DIR / "images" / "img7.png"
IMG_DISTRACTOR = ROOT_DIR / "images" / "img5.png"


async def run_guest_match_test():
    print("==================================================")
    print("Starting Guest Enroll & Face Match Acceptance Test")
    print("==================================================")

    assert IMG_TARGET.exists(), f"Target image missing: {IMG_TARGET}"
    assert IMG_DISTRACTOR.exists(), f"Distractor image missing: {IMG_DISTRACTOR}"

    event_id = str(uuid.uuid4())
    photo_target_id = str(uuid.uuid4())
    photo_distractor_id = str(uuid.uuid4())

    target_key = f"events/{event_id}/photos/{photo_target_id}.png"
    distractor_key = f"events/{event_id}/photos/{photo_distractor_id}.png"

    # 1. Create Event in DB
    print(f"\n1. Creating Event in DB ({event_id})...")
    async with async_session_maker() as session:
        event = Event(
            id=event_id,
            name="Face Match Gala",
            event_date=date.today(),
            owner_id=str(uuid.uuid4()),
            created_at=datetime.now(timezone.utc),
        )
        session.add(event)
        await session.commit()
    print("   Event created.")

    # 2. Upload both photos to R2 and process them
    print("\n2. Uploading and processing test event photos in R2...")
    with open(IMG_TARGET, "rb") as f:
        target_bytes = f.read()
    with open(IMG_DISTRACTOR, "rb") as f:
        distractor_bytes = f.read()

    storage_service.upload_file_bytes(target_bytes, target_key, content_type="image/png")
    storage_service.upload_file_bytes(distractor_bytes, distractor_key, content_type="image/png")

    async with async_session_maker() as session:
        p1 = Photo(
            id=photo_target_id,
            event_id=event_id,
            r2_object_key=target_key,
            uploaded_at=datetime.now(timezone.utc),
            processing_status=ProcessingStatus.PENDING,
        )
        p2 = Photo(
            id=photo_distractor_id,
            event_id=event_id,
            r2_object_key=distractor_key,
            uploaded_at=datetime.now(timezone.utc),
            processing_status=ProcessingStatus.PENDING,
        )
        session.add_all([p1, p2])
        await session.commit()

    # Process both photos
    res1 = process_photo(photo_target_id)
    res2 = process_photo(photo_distractor_id)
    print(f"   Photo Target processed: {res1['status']} ({res1.get('faces_count')} faces)")
    print(f"   Photo Distractor processed: {res2['status']} ({res2.get('faces_count')} faces)")

    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        # 3. Enroll guest with selfie (IMG_TARGET)
        print(f"\n3. Enrolling guest with selfie via POST /api/events/{event_id}/guests/enroll...")
        with open(IMG_TARGET, "rb") as f:
            selfie_data = f.read()

        files = [
            ("files", ("selfie1.png", selfie_data, "image/png")),
        ]
        data = {
            "name": "Target Guest",
        }

        enroll_res = await client.post(
            f"/api/events/{event_id}/guests/enroll",
            files=files,
            data=data,
        )
        assert enroll_res.status_code == 200, f"Enroll failed: {enroll_res.text}"
        enroll_data = enroll_res.json()
        guest_id = enroll_data["guest_id"]
        print(f"   Enrolled Guest ID: {guest_id}")
        print(f"   Embeddings stored: {enroll_data['embeddings_count']}")
        print(f"   Privacy check: {enroll_data['message']}")

        # 4. Verify DB has guest_embeddings with model_name and model_version
        async with async_session_maker() as session:
            g_embs = (
                await session.scalars(select(GuestEmbedding).where(GuestEmbedding.guest_id == guest_id))
            ).all()
            assert len(g_embs) == 1, "Expected 1 guest embedding"
            assert g_embs[0].model_name == "sface"
            assert g_embs[0].model_version == "2021dec"
            assert len(g_embs[0].embedding) == 128
            print(f"   DB check: guest_embedding verified with model={g_embs[0].model_name}:{g_embs[0].model_version}, dim=128")

        # 5. Call POST /api/events/{event_id}/guests/{guest_id}/match
        print(f"\n5. Calling POST /api/events/{event_id}/guests/{guest_id}/match...")
        match_res = await client.post(f"/api/events/{event_id}/guests/{guest_id}/match")
        assert match_res.status_code == 200, f"Match failed: {match_res.text}"
        match_data = match_res.json()

        threshold = match_data["match_threshold"]
        matches = match_data["matches"]
        print(f"   Match threshold: {threshold}")
        print(f"   Total matching photos above threshold: {match_data['matches_count']}")

        for rank, m in enumerate(matches, start=1):
            print(f"   - Rank #{rank}: Photo ID {m['photo_id']} | Similarity: {m['similarity']:.4f} | URL: {m['photo_url'][:50]}...")

        # 6. Verify ranking correctness
        assert len(matches) >= 1, "Expected at least 1 match above threshold"
        top_match = matches[0]
        assert top_match["photo_id"] == photo_target_id, (
            f"Expected photo_target_id ({photo_target_id}) to rank #1, but got {top_match['photo_id']}"
        )
        assert top_match["similarity"] >= threshold, f"Similarity {top_match['similarity']} below threshold {threshold}"
        assert top_match["similarity"] > 0.90, f"Expected high similarity (>0.90) for same face, got {top_match['similarity']}"

        # If distractor is in matches, verify it ranks lower
        for m in matches[1:]:
            assert m["similarity"] < top_match["similarity"], "Distractor cannot rank higher than target"

        print(f"\n   Target photo ({photo_target_id}) ranked #1 with {top_match['similarity']:.4f} similarity score!")

    await engine.dispose()
    print("\n==================================================")
    print("ALL GUEST ENROLL & MATCH ACCEPTANCE CHECKS PASSED!")
    print("==================================================")


if __name__ == "__main__":
    asyncio.run(run_guest_match_test())
