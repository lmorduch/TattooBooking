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

export async function saveInstagramCreds(username: string, password: string): Promise<User> {
  const r = await api.put<User>("/auth/me", { instagram_username: username, instagram_password: password });
  return r.data;
}

export async function importFromInstagram(): Promise<{ added: number; skipped: number }> {
  const r = await api.post<{ added: number; skipped: number }>("/artists/import");
  return r.data;
}
