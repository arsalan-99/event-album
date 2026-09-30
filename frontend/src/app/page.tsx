import Link from "next/link";

export default function HomePage() {
  return (
    <div className="container" style={{ paddingTop: "4rem", maxWidth: "780px" }}>
      <div style={{ marginBottom: "3rem" }}>
        <span className="eyebrow">Archival Photography &bull; Private Face Matching</span>
        <h1
          style={{
            fontSize: "2.75rem",
            fontWeight: 600,
            lineHeight: 1.15,
            letterSpacing: "-0.03em",
            marginBottom: "1.25rem",
          }}
        >
          Event Photo Delivery, <br />
          Instant &amp; Private.
        </h1>
        <p
          style={{
            fontSize: "1.05rem",
            color: "var(--text-secondary)",
            lineHeight: 1.6,
            maxWidth: "580px",
            marginBottom: "2rem",
          }}
        >
          Guests upload a single selfie to retrieve their event photos. Direct S3/R2 storage,
          in-memory YuNet face detection and SFace embeddings, with zero selfie data retained.
        </p>

        <div style={{ display: "flex", gap: "0.75rem", flexWrap: "wrap" }}>
          <Link href="/events" className="btn btn-primary">
            View All Events &rarr;
          </Link>
          <Link href="/events/new" className="btn btn-secondary">
            + Create New Event
          </Link>
        </div>
      </div>

      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))",
          gap: "1rem",
          borderTop: "1px solid var(--border-color)",
          paddingTop: "2.5rem",
        }}
      >
        <div className="card" style={{ padding: "1.25rem" }}>
          <span className="eyebrow">Architecture</span>
          <h3 style={{ fontSize: "0.95rem", fontWeight: 600, marginBottom: "0.4rem" }}>
            Direct R2 Uploads
          </h3>
          <p style={{ color: "var(--text-secondary)", fontSize: "0.82rem", lineHeight: 1.5 }}>
            Photos upload straight from photographer browser to Cloudflare R2 via presigned PUT.
            FastAPI handles auth and metadata without proxying media bytes.
          </p>
        </div>

        <div className="card" style={{ padding: "1.25rem" }}>
          <span className="eyebrow">Privacy</span>
          <h3 style={{ fontSize: "0.95rem", fontWeight: 600, marginBottom: "0.4rem" }}>
            In-Memory Processing
          </h3>
          <p style={{ color: "var(--text-secondary)", fontSize: "0.82rem", lineHeight: 1.5 }}>
            Guest selfies are mapped to 128-dimensional vectors in memory and immediately discarded.
            Raw selfies are never stored on disk or in object storage.
          </p>
        </div>

        <div className="card" style={{ padding: "1.25rem" }}>
          <span className="eyebrow">Search Engine</span>
          <h3 style={{ fontSize: "0.95rem", fontWeight: 600, marginBottom: "0.4rem" }}>
            pgvector Cosine Index
          </h3>
          <p style={{ color: "var(--text-secondary)", fontSize: "0.82rem", lineHeight: 1.5 }}>
            HNSW cosine distance indexing in PostgreSQL enables fast multi-face retrieval
            ranked by true similarity.
          </p>
        </div>
      </div>
    </div>
  );
}
