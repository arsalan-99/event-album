"""
Acceptance test script:
1. Verifies Alembic upgrade head
2. Inserts dummy embedding with model_name and model_version
3. Queries vector using pgvector <=> operator (cosine distance)
"""
import asyncio
import uuid
from datetime import datetime, timezone, date
import numpy as np
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select
from alembic import command
from alembic.config import Config

from app.core.database import async_session_maker, engine
from app.models import (
    Base,
    Event,
    Photo,
    FaceEmbedding,
    ProcessingStatus,
)


def run_migrations():
    print("Running alembic upgrade head...")
    alembic_cfg = Config("alembic.ini")
    command.upgrade(alembic_cfg, "head")
    print("Alembic upgrade head completed cleanly.")


async def test_insert_and_query():
    print("Testing insert and query with pgvector...")
    async with async_session_maker() as session:
        # Create event & photo
        event_id = str(uuid.uuid4())
        event = Event(
            id=event_id,
            name="Test Event",
            event_date=date.today(),
            owner_id=str(uuid.uuid4()),
            created_at=datetime.now(timezone.utc),
        )
        session.add(event)

        photo_id = str(uuid.uuid4())
        photo = Photo(
            id=photo_id,
            event_id=event_id,
            r2_object_key=f"test/{photo_id}.jpg",
            uploaded_at=datetime.now(timezone.utc),
            processing_status=ProcessingStatus.DONE,
        )
        session.add(photo)

        # Generate dummy 128-d vector
        dummy_vec = np.random.randn(128).astype(np.float32)
        dummy_vec = (dummy_vec / np.linalg.norm(dummy_vec)).tolist()

        face_id = str(uuid.uuid4())
        face = FaceEmbedding(
            id=face_id,
            photo_id=photo_id,
            embedding=dummy_vec,
            bbox_json={"x": 50, "y": 50, "w": 60, "h": 60},
            model_name="sface",
            model_version="2021dec",
            is_low_quality=False,
            created_at=datetime.now(timezone.utc),
        )
        session.add(face)
        await session.commit()
        print(f"Successfully inserted dummy FaceEmbedding (ID: {face_id})")

        # Query using pgvector <=> operator (cosine distance)
        stmt = (
            select(
                FaceEmbedding.id,
                FaceEmbedding.model_name,
                FaceEmbedding.model_version,
                FaceEmbedding.embedding.cosine_distance(dummy_vec).label("distance"),
            )
            .where(FaceEmbedding.id == face_id)
            .order_by(FaceEmbedding.embedding.cosine_distance(dummy_vec))
        )
        res = await session.execute(stmt)
        row = res.first()

        assert row is not None, "Failed to retrieve inserted embedding"
        assert row.id == face_id, f"Expected ID {face_id}, got {row.id}"
        assert row.model_name == "sface", f"Expected sface, got {row.model_name}"
        assert row.model_version == "2021dec", f"Expected 2021dec, got {row.model_version}"
        assert abs(row.distance) < 1e-4, f"Self-distance should be ~0.0, got {row.distance}"

        print(f"Query matched inserted embedding with cosine distance {row.distance:.6f}")
        print("ALL ACCEPTANCE CHECKS PASSED.")

    await engine.dispose()


if __name__ == "__main__":
    run_migrations()
    asyncio.run(test_insert_and_query())
