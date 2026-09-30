"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { API_BASE_URL } from "@/lib/api";

export default function NewEventPage() {
  const router = useRouter();
  const [name, setName] = useState("");
  const [date, setDate] = useState(() => new Date().toISOString().split("T")[0]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!name.trim()) {
      setError("Please provide an event name");
      return;
    }

    setLoading(true);
    setError(null);

    try {
      const res = await fetch(`${API_BASE_URL}/api/events`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name: name.trim(),
          event_date: date,
        }),
      });

      if (!res.ok) {
        const errJson = await res.json().catch(() => ({}));
        throw new Error(errJson.detail || `Failed to create event (HTTP ${res.status})`);
      }

      const created = await res.json();
      router.push(`/events/${created.id}`);
    } catch (err: unknown) {
      if (err instanceof Error) {
        setError(err.message);
      } else {
        setError("An unexpected error occurred");
      }
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="container" style={{ maxWidth: "520px", paddingTop: "2.5rem" }}>
      <div style={{ marginBottom: "1.5rem" }}>
        <Link href="/events" style={{ fontSize: "0.8rem", color: "var(--text-secondary)" }}>
          &larr; Back to All Events
        </Link>
      </div>

      <div className="card">
        <span className="eyebrow">New Collection</span>
        <h1 style={{ fontSize: "1.5rem", marginBottom: "0.4rem", fontWeight: 600 }}>
          Create Event
        </h1>
        <p style={{ color: "var(--text-secondary)", marginBottom: "1.75rem", fontSize: "0.85rem" }}>
          Set up an album space for guests and photographers.
        </p>

        {error && <div className="alert alert-error">{error}</div>}

        <form onSubmit={handleSubmit}>
          <div className="form-group">
            <label className="form-label" htmlFor="eventName">
              Event Name
            </label>
            <input
              id="eventName"
              type="text"
              className="form-input"
              placeholder="e.g. Annual Gala 2026"
              value={name}
              onChange={(e) => setName(e.target.value)}
              disabled={loading}
              required
            />
          </div>

          <div className="form-group">
            <label className="form-label" htmlFor="eventDate">
              Event Date
            </label>
            <input
              id="eventDate"
              type="date"
              className="form-input"
              value={date}
              onChange={(e) => setDate(e.target.value)}
              disabled={loading}
              required
            />
          </div>

          <div style={{ display: "flex", gap: "0.75rem", marginTop: "1.5rem" }}>
            <Link href="/events" className="btn btn-secondary" style={{ flex: 1 }}>
              Cancel
            </Link>
            <button
              type="submit"
              className="btn btn-primary"
              style={{ flex: 2 }}
              disabled={loading}
            >
              {loading ? (
                <>
                  <span className="spinner"></span> Creating...
                </>
              ) : (
                "Create Event"
              )}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
