"use client";

import { useEffect, useState, useRef, use, useCallback } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { API_BASE_URL } from "@/lib/api";

interface EventData {
  id: string;
  name: string;
  event_date: string;
  photos_count: number;
}

interface UploadingFile {
  id: string;
  file: File;
  progress: number;
  status: "waiting" | "uploading" | "confirming" | "done" | "error";
  error?: string;
  r2Key?: string;
}

interface PhotoItem {
  id: string;
  r2_object_key: string;
  processing_status: string;
  uploaded_at: string;
  url: string;
  thumbnail_url: string;
}

export default function PhotographerUploadPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id: eventId } = use(params);
  const router = useRouter();

  const [event, setEvent] = useState<EventData | null>(null);
  const [eventPhotos, setEventPhotos] = useState<PhotoItem[]>([]);
  const [uploadQueue, setUploadQueue] = useState<UploadingFile[]>([]);
  const [isUploading, setIsUploading] = useState(false);
  const [loadingEvent, setLoadingEvent] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [isDragging, setIsDragging] = useState(false);
  const [deletingPhotoId, setDeletingPhotoId] = useState<string | null>(null);
  const [isDeletingEvent, setIsDeletingEvent] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const fetchPhotos = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE_URL}/api/events/${eventId}/photos`);
      if (res.ok) {
        const data = await res.json();
        setEventPhotos(data.photos || []);
      }
    } catch {
      // ignore
    }
  }, [eventId]);

  useEffect(() => {
    async function fetchEventDetails() {
      try {
        const res = await fetch(`${API_BASE_URL}/api/events/${eventId}`);
        if (!res.ok) throw new Error("Event not found");
        const data = await res.json();
        setEvent(data);
      } catch (err: unknown) {
        setError(err instanceof Error ? err.message : "Failed to load event");
      } finally {
        setLoadingEvent(false);
      }
    }
    fetchEventDetails();
    fetchPhotos();
  }, [eventId, fetchPhotos]);

  // Polling for processing completion
  useEffect(() => {
    const hasUnfinished = eventPhotos.some(
      (p) => p.processing_status === "pending" || p.processing_status === "processing"
    );
    if (!hasUnfinished) return;

    const interval = setInterval(() => {
      fetchPhotos();
    }, 3000);
    return () => clearInterval(interval);
  }, [eventPhotos, eventId, fetchPhotos]);

  function handleFilesSelected(files: FileList | null) {
    if (!files || files.length === 0) return;
    const newItems: UploadingFile[] = Array.from(files).map((file) => ({
      id: Math.random().toString(36).substring(2, 9),
      file,
      progress: 0,
      status: "waiting",
    }));
    setUploadQueue((prev) => [...prev, ...newItems]);
  }

  function handleDrop(e: React.DragEvent) {
    e.preventDefault();
    setIsDragging(false);
    handleFilesSelected(e.dataTransfer.files);
  }

  // Direct PUT to R2 via XMLHttpRequest
  function uploadSingleFile(item: UploadingFile, presignedUrl: string): Promise<void> {
    return new Promise((resolve, reject) => {
      const xhr = new XMLHttpRequest();
      xhr.open("PUT", presignedUrl, true);

      const mimeType = item.file.type || "image/jpeg";
      xhr.setRequestHeader("Content-Type", mimeType);

      xhr.upload.onprogress = (event) => {
        if (event.lengthComputable) {
          const percent = Math.round((event.loaded / event.total) * 100);
          setUploadQueue((prev) =>
            prev.map((i) => (i.id === item.id ? { ...i, progress: percent } : i))
          );
        }
      };

      xhr.onload = () => {
        if (xhr.status >= 200 && xhr.status < 300) {
          resolve();
        } else {
          reject(new Error(`Storage PUT failed (HTTP ${xhr.status})`));
        }
      };

      xhr.onerror = () => reject(new Error("Network error during direct upload to R2"));
      xhr.send(item.file);
    });
  }

  // Start Batch Upload
  async function startUpload() {
    const waitingItems = uploadQueue.filter((i) => i.status === "waiting" || i.status === "error");
    if (waitingItems.length === 0) return;

    setIsUploading(true);
    setError(null);

    try {
      const presignPayload = {
        files: waitingItems.map((item) => ({
          filename: item.file.name,
          content_type: item.file.type || "image/jpeg",
        })),
      };

      const presignRes = await fetch(`${API_BASE_URL}/api/events/${eventId}/photos/presign`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(presignPayload),
      });

      if (!presignRes.ok) {
        const err = await presignRes.json().catch(() => ({}));
        throw new Error(err.detail || "Failed to generate presigned upload URLs");
      }

      const presignData = await presignRes.json();
      const presignedItems = presignData.items;

      const confirmedBatch: { photo_id: string; r2_object_key: string }[] = [];

      // Upload with concurrency limit of 3
      const concurrency = 3;
      for (let i = 0; i < waitingItems.length; i += concurrency) {
        const slice = waitingItems.slice(i, i + concurrency);
        await Promise.all(
          slice.map(async (item, sliceIdx) => {
            const presigned = presignedItems[i + sliceIdx];
            if (!presigned) return;

            setUploadQueue((prev) =>
              prev.map((q) =>
                q.id === item.id ? { ...q, status: "uploading", progress: 0, r2Key: presigned.r2_object_key } : q
              )
            );

            try {
              await uploadSingleFile(item, presigned.upload_url);
              setUploadQueue((prev) =>
                prev.map((q) =>
                  q.id === item.id ? { ...q, status: "confirming", progress: 100 } : q
                )
              );
              confirmedBatch.push({
                photo_id: presigned.photo_id,
                r2_object_key: presigned.r2_object_key,
              });
            } catch (uploadErr: unknown) {
              setUploadQueue((prev) =>
                prev.map((q) =>
                  q.id === item.id
                    ? {
                        ...q,
                        status: "error",
                        error: uploadErr instanceof Error ? uploadErr.message : "Upload failed",
                      }
                    : q
                )
              );
            }
          })
        );
      }

      // Confirm uploaded batch with backend
      if (confirmedBatch.length > 0) {
        const confirmRes = await fetch(`${API_BASE_URL}/api/events/${eventId}/photos/confirm`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ photos: confirmedBatch }),
        });

        if (!confirmRes.ok) {
          throw new Error("Photos uploaded to storage, but confirmation call failed");
        }

        const confirmedKeys = new Set(confirmedBatch.map((b) => b.r2_object_key));
        setUploadQueue((prev) =>
          prev.map((q) =>
            q.r2Key && confirmedKeys.has(q.r2Key) ? { ...q, status: "done" } : q
          )
        );

        fetchPhotos();
      }
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Error during upload sequence");
    } finally {
      setIsUploading(false);
    }
  }

  const [photoToDelete, setPhotoToDelete] = useState<string | null>(null);
  const [showDeleteEventModal, setShowDeleteEventModal] = useState(false);

  // Delete Individual Photo
  async function confirmDeletePhoto() {
    if (!photoToDelete) return;

    try {
      setDeletingPhotoId(photoToDelete);
      const res = await fetch(`${API_BASE_URL}/api/photos/${photoToDelete}`, {
        method: "DELETE",
      });
      if (!res.ok) throw new Error("Failed to delete photo");
      setEventPhotos((prev) => prev.filter((p) => p.id !== photoToDelete));
      setPhotoToDelete(null);
    } catch (err: unknown) {
      alert(err instanceof Error ? err.message : "Failed to delete photo");
    } finally {
      setDeletingPhotoId(null);
    }
  }

  // Delete Entire Event
  async function confirmDeleteEvent() {
    if (!event) return;

    try {
      setIsDeletingEvent(true);
      const res = await fetch(`${API_BASE_URL}/api/events/${eventId}`, {
        method: "DELETE",
      });
      if (!res.ok) throw new Error("Failed to delete event");
      router.push("/events");
    } catch (err: unknown) {
      alert(err instanceof Error ? err.message : "Failed to delete event");
      setIsDeletingEvent(false);
      setShowDeleteEventModal(false);
    }
  }

  if (loadingEvent) {
    return (
      <div className="container" style={{ textAlign: "center", paddingTop: "5rem" }}>
        <span className="spinner"></span>
        <p style={{ marginTop: "1rem", color: "var(--text-secondary)", fontSize: "0.85rem" }}>
          Loading event...
        </p>
      </div>
    );
  }

  return (
    <div className="container" style={{ maxWidth: "900px" }}>
      {/* Navigation header */}
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          marginBottom: "1.5rem",
          fontSize: "0.8rem",
          color: "var(--text-secondary)",
        }}
      >
        <Link href="/events" style={{ textDecoration: "none" }}>
          &larr; All Events
        </Link>
        <div style={{ display: "flex", gap: "0.5rem", alignItems: "center" }}>
          <Link href={`/events/${eventId}`} className="btn btn-secondary btn-sm">
            Guest Portal View
          </Link>
          <button
            onClick={() => setShowDeleteEventModal(true)}
            disabled={isDeletingEvent}
            className="btn btn-danger btn-sm"
          >
            {isDeletingEvent ? "Deleting..." : "Delete Event"}
          </button>
        </div>
      </div>

      {/* Header Info */}
      <div style={{ marginBottom: "2rem" }}>
        <span className="eyebrow">Photographer Portal &bull; Direct Storage</span>
        <h1 style={{ fontSize: "1.85rem", fontWeight: 600, marginBottom: "0.25rem" }}>
          {event?.name}
        </h1>
        <p style={{ color: "var(--text-secondary)", fontSize: "0.85rem" }}>
          Event Date: {event?.event_date} &bull; Total photos: {eventPhotos.length}
        </p>
      </div>

      {error && <div className="alert alert-error">{error}</div>}

      {/* Drag and Drop Zone */}
      <div
        className={`dropzone ${isDragging ? "active" : ""}`}
        style={{ marginBottom: "2rem" }}
        onDragOver={(e) => {
          e.preventDefault();
          setIsDragging(true);
        }}
        onDragLeave={() => setIsDragging(false)}
        onDrop={handleDrop}
        onClick={() => fileInputRef.current?.click()}
      >
        <div style={{ maxWidth: "420px", margin: "0 auto" }}>
          <h3 style={{ fontSize: "1rem", fontWeight: 600, marginBottom: "0.4rem" }}>
            Drag &amp; drop photos here
          </h3>
          <p style={{ color: "var(--text-secondary)", fontSize: "0.82rem", marginBottom: "1rem" }}>
            Direct-to-storage upload. Supported formats: JPEG, PNG, WebP.
          </p>
          <button
            type="button"
            className="btn btn-secondary btn-sm"
            onClick={(e) => {
              e.stopPropagation();
              fileInputRef.current?.click();
            }}
          >
            Select Files
          </button>
        </div>
        <input
          ref={fileInputRef}
          type="file"
          multiple
          accept="image/jpeg,image/png,image/webp"
          style={{ display: "none" }}
          onChange={(e) => handleFilesSelected(e.target.files)}
        />
      </div>

      {/* Upload Queue */}
      {uploadQueue.length > 0 && (
        <div className="card" style={{ marginBottom: "2rem" }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "1rem" }}>
            <h3 style={{ fontSize: "0.95rem", fontWeight: 600 }}>
              Upload Queue ({uploadQueue.length})
            </h3>
            <div style={{ display: "flex", gap: "0.5rem" }}>
              <button
                className="btn btn-secondary btn-sm"
                onClick={() => setUploadQueue([])}
                disabled={isUploading}
              >
                Clear
              </button>
              <button
                className="btn btn-primary btn-sm"
                onClick={startUpload}
                disabled={isUploading || uploadQueue.every((i) => i.status === "done")}
              >
                {isUploading ? (
                  <>
                    <span className="spinner"></span> Uploading...
                  </>
                ) : (
                  "Start Upload"
                )}
              </button>
            </div>
          </div>

          <div style={{ display: "flex", flexDirection: "column", gap: "0.5rem" }}>
            {uploadQueue.map((item) => (
              <div
                key={item.id}
                style={{
                  padding: "0.6rem 0.85rem",
                  borderRadius: "var(--radius-sm)",
                  background: "var(--bg-primary)",
                  border: "1px solid var(--border-color)",
                }}
              >
                <div style={{ display: "flex", justifyContent: "space-between", fontSize: "0.8rem", marginBottom: "0.3rem" }}>
                  <span style={{ fontWeight: 500, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", maxWidth: "65%" }}>
                    {item.file.name}
                  </span>
                  <span style={{ color: item.status === "error" ? "var(--danger-text)" : "var(--text-secondary)", fontSize: "0.75rem" }}>
                    {item.status === "uploading" && `${item.progress}%`}
                    {item.status === "confirming" && "Enqueuing..."}
                    {item.status === "done" && "Uploaded"}
                    {item.status === "waiting" && "Ready"}
                    {item.status === "error" && (item.error || "Failed")}
                  </span>
                </div>
                <div style={{ width: "100%", height: "3px", background: "var(--border-color)", borderRadius: "2px", overflow: "hidden" }}>
                  <div
                    style={{
                      height: "100%",
                      width: `${item.progress}%`,
                      background: item.status === "error" ? "var(--danger-text)" : "var(--text-primary)",
                      transition: "width 0.2s ease",
                    }}
                  />
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Photo Gallery with Delete Buttons */}
      <div>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "1rem" }}>
          <h2 style={{ fontSize: "1.15rem", fontWeight: 600 }}>
            Gallery Photos ({eventPhotos.length})
          </h2>
          <button className="btn btn-secondary btn-sm" onClick={fetchPhotos}>
            Refresh
          </button>
        </div>

        {eventPhotos.length === 0 ? (
          <div className="card" style={{ textAlign: "center", padding: "3rem 1.5rem", color: "var(--text-secondary)", fontSize: "0.85rem" }}>
            No photos uploaded yet for this event.
          </div>
        ) : (
          <div className="photo-grid">
            {eventPhotos.map((photo) => (
              <div
                key={photo.id}
                className="card"
                style={{ padding: "0.5rem", display: "flex", flexDirection: "column" }}
              >
                <div
                  style={{
                    position: "relative",
                    width: "100%",
                    height: "180px",
                    borderRadius: "var(--radius-sm)",
                    overflow: "hidden",
                    backgroundColor: "var(--bg-primary)",
                  }}
                >
                  {/* eslint-disable-next-line @next/next/no-img-element */}
                  <img
                    src={photo.thumbnail_url || photo.url}
                    alt="Event photo"
                    style={{ width: "100%", height: "100%", objectFit: "cover" }}
                    loading="lazy"
                  />
                  <div style={{ position: "absolute", top: "6px", right: "6px" }}>
                    <span className={`badge badge-${photo.processing_status}`}>
                      {photo.processing_status}
                    </span>
                  </div>
                </div>

                <div
                  style={{
                    display: "flex",
                    justifyContent: "space-between",
                    alignItems: "center",
                    marginTop: "0.5rem",
                    padding: "0 0.15rem",
                  }}
                >
                  <span style={{ fontSize: "0.72rem", color: "var(--text-muted)", fontFamily: "var(--font-mono)" }}>
                    {new Date(photo.uploaded_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}
                  </span>

                  <div style={{ display: "flex", gap: "0.4rem", alignItems: "center" }}>
                    <a
                      href={photo.url}
                      target="_blank"
                      rel="noreferrer"
                      style={{ fontSize: "0.75rem", color: "var(--text-secondary)", textDecoration: "underline" }}
                    >
                      View
                    </a>
                    <button
                      onClick={() => setPhotoToDelete(photo.id)}
                      disabled={deletingPhotoId === photo.id}
                      className="btn btn-danger btn-sm"
                      style={{ padding: "0.15rem 0.45rem", fontSize: "0.7rem" }}
                      title="Delete photo"
                    >
                      {deletingPhotoId === photo.id ? "..." : "Delete"}
                    </button>
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Delete Photo Confirmation Modal */}
      {photoToDelete && (
        <div
          style={{
            position: "fixed",
            inset: 0,
            background: "rgba(10, 10, 9, 0.8)",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            padding: "1rem",
            zIndex: 100,
          }}
        >
          <div className="card" style={{ width: "100%", maxWidth: "400px", padding: "1.75rem" }}>
            <span className="eyebrow" style={{ color: "var(--danger-text)" }}>Delete Photo</span>
            <h3 style={{ fontSize: "1.1rem", fontWeight: 600, marginBottom: "0.5rem" }}>
              Remove this photo?
            </h3>
            <p style={{ color: "var(--text-secondary)", fontSize: "0.85rem", lineHeight: 1.5, marginBottom: "1.5rem" }}>
              This permanently deletes the original and thumbnail from storage, and removes all face recognition vectors.
            </p>
            <div style={{ display: "flex", gap: "0.75rem", justifyContent: "flex-end" }}>
              <button
                className="btn btn-secondary btn-sm"
                onClick={() => setPhotoToDelete(null)}
                disabled={Boolean(deletingPhotoId)}
              >
                Cancel
              </button>
              <button
                className="btn btn-danger btn-sm"
                onClick={confirmDeletePhoto}
                disabled={Boolean(deletingPhotoId)}
              >
                {deletingPhotoId ? "Deleting..." : "Confirm Delete"}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Delete Event Confirmation Modal */}
      {showDeleteEventModal && (
        <div
          style={{
            position: "fixed",
            inset: 0,
            background: "rgba(10, 10, 9, 0.8)",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            padding: "1rem",
            zIndex: 100,
          }}
        >
          <div className="card" style={{ width: "100%", maxWidth: "420px", padding: "1.75rem" }}>
            <span className="eyebrow" style={{ color: "var(--danger-text)" }}>Danger Zone</span>
            <h3 style={{ fontSize: "1.15rem", fontWeight: 600, marginBottom: "0.5rem" }}>
              Delete Event?
            </h3>
            <p style={{ color: "var(--text-secondary)", fontSize: "0.85rem", lineHeight: 1.5, marginBottom: "1.5rem" }}>
              Permanently delete &ldquo;{event?.name}&rdquo; and all {eventPhotos.length} photos? This cannot be undone.
            </p>
            <div style={{ display: "flex", gap: "0.75rem", justifyContent: "flex-end" }}>
              <button
                className="btn btn-secondary btn-sm"
                onClick={() => setShowDeleteEventModal(false)}
                disabled={isDeletingEvent}
              >
                Cancel
              </button>
              <button
                className="btn btn-danger btn-sm"
                onClick={confirmDeleteEvent}
                disabled={isDeletingEvent}
              >
                {isDeletingEvent ? "Deleting..." : "Confirm Delete"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
