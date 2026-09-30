"use client";

import { useEffect, useState, useRef, use } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import JSZip from "jszip";
import { API_BASE_URL } from "@/lib/api";

interface EventData {
  id: string;
  name: string;
  event_date: string;
  photos_count: number;
}

interface MatchedPhoto {
  photo_id: string;
  similarity: number;
  r2_object_key?: string;
  thumbnail_url?: string;
  photo_url?: string;
}

export default function GuestEventPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id: eventId } = use(params);
  const router = useRouter();

  const [event, setEvent] = useState<EventData | null>(null);
  const [loadingEvent, setLoadingEvent] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Camera & Selfie Modal
  const [showCameraModal, setShowCameraModal] = useState(false);
  const [cameraStream, setCameraStream] = useState<MediaStream | null>(null);
  const [capturedSelfies, setCapturedSelfies] = useState<Blob[]>([]);
  const [guestName, setGuestName] = useState("");
  const [cameraError, setCameraError] = useState<string | null>(null);

  // Matching & Results
  const [isProcessing, setIsProcessing] = useState(false);
  const [processingStep, setProcessingStep] = useState<string>("");
  const [matchedPhotos, setMatchedPhotos] = useState<MatchedPhoto[] | null>(null);
  const [isZipping, setIsZipping] = useState(false);
  const [isDeleting, setIsDeleting] = useState(false);

  const videoRef = useRef<HTMLVideoElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const fallbackFileRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    async function fetchEvent() {
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
    fetchEvent();
  }, [eventId]);

  useEffect(() => {
    return () => {
      if (cameraStream) {
        cameraStream.getTracks().forEach((t) => t.stop());
      }
    };
  }, [cameraStream]);

  async function startCamera() {
    setCameraError(null);
    setShowCameraModal(true);
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        video: {
          facingMode: "user",
          width: { ideal: 640 },
          height: { ideal: 640 },
        },
        audio: false,
      });
      setCameraStream(stream);
      if (videoRef.current) {
        videoRef.current.srcObject = stream;
        videoRef.current.play();
      }
    } catch {
      setCameraError("Camera unavailable. You can upload a photo from your device.");
    }
  }

  function stopCamera() {
    if (cameraStream) {
      cameraStream.getTracks().forEach((t) => t.stop());
      setCameraStream(null);
    }
    setShowCameraModal(false);
  }

  function captureSnapshot() {
    if (!videoRef.current || !canvasRef.current) return;
    const video = videoRef.current;
    const canvas = canvasRef.current;
    canvas.width = video.videoWidth || 480;
    canvas.height = video.videoHeight || 480;

    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    ctx.drawImage(video, 0, 0, canvas.width, canvas.height);

    canvas.toBlob(
      (blob) => {
        if (blob) {
          setCapturedSelfies((prev) => [...prev, blob].slice(0, 3));
        }
      },
      "image/jpeg",
      0.9
    );
  }

  function handleFallbackFiles(e: React.ChangeEvent<HTMLInputElement>) {
    if (e.target.files) {
      const files = Array.from(e.target.files).slice(0, 3);
      setCapturedSelfies(files);
    }
  }

  async function handleFindPhotos() {
    if (capturedSelfies.length === 0) return;

    stopCamera();
    setIsProcessing(true);
    setError(null);
    setProcessingStep("Analyzing face vectors in memory...");

    try {
      const formData = new FormData();
      if (guestName.trim()) {
        formData.append("name", guestName.trim());
      }
      capturedSelfies.forEach((blob, i) => {
        formData.append("files", blob, `selfie_${i + 1}.jpg`);
      });

      const enrollRes = await fetch(
        `${API_BASE_URL}/api/events/${eventId}/guests/enroll`,
        {
          method: "POST",
          body: formData,
        }
      );

      if (!enrollRes.ok) {
        const errJson = await enrollRes.json().catch(() => ({}));
        throw new Error(errJson.detail || "Failed to scan selfie");
      }

      const enrollData = await enrollRes.json();
      const guestId = enrollData.guest_id;

      setProcessingStep("Searching event gallery...");
      const matchRes = await fetch(
        `${API_BASE_URL}/api/events/${eventId}/guests/${guestId}/match`,
        {
          method: "POST",
        }
      );

      if (!matchRes.ok) {
        const errJson = await matchRes.json().catch(() => ({}));
        throw new Error(errJson.detail || "Failed to match photos");
      }

      const matchData = await matchRes.json();
      setMatchedPhotos(matchData.matches || []);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Error during face search");
    } finally {
      setIsProcessing(false);
      setProcessingStep("");
    }
  }

  async function downloadAllZip() {
    if (!matchedPhotos || matchedPhotos.length === 0) return;
    setIsZipping(true);
    try {
      const zip = new JSZip();
      const folder = zip.folder("photos");

      for (let i = 0; i < matchedPhotos.length; i++) {
        const p = matchedPhotos[i];
        if (!p.photo_url) continue;
        const res = await fetch(p.photo_url);
        const blob = await res.blob();
        folder?.file(`photo_${i + 1}_${p.photo_id.substring(0, 8)}.jpg`, blob);
      }

      const content = await zip.generateAsync({ type: "blob" });
      const downloadUrl = URL.createObjectURL(content);
      const a = document.createElement("a");
      a.href = downloadUrl;
      a.download = `${event?.name || "event"}-matched-photos.zip`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(downloadUrl);
    } catch {
      alert("Failed to build ZIP archive. You can download individual photos directly.");
    } finally {
      setIsZipping(false);
    }
  }

  const [showDeleteEventModal, setShowDeleteEventModal] = useState(false);

  async function confirmDeleteEvent() {
    if (!event) return;
    try {
      setIsDeleting(true);
      const res = await fetch(`${API_BASE_URL}/api/events/${eventId}`, {
        method: "DELETE",
      });
      if (!res.ok) throw new Error("Failed to delete event");
      router.push("/events");
    } catch (err: unknown) {
      alert(err instanceof Error ? err.message : "Failed to delete event");
      setIsDeleting(false);
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
    <div className="container" style={{ maxWidth: "860px" }}>
      {/* Navigation breadcrumb bar */}
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
          <Link href={`/events/${eventId}/upload`} className="btn btn-secondary btn-sm">
            Photographer Upload
          </Link>
          <button
            onClick={() => setShowDeleteEventModal(true)}
            disabled={isDeleting}
            className="btn btn-danger btn-sm"
          >
            {isDeleting ? "Deleting..." : "Delete Event"}
          </button>
        </div>
      </div>

      {/* Main Event Card */}
      <div className="card" style={{ padding: "2.5rem 2rem", marginBottom: "2rem" }}>
        <span className="eyebrow">Guest Portal &bull; Face Search</span>
        <h1 style={{ fontSize: "2rem", fontWeight: 600, marginBottom: "0.4rem" }}>
          {event?.name}
        </h1>
        <p style={{ color: "var(--text-secondary)", fontSize: "0.9rem", marginBottom: "1.75rem" }}>
          Date: {event?.event_date} &bull; {event?.photos_count || 0} Photos in Gallery
        </p>

        <div style={{ display: "flex", gap: "0.75rem", flexWrap: "wrap", alignItems: "center" }}>
          <button
            id="findMyPhotosBtn"
            className="btn btn-primary"
            style={{ padding: "0.75rem 1.75rem", fontSize: "0.95rem" }}
            onClick={startCamera}
            disabled={isProcessing}
          >
            Upload Selfie
          </button>
          <button
            className="btn btn-secondary"
            onClick={() => fallbackFileRef.current?.click()}
            disabled={isProcessing}
          >
            Upload Selfie from Device
          </button>
          <input
            type="file"
            ref={fallbackFileRef}
            accept="image/*"
            multiple
            style={{ display: "none" }}
            onChange={handleFallbackFiles}
          />
        </div>

        {capturedSelfies.length > 0 && !showCameraModal && (
          <div style={{ marginTop: "1.25rem", padding: "1rem", background: "var(--bg-surface)", borderRadius: "var(--radius-sm)" }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "0.5rem" }}>
              <span style={{ fontSize: "0.8rem", color: "var(--text-secondary)" }}>
                Selected {capturedSelfies.length} selfie file(s):
              </span>
              <button
                onClick={() => setCapturedSelfies([])}
                style={{ background: "none", border: "none", color: "var(--danger-text)", fontSize: "0.75rem", cursor: "pointer" }}
              >
                Clear
              </button>
            </div>
            <button
              className="btn btn-primary btn-sm"
              onClick={handleFindPhotos}
              disabled={isProcessing}
            >
              Run Search Now
            </button>
          </div>
        )}

        <p style={{ marginTop: "1.25rem", fontSize: "0.75rem", color: "var(--text-muted)", lineHeight: 1.5 }}>
          Privacy Notice: Your selfie is processed strictly in temporary memory to generate a 128-dimensional mathematical vector.
          Raw photos are immediately discarded and never written to storage.
        </p>
      </div>

      {error && <div className="alert alert-error">{error}</div>}

      {/* Processing State */}
      {isProcessing && (
        <div className="card" style={{ textAlign: "center", padding: "2.5rem 1.5rem", marginBottom: "2rem" }}>
          <span className="spinner" style={{ width: "1.5rem", height: "1.5rem" }}></span>
          <h3 style={{ fontSize: "1rem", fontWeight: 600, marginTop: "1rem", marginBottom: "0.25rem" }}>
            Processing Search
          </h3>
          <p style={{ color: "var(--text-secondary)", fontSize: "0.85rem" }}>{processingStep}</p>
        </div>
      )}

      {/* Results Section */}
      {matchedPhotos !== null && !isProcessing && (
        <div>
          <div
            style={{
              display: "flex",
              justifyContent: "space-between",
              alignItems: "flex-end",
              flexWrap: "wrap",
              gap: "1rem",
              marginBottom: "1.25rem",
              borderBottom: "1px solid var(--border-color)",
              paddingBottom: "0.75rem",
            }}
          >
            <div>
              <span className="eyebrow">Results</span>
              <h2 style={{ fontSize: "1.35rem", fontWeight: 600 }}>
                {matchedPhotos.length > 0
                  ? `Found ${matchedPhotos.length} Photo${matchedPhotos.length > 1 ? "s" : ""}`
                  : "No Matching Photos"}
              </h2>
            </div>

            {matchedPhotos.length > 0 && (
              <button
                id="downloadAllZipBtn"
                className="btn btn-primary btn-sm"
                onClick={downloadAllZip}
                disabled={isZipping}
              >
                {isZipping ? (
                  <>
                    <span className="spinner"></span> Archiving...
                  </>
                ) : (
                  "Download All (ZIP)"
                )}
              </button>
            )}
          </div>

          {matchedPhotos.length === 0 ? (
            <div className="card" style={{ textAlign: "center", padding: "3rem 1.5rem" }}>
              <p style={{ color: "var(--text-secondary)", fontSize: "0.9rem", marginBottom: "1rem" }}>
                No photos matched above the similarity threshold.
              </p>
              <button className="btn btn-secondary btn-sm" onClick={startCamera}>
                Try Another Photo
              </button>
            </div>
          ) : (
            <div className="photo-grid">
              {matchedPhotos.map((photo, index) => (
                <div
                  key={photo.photo_id}
                  className="card"
                  style={{ padding: "0.5rem", display: "flex", flexDirection: "column" }}
                >
                  <div
                    style={{
                      position: "relative",
                      width: "100%",
                      height: "220px",
                      borderRadius: "var(--radius-sm)",
                      overflow: "hidden",
                      backgroundColor: "var(--bg-primary)",
                    }}
                  >
                    {/* eslint-disable-next-line @next/next/no-img-element */}
                    <img
                      src={photo.thumbnail_url || photo.photo_url}
                      alt={`Match ${index + 1}`}
                      style={{ width: "100%", height: "100%", objectFit: "cover" }}
                      loading="lazy"
                    />
                    <div style={{ position: "absolute", top: "6px", right: "6px" }}>
                      <span className="badge badge-done">
                        {Math.round(photo.similarity * 100)}% match
                      </span>
                    </div>
                  </div>

                  <div
                    style={{
                      marginTop: "0.6rem",
                      display: "flex",
                      justifyContent: "space-between",
                      alignItems: "center",
                      padding: "0 0.2rem",
                    }}
                  >
                    <span style={{ fontSize: "0.75rem", color: "var(--text-muted)", fontFamily: "var(--font-mono)" }}>
                      #{index + 1}
                    </span>
                    <a
                      href={photo.photo_url}
                      download={`photo-${index + 1}.jpg`}
                      target="_blank"
                      rel="noreferrer"
                      className="btn btn-secondary btn-sm"
                      style={{ fontSize: "0.75rem", padding: "0.25rem 0.6rem" }}
                    >
                      Download
                    </a>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* Selfie Capture Modal */}
      {showCameraModal && (
        <div
          style={{
            position: "fixed",
            inset: 0,
            background: "rgba(10, 10, 9, 0.85)",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            padding: "1rem",
            zIndex: 100,
          }}
        >
          <div
            className="card"
            style={{
              width: "100%",
              maxWidth: "460px",
              padding: "1.5rem",
              background: "var(--bg-secondary)",
            }}
          >
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "1rem" }}>
              <h3 style={{ fontSize: "1rem", fontWeight: 600 }}>Take Reference Photo</h3>
              <button
                onClick={stopCamera}
                style={{ background: "transparent", border: "none", color: "var(--text-muted)", fontSize: "1.2rem", cursor: "pointer" }}
              >
                &times;
              </button>
            </div>

            {cameraError && (
              <div className="alert alert-error" style={{ marginBottom: "1rem" }}>
                {cameraError}
              </div>
            )}

            <div
              style={{
                position: "relative",
                width: "100%",
                height: "280px",
                borderRadius: "var(--radius-sm)",
                overflow: "hidden",
                background: "#000",
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
              }}
            >
              <video
                ref={videoRef}
                autoPlay
                playsInline
                muted
                style={{ width: "100%", height: "100%", objectFit: "cover" }}
              />
              <canvas ref={canvasRef} style={{ display: "none" }} />

              {cameraStream && (
                <button
                  onClick={captureSnapshot}
                  disabled={capturedSelfies.length >= 3}
                  style={{
                    position: "absolute",
                    bottom: "1rem",
                    width: "50px",
                    height: "50px",
                    borderRadius: "50%",
                    background: "#ffffff",
                    border: "3px solid #141413",
                    cursor: "pointer",
                  }}
                  title="Capture"
                />
              )}
            </div>

            {capturedSelfies.length > 0 && (
              <div style={{ marginTop: "0.85rem" }}>
                <span style={{ fontSize: "0.75rem", color: "var(--text-secondary)", display: "block", marginBottom: "0.4rem" }}>
                  Captured ({capturedSelfies.length}/3 photos):
                </span>
                <div style={{ display: "flex", gap: "0.5rem" }}>
                  {capturedSelfies.map((blob, i) => (
                    <div
                      key={i}
                      style={{
                        position: "relative",
                        width: "54px",
                        height: "54px",
                        borderRadius: "var(--radius-sm)",
                        overflow: "hidden",
                        border: "1px solid var(--border-color)",
                      }}
                    >
                      {/* eslint-disable-next-line @next/next/no-img-element */}
                      <img
                        src={URL.createObjectURL(blob)}
                        alt={`Photo ${i + 1}`}
                        style={{ width: "100%", height: "100%", objectFit: "cover" }}
                      />
                      <button
                        onClick={() =>
                          setCapturedSelfies((prev) => prev.filter((_, idx) => idx !== i))
                        }
                        style={{
                          position: "absolute",
                          top: "2px",
                          right: "2px",
                          background: "rgba(0,0,0,0.8)",
                          color: "#fff",
                          border: "none",
                          borderRadius: "50%",
                          width: "16px",
                          height: "16px",
                          fontSize: "10px",
                          cursor: "pointer",
                        }}
                      >
                        &times;
                      </button>
                    </div>
                  ))}
                </div>
              </div>
            )}

            <div className="form-group" style={{ marginTop: "0.85rem", marginBottom: "0" }}>
              <input
                type="text"
                className="form-input"
                placeholder="Your Name (optional)"
                value={guestName}
                onChange={(e) => setGuestName(e.target.value)}
                style={{ fontSize: "0.8rem", padding: "0.5rem 0.75rem" }}
              />
            </div>

            <div style={{ display: "flex", gap: "0.75rem", marginTop: "1.25rem" }}>
              <button className="btn btn-secondary" style={{ flex: 1 }} onClick={stopCamera}>
                Cancel
              </button>
              <button
                id="searchPhotosModalBtn"
                className="btn btn-primary"
                style={{ flex: 2 }}
                onClick={handleFindPhotos}
                disabled={capturedSelfies.length === 0}
              >
                Search ({capturedSelfies.length})
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Delete Event In-UI Modal */}
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
              Permanently delete &ldquo;{event?.name}&rdquo;? All photos and search records will be removed immediately.
            </p>
            <div style={{ display: "flex", gap: "0.75rem", justifyContent: "flex-end" }}>
              <button
                className="btn btn-secondary btn-sm"
                onClick={() => setShowDeleteEventModal(false)}
                disabled={isDeleting}
              >
                Cancel
              </button>
              <button
                className="btn btn-danger btn-sm"
                onClick={confirmDeleteEvent}
                disabled={isDeleting}
              >
                {isDeleting ? "Deleting..." : "Confirm Delete"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
