"use client";

import { api, unwrap } from "@/lib/api/client";
import { useLoad } from "@/lib/useLoad";
import { Empty, ErrorBox, KeyVal, Loading, PageHeader, pct } from "@/components/ui";

function Bars({ data, label }: { data: Record<string, number>; label: string }) {
  const entries = Object.entries(data);
  const max = Math.max(1, ...entries.map(([, v]) => v));
  if (entries.length === 0) return <p className="text-sm text-slate-500">No data yet.</p>;
  return (
    <ul className="space-y-1.5" aria-label={label}>
      {entries.map(([k, v]) => (
        <li key={k} className="flex items-center gap-2 text-sm">
          <span className="w-36 shrink-0 truncate capitalize" title={k}>
            {k.replace(/_/g, " ")}
          </span>
          <svg role="img" aria-label={`${k}: ${v}`} className="h-3 flex-1" preserveAspectRatio="none" viewBox="0 0 100 10">
            <rect width="100" height="10" rx="2" fill="#e2e8f0" />
            <rect width={(v / max) * 100} height="10" rx="2" fill="#4f46e5" />
          </svg>
          <span className="w-8 text-right tabular-nums">{v}</span>
        </li>
      ))}
    </ul>
  );
}

export default function AnalyticsPage() {
  const a = useLoad(() => unwrap(api.GET("/api/analytics")), [], 20000);
  if (a.loading && !a.data) return <Loading label="Loading analytics" />;
  if (a.error && !a.data) return <ErrorBox message={a.error} onRetry={a.reload} />;
  const d = a.data;
  if (!d) return null;
  if (d.runs_total === 0) return <Empty title="No runs yet" hint="Analytics appear after the agents have analysed some jobs." />;

  return (
    <div>
      <PageHeader title="Analytics" />
      <div className="grid gap-4 md:grid-cols-2">
        <section className="card" aria-label="Outcomes">
          <h2 className="h2">Outcomes</h2>
          <dl>
            <KeyVal k="Runs" v={d.runs_total} />
            <KeyVal k="Submitted" v={d.submitted} />
            <KeyVal k="Rejected by you" v={d.rejected} />
            <KeyVal k="Client replies" v={d.replied} />
            <KeyVal k="Reply rate" v={pct(d.reply_rate)} />
            <KeyVal k="Average steps per run" v={d.avg_steps !== null && d.avg_steps !== undefined ? d.avg_steps.toFixed(1) : "n/a"} />
          </dl>
        </section>
        <section className="card" aria-label="Connects">
          <h2 className="h2">Connects spent vs outcomes</h2>
          <dl>
            <KeyVal k="Connects spent" v={d.connects_spent} />
            <KeyVal k="Submitted proposals" v={d.submitted} />
            <KeyVal k="Replies" v={d.replied} />
            <KeyVal k="Connects per reply" v={d.replied > 0 ? (d.connects_spent / d.replied).toFixed(1) : "n/a"} />
          </dl>
          <p className="mt-2 text-xs text-slate-500">
            Cost and latency per proposal and reply rate by category are not exposed by the API yet, so they are not
            shown here. Measured values live in the evaluation results.
          </p>
        </section>
        <section className="card" aria-label="Runs by status">
          <h2 className="h2">Runs by status</h2>
          <Bars data={d.by_status} label="Runs by status" />
        </section>
        <section className="card" aria-label="Runs by action">
          <h2 className="h2">Decisions by action</h2>
          <Bars data={d.by_action} label="Decisions by action" />
        </section>
        <section className="card md:col-span-2" aria-label="Top rejection reasons">
          <h2 className="h2">Top rejection reasons</h2>
          {(d.top_rejection_reasons ?? []).length === 0 ? (
            <p className="text-sm text-slate-500">You have not rejected any proposal yet.</p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-left text-sm">
                <thead>
                  <tr className="border-b border-slate-200 text-xs uppercase text-slate-500">
                    <th className="py-2">Reason</th>
                    <th className="py-2 text-right">Count</th>
                  </tr>
                </thead>
                <tbody>
                  {(d.top_rejection_reasons ?? []).map((r) => (
                    <tr key={r.reason} className="border-b border-slate-100">
                      <td className="py-2">{r.reason}</td>
                      <td className="py-2 text-right tabular-nums">{r.count}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>
      </div>
    </div>
  );
}
