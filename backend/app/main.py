from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.router import api_router
from app.core.config import settings


import time
import cv2
from app.services.face import get_face_embedder
from app.services.storage import storage_service


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Set OpenCV thread cap to prevent oversubscribing CPU
    cv2.setNumThreads(settings.OPENCV_NUM_THREADS)

    # Pre-load FaceEmbedder singleton once at startup (not per request)
    t0 = time.perf_counter()
    embedder = get_face_embedder()
    elapsed_ms = (time.perf_counter() - t0) * 1000
    print(f"[app:lifespan] FaceEmbedder pre-loaded in {elapsed_ms:.1f}ms (cv2 threads={cv2.getNumThreads()})", flush=True)

    # Ensure Cloudflare R2 bucket has CORS configured for browser uploads
    storage_service.ensure_cors_configured()
    yield
    # Shutdown cleanup


app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.VERSION,
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Health endpoint at root as requested: GET /health -> {"status": "ok"}
@app.get("/health", tags=["Health"])
def health_check():
    return {"status": "ok"}


@app.get("/health/queue", tags=["Health"])
def queue_health_check():
    import redis
    from app.core.celery_app import celery_app

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


# Mount API routers
app.include_router(api_router)
