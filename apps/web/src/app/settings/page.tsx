"use client";

import { useEffect, useState, type FormEvent } from "react";
import { api, errorMessage, unwrap, type Schemas } from "@/lib/api/client";
import { useLoad } from "@/lib/useLoad";
import { Badge, Empty, ErrorBox, KeyVal, Loading, PageHeader } from "@/components/ui";

type Form = {
  autonomy: "manual" | "auto_skip_low_fit";
  weekly_connects_budget: string;
  min_hourly_rate: string;
  keywords: string;
  saved_searches: Schemas["SavedSearch"][];
};

export default function SettingsPage() {
  const settings = useLoad(() => unwrap(api.GET("/api/settings")), []);
  const memory = useLoad(() => unwrap(api.GET("/api/memory")), []);
  const [form, setForm] = useState<Form | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [newName, setNewName] = useState("");
  const [newQuery, setNewQuery] = useState("");
  const [memError, setMemError] = useState<string | null>(null);

  useEffect(() => {
    const s = settings.data;
    if (s && !form) {
      setForm({
        autonomy: s.autonomy ?? "manual",
        weekly_connects_budget: String(s.weekly_connects_budget ?? 100),
        min_hourly_rate: String(s.min_hourly_rate ?? 25),
        keywords: (s.keywords ?? []).join(", "),
        saved_searches: s.saved_searches ?? [],
      });
    }
  }, [settings.data, form]);

  if (settings.loading && !settings.data) return <Loading label="Loading settings" />;
  if (settings.error && !settings.data) return <ErrorBox message={settings.error} onRetry={settings.reload} />;
  const s = settings.data;
  if (!s || !form) return null;

  const set = (patch: Partial<Form>) => setForm({ ...form, ...patch });

  async function save(e: FormEvent) {
    e.preventDefault();
    if (!form) return;
    setError(null);
    setMsg(null);
    try {
      await unwrap(
        api.PUT("/api/settings", {
          body: {
            autonomy: form.autonomy,
            weekly_connects_budget: Math.max(0, Math.round(Number(form.weekly_connects_budget) || 0)),
            min_hourly_rate: Math.max(0, Number(form.min_hourly_rate) || 0),
            keywords: form.keywords.split(",").map((k) => k.trim()).filter(Boolean),
            saved_searches: form.saved_searches,
          },
        }),
      );
      setMsg("Settings saved.");
    } catch (err) {
      setError(errorMessage(err));
    }
  }

  function addSearch() {
    if (!form || !newName.trim()) return;
    set({ saved_searches: [...form.saved_searches, { name: newName.trim(), query: newQuery.trim(), interval_minutes: 30 }] });
    setNewName("");
    setNewQuery("");
  }

  async function forget(ns: string, key: string) {
    setMemError(null);
    try {
      await unwrap(api.DELETE("/api/memory/{ns}/{key}", { params: { path: { ns, key } } }));
      await memory.reload();
    } catch (err) {
      setMemError(errorMessage(err));
    }
  }

  return (
    <div className="space-y-6">
      <PageHeader title="Settings" />
      <form onSubmit={save} className="space-y-4" aria-label="Settings form">
        <section className="card">
          <h2 className="h2">Autonomy</h2>
          <label htmlFor="autonomy" className="label">
            Automatic actions
          </label>
          <select
            id="autonomy"
            className="input max-w-sm"
            value={form.autonomy}
            onChange={(e) => set({ autonomy: e.target.value as Form["autonomy"] })}
          >
            <option value="manual">Off: I review every job</option>
            <option value="auto_skip_low_fit">Auto skip low fit jobs</option>
          </select>
          <p className="mt-2 text-xs text-slate-500">GigBid never sends a proposal or message without your approval, at any level.</p>
        </section>

        <section className="card grid gap-4 sm:grid-cols-2">
          <h2 className="h2 sm:col-span-2">Budgets and filters</h2>
          <div>
            <label htmlFor="budget" className="label">
              Weekly Connects budget
            </label>
            <input id="budget" type="number" min={0} className="input" value={form.weekly_connects_budget} onChange={(e) => set({ weekly_connects_budget: e.target.value })} />
          </div>
          <div>
            <label htmlFor="rate" className="label">
              Minimum hourly rate (USD)
            </label>
            <input id="rate" type="number" min={0} className="input" value={form.min_hourly_rate} onChange={(e) => set({ min_hourly_rate: e.target.value })} />
          </div>
          <div className="sm:col-span-2">
            <label htmlFor="keywords" className="label">
              Keyword filters (comma separated)
            </label>
            <input id="keywords" className="input" value={form.keywords} onChange={(e) => set({ keywords: e.target.value })} />
          </div>
        </section>

        <section className="card">
          <h2 className="h2">Saved searches</h2>
          {form.saved_searches.length === 0 ? (
            <p className="mb-3 text-sm text-slate-500">No saved searches.</p>
          ) : (
            <ul className="mb-3 divide-y divide-slate-100">
              {form.saved_searches.map((ss, i) => (
                <li key={i} className="flex items-center justify-between gap-2 py-2 text-sm">
                  <span>
                    <span className="font-medium">{ss.name}</span> <span className="text-slate-500">{ss.query || "all jobs"}, every {ss.interval_minutes} min</span>
                  </span>
                  <button type="button" className="btn" onClick={() => set({ saved_searches: form.saved_searches.filter((_, k) => k !== i) })} aria-label={`Remove ${ss.name}`}>
                    Remove
                  </button>
                </li>
              ))}
            </ul>
          )}
          <div className="flex flex-wrap items-end gap-2">
            <div>
              <label htmlFor="ss-name" className="label">
                Name
              </label>
              <input id="ss-name" className="input" value={newName} onChange={(e) => setNewName(e.target.value)} />
            </div>
            <div>
              <label htmlFor="ss-query" className="label">
                Query
              </label>
              <input id="ss-query" className="input" value={newQuery} onChange={(e) => setNewQuery(e.target.value)} />
            </div>
            <button type="button" className="btn" onClick={addSearch}>
              Add search
            </button>
          </div>
        </section>

        <div className="flex items-center gap-3">
          <button type="submit" className="btn-primary">
            Save settings
          </button>
          {msg && (
            <span role="status" className="text-sm text-emerald-700">
              {msg}
            </span>
          )}
        </div>
        {error && <ErrorBox message={error} />}
      </form>

      <section className="card" aria-label="Connected accounts">
        <h2 className="h2">Connected accounts</h2>
        <dl>
          <KeyVal k="Marketplace mode" v={<Badge tone="green">{s.marketplace_mode}</Badge>} />
          <KeyVal k="Upwork" v={s.upwork_status} />
          <KeyVal k="Persona" v={s.persona} />
        </dl>
      </section>

      <section className="card" aria-label="Memory viewer">
        <h2 className="h2">What GigBid learned</h2>
        <p className="mb-3 text-sm text-slate-600">
          Only items promoted by an explicit rule appear here. Delete anything you do not want used again.
        </p>
        {memError && <ErrorBox message={memError} />}
        {memory.loading && !memory.data ? (
          <Loading label="Loading memory" />
        ) : memory.error && !memory.data ? (
          <ErrorBox message={memory.error} onRetry={memory.reload} />
        ) : (memory.data?.items.length ?? 0) === 0 ? (
          <Empty title="Nothing learned yet" hint="Edit a draft before approving and GigBid may learn your style." />
        ) : (
          <ul className="divide-y divide-slate-100" data-testid="memory-list">
            {memory.data?.items.map((m) => (
              <li key={`${m.ns}/${m.key}`} className="flex items-start justify-between gap-3 py-2 text-sm">
                <div className="min-w-0">
                  <Badge tone="indigo">{m.ns}</Badge>
                  <p className="mt-1 break-words">{summarise(m.value)}</p>
                </div>
                <button type="button" className="btn-danger shrink-0" onClick={() => forget(m.ns, m.key)} aria-label={`Delete memory ${m.key}`}>
                  Delete
                </button>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}

function summarise(v: Record<string, unknown>): string {
  for (const k of ["rule", "note", "text", "summary", "description"]) {
    if (typeof v[k] === "string") return v[k] as string;
  }
  return JSON.stringify(v);
}
