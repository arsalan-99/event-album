"""
Seed script: populates the database with sample event, photos, face embeddings,
and guest embeddings, then verifies vector search with pgvector's <=> operator.
"""
import asyncio
import uuid
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from datetime import datetime, timezone, date
import numpy as np
from sqlalchemy import select, text

from app.core.database import async_session_maker, engine
from app.models import (
    Base,
    Event,
    Photo,
    FaceEmbedding,
    Guest,
    GuestEmbedding,
    ProcessingStatus,
)


def generate_unit_vector(dim: int = 128) -> list:
    """Generate normalized unit vector for cosine distance testing."""
    vec = np.random.randn(dim).astype(np.float32)
    norm = np.linalg.norm(vec)
    return (vec / norm).tolist()


async def seed():
    print("Starting database seed...")

    async with async_session_maker() as session:
        # 1. Create sample Event
        event_id = str(uuid.uuid4())
        event = Event(
            id=event_id,
            name="Sarah & Alex Wedding",
            event_date=date(2026, 6, 20),
            owner_id=str(uuid.uuid4()),
            created_at=datetime.now(timezone.utc),
        )
        session.add(event)

        # 2. Create sample Photo
        photo_id = str(uuid.uuid4())
        photo = Photo(
            id=photo_id,
            event_id=event_id,
            r2_object_key=f"events/{event_id}/photos/{photo_id}.jpg",
            thumbnail_key=f"events/{event_id}/thumbnails/{photo_id}_thumb.jpg",
            uploaded_at=datetime.now(timezone.utc),
            processing_status=ProcessingStatus.DONE,
        )
        session.add(photo)

        # Generate target face vector
        target_vec = generate_unit_vector(128)

        # 3. Create FaceEmbedding on photo
        face_emb = FaceEmbedding(
            id=str(uuid.uuid4()),
            photo_id=photo_id,
            embedding=target_vec,
            bbox_json={"x": 120, "y": 80, "w": 95, "h": 110, "confidence": 0.98},
            model_name="sface",
            model_version="2021dec",
            is_low_quality=False,
            created_at=datetime.now(timezone.utc),
        )
        session.add(face_emb)

        # Add distractor face embedding in same photo
        other_vec = generate_unit_vector(128)
        distractor_face = FaceEmbedding(
            id=str(uuid.uuid4()),
            photo_id=photo_id,
            embedding=other_vec,
            bbox_json={"x": 300, "y": 90, "w": 90, "h": 105, "confidence": 0.94},
            model_name="sface",
            model_version="2021dec",
            is_low_quality=False,
            created_at=datetime.now(timezone.utc),
        )
        session.add(distractor_face)

        # 4. Create Guest
        guest_id = str(uuid.uuid4())
        guest = Guest(
            id=guest_id,
            event_id=event_id,
            name="John Doe",
            created_at=datetime.now(timezone.utc),
        )
        session.add(guest)

        # 5. Create 2 selfie embeddings for Guest (slightly perturbed versions of target_vec)
        for i in range(2):
            # Add small noise to target vector to simulate slight selfie angle variations
            noise = np.random.randn(128).astype(np.float32) * 0.05
            guest_vec = np.array(target_vec) + noise
            guest_vec = (guest_vec / np.linalg.norm(guest_vec)).tolist()

            g_emb = GuestEmbedding(
                id=str(uuid.uuid4()),
                guest_id=guest_id,
                embedding=guest_vec,
                model_name="sface",
                model_version="2021dec",
                created_at=datetime.now(timezone.utc),
            )
            session.add(g_emb)

        await session.commit()
        print(f"Seeded Event ({event.name}), Photo ({photo.id}), 2 Faces, 1 Guest with 2 Selfie Embeddings.")

        # 6. Verification query: search face_embeddings using pgvector cosine distance (<=>)
        # SFace cosine distance = 1 - cosine_similarity. Lower distance = closer match.
        print("\nTesting pgvector cosine query (<=> operator)...")
        query = (
            select(
                FaceEmbedding.id,
                FaceEmbedding.photo_id,
                FaceEmbedding.model_name,
                FaceEmbedding.model_version,
                FaceEmbedding.embedding.cosine_distance(target_vec).label("distance"),
            )
            .where(FaceEmbedding.model_name == "sface")
            .where(FaceEmbedding.model_version == "2021dec")
            .order_by(FaceEmbedding.embedding.cosine_distance(target_vec))
            .limit(5)
        )

        result = await session.execute(query)
        rows = result.all()
        print(f"Found {len(rows)} matching faces:")
        for r in rows:
            print(f" - Face ID: {r.id}, Photo ID: {r.photo_id}, Model: {r.model_name}:{r.model_version}, Cosine Distance: {r.distance:.4f}")

    await engine.dispose()
    print("\nSeed & vector search test complete!")


if __name__ == "__main__":
    asyncio.run(seed())
