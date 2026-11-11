"use client";

import Link from "next/link";
import { api, unwrap } from "@/lib/api/client";
import { useLoad } from "@/lib/useLoad";
import { Badge, Empty, ErrorBox, Loading, PageHeader, money } from "@/components/ui";

export default function PipelinePage() {
  const board = useLoad(() => unwrap(api.GET("/api/pipeline")), [], 10000);

  if (board.loading && !board.data) return <Loading label="Loading pipeline" />;
  if (board.error && !board.data) return <ErrorBox message={board.error} onRetry={board.reload} />;
  const b = board.data;
  if (!b) return null;
  const total = b.stages.reduce((n, s) => n + (b.columns[s]?.length ?? 0), 0);

  return (
    <div>
      <PageHeader title="Pipeline">
        <span className="text-xs text-slate-500">Updates every 10 seconds</span>
      </PageHeader>
      {board.error && (
        <p role="alert" className="mb-3 text-sm text-amber-800">
          Could not refresh ({board.error}). Showing the last known board.
        </p>
      )}
      {total === 0 && <Empty title="No proposals in the pipeline yet" hint="Run the agents on a job from the inbox." />}
      <div className="mt-4 flex gap-3 overflow-x-auto pb-2" data-testid="kanban">
        {b.stages.map((stage) => {
          const cards = b.columns[stage] ?? [];
          return (
            <section
              key={stage}
              aria-label={`${stage} column`}
              className="w-64 shrink-0 rounded-lg border border-slate-200 bg-slate-100 p-2"
            >
              <h2 className="mb-2 flex items-center justify-between px-1 text-sm font-semibold capitalize">
                {stage}
                <Badge>{cards.length}</Badge>
              </h2>
              <ul className="space-y-2">
                {cards.length === 0 && <li className="px-1 py-3 text-xs text-slate-400">Empty</li>}
                {cards.map((c) => (
                  <li key={c.thread_id} className="rounded-md border border-slate-200 bg-white p-2 text-sm">
                    <Link
                      href={stage === "drafted" ? `/studio/${encodeURIComponent(c.thread_id)}` : `/runs/${encodeURIComponent(c.thread_id)}`}
                      className="font-medium text-indigo-700 hover:underline"
                    >
                      {c.title || c.job_id}
                    </Link>
                    <p className="mt-1 text-xs text-slate-500">
                      {c.amount !== null && c.amount !== undefined ? money(c.amount) : "no price"}
                      {c.client_id ? ` | ${c.client_id}` : ""}
                    </p>
                  </li>
                ))}
              </ul>
            </section>
          );
        })}
      </div>
    </div>
  );
}
