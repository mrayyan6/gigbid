"use client";

import { useEffect, useState } from "react";
import { getToken } from "@/lib/auth";
import { Badge, statusTone } from "./ui";

type StepEvent = {
  key: number;
  kind: "node" | "custom" | "interrupt" | "status" | "error";
  node?: string;
  detail: string;
};

type Conn = "connecting" | "live" | "closed" | "error";

function describe(update: unknown): string {
  if (!update || typeof update !== "object") return "";
  const u = update as Record<string, unknown>;
  const trace = Array.isArray(u.trace) ? (u.trace as Record<string, unknown>[]) : [];
  const parts: string[] = [];
  for (const t of trace) {
    const extra = Object.entries(t)
      .filter(([k, v]) => k !== "node" && typeof v !== "object")
      .map(([k, v]) => `${k}=${String(v)}`);
    if (extra.length) parts.push(extra.join(" "));
  }
  if (parts.length) return parts.join("; ");
  const keys = Object.keys(u).filter((k) => !["trace", "steps", "tokens", "cost_usd"].includes(k));
  return keys.length ? `updated ${keys.join(", ")}` : "";
}

/** Node by node progress from GET /api/runs/{id}/stream (SSE). */
export function RunTimeline({
  threadId,
  traceId,
  onFinished,
}: {
  threadId: string;
  traceId?: string | null;
  onFinished?: (status: string | null) => void;
}) {
  const [events, setEvents] = useState<StepEvent[]>([]);
  const [conn, setConn] = useState<Conn>("connecting");
  const [status, setStatus] = useState<string | null>(null);

  useEffect(() => {
    setEvents([]);
    setConn("connecting");
    const token = getToken() ?? "";
    const es = new EventSource(`/api/runs/${encodeURIComponent(threadId)}/stream?token=${encodeURIComponent(token)}`);
    let n = 0;
    let last: string | null = null;
    const add = (e: Omit<StepEvent, "key">) => setEvents((prev) => [...prev, { ...e, key: n++ }]);
    const parse = (ev: MessageEvent): Record<string, unknown> => {
      try {
        return JSON.parse(ev.data) as Record<string, unknown>;
      } catch {
        return {};
      }
    };

    es.onopen = () => setConn("live");
    es.addEventListener("node", (ev) => {
      const d = parse(ev as MessageEvent);
      add({ kind: "node", node: String(d.node ?? "node"), detail: describe(d.update) });
    });
    es.addEventListener("custom", (ev) => {
      const d = parse(ev as MessageEvent);
      add({ kind: "custom", detail: JSON.stringify(d).slice(0, 160) });
    });
    es.addEventListener("interrupt", () => {
      add({ kind: "interrupt", node: "approval", detail: "Waiting for your approval" });
    });
    es.addEventListener("status", (ev) => {
      const d = parse(ev as MessageEvent);
      last = String(d.status ?? "");
      setStatus(last);
      add({ kind: "status", detail: `Run status: ${last}` });
    });
    es.addEventListener("error", (ev) => {
      const data = (ev as MessageEvent).data;
      if (typeof data === "string" && data) add({ kind: "error", detail: data.slice(0, 200) });
    });
    es.addEventListener("done", () => {
      setConn("closed");
      es.close();
      onFinished?.(last);
    });
    es.onerror = () => {
      // The browser retries by itself. After a clean close we are already in "closed".
      setConn((c) => (c === "closed" ? c : "error"));
    };
    return () => es.close();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [threadId]);

  return (
    <section aria-label="Run timeline" data-testid="run-timeline" className="card">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <h2 className="h2 mb-0">Live agent progress</h2>
        <div className="flex items-center gap-2 text-xs">
          <Badge tone={conn === "live" ? "green" : conn === "error" ? "red" : "slate"}>
            {conn === "live" ? "streaming" : conn === "closed" ? "finished" : conn === "error" ? "reconnecting" : "connecting"}
          </Badge>
          {status && <Badge tone={statusTone(status)}>{status.replace("_", " ")}</Badge>}
        </div>
      </div>
      {events.length === 0 ? (
        <p className="text-sm text-slate-500" role="status">
          Waiting for the first agent step...
        </p>
      ) : (
        <ol className="space-y-2" aria-live="polite">
          {events.map((e) => (
            <li key={e.key} className="flex gap-3 text-sm">
              <span
                aria-hidden
                className={`mt-1.5 h-2.5 w-2.5 shrink-0 rounded-full ${
                  e.kind === "error" ? "bg-rose-500" : e.kind === "interrupt" ? "bg-indigo-500" : "bg-emerald-500"
                }`}
              />
              <div className="min-w-0">
                <p className="font-medium text-slate-900">{e.node ?? e.kind}</p>
                {e.detail && <p className="break-words text-slate-600">{e.detail}</p>}
              </div>
            </li>
          ))}
        </ol>
      )}
      {traceId && (
        <p className="mt-4 border-t border-slate-100 pt-3 text-xs text-slate-500">
          Trace id: <code data-testid="trace-id">{traceId}</code>. Full trace is in the tracing backend under this id.
        </p>
      )}
    </section>
  );
}
