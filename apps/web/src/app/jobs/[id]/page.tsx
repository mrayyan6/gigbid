"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useState } from "react";
import { api, errorMessage, unwrap } from "@/lib/api/client";
import { useLoad } from "@/lib/useLoad";
import { Badge, Empty, ErrorBox, KeyVal, Loading, PageHeader, actionTone, money, pct, statusTone } from "@/components/ui";

type Dict = Record<string, unknown>;
const asDict = (v: unknown): Dict => (v && typeof v === "object" ? (v as Dict) : {});
const asList = <T,>(v: unknown): T[] => (Array.isArray(v) ? (v as T[]) : []);

export default function JobDetailPage() {
  const params = useParams<{ id: string }>();
  const id = decodeURIComponent(params.id);
  const router = useRouter();
  const [starting, setStarting] = useState(false);
  const [startError, setStartError] = useState<string | null>(null);

  const detail = useLoad(
    () => unwrap(api.GET("/api/jobs/{job_id}", { params: { path: { job_id: id } } })),
    [id],
  );

  if (detail.loading && !detail.data) return <Loading label="Loading job" />;
  if (detail.error || !detail.data) return <ErrorBox message={detail.error ?? "Job not found"} onRetry={detail.reload} />;

  const { job, run } = detail.data;
  const spec = asDict(run?.job_spec);
  const risk = asDict(run?.risk_report);
  const fit = asDict(run?.fit_report);
  const decision = asDict(run?.decision);
  const price = asDict(run?.price_quote);
  const evidence = asList<Dict>(run?.evidence);
  const matched = asList<string>(fit.matched_skills);
  const missing = asList<string>(fit.missing_skills);
  const deliverables = asList<string>(spec.deliverables);

  async function start() {
    setStarting(true);
    setStartError(null);
    try {
      const out = await unwrap(api.POST("/api/runs", { body: { job_id: id } }));
      router.push(`/runs/${encodeURIComponent(out.thread_id)}`);
    } catch (e) {
      setStartError(errorMessage(e));
    } finally {
      setStarting(false);
    }
  }

  return (
    <div>
      <PageHeader title={job.title}>
        <div className="flex gap-2">
          {run ? (
            <>
              <Link href={`/runs/${encodeURIComponent(run.thread_id)}`} className="btn">
                View run
              </Link>
              {run.status === "awaiting_approval" && (
                <Link href={`/studio/${encodeURIComponent(run.thread_id)}`} className="btn-primary">
                  Review proposal
                </Link>
              )}
            </>
          ) : (
            <button type="button" className="btn-primary" disabled={starting} onClick={start}>
              {starting ? "Starting..." : "Run agents"}
            </button>
          )}
        </div>
      </PageHeader>
      {startError && <ErrorBox message={startError} />}

      <div className="grid gap-4 lg:grid-cols-3">
        <section className="card lg:col-span-2" aria-label="Job spec">
          <h2 className="h2">Job spec</h2>
          <p className="whitespace-pre-wrap text-sm text-slate-700">{job.description || "No description."}</p>
          {deliverables.length > 0 && (
            <>
              <h3 className="mt-3 text-sm font-semibold">Deliverables</h3>
              <ul className="ml-5 list-disc text-sm">
                {deliverables.map((d, i) => (
                  <li key={i}>{d}</li>
                ))}
              </ul>
            </>
          )}
          <div className="mt-3 flex flex-wrap gap-1.5">
            {(job.required_skills ?? []).map((s) => (
              <Badge key={s} tone="blue">
                {s}
              </Badge>
            ))}
          </div>
        </section>

        <section className="card" aria-label="Summary">
          <h2 className="h2">Summary</h2>
          <dl>
            <KeyVal k="Budget" v={`${money(job.budget_min, job.currency)} to ${money(job.budget_max, job.currency)}`} />
            <KeyVal k="Connects cost" v={job.connects_cost} />
            <KeyVal k="Fit" v={pct(job.fit_score)} />
            <KeyVal k="Action" v={<Badge tone={actionTone(job.recommended_action)}>{job.recommended_action}</Badge>} />
            <KeyVal k="Run" v={job.run_status ? <Badge tone={statusTone(job.run_status)}>{job.run_status.replace("_", " ")}</Badge> : "not run"} />
          </dl>
        </section>

        {!run ? (
          <div className="lg:col-span-3">
            <Empty title="Agents have not analysed this job yet" hint="Run the agents to get a risk report, evidence matrix, price rationale and a decision.">
              <button type="button" className="btn-primary" disabled={starting} onClick={start}>
                Run agents
              </button>
            </Empty>
          </div>
        ) : (
          <>
            <section className="card" aria-label="Risk report">
              <h2 className="h2">Risk report</h2>
              <dl>
                <KeyVal k="Risk score" v={risk.score !== undefined ? String(risk.score) : "n/a"} />
              </dl>
              <div className="my-2 flex flex-wrap gap-1.5">
                {asList<string>(risk.flags).length === 0 ? (
                  <Badge tone="green">no flags</Badge>
                ) : (
                  asList<string>(risk.flags).map((f) => (
                    <Badge key={f} tone="red">
                      {f.replace(/_/g, " ")}
                    </Badge>
                  ))
                )}
              </div>
              <p className="text-sm text-slate-700">{String(risk.explanation ?? "")}</p>
            </section>

            <section className="card" aria-label="Decision">
              <h2 className="h2">Bid or skip reasoning</h2>
              <Badge tone={actionTone(String(decision.action))}>{String(decision.action ?? "pending")}</Badge>
              <p className="mt-2 text-sm text-slate-700">{String(decision.reason ?? "No decision yet.")}</p>
            </section>

            <section className="card" aria-label="Price rationale">
              <h2 className="h2">Price rationale</h2>
              {price.amount !== undefined ? (
                <>
                  <dl>
                    <KeyVal k="Quote" v={money(Number(price.amount))} />
                    <KeyVal k="Fair band" v={`${money(Number(price.band_low))} to ${money(Number(price.band_high))}`} />
                  </dl>
                  <p className="mt-2 text-sm text-slate-700">{String(price.rationale ?? "")}</p>
                </>
              ) : (
                <p className="text-sm text-slate-500">No price quote (job skipped or not priced).</p>
              )}
            </section>

            <section className="card lg:col-span-3" aria-label="Requirement to evidence matrix">
              <h2 className="h2">Requirement to evidence matrix</h2>
              {(job.required_skills ?? []).length === 0 ? (
                <p className="text-sm text-slate-500">This job lists no required skills.</p>
              ) : (
                <div className="overflow-x-auto">
                  <table className="w-full text-left text-sm">
                    <thead>
                      <tr className="border-b border-slate-200 text-xs uppercase text-slate-500">
                        <th className="py-2 pr-4">Requirement</th>
                        <th className="py-2 pr-4">Covered</th>
                        <th className="py-2">Evidence</th>
                      </tr>
                    </thead>
                    <tbody>
                      {(job.required_skills ?? []).map((skill) => {
                        const hits = evidence.filter((e) =>
                          asList<string>(e.skills).some((s) => s.toLowerCase() === skill.toLowerCase()),
                        );
                        const covered = hits.length > 0 || matched.some((m) => m.toLowerCase() === skill.toLowerCase());
                        const isMissing = missing.some((m) => m.toLowerCase() === skill.toLowerCase());
                        return (
                          <tr key={skill} className="border-b border-slate-100 align-top">
                            <td className="py-2 pr-4 font-medium">{skill}</td>
                            <td className="py-2 pr-4">
                              <Badge tone={covered ? "green" : isMissing || !covered ? "red" : "slate"}>{covered ? "yes" : "no evidence"}</Badge>
                            </td>
                            <td className="py-2">
                              {hits.length === 0 ? (
                                <span className="text-slate-400">none</span>
                              ) : (
                                <ul className="space-y-1">
                                  {hits.map((h) => (
                                    <li key={String(h.evidence_id)}>
                                      <span className="font-medium">{String(h.title ?? h.evidence_id)}</span>
                                      {h.outcome ? <span className="text-slate-600">: {String(h.outcome)}</span> : null}
                                    </li>
                                  ))}
                                </ul>
                              )}
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              )}
            </section>
          </>
        )}
      </div>
    </div>
  );
}
