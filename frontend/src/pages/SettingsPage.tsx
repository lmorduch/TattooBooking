// ABOUTME: Settings page for configuring Instagram credentials.
// ABOUTME: Stores credentials securely in the backend; streams import progress via SSE.

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { saveInstagramCreds, streamImport, type User } from "../api";

type ImportState =
  | { status: "idle" }
  | { status: "running"; done: number; total: number; added: number }
  | { status: "done"; added: number; skipped: number }
  | { status: "error"; message: string };

export default function SettingsPage({ user }: { user: User }) {
  const qc = useQueryClient();
  const [username, setUsername] = useState(user.instagram_username ?? "");
  const [password, setPassword] = useState("");
  const [importState, setImportState] = useState<ImportState>({ status: "idle" });

  const saveMut = useMutation({
    mutationFn: () => saveInstagramCreds(username, password),
    onSuccess: () => {
      setPassword("");
      qc.invalidateQueries({ queryKey: ["me"] });
    },
  });

  function handleSave(e: React.FormEvent) {
    e.preventDefault();
    saveMut.mutate();
  }

  function handleImport() {
    setImportState({ status: "running", done: 0, total: 0, added: 0 });

    streamImport(
      (done, total, added) => setImportState({ status: "running", done, total, added }),
      (added, skipped) => {
        setImportState({ status: "done", added, skipped });
        qc.invalidateQueries({ queryKey: ["artists"] });
      },
      (message) => setImportState({ status: "error", message }),
    );
  }

  return (
    <div>
      <div className="page-header">
        <h1>Settings</h1>
      </div>

      <div className="settings-section">
        <h2>Instagram Account</h2>
        <p className="hint">
          Used to fetch your following list and improve scraping reliability.
          Your password is encrypted before being stored.
        </p>
        <form className="settings-form" onSubmit={handleSave}>
          <label>
            Username
            <input
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              placeholder="your_instagram_handle"
              autoComplete="username"
            />
          </label>
          <label>
            Password
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder={user.has_instagram ? "Enter new password to update" : "Instagram password"}
              autoComplete="current-password"
            />
          </label>
          <button type="submit" disabled={saveMut.isPending || !username}>
            {saveMut.isPending ? "Saving…" : "Save credentials"}
          </button>
          {saveMut.isSuccess && <span className="save-ok">✓ Saved</span>}
          {saveMut.isError && (
            <span className="error-msg">
              {(saveMut.error as { response?: { data?: { detail?: string } } })?.response?.data?.detail ?? "Save failed"}
            </span>
          )}
        </form>
      </div>

      {user.has_instagram && (
        <div className="settings-section">
          <h2>Import Following List</h2>
          <p className="hint">
            Adds everyone you follow on Instagram as a tracked artist. Already-tracked accounts are skipped.
          </p>

          <button
            onClick={handleImport}
            disabled={importState.status === "running"}
          >
            {importState.status === "running" ? "Importing…" : "Import from Instagram"}
          </button>

          {importState.status === "running" && (
            <div className="import-progress">
              <div className="import-progress-bar-track">
                <div
                  className="import-progress-bar-fill"
                  style={{
                    width: importState.total > 0
                      ? `${Math.round((importState.done / importState.total) * 100)}%`
                      : "0%"
                  }}
                />
              </div>
              <div className="import-progress-label">
                {importState.total > 0
                  ? `${importState.done} / ${importState.total} — ${importState.added} added`
                  : "Connecting…"}
              </div>
            </div>
          )}

          {importState.status === "done" && (
            <p className="import-msg">
              ✓ Done — {importState.added} artists added, {importState.skipped} already tracked.
            </p>
          )}

          {importState.status === "error" && (
            <p className="error-msg">Error: {importState.message}</p>
          )}
        </div>
      )}
    </div>
  );
}
