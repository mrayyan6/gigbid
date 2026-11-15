"use client";

import { useState } from "react";
import { api, errorMessage, unwrap } from "@/lib/api/client";
import { getToken } from "@/lib/auth";
import { useLoad } from "@/lib/useLoad";
import { Badge, ErrorBox, Loading } from "@/components/ui";

type UploadResult = {
  added: number;
  duplicates: number;
  rejected: string[];
  chunks_embedded: number;
  reindex_seconds: number;
  user_items: number;
  seeded_items: number;
};

export function describeUpload(r: UploadResult): string {
  const parts = [
    r.added > 0
      ? `Added ${r.added} item${r.added === 1 ? "" : "s"}. Only ${r.chunks_embedded} new chunk${r.chunks_embedded === 1 ? "" : "s"} ` +
        `needed indexing (${r.reindex_seconds}s), the ${r.seeded_items + r.user_items - r.added} existing items were not re-indexed.`
      : "Nothing new was added.",
  ];
  if (r.duplicates > 0) parts.push(`${r.duplicates} already in your portfolio.`);
  if (r.rejected.length > 0) parts.push(`Skipped: ${r.rejected.join("; ")}.`);
  return parts.join(" ");
}

/** Add your own work (PDF, Markdown, text, JSON). The server re-indexes incrementally and your agents use it. */
export default function PortfolioUpload() {
  const portfolio = useLoad(() => unwrap(api.GET("/api/portfolio")), []);
  const [files, setFiles] = useState<FileList | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [repo, setRepo] = useState("");
  const [repoPath, setRepoPath] = useState("README.md");

  async function upload() {
    if (!files || files.length === 0) return;
    setBusy(true);
    setError(null);
    setNote(null);
    try {
      const form = new FormData();
      Array.from(files).forEach((f) => form.append("files", f));
      const res = await fetch("/api/portfolio/upload", {
        method: "POST",
        headers: { Authorization: `Bearer ${getToken() ?? ""}` },
        body: form,
      });
      if (!res.ok) {
        const detail = await res.json().catch(() => ({}));
        throw new Error(typeof detail.detail === "string" ? detail.detail : `Upload failed (${res.status})`);
      }
      setNote(describeUpload((await res.json()) as UploadResult));
      setFiles(null);
      portfolio.reload();
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  }

  async function importFromGithub() {
    if (!repo.trim()) return;
    setBusy(true);
    setError(null);
    setNote(null);
    try {
      const r = await unwrap(
        api.POST("/api/portfolio/github", { body: { repo: repo.trim(), path: repoPath.trim() || "README.md" } }),
      );
      setNote(describeUpload(r as UploadResult));
      portfolio.reload();
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="card" aria-label="Your portfolio">
      <h2 className="h2">Your portfolio</h2>
      <p className="mb-2 text-sm text-slate-600">
        Add case studies, READMEs, reviews, past proposals or a CV (PDF, Markdown, text or JSON). Your agents use them as
        evidence in your own runs. Uploads are private to your account.
      </p>
      {portfolio.loading && !portfolio.data ? (
        <Loading label="Loading portfolio" />
      ) : portfolio.error && !portfolio.data ? (
        <ErrorBox message={portfolio.error} onRetry={portfolio.reload} />
      ) : (
        <p className="mb-2 text-sm" data-testid="portfolio-counts">
          {portfolio.data?.seeded_items} built in items, {portfolio.data?.uploaded.length} added by you.
        </p>
      )}
      <ul className="mb-3 space-y-1 text-sm">
        {(portfolio.data?.uploaded ?? []).map((i) => (
          <li key={i.evidence_id} className="flex flex-wrap items-center gap-2">
            <span>{i.title}</span>
            <Badge tone="indigo">{i.type.replace(/_/g, " ")}</Badge>
            <span className="text-xs text-slate-500">{(i.skills ?? []).join(", ")}</span>
          </li>
        ))}
      </ul>
      <label htmlFor="portfolio-files" className="label">
        Files to add
      </label>
      <input
        id="portfolio-files"
        type="file"
        multiple
        accept=".pdf,.md,.markdown,.txt,.json"
        className="block w-full text-sm"
        onChange={(e) => setFiles(e.target.files)}
      />
      <button type="button" className="btn-primary mt-2" disabled={busy || !files || files.length === 0} onClick={upload}>
        {busy ? "Indexing..." : "Upload and index"}
      </button>
      <div className="mt-4 border-t border-slate-200 pt-3">
        <p className="mb-1 text-sm font-medium">Import a README or code file from GitHub</p>
        <p className="mb-2 text-xs text-slate-500">Read through the official GitHub MCP server (read only).</p>
        <div className="flex flex-wrap items-end gap-2">
          <div>
            <label htmlFor="gh-repo" className="label">
              Repository (owner/name)
            </label>
            <input id="gh-repo" className="input" placeholder="octocat/hello-world" value={repo} onChange={(e) => setRepo(e.target.value)} />
          </div>
          <div>
            <label htmlFor="gh-path" className="label">
              File
            </label>
            <input id="gh-path" className="input" value={repoPath} onChange={(e) => setRepoPath(e.target.value)} />
          </div>
          <button type="button" className="btn" disabled={busy || !repo.trim()} onClick={importFromGithub}>
            Import from GitHub
          </button>
        </div>
      </div>
      {note && (
        <p className="mt-2 text-sm text-green-700" role="status" data-testid="upload-note">
          {note}
        </p>
      )}
      {error && <ErrorBox message={error} />}
    </section>
  );
}
