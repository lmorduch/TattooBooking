// ABOUTME: Typed API client for all backend endpoints.
// ABOUTME: Uses axios with a base URL from env var.

import axios from "axios";

const api = axios.create({
  baseURL: import.meta.env.VITE_API_URL ?? "",
});

export interface User {
  id: number;
  email: string;
  name: string;
  picture: string | null;
  has_instagram: boolean;
  instagram_username: string | null;
}

export interface Artist {
  id: number;
  handle: string;
  active: boolean;
  last_checked_at: string | null;
  last_status: "pending" | "ok" | "hit" | "error";
  consecutive_errors: number;
  created_at: string;
}

export interface CheckResult {
  id: number;
  checked_at: string;
  status: "ok" | "hit" | "error";
  keyword_found: string | null;
  post_url: string | null;
  caption_snippet: string | null;
  error_message: string | null;
}

export async function getMe(): Promise<User> {
  const r = await api.get<User>("/auth/me");
  return r.data;
}

export async function logout(): Promise<void> {
  await api.post("/auth/logout");
}

export async function listArtists(): Promise<Artist[]> {
  const r = await api.get<Artist[]>("/artists");
  return r.data;
}

export async function addArtist(handle: string): Promise<Artist> {
  const r = await api.post<Artist>("/artists", { handle });
  return r.data;
}

export async function deleteArtist(id: number): Promise<void> {
  await api.delete(`/artists/${id}`);
}

export async function toggleArtist(id: number, active: boolean): Promise<Artist> {
  const r = await api.patch<Artist>(`/artists/${id}`, { active });
  return r.data;
}

export async function getChecks(artistId: number): Promise<CheckResult[]> {
  const r = await api.get<CheckResult[]>(`/artists/${artistId}/checks`);
  return r.data;
}

export async function triggerRun(): Promise<void> {
  await api.post("/artists/run");
}

export async function saveInstagramCreds(sessionCookie: string): Promise<User> {
  const r = await api.put<User>("/auth/me", { instagram_session_cookie: sessionCookie || null });
  return r.data;
}

export function streamImport(
  onProgress: (done: number, total: number, added: number) => void,
  onDone: (added: number, skipped: number) => void,
  onError: (message: string) => void,
): () => void {
  const base = import.meta.env.VITE_API_URL ?? "";
  const es = new EventSource(`${base}/artists/import/stream`, { withCredentials: true });

  es.onmessage = (e) => {
    const event = JSON.parse(e.data) as {
      type: string; total?: number; done?: number; added?: number; skipped?: number; message?: string;
    };
    if (event.type === "progress" || event.type === "start") {
      onProgress(event.done ?? 0, event.total ?? 0, event.added ?? 0);
    } else if (event.type === "done") {
      es.close();
      onDone(event.added ?? 0, event.skipped ?? 0);
    } else if (event.type === "error") {
      es.close();
      onError(event.message ?? "Import failed");
    }
  };

  es.onerror = () => {
    es.close();
    onError("Connection lost during import");
  };

  return () => es.close();
}
