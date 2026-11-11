"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { api, errorMessage, unwrap, type Schemas } from "@/lib/api/client";
import { useLoad } from "@/lib/useLoad";
import { Badge, Empty, ErrorBox, Loading, PageHeader, actionTone, money, pct, statusTone } from "@/components/ui";

const SKIP_KEY = "gigbid.skipped";

function readSkipped(): string[] {
  try {
    return JSON.parse(window.localStorage.getItem(SKIP_KEY) ?? "[]") as string[];
  } catch {
    return [];
  }
}

export default function InboxPage() {
  const router = useRouter();
  const [filter, setFilter] = useState("all");
  const [query, setQuery] = useState("");
  const [skipped, setSkipped] = useState<string[]>([]);
  const [startError, setStartError] = useState<string | null>(null);
  const [starting, setStarting] = useState<string | null>(null);

  useEffect(() => setSkipped(readSkipped()), []);

  const jobs = useLoad(() => unwrap(api.GET("/api/jobs", { params: { query: { limit: 60, query } } })), [query], 15000);
  const approvals = useLoad(() => unwrap(api.GET("/api/approvals")), [], 8000);

  function skip(id: string) {
    const next = Array.from(new Set([...skipped, id]));
    setSkipped(next);
    try {
      window.localStorage.setItem(SKIP_KEY, JSON.stringify(next));
    } catch {
      /* ignore */
    }
  }

  async function run(job: Schemas["JobOut"]) {
    setStarting(job.job_id);
    setStartError(null);
    try {
      const out = await unwrap(api.POST("/api/runs", { body: { job_id: job.job_id } }));
      router.push(`/runs/${encodeURIComponent(out.thread_id)}`);
    } catch (e) {
      setStartError(errorMessage(e));
    } finally {
      setStarting(null);
    }
  }

  const visible = (jobs.data ?? []).filter(
    (j) => !skipped.includes(j.job_id) && (filter === "all" || j.recommended_action === filter),
  );

  return (
    <div>
      <PageHeader title="Job inbox" />

      {approvals.data && approvals.data.length > 0 && (
        <section aria-label="Pending approvals" data-testid="pending-approvals" className="mb-6 rounded-lg border border-indigo-200 bg-indigo-50 p-4">
          <h2 className="h2">Waiting for your approval ({approvals.data.length})</h2>
          <ul className="divide-y divide-indigo-100">
            {approvals.data.map((a) => (
              <li key={a.thread_id} className="flex flex-wrap items-center justify-between gap-2 py-2 text-sm">
                <span className="min-w-0 truncate">{a.title || a.job_id}</span>
                <Link href={`/studio/${encodeURIComponent(a.thread_id)}`} className="btn-primary">
                  Review proposal
                </Link>
              </li>
            ))}
          </ul>
        </section>
      )}

      <div className="mb-4 flex flex-wrap gap-3">
        <div className="min-w-[12rem] flex-1">
          <label htmlFor="q" className="label">
            Search
          </label>
          <input id="q" className="input" value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Search jobs" />
        </div>
        <div>
          <label htmlFor="action" className="label">
            Recommended action
          </label>
          <select id="action" className="input" value={filter} onChange={(e) => setFilter(e.target.value)}>
            <option value="all">All</option>
            <option value="bid">Bid</option>
            <option value="watch">Watch</option>
            <option value="skip">Skip</option>
            <option value="unscored">Not scored yet</option>
          </select>
        </div>
      </div>

      {startError && <ErrorBox message={startError} />}
      {jobs.loading && !jobs.data ? (
        <Loading label="Loading jobs" />
      ) : jobs.error && !jobs.data ? (
        <ErrorBox message={jobs.error} onRetry={jobs.reload} />
      ) : visible.length === 0 ? (
        <Empty title="No jobs match" hint="Change the filter or search, or restore skipped jobs by clearing site data." />
      ) : (
        <ul className="space-y-3" data-testid="job-list">
          {visible.map((j) => (
            <li key={j.job_id} className="card" data-testid="job-row">
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div className="min-w-0 flex-1">
                  <Link href={`/jobs/${encodeURIComponent(j.job_id)}`} className="font-medium text-indigo-700 hover:underline">
                    {j.title}
                  </Link>
                  <div className="mt-1 flex flex-wrap gap-1.5">
                    <Badge tone={actionTone(j.recommended_action)}>{j.recommended_action}</Badge>
                    {j.run_status && <Badge tone={statusTone(j.run_status)}>{j.run_status.replace("_", " ")}</Badge>}
                    {(j.risk_badges ?? []).map((b) => (
                      <Badge key={b} tone="red">
                        {b.replace(/_/g, " ")}
                      </Badge>
                    ))}
                  </div>
                  <p className="mt-1 text-xs text-slate-500">{(j.required_skills ?? []).slice(0, 6).join(", ")}</p>
                </div>
                <dl className="grid grid-cols-3 gap-x-4 text-right text-sm">
                  <div>
                    <dt className="text-xs text-slate-500">Fit</dt>
                    <dd className="font-medium">{pct(j.fit_score)}</dd>
                  </div>
                  <div>
                    <dt className="text-xs text-slate-500">Price</dt>
                    <dd className="font-medium">{j.price !== null && j.price !== undefined ? money(j.price, j.currency) : `${money(j.budget_min, j.currency)} to ${money(j.budget_max, j.currency)}`}</dd>
                  </div>
                  <div>
                    <dt className="text-xs text-slate-500">Connects</dt>
                    <dd className="font-medium">{j.connects_cost}</dd>
                  </div>
                </dl>
              </div>
              <div className="mt-3 flex flex-wrap gap-2">
                <Link href={`/jobs/${encodeURIComponent(j.job_id)}`} className="btn">
                  Open
                </Link>
                {j.thread_id ? (
                  <Link href={`/runs/${encodeURIComponent(j.thread_id)}`} className="btn">
                    View run
                  </Link>
                ) : (
                  <button type="button" className="btn-primary" disabled={starting === j.job_id} onClick={() => run(j)}>
                    {starting === j.job_id ? "Starting..." : "Run agents"}
                  </button>
                )}
                <button type="button" className="btn" onClick={() => skip(j.job_id)} aria-label={`Skip ${j.title}`}>
                  Skip
                </button>
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
