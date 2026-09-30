"""Initial Postgres schema with pgvector and SFace embeddings

Revision ID: 0001_initial_schema
Revises: 
Create Date: 2026-09-19 19:45:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '0001_initial_schema'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Enable pgvector extension
    op.execute("CREATE EXTENSION IF NOT EXISTS vector;")

    # 2. Create processing_status_enum safely
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'processing_status_enum') THEN
                CREATE TYPE processing_status_enum AS ENUM ('pending', 'processing', 'done', 'failed');
            END IF;
        END
        $$;
        """
    )
    processing_status_type = postgresql.ENUM(
        'pending', 'processing', 'done', 'failed',
        name='processing_status_enum',
        create_type=False,
    )

    # 3. Create events table
    op.create_table(
        'events',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('event_date', sa.Date(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('owner_id', sa.String(length=36), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_events_owner_id', 'events', ['owner_id'], unique=False)

    # 4. Create photos table
    op.create_table(
        'photos',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('event_id', sa.String(length=36), nullable=False),
        sa.Column('r2_object_key', sa.String(length=512), nullable=False),
        sa.Column('thumbnail_key', sa.String(length=512), nullable=True),
        sa.Column('uploaded_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('processing_status', processing_status_type, nullable=False),
        sa.ForeignKeyConstraint(['event_id'], ['events.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('r2_object_key')
    )
    op.create_index('ix_photos_event_id', 'photos', ['event_id'], unique=False)
    op.create_index('ix_photos_processing_status', 'photos', ['processing_status'], unique=False)

    # 5. Create face_embeddings table
    op.create_table(
        'face_embeddings',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('photo_id', sa.String(length=36), nullable=False),
        sa.Column('embedding', Vector(128), nullable=False),
        sa.Column('bbox_json', sa.JSON(), nullable=False),
        sa.Column('model_name', sa.String(length=50), nullable=False),
        sa.Column('model_version', sa.String(length=50), nullable=False),
        sa.Column('is_low_quality', sa.Boolean(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['photo_id'], ['photos.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_face_embeddings_photo_id', 'face_embeddings', ['photo_id'], unique=False)
    op.create_index('ix_face_embeddings_model_version', 'face_embeddings', ['model_name', 'model_version'], unique=False)

    # HNSW Cosine vector index on face_embeddings.embedding
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_face_embeddings_embedding_hnsw 
        ON face_embeddings 
        USING hnsw (embedding vector_cosine_ops);
        """
    )

    # 6. Create guests table
    op.create_table(
        'guests',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('event_id', sa.String(length=36), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['event_id'], ['events.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_guests_event_id', 'guests', ['event_id'], unique=False)

    # 7. Create guest_embeddings table
    op.create_table(
        'guest_embeddings',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('guest_id', sa.String(length=36), nullable=False),
        sa.Column('embedding', Vector(128), nullable=False),
        sa.Column('model_name', sa.String(length=50), nullable=False),
        sa.Column('model_version', sa.String(length=50), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['guest_id'], ['guests.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_guest_embeddings_guest_id', 'guest_embeddings', ['guest_id'], unique=False)
    op.create_index('ix_guest_embeddings_model_version', 'guest_embeddings', ['model_name', 'model_version'], unique=False)

    # HNSW Cosine vector index on guest_embeddings.embedding
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_guest_embeddings_embedding_hnsw 
        ON guest_embeddings 
        USING hnsw (embedding vector_cosine_ops);
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_guest_embeddings_embedding_hnsw;")
    op.drop_index('ix_guest_embeddings_model_version', table_name='guest_embeddings')
    op.drop_index('ix_guest_embeddings_guest_id', table_name='guest_embeddings')
    op.drop_table('guest_embeddings')

    op.drop_index('ix_guests_event_id', table_name='guests')
    op.drop_table('guests')

    op.execute("DROP INDEX IF EXISTS ix_face_embeddings_embedding_hnsw;")
    op.drop_index('ix_face_embeddings_model_version', table_name='face_embeddings')
    op.drop_index('ix_face_embeddings_photo_id', table_name='face_embeddings')
    op.drop_table('face_embeddings')

    op.drop_index('ix_photos_processing_status', table_name='photos')
    op.drop_index('ix_photos_event_id', table_name='photos')
    op.drop_table('photos')

    op.drop_index('ix_events_owner_id', table_name='events')
    op.drop_table('events')

    op.execute("DROP TYPE IF EXISTS processing_status_enum;")
