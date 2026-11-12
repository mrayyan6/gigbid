"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import { api, errorMessage, unwrap, type Schemas } from "@/lib/api/client";
import { wordDiff } from "@/lib/diff";
import { DraftView, type Claim } from "./DraftView";
import type { Evidence } from "./EvidenceHover";
import { Badge, KeyVal, money, statusTone } from "./ui";

type Dict = Record<string, unknown>;
type Mode = "view" | "edit" | "diff" | "reject";

function asDict(v: unknown): Dict {
  return v && typeof v === "object" ? (v as Dict) : {};
}
function asList<T = unknown>(v: unknown): T[] {
  return Array.isArray(v) ? (v as T[]) : [];
}

export function ApprovalPanel({
  threadId,
  payload,
  critique,
  onDecided,
  onRegenerated,
}: {
  threadId: string;
  payload: Dict;
  critique?: Dict | null;
  onDecided: (result: Schemas["ApprovalOut"]) => void;
  onRegenerated?: () => void;
}) {
  const draft = asDict(payload.draft);
  const original = String(draft.cover_letter ?? "");
  const evidence = asList<Evidence>(payload.evidence);
  const claims = asList<Claim>(payload.claims);
  const compliance = asDict(payload.compliance);
  const price = asDict(payload.price);
  const risk = asDict(payload.risk);
  const dry = asDict(payload.dry_run);
  const wouldSend = asDict(dry.would_send);
  const styleNotes = asList<string>(payload.style_notes);
  const issues = asList<string>(asDict(critique).issues);
  const violations = asList<string>(compliance.violations);

  const [mode, setMode] = useState<Mode>("view");
  const [text, setText] = useState(original);
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [regenNote, setRegenNote] = useState<string | null>(null);
  const [regenIndex, setRegenIndex] = useState<number | null>(null);

  const diff = useMemo(() => wordDiff(original, text), [original, text]);
  const changed = text.trim() !== original.trim();

  async function decide(action: "approve" | "edit" | "reject") {
    setBusy(true);
    setError(null);
    try {
      const body =
        action === "approve"
          ? { action }
          : action === "edit"
            ? { action, text: text.trim() }
            : { action, reason: reason.trim() };
      const res = await unwrap(
        api.POST("/api/approvals/{tid}", { params: { path: { tid: threadId } }, body }),
      );
      onDecided(res);
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  }

  async function regenerate(i: number) {
    setRegenIndex(i);
    setRegenNote(null);
    try {
      const res = await unwrap(
        api.POST("/api/proposals/{tid}/regenerate", {
          params: { path: { tid: threadId } },
          body: { paragraph_index: i },
        }),
      );
      setRegenNote(res.message || (res.regenerated ? "Paragraph regenerated." : "Nothing changed."));
      if (res.regenerated) {
        setText(String(asDict(res.draft).cover_letter ?? ""));
        onRegenerated?.();
      }
    } catch (e) {
      setRegenNote(errorMessage(e));
    } finally {
      setRegenIndex(null);
    }
  }

  const blocked = compliance.allowed === false;

  return (
    <section aria-label="Approval panel" data-testid="approval-panel" className="grid gap-4 lg:grid-cols-3">
      <div className="space-y-4 lg:col-span-2">
        <div className="card">
          <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
            <h2 className="h2 mb-0">Cover letter</h2>
            <Badge tone="indigo">Awaiting your approval</Badge>
          </div>
          {mode === "view" || mode === "reject" ? (
            <DraftView
              text={original}
              evidence={evidence}
              claims={claims}
              onRegenerate={regenerate}
              busyIndex={regenIndex}
            />
          ) : mode === "edit" ? (
            <div>
              <label htmlFor="edit-text" className="label">
                Edit the letter (keep [ev:id] tags on claims that cite evidence)
              </label>
              <textarea
                id="edit-text"
                data-testid="edit-textarea"
                className="input min-h-[14rem] font-mono"
                value={text}
                onChange={(e) => setText(e.target.value)}
              />
            </div>
          ) : (
            <div data-testid="diff-view" className="whitespace-pre-wrap rounded-md bg-slate-50 p-3 text-sm">
              {diff.map((d, i) => (
                <span
                  key={i}
                  className={
                    d.kind === "add"
                      ? "bg-emerald-100 text-emerald-900"
                      : d.kind === "del"
                        ? "bg-rose-100 text-rose-900 line-through"
                        : ""
                  }
                >
                  {d.text}
                </span>
              ))}
            </div>
          )}
          {regenNote && (
            <p role="status" className="mt-2 text-sm text-slate-600">
              {regenNote}
            </p>
          )}
        </div>

        <div className="card" aria-label="Critic and compliance comments">
          <h2 className="h2">Critic and compliance</h2>
          <div className="space-y-2 text-sm">
            <div>
              <span className="font-medium">Critic: </span>
              {issues.length === 0 ? (
                <span className="text-emerald-700">no open issues</span>
              ) : (
                <ul className="ml-5 list-disc text-amber-800">
                  {issues.map((i, k) => (
                    <li key={k}>{i}</li>
                  ))}
                </ul>
              )}
            </div>
            <div>
              <span className="font-medium">Compliance: </span>
              {violations.length === 0 && !blocked ? (
                <span className="text-emerald-700">passed</span>
              ) : (
                <ul className="ml-5 list-disc text-rose-800">
                  {violations.map((v, k) => (
                    <li key={k}>{v}</li>
                  ))}
                </ul>
              )}
            </div>
            {styleNotes.length > 0 && (
              <div>
                <span className="font-medium">Style memory applied: </span>
                {styleNotes.join("; ")}
              </div>
            )}
          </div>
        </div>

        <div className="card">
          <h2 className="h2">Claims and evidence</h2>
          {claims.length === 0 ? (
            <p className="text-sm text-slate-500">No claim verification data.</p>
          ) : (
            <ul className="space-y-1 text-sm">
              {claims.map((c, i) => (
                <li key={i} className="flex items-start gap-2">
                  <Badge
                    tone={c.status === "supported" ? "green" : c.status === "no_claim" ? "slate" : c.status === "partly_supported" ? "amber" : "red"}
                  >
                    {(c.status ?? "unknown").replace("_", " ")}
                  </Badge>
                  <span>{(c.claim ?? "").replace(/\[ev:[^\]]+\]/g, "").trim()}</span>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>

      <aside className="space-y-4">
        <div className="card" data-testid="dry-run">
          <h2 className="h2">Dry run preview</h2>
          <p className="mb-2 text-xs text-slate-500">Exactly what would be sent. Nothing is sent until you approve.</p>
          <dl>
            <KeyVal k="Bid amount" v={money(Number(wouldSend.bid_amount ?? price.amount))} />
            <KeyVal k="Connects cost" v={String(dry.connects_cost ?? price.connects_cost ?? "n/a")} />
            <KeyVal k="Balance after" v={String(dry.balance_after ?? "n/a")} />
            <KeyVal k="Fair band" v={`${money(Number(price.band_low))} to ${money(Number(price.band_high))}`} />
            <KeyVal k="Risk score" v={risk.score !== undefined ? String(risk.score) : "n/a"} />
          </dl>
          {typeof price.rationale === "string" && <p className="mt-2 text-xs text-slate-600">{price.rationale}</p>}
        </div>

        <div className="card">
          <h2 className="h2">Decision</h2>
          {blocked && (
            <p role="alert" className="mb-3 rounded-md bg-rose-50 p-2 text-sm text-rose-800">
              Compliance Guard blocked this proposal. Edit it to fix the violations before approving.
            </p>
          )}
          {error && (
            <p role="alert" className="mb-3 rounded-md bg-rose-50 p-2 text-sm text-rose-800">
              {error}
            </p>
          )}

          {mode === "view" && (
            <div className="flex flex-col gap-2">
              <button type="button" className="btn-primary" disabled={busy || blocked} onClick={() => decide("approve")}>
                {busy ? "Working..." : "Approve and send"}
              </button>
              <button type="button" className="btn" onClick={() => setMode("edit")}>
                Edit draft
              </button>
              <button type="button" className="btn" onClick={() => setMode("reject")}>
                Reject
              </button>
            </div>
          )}

          {mode === "edit" && (
            <div className="flex flex-col gap-2">
              <button type="button" className="btn-primary" disabled={!changed} onClick={() => setMode("diff")}>
                Review changes
              </button>
              <button
                type="button"
                className="btn"
                onClick={() => {
                  setText(original);
                  setMode("view");
                }}
              >
                Cancel
              </button>
            </div>
          )}

          {mode === "diff" && (
            <div className="flex flex-col gap-2">
              <p className="text-xs text-slate-600">
                Your edit is re-checked by Compliance and saved to style memory by the promotion rule.
              </p>
              <button type="button" className="btn-primary" disabled={busy} onClick={() => decide("edit")}>
                {busy ? "Working..." : "Approve edited version"}
              </button>
              <button type="button" className="btn" onClick={() => setMode("edit")}>
                Back to editing
              </button>
            </div>
          )}

          {mode === "reject" && (
            <div className="flex flex-col gap-2">
              <label htmlFor="reject-reason" className="label">
                Reason (required)
              </label>
              <textarea
                id="reject-reason"
                data-testid="reject-reason"
                className="input min-h-[5rem]"
                value={reason}
                onChange={(e) => setReason(e.target.value)}
                placeholder="Why should this proposal not be sent?"
              />
              <button
                type="button"
                className="btn-danger"
                disabled={busy || reason.trim().length === 0}
                onClick={() => decide("reject")}
              >
                {busy ? "Working..." : "Confirm rejection"}
              </button>
              <button type="button" className="btn" onClick={() => setMode("view")}>
                Cancel
              </button>
            </div>
          )}
        </div>
      </aside>
    </section>
  );
}

export function DecisionResult({ result }: { result: Schemas["ApprovalOut"] }) {
  const outcome = result.outcome as Dict | null | undefined;
  return (
    <div className="card" role="status" data-testid="decision-result">
      <div className="mb-2 flex items-center gap-2">
        <h2 className="h2 mb-0">Decision recorded</h2>
        <Badge tone={statusTone(result.status)}>{result.status.replace("_", " ")}</Badge>
      </div>
      {outcome && (
        <dl>
          {Object.entries(outcome)
            .filter(([, v]) => typeof v !== "object")
            .map(([k, v]) => (
              <KeyVal key={k} k={k.replace(/_/g, " ")} v={String(v)} />
            ))}
        </dl>
      )}
      {(result.promoted_memory ?? []).length > 0 && (
        <p className="mt-2 text-sm">Learned from your edit: {(result.promoted_memory ?? []).join("; ")}</p>
      )}
      <div className="mt-3 flex gap-2">
        <Link href="/pipeline" className="btn">
          Open pipeline
        </Link>
        <Link href="/inbox" className="btn">
          Back to inbox
        </Link>
      </div>
    </div>
  );
}
