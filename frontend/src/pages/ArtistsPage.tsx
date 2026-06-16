// ABOUTME: Main page — manage tracked artists and view check history.
// ABOUTME: Add/remove artists, toggle active, live check run feed.

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRef, useState } from "react";
import {
  addArtist,
  deleteArtist,
  getChecks,
  listArtists,
  streamCheck,
  toggleArtist,
  type Artist,
  type CheckEvent,
  type CheckResult,
} from "../api";

type HitEntry = { handle: string; hits: NonNullable<CheckEvent["hits"]> };
type ScanMeta = { scanned_to: string; scanned_to_handle: string; scanned_to_preview: string };
type LogLine = { level: string; message: string };

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

// ── Feed scan result panel ────────────────────────────────────────────────────

function ScanResult({
  hits,
  watching,
  isRunning,
  currentPost,
  scanCount,
  logs,
  meta,
  onClose,
}: {
  hits: HitEntry[];
  watching: number;
  isRunning: boolean;
  currentPost: { handle: string; taken_at: string; caption_snippet: string } | null;
  scanCount: number;
  logs: LogLine[];
  meta: ScanMeta | null;
  onClose: () => void;
}) {
  return (
    <div className="check-feed">
      <div className="check-feed-header">
        <span className="check-feed-title">
          {isRunning
            ? `Scanning feed… (watching ${watching} artists)`
            : hits.length > 0
              ? `Found ${hits.length} artist${hits.length === 1 ? "" : "s"} with booking posts`
              : "Feed scanned — no booking posts found"}
        </span>
        {!isRunning && (
          <button className="btn-ghost" onClick={onClose}>Dismiss</button>
        )}
      </div>

      {isRunning && (
        <div className="scan-current-post">
          {currentPost ? (
            <>
              <span className="scan-current-count">{scanCount}</span>
              <span className="scan-current-handle">@{currentPost.handle}</span>
              <span className="scan-current-date">{formatDate(currentPost.taken_at)}</span>
              {currentPost.caption_snippet && (
                <span className="scan-current-caption">"{currentPost.caption_snippet}"</span>
              )}
            </>
          ) : (
            <span className="scan-current-handle">connecting…</span>
          )}
        </div>
      )}

      {hits.length > 0 && (
        <div className="feed-entries">
          {hits.map((e, i) => (
            <div key={i} className="feed-entry">
              <span className="feed-handle">@{e.handle}</span>
              <span className="feed-status hit">
                📬 {e.hits.map(h => `"${h.keyword}"`).join(", ")}
              </span>
            </div>
          ))}
        </div>
      )}

      {logs.length > 0 && (
        <div className="scan-logs">
          {logs.map((l, i) => (
            <div key={i} className={`scan-log-line scan-log-${l.level.toLowerCase()}`}>
              {l.message}
            </div>
          ))}
        </div>
      )}

      {!isRunning && meta && (
        <div className="scan-coverage">
          Scanned back to {formatDate(meta.scanned_to)}
          {meta.scanned_to_handle && (
            <> · last: @{meta.scanned_to_handle}{meta.scanned_to_preview ? `: "${meta.scanned_to_preview}"` : ""}</>
          )}
        </div>
      )}
    </div>
  );
}

// ── Check history panel ──────────────────────────────────────────────────────

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

// ── Artist card ───────────────────────────────────────────────────────────────

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
        <span className="artist-meta">
          {artist.last_post_url
            ? <a className="artist-link" href={artist.last_post_url} target="_blank" rel="noreferrer" onClick={(e) => e.stopPropagation()}>last post {formatDate(artist.last_post_at)} ↗</a>
            : <span>checked {formatDate(artist.last_checked_at)}</span>
          }
        </span>
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

// ── Page ──────────────────────────────────────────────────────────────────────

export default function ArtistsPage() {
  const qc = useQueryClient();
  const [handle, setHandle] = useState("");
  const [addError, setAddError] = useState("");

  const [scanHits, setScanHits] = useState<HitEntry[]>([]);
  const [watching, setWatching] = useState(0);
  const [isChecking, setIsChecking] = useState(false);
  const [showScan, setShowScan] = useState(false);
  const [checkError, setCheckError] = useState("");
  const [scanMeta, setScanMeta] = useState<ScanMeta | null>(null);
  const [currentPost, setCurrentPost] = useState<{ handle: string; taken_at: string; caption_snippet: string } | null>(null);
  const [scanLogs, setScanLogs] = useState<LogLine[]>([]);
  const [scanCount, setScanCount] = useState(0);
  const pendingPostRef = useRef<{ handle: string; taken_at: string; caption_snippet: string } | null>(null);
  const rafRef = useRef<number | null>(null);

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

  function handleAdd(e: React.FormEvent) {
    e.preventDefault();
    if (!handle.trim()) return;
    setAddError("");
    addMut.mutate();
  }

  function startCheck() {
    setScanHits([]);
    setWatching(0);
    setCheckError("");
    setScanMeta(null);
    setCurrentPost(null);
    setScanCount(0);
    setScanLogs([]);
    pendingPostRef.current = null;
    if (rafRef.current) cancelAnimationFrame(rafRef.current);
    setIsChecking(true);
    setShowScan(true);

    streamCheck(
      (event) => {
        if (event.type === "start") {
          setWatching(event.watching ?? 0);
        } else if (event.type === "log") {
          setScanLogs((prev) => [...prev, { level: event.level ?? "INFO", message: event.message ?? "" }]);
        } else if (event.type === "scanning") {
          pendingPostRef.current = {
            handle: event.handle!,
            taken_at: event.taken_at!,
            caption_snippet: event.caption_snippet ?? "",
          };
          setScanCount((n) => n + 1);
          if (!rafRef.current) {
            rafRef.current = requestAnimationFrame(() => {
              rafRef.current = null;
              setCurrentPost(pendingPostRef.current);
            });
          }
        } else if (event.type === "result" && event.status === "hit") {
          setScanHits((prev) => [...prev, { handle: event.handle!, hits: event.hits ?? [] }]);
        } else if (event.type === "done" && event.scanned_to) {
          setScanMeta({
            scanned_to: event.scanned_to,
            scanned_to_handle: event.scanned_to_handle ?? "",
            scanned_to_preview: event.scanned_to_preview ?? "",
          });
        }
      },
      () => {
        setIsChecking(false);
        qc.invalidateQueries({ queryKey: ["artists"] });
      },
      (msg) => {
        setIsChecking(false);
        setCheckError(msg);
      },
    );
  }

  return (
    <div>
      <div className="page-header">
        <h1>Artists</h1>
        <button className="btn-sm" onClick={startCheck} disabled={isChecking}>
          {isChecking ? "Checking…" : "Check now"}
        </button>
      </div>

      {checkError && <div className="error-msg" style={{ marginBottom: "1rem" }}>{checkError}</div>}

      {showScan && (
        <ScanResult
          hits={scanHits}
          watching={watching}
          isRunning={isChecking}
          currentPost={currentPost}
          scanCount={scanCount}
          logs={scanLogs}
          meta={scanMeta}
          onClose={() => setShowScan(false)}
        />
      )}

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
