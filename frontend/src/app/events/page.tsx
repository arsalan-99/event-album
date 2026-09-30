"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { API_BASE_URL } from "@/lib/api";

interface EventItem {
  id: string;
  name: string;
  event_date: string;
  created_at: string;
  photos_count: number;
  guests_count: number;
}

export default function AllEventsPage() {
  const [events, setEvents] = useState<EventItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [eventToDelete, setEventToDelete] = useState<{ id: string; name: string } | null>(null);

  async function fetchEvents() {
    try {
      setLoading(true);
      setError(null);
      const res = await fetch(`${API_BASE_URL}/api/events`);
      if (!res.ok) throw new Error("Failed to load events");
      const data = await res.json();
      setEvents(data);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Error fetching events");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    fetchEvents();
  }, []);

  async function confirmDeleteEvent(id: string) {
    try {
      setDeletingId(id);
      const res = await fetch(`${API_BASE_URL}/api/events/${id}`, {
        method: "DELETE",
      });
      if (!res.ok) {
        throw new Error("Failed to delete event");
      }
      setEvents((prev) => prev.filter((e) => e.id !== id));
      setEventToDelete(null);
    } catch (err: unknown) {
      alert(err instanceof Error ? err.message : "Failed to delete event");
    } finally {
      setDeletingId(null);
    }
  }

  return (
    <div className="container" style={{ maxWidth: "900px" }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-end", marginBottom: "2rem" }}>
        <div>
          <span className="eyebrow">Overview</span>
          <h1 style={{ fontSize: "1.85rem", fontWeight: 600 }}>All Events</h1>
        </div>
        <Link href="/events/new" className="btn btn-primary">
          + Create Event
        </Link>
      </div>

      {error && <div className="alert alert-error">{error}</div>}

      {loading ? (
        <div className="card" style={{ textAlign: "center", padding: "3rem" }}>
          <span className="spinner"></span>
          <p style={{ marginTop: "0.75rem", color: "var(--text-secondary)", fontSize: "0.85rem" }}>
            Loading events...
          </p>
        </div>
      ) : events.length === 0 ? (
        <div className="card" style={{ textAlign: "center", padding: "3.5rem 1.5rem" }}>
          <p style={{ color: "var(--text-secondary)", marginBottom: "1.25rem", fontSize: "0.95rem" }}>
            No events found.
          </p>
          <Link href="/events/new" className="btn btn-primary">
            Create First Event
          </Link>
        </div>
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: "0.85rem" }}>
          {events.map((ev) => (
            <div
              key={ev.id}
              className="card"
              style={{
                display: "flex",
                justifyContent: "space-between",
                alignItems: "center",
                flexWrap: "wrap",
                gap: "1rem",
                padding: "1.25rem 1.5rem",
              }}
            >
              <div>
                <div style={{ display: "flex", alignItems: "center", gap: "0.75rem", marginBottom: "0.25rem" }}>
                  <h3 style={{ fontSize: "1.1rem", fontWeight: 600 }}>{ev.name}</h3>
                  <span className="badge">
                    {ev.photos_count} photo{ev.photos_count !== 1 ? "s" : ""}
                  </span>
                </div>
                <div style={{ fontSize: "0.8rem", color: "var(--text-secondary)" }}>
                  Date: {ev.event_date} &bull; ID: <span style={{ fontFamily: "var(--font-mono)" }}>{ev.id.substring(0, 8)}</span>
                </div>
              </div>

              <div style={{ display: "flex", alignItems: "center", gap: "0.6rem" }}>
                <Link href={`/events/${ev.id}`} className="btn btn-secondary btn-sm">
                  Guest View
                </Link>
                <Link href={`/events/${ev.id}/upload`} className="btn btn-secondary btn-sm">
                  Upload & Manage
                </Link>
                <button
                  onClick={() => setEventToDelete({ id: ev.id, name: ev.name })}
                  className="btn btn-danger btn-sm"
                  title="Delete event"
                >
                  Delete
                </button>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* In-UI Confirmation Modal */}
      {eventToDelete && (
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
              Permanently delete &ldquo;{eventToDelete.name}&rdquo;? All photos, face embeddings, and storage records will be removed immediately.
            </p>
            <div style={{ display: "flex", gap: "0.75rem", justifyContent: "flex-end" }}>
              <button
                className="btn btn-secondary btn-sm"
                onClick={() => setEventToDelete(null)}
                disabled={Boolean(deletingId)}
              >
                Cancel
              </button>
              <button
                className="btn btn-danger btn-sm"
                onClick={() => confirmDeleteEvent(eventToDelete.id)}
                disabled={Boolean(deletingId)}
              >
                {deletingId ? "Deleting..." : "Confirm Delete"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
