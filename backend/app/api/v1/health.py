from fastapi import APIRouter
import redis
from app.core.celery_app import celery_app
from app.core.config import settings

router = APIRouter(tags=["Health"])


@router.get("/health")
def health_check():
    return {"status": "ok"}


@router.get("/health/queue")
def queue_health_check():
    """Reports whether Redis and Celery worker are reachable."""
    redis_reachable = False
    celery_reachable = False
    active_workers = []
    error = None
    try:
        r = redis.from_url(settings.REDIS_URL, socket_connect_timeout=0.5, socket_timeout=0.5)
        redis_reachable = bool(r.ping())
        inspector = celery_app.control.inspect(timeout=0.5)
        ping_res = inspector.ping() if inspector else None
        if ping_res:
            celery_reachable = True
            active_workers = list(ping_res.keys())
    except Exception as e:
        error = str(e)

    status_str = "ok" if (redis_reachable and celery_reachable) else "degraded"
    return {
        "status": status_str,
        "redis_reachable": redis_reachable,
        "celery_reachable": celery_reachable,
        "active_workers": active_workers,
        "workers_count": len(active_workers),
        "error": error,
    }
