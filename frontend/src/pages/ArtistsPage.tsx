// ABOUTME: Main page — manage tracked artists and view check history.
// ABOUTME: Add/remove artists, toggle active, expand rows for check history.

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import {
  addArtist,
  deleteArtist,
  getChecks,
  listArtists,
  toggleArtist,
  triggerRun,
  type Artist,
  type CheckResult,
} from "../api";

function statusLabel(status: Artist["last_status"]) {
  switch (status) {
    case "hit": return "📬 Books may be open";
    case "ok": return "✓ No keywords found";
    case "error": return "⚠ Check failed";
    case "pending": return "Not checked yet";
  }
}

function statusClass(status: Artist["last_status"]) {
  return `status-badge status-${status}`;
}

function formatDate(iso: string | null) {
  if (!iso) return "never";
  const d = new Date(iso + (iso.endsWith("Z") ? "" : "Z"));
  return d.toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
}

function ChecksPanel({ artistId }: { artistId: number }) {
  const { data: checks, isLoading } = useQuery<CheckResult[]>({
    queryKey: ["checks", artistId],
    queryFn: () => getChecks(artistId),
  });

  if (isLoading) return <div className="checks-panel"><span className="checks-loading">Loading…</span></div>;
  if (!checks || checks.length === 0) return <div className="checks-panel"><span className="checks-empty">No checks yet.</span></div>;

  return (
    <div className="checks-panel">
      <div className="check-list">
        {checks.map((c) => (
          <div key={c.id} className="check-row">
            <span className="check-time">{formatDate(c.checked_at)}</span>
            <div className="check-detail">
              {c.status === "hit" && (
                <>
                  <div className="check-keyword">"{c.keyword_found}"</div>
                  {c.caption_snippet && <div className="check-snippet">"{c.caption_snippet}"</div>}
                  {c.post_url && <a className="check-post-link" href={c.post_url} target="_blank" rel="noreferrer">View post →</a>}
                </>
              )}
              {c.status === "ok" && <span style={{ color: "var(--muted)" }}>No keywords found</span>}
              {c.status === "error" && <span className="check-error">{c.error_message}</span>}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function ArtistCard({ artist }: { artist: Artist }) {
  const qc = useQueryClient();
  const [expanded, setExpanded] = useState(false);

  const deleteMut = useMutation({
    mutationFn: () => deleteArtist(artist.id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["artists"] }),
  });

  const toggleMut = useMutation({
    mutationFn: () => toggleArtist(artist.id, !artist.active),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["artists"] }),
  });

  return (
    <div className={`artist-card${artist.active ? "" : " inactive"}`}>
      <div className="artist-row" onClick={() => setExpanded((e) => !e)}>
        <span className="artist-handle">
          @{artist.handle}
          {" "}
          <a
            className="artist-link"
            href={`https://www.instagram.com/${artist.handle}/`}
            target="_blank"
            rel="noreferrer"
            onClick={(e) => e.stopPropagation()}
          >
            IG ↗
          </a>
        </span>
        <span className={statusClass(artist.last_status)}>{statusLabel(artist.last_status)}</span>
        <span className="artist-meta">{formatDate(artist.last_checked_at)}</span>
        <div className="artist-actions" onClick={(e) => e.stopPropagation()}>
          <button
            className="btn-sm"
            onClick={() => toggleMut.mutate()}
            disabled={toggleMut.isPending}
          >
            {artist.active ? "Pause" : "Resume"}
          </button>
          <button
            className="btn-sm btn-danger"
            onClick={() => { if (confirm(`Remove @${artist.handle}?`)) deleteMut.mutate(); }}
            disabled={deleteMut.isPending}
          >
            Remove
          </button>
        </div>
      </div>
      {expanded && <ChecksPanel artistId={artist.id} />}
    </div>
  );
}

export default function ArtistsPage() {
  const qc = useQueryClient();
  const [handle, setHandle] = useState("");
  const [addError, setAddError] = useState("");
  const [runTriggered, setRunTriggered] = useState(false);

  const { data: artists, isLoading } = useQuery<Artist[]>({
    queryKey: ["artists"],
    queryFn: listArtists,
  });

  const addMut = useMutation({
    mutationFn: () => addArtist(handle),
    onSuccess: () => {
      setHandle("");
      setAddError("");
      qc.invalidateQueries({ queryKey: ["artists"] });
    },
    onError: (e: unknown) => {
      const msg = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail ?? "Failed to add artist";
      setAddError(msg);
    },
  });

  const runMut = useMutation({
    mutationFn: triggerRun,
    onSuccess: () => {
      setRunTriggered(true);
      setTimeout(() => setRunTriggered(false), 5000);
    },
  });

  function handleAdd(e: React.FormEvent) {
    e.preventDefault();
    if (!handle.trim()) return;
    setAddError("");
    addMut.mutate();
  }

  return (
    <div>
      <div className="page-header">
        <h1>Artists</h1>
        <button
          className="btn-sm"
          onClick={() => runMut.mutate()}
          disabled={runMut.isPending || runTriggered}
        >
          {runTriggered ? "Check started…" : "Check now"}
        </button>
      </div>

      <form className="add-form" onSubmit={handleAdd}>
        <input
          value={handle}
          onChange={(e) => setHandle(e.target.value)}
          placeholder="Instagram handle (e.g. artist_name)"
          disabled={addMut.isPending}
        />
        <button type="submit" disabled={addMut.isPending || !handle.trim()}>
          Add
        </button>
      </form>
      {addError && <div className="error-msg">{addError}</div>}

      {isLoading && <div style={{ color: "var(--muted)" }}>Loading…</div>}

      {artists && artists.length === 0 && (
        <div className="empty">No artists yet. Add an Instagram handle above.</div>
      )}

      {artists && artists.length > 0 && (
        <div className="artist-list">
          {artists.map((a) => <ArtistCard key={a.id} artist={a} />)}
        </div>
      )}
    </div>
  );
}
