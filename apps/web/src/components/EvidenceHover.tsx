"use client";

import { useId, useState, type ReactNode } from "react";

export type Evidence = {
  evidence_id?: string;
  title?: string;
  type?: string;
  outcome?: string;
  source?: string;
  date?: string;
  summary?: string;
  skills?: string[];
};

const EV_TAG = /\[ev:([^\]]+)\]/g;

export function evidenceIds(sentence: string): string[] {
  return Array.from(sentence.matchAll(EV_TAG)).map((m) => m[1]);
}

export function stripTags(sentence: string): string {
  return sentence.replace(EV_TAG, "").replace(/\s+/g, " ").trim();
}

/**
 * A claim that cites evidence. Underlined; hover or keyboard focus opens a panel with the
 * title, outcome and source of each cited evidence item. A missing item is shown as such.
 */
export function EvidenceHover({
  ids,
  evidence,
  status,
  children,
}: {
  ids: string[];
  evidence: Evidence[];
  status?: string;
  children: ReactNode;
}) {
  const [open, setOpen] = useState(false);
  const panelId = useId();
  const items = ids.map((id) => ({ id, ev: evidence.find((e) => e.evidence_id === id) }));
  const tone =
    status === "unsupported"
      ? "decoration-rose-500"
      : status === "partly_supported"
        ? "decoration-amber-500"
        : "decoration-emerald-500";

  return (
    <span className="relative inline">
      <span
        role="button"
        tabIndex={0}
        aria-describedby={open ? panelId : undefined}
        aria-expanded={open}
        data-testid="evidence-claim"
        className={`cursor-help underline decoration-2 underline-offset-2 ${tone}`}
        onMouseEnter={() => setOpen(true)}
        onMouseLeave={() => setOpen(false)}
        onFocus={() => setOpen(true)}
        onBlur={() => setOpen(false)}
        onKeyDown={(e) => {
          if (e.key === "Escape") setOpen(false);
        }}
      >
        {children}
        <sup className="ml-0.5 text-[10px] text-slate-500">{ids.join(", ")}</sup>
      </span>
      {open && (
        <span
          id={panelId}
          role="tooltip"
          data-testid="evidence-panel"
          className="absolute left-0 top-full z-20 mt-1 block w-72 max-w-[85vw] rounded-md border border-slate-200 bg-white p-3 text-left text-xs text-slate-700 shadow-lg"
        >
          {items.map(({ id, ev }) => (
            <span key={id} className="mb-2 block last:mb-0">
              {ev ? (
                <>
                  <span className="block font-semibold text-slate-900">{ev.title ?? id}</span>
                  {ev.outcome && <span className="block">Outcome: {ev.outcome}</span>}
                  <span className="block text-slate-500">
                    {[ev.type, ev.source, ev.date].filter(Boolean).join(" | ")}
                  </span>
                </>
              ) : (
                <span className="block text-rose-700">Evidence {id} was not found. This claim is unsupported.</span>
              )}
            </span>
          ))}
          {status && <span className="mt-1 block font-medium">Verification: {status.replace("_", " ")}</span>}
        </span>
      )}
    </span>
  );
}
