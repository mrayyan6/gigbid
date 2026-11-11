"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useState } from "react";
import { api, unwrap, type Schemas } from "@/lib/api/client";
import { useLoad } from "@/lib/useLoad";
import { ApprovalPanel, DecisionResult } from "@/components/ApprovalPanel";
import { DraftView, type Claim } from "@/components/DraftView";
import type { Evidence } from "@/components/EvidenceHover";
import { Badge, Empty, ErrorBox, Loading, PageHeader, statusTone } from "@/components/ui";

type Dict = Record<string, unknown>;

export default function StudioPage() {
  const params = useParams<{ id: string }>();
  const id = decodeURIComponent(params.id);
  const [result, setResult] = useState<Schemas["ApprovalOut"] | null>(null);
  const run = useLoad(() => unwrap(api.GET("/api/runs/{tid}", { params: { path: { tid: id } } })), [id], result ? undefined : 6000);

  if (run.loading && !run.data) return <Loading label="Loading proposal" />;
  if (run.error && !run.data) return <ErrorBox message={run.error} onRetry={run.reload} />;
  const r = run.data;
  if (!r) return null;

  // A pending approval is read from the checkpoint, so a page refresh never loses it.
  const pending = (r.pending_approval ?? [])[0] as Dict | undefined;
  const draftText = String((r.proposal_draft as Dict | null)?.cover_letter ?? "");

  return (
    <div>
      <PageHeader title="Proposal studio">
        <div className="flex items-center gap-2">
          <Badge tone={statusTone(result?.status ?? r.status)}>{(result?.status ?? r.status).replace("_", " ")}</Badge>
          <Link href={`/runs/${encodeURIComponent(id)}`} className="btn">
            Run viewer
          </Link>
        </div>
      </PageHeader>

      {result ? (
        <DecisionResult result={result} />
      ) : pending ? (
        <ApprovalPanel
          threadId={id}
          payload={pending}
          critique={r.critique as Dict | null}
          onDecided={(res) => {
            setResult(res);
            void run.reload();
          }}
        />
      ) : draftText ? (
        <div className="space-y-4">
          <div className="card">
            <h2 className="h2">Cover letter</h2>
            <DraftView text={draftText} evidence={r.evidence as Evidence[]} claims={r.claim_verification as Claim[]} />
          </div>
          <p className="text-sm text-slate-600">
            This proposal is no longer waiting for approval (status: {r.status.replace("_", " ")}).
          </p>
        </div>
      ) : (
        <Empty
          title="No proposal to review yet"
          hint={
            r.status === "running" || r.status === "queued"
              ? "The agents are still working. This page refreshes by itself."
              : "This run did not produce a proposal."
          }
        />
      )}
    </div>
  );
}
