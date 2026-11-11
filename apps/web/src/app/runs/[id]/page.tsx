"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { api, unwrap } from "@/lib/api/client";
import { useLoad } from "@/lib/useLoad";
import { RunTimeline } from "@/components/RunTimeline";
import { Badge, ErrorBox, KeyVal, Loading, PageHeader, statusTone } from "@/components/ui";

export default function RunPage() {
  const params = useParams<{ id: string }>();
  const id = decodeURIComponent(params.id);
  const run = useLoad(() => unwrap(api.GET("/api/runs/{tid}", { params: { path: { tid: id } } })), [id], 5000);

  if (run.loading && !run.data) return <Loading label="Loading run" />;
  if (run.error && !run.data) return <ErrorBox message={run.error} onRetry={run.reload} />;
  const r = run.data;
  if (!r) return null;
  const attention = r.status === "needs_attention" || r.status === "failed" || r.status === "blocked";

  return (
    <div>
      <PageHeader title="Agent run">
        <div className="flex flex-wrap gap-2">
          <Link href={`/jobs/${encodeURIComponent(r.job_id)}`} className="btn">
            Job detail
          </Link>
          {r.proposal_draft && (
            <Link href={`/studio/${encodeURIComponent(r.thread_id)}`} className="btn-primary">
              {r.status === "awaiting_approval" ? "Review proposal" : "Open proposal"}
            </Link>
          )}
        </div>
      </PageHeader>

      {attention && (
        <div role="alert" className="mb-4 rounded-md border border-rose-200 bg-rose-50 p-3 text-sm text-rose-800">
          This run needs attention ({r.status.replace("_", " ")}).
          {(r.errors ?? []).length > 0 && <span> {(r.errors ?? []).join("; ")}</span>}
        </div>
      )}
      {r.status === "queued" && (
        <div role="status" className="mb-4 rounded-md border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900">
          Queued. The run starts automatically once the marketplace is reachable.
        </div>
      )}

      <div className="grid gap-4 lg:grid-cols-3">
        <div className="lg:col-span-2">
          <RunTimeline threadId={id} traceId={r.trace_id} onFinished={() => void run.reload()} />
        </div>
        <section className="card" aria-label="Run summary">
          <h2 className="h2">Summary</h2>
          <dl>
            <KeyVal k="Status" v={<Badge tone={statusTone(r.status)}>{r.status.replace("_", " ")}</Badge>} />
            <KeyVal k="Job" v={r.job_id} />
            <KeyVal k="Next node" v={(r.next ?? []).length ? (r.next ?? []).join(", ") : "none"} />
            <KeyVal k="Decision" v={String((r.decision as Record<string, unknown> | null)?.action ?? "pending")} />
            <KeyVal k="Steps logged" v={(r.trace ?? []).length} />
          </dl>
        </section>
      </div>
    </div>
  );
}
