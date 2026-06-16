// ABOUTME: Settings page for connecting an Instagram account via session cookie.
// ABOUTME: Guides the user through finding their session cookie; streams import progress.

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
  const [cookie, setCookie] = useState("");
  const [importState, setImportState] = useState<ImportState>({ status: "idle" });

  const saveMut = useMutation({
    mutationFn: () => saveInstagramCreds(cookie),
    onSuccess: () => {
      setCookie("");
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

        {user.has_instagram ? (
          <div className="ig-connected">
            <span className="save-ok">✓ Connected as @{user.instagram_username}</span>
            <button className="btn-sm" style={{ marginLeft: "1rem" }} onClick={() => saveMut.mutate()}>
              Disconnect
            </button>
          </div>
        ) : (
          <>
            <p className="hint">
              Connect your Instagram account to import your following list. We use your browser
              session — no password ever leaves your device.
            </p>

            <div className="cookie-steps">
              <p className="step"><strong>1.</strong> Open <a href="https://www.instagram.com" target="_blank" rel="noreferrer">instagram.com</a> and log in.</p>
              <p className="step"><strong>2.</strong> Open DevTools: <code>F12</code> (Windows) or <code>Cmd+Option+I</code> (Mac).</p>
              <p className="step"><strong>3.</strong> Go to <strong>Application</strong> → <strong>Cookies</strong> → <strong>https://www.instagram.com</strong>.</p>
              <p className="step"><strong>4.</strong> Find the cookie named <code>sessionid</code> and copy its <strong>Value</strong>.</p>
              <p className="step"><strong>5.</strong> Paste it below:</p>
            </div>

            <form className="settings-form" onSubmit={handleSave}>
              <label>
                Session cookie value
                <input
                  value={cookie}
                  onChange={(e) => setCookie(e.target.value)}
                  placeholder="Paste sessionid value here"
                  autoComplete="off"
                />
              </label>
              <button type="submit" disabled={saveMut.isPending || !cookie.trim()}>
                {saveMut.isPending ? "Verifying…" : "Connect Instagram"}
              </button>
              {saveMut.isError && (
                <span className="error-msg">
                  {(saveMut.error as { response?: { data?: { detail?: string } } })?.response?.data?.detail ?? "Invalid or expired session cookie"}
                </span>
              )}
            </form>
          </>
        )}
      </div>

      {user.has_instagram && (
        <div className="settings-section">
          <h2>Import Following List</h2>
          <p className="hint">
            Seeds your watchlist from everyone you follow on Instagram. The feed scanner checks posts from your watchlist — run this once to populate it. Already-tracked accounts are skipped.
          </p>

          <button onClick={handleImport} disabled={importState.status === "running"}>
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
                      : "0%",
                  }}
                />
              </div>
              <div className="import-progress-label">
                {importState.total > 0
                  ? `${importState.done} / ${importState.total} — ${importState.added} added`
                  : "Connecting to Instagram…"}
              </div>
            </div>
          )}

          {importState.status === "done" && (
            <p className="import-msg">✓ Done — {importState.added} artists added, {importState.skipped} already tracked.</p>
          )}
          {importState.status === "error" && (
            <p className="error-msg">Error: {importState.message}</p>
          )}
        </div>
      )}
    </div>
  );
}
