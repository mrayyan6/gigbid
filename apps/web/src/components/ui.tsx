"use client";

import type { ReactNode } from "react";

export function Loading({ label = "Loading" }: { label?: string }) {
  return (
    <div role="status" aria-live="polite" className="flex items-center gap-2 p-6 text-sm text-slate-500">
      <span className="h-4 w-4 animate-spin rounded-full border-2 border-slate-300 border-t-indigo-600" />
      {label}...
    </div>
  );
}

export function ErrorBox({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div role="alert" className="rounded-md border border-rose-200 bg-rose-50 p-4 text-sm text-rose-800">
      <p className="font-medium">Something went wrong</p>
      <p className="mt-1">{message}</p>
      {onRetry && (
        <button type="button" className="btn mt-3" onClick={onRetry}>
          Try again
        </button>
      )}
    </div>
  );
}

export function Empty({ title, hint, children }: { title: string; hint?: string; children?: ReactNode }) {
  return (
    <div className="rounded-md border border-dashed border-slate-300 bg-white p-8 text-center">
      <p className="text-sm font-medium text-slate-700">{title}</p>
      {hint && <p className="mt-1 text-sm text-slate-500">{hint}</p>}
      {children && <div className="mt-3">{children}</div>}
    </div>
  );
}

const TONES: Record<string, string> = {
  green: "bg-emerald-100 text-emerald-800",
  amber: "bg-amber-100 text-amber-800",
  red: "bg-rose-100 text-rose-800",
  blue: "bg-sky-100 text-sky-800",
  slate: "bg-slate-100 text-slate-700",
  indigo: "bg-indigo-100 text-indigo-800",
};

export function Badge({ children, tone = "slate" }: { children: ReactNode; tone?: keyof typeof TONES }) {
  return (
    <span className={`inline-block rounded-full px-2 py-0.5 text-xs font-medium ${TONES[tone]}`}>{children}</span>
  );
}

export function actionTone(action?: string | null): keyof typeof TONES {
  if (action === "bid") return "green";
  if (action === "watch") return "amber";
  if (action === "skip") return "slate";
  return "blue";
}

export function statusTone(status?: string | null): keyof typeof TONES {
  switch (status) {
    case "completed":
      return "green";
    case "awaiting_approval":
      return "indigo";
    case "running":
    case "queued":
      return "blue";
    case "needs_attention":
    case "failed":
    case "blocked":
      return "red";
    case "rejected":
    case "skipped":
      return "slate";
    default:
      return "slate";
  }
}

export function PageHeader({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="mb-4 flex flex-wrap items-center justify-between gap-2">
      <h1 className="h1">{title}</h1>
      {children}
    </div>
  );
}

export function KeyVal({ k, v }: { k: string; v: ReactNode }) {
  return (
    <div className="flex justify-between gap-4 py-1 text-sm">
      <dt className="text-slate-500">{k}</dt>
      <dd className="text-right font-medium text-slate-900">{v}</dd>
    </div>
  );
}

export function money(n?: number | null, currency = "USD"): string {
  if (n === null || n === undefined) return "n/a";
  return `${currency === "USD" ? "$" : currency + " "}${Math.round(n * 100) / 100}`;
}

export function pct(n?: number | null): string {
  if (n === null || n === undefined) return "n/a";
  return `${Math.round(n * 100)}%`;
}
