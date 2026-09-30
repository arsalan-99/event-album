# Event Album

This is an AI powered visual retrieval platform that eliminates the friction of manual event photo curation. Using YuNet face detection, 128-dimensional SFace embeddings, and HNSW vector indexing via pgvector, it lets guests instantly surface every photo they appear in from thousands of crowd shots in milliseconds with a single selfie and zero image retention.

## Uploading images

<div align="center">
  <img src="frontend/Uploading images Preview.png" alt="Web App Preview" width="600">
</div>
<div align="center">

## Finding Matches

<div align="center">
  <img src="frontend/Finding matches Preview.png" alt="Web App Preview" width="600">
</div>
<div align="center">

## Tech Stack

- Python (FastAPI, Celery, OpenCV, NumPy, SQLAlchemy)
- PostgreSQL with pgvector
- Redis
- Cloudflare R2 (S3-compatible object storage)
- Next.js (React, TypeScript)
- Docker & Docker Compose

## How It Works

- Photographers upload event photos directly from the browser to Cloudflare R2 using presigned URLs.
- A Celery background worker downloads each photo, runs YuNet to detect faces, extracts 128-dimensional embeddings with SFace, and generates a compressed thumbnail.
- Face embeddings are saved in PostgreSQL with an HNSW cosine index using pgvector.
- When a guest takes or uploads a selfie, the backend generates an embedding in memory, queries PostgreSQL for matching faces using cosine distance, and returns the matching photos without storing the guest's selfie.

## Run It

Prerequisites: Docker, Docker Compose, and Node.js 18+.

1. Clone the repository and configure environment variables:

```bash
git clone <repo-url>
cd event-album
cp .env.example .env
```

Add your Cloudflare R2 credentials to `.env`.

2. Download the model weights (if not already present):

```bash
./download_models.sh
```

3. Start backend services:

```bash
docker compose up -d --build
```

The API will be available at `http://localhost:8000` (docs at `http://localhost:8000/docs`).

4. Start frontend:

```bash
cd frontend
npm install
npm run dev
```

The frontend will be available at `http://localhost:3000`.
