import os
from celery import Celery
from app.core.config import settings

celery_app = Celery(
    "event_album_worker",
    broker=settings.REDIS_URL,
    backend=settings.REDIS_URL,
)

concurrency = settings.CELERY_CONCURRENCY or os.cpu_count() or 4

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_time_limit=300,
    worker_concurrency=concurrency,
    imports=["app.worker"],
)
