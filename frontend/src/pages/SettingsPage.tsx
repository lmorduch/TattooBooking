// ABOUTME: Settings page for configuring Instagram credentials.
// ABOUTME: Stores credentials securely in the backend; shows import button once set.

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { importFromInstagram, saveInstagramCreds, type User } from "../api";

export default function SettingsPage({ user }: { user: User }) {
  const qc = useQueryClient();
  const [username, setUsername] = useState(user.instagram_username ?? "");
  const [password, setPassword] = useState("");
  const [importMsg, setImportMsg] = useState("");

  const saveMut = useMutation({
    mutationFn: () => saveInstagramCreds(username, password),
    onSuccess: () => {
      setPassword("");
      qc.invalidateQueries({ queryKey: ["me"] });
    },
  });

  const importMut = useMutation({
    mutationFn: importFromInstagram,
    onSuccess: (result) => {
      setImportMsg(`Done — added ${result.added} artists, skipped ${result.skipped} already tracked.`);
      qc.invalidateQueries({ queryKey: ["artists"] });
    },
    onError: (e: unknown) => {
      const msg = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail ?? "Import failed";
      setImportMsg(`Error: ${msg}`);
    },
  });

  function handleSave(e: React.FormEvent) {
    e.preventDefault();
    saveMut.mutate();
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
            This may take a few minutes depending on how many accounts you follow.
          </p>
          <button
            onClick={() => { setImportMsg(""); importMut.mutate(); }}
            disabled={importMut.isPending}
          >
            {importMut.isPending ? "Importing… (this may take a while)" : "Import from Instagram"}
          </button>
          {importMsg && <p className="import-msg">{importMsg}</p>}
        </div>
      )}
    </div>
  );
}
