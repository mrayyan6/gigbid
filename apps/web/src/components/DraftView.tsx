"use client";

import { Fragment } from "react";
import { EvidenceHover, evidenceIds, stripTags, type Evidence } from "./EvidenceHover";

export type Claim = { claim?: string; status?: string };

function sentences(paragraph: string): string[] {
  return paragraph.split(/(?<=[.!?])\s+/).filter((s) => s.trim());
}

function statusFor(sentence: string, claims: Claim[]): string | undefined {
  const plain = stripTags(sentence);
  const hit = claims.find((c) => c.claim && stripTags(c.claim) === plain);
  return hit?.status;
}

/** Cover letter split into paragraphs; every sentence that cites evidence is an EvidenceHover. */
export function DraftView({
  text,
  evidence,
  claims,
  onRegenerate,
  busyIndex,
}: {
  text: string;
  evidence: Evidence[];
  claims: Claim[];
  onRegenerate?: (index: number) => void;
  busyIndex?: number | null;
}) {
  const paragraphs = text.split(/\n\s*\n/).filter((p) => p.trim());
  return (
    <div data-testid="draft-view" className="space-y-3 text-sm leading-relaxed text-slate-900">
      {paragraphs.map((p, i) => (
        <div key={i} className="group rounded-md border border-transparent p-2 hover:border-slate-200">
          <p>
            {sentences(p).map((s, j) => {
              const ids = evidenceIds(s);
              return (
                <Fragment key={j}>
                  {ids.length > 0 ? (
                    <EvidenceHover ids={ids} evidence={evidence} status={statusFor(s, claims)}>
                      {stripTags(s)}
                    </EvidenceHover>
                  ) : (
                    stripTags(s)
                  )}{" "}
                </Fragment>
              );
            })}
          </p>
          {onRegenerate && (
            <button
              type="button"
              className="btn mt-2 text-xs"
              disabled={busyIndex === i}
              onClick={() => onRegenerate(i)}
              aria-label={`Regenerate paragraph ${i + 1}`}
            >
              {busyIndex === i ? "Regenerating..." : "Regenerate paragraph"}
            </button>
          )}
        </div>
      ))}
    </div>
  );
}
