"use client";

import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";
import { api, errorMessage, unwrap } from "@/lib/api/client";
import { getToken, getUser, markOnboarded } from "@/lib/auth";
import { Loading, ErrorBox } from "@/components/ui";
import { useLoad } from "@/lib/useLoad";

const PERSONAS = [
  { id: "ai_ml", label: "AI and ML engineer" },
  { id: "web", label: "Full stack web developer" },
  { id: "data", label: "Data analyst" },
];

export default function OnboardingPage() {
  const router = useRouter();
  const settings = useLoad(() => unwrap(api.GET("/api/settings")), []);
  const [rate, setRate] = useState<string>("");
  const [budget, setBudget] = useState<string>("");
  const [keywords, setKeywords] = useState<string>("");
  const [files, setFiles] = useState<FileList | null>(null);
  const [uploadNote, setUploadNote] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [touched, setTouched] = useState(false);

  if (settings.loading) return <Loading />;
  if (settings.error || !settings.data) {
    return <ErrorBox message={settings.error ?? "Could not load settings"} onRetry={settings.reload} />;
  }
  const s = settings.data;
  const persona = getUser()?.persona ?? s.persona;

  const rateVal = touched ? rate : String(s.min_hourly_rate);
  const budgetVal = touched ? budget : String(s.weekly_connects_budget);
  const kwVal = touched ? keywords : (s.keywords ?? []).join(", ");

  function edit(setter: (v: string) => void, v: string) {
    if (!touched) {
      setRate(String(s.min_hourly_rate));
      setBudget(String(s.weekly_connects_budget));
      setKeywords((s.keywords ?? []).join(", "));
      setTouched(true);
    }
    setter(v);
  }

  async function upload(): Promise<void> {
    if (!files || files.length === 0) return;
    const form = new FormData();
    Array.from(files).forEach((f) => form.append("files", f));
    try {
      const res = await fetch("/api/portfolio/upload", {
        method: "POST",
        headers: { Authorization: `Bearer ${getToken() ?? ""}` },
        body: form,
      });
      if (res.ok) setUploadNote("Portfolio uploaded. Re-indexing started.");
      else if (res.status === 404 || res.status === 405)
        setUploadNote("Upload is not enabled on this server yet. Your persona's seeded portfolio is used.");
      else setUploadNote(`Upload failed (${res.status}).`);
    } catch {
      setUploadNote("Upload failed, the API is unreachable.");
    }
  }

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await upload();
      await unwrap(
        api.PUT("/api/settings", {
          body: {
            autonomy: s.autonomy,
            weekly_connects_budget: Math.max(0, Math.round(Number(budgetVal) || 0)),
            min_hourly_rate: Math.max(0, Number(rateVal) || 0),
            keywords: kwVal
              .split(",")
              .map((k) => k.trim())
              .filter(Boolean),
            saved_searches: s.saved_searches,
          },
        }),
      );
      const u = getUser();
      if (u) markOnboarded(u.id);
      router.replace("/inbox");
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={submit} className="mx-auto max-w-2xl space-y-6" aria-label="Onboarding">
      <div>
        <h1 className="h1">Set up your workspace</h1>
        <p className="text-sm text-slate-600">Four quick choices. You can change all of them later in Settings.</p>
      </div>

      <fieldset className="card">
        <legend className="h2 px-1">1. Persona</legend>
        <div className="grid gap-2 sm:grid-cols-3">
          {PERSONAS.map((p) => {
            const selected = p.id === persona;
            return (
              <label
                key={p.id}
                className={`flex cursor-pointer items-center gap-2 rounded-md border p-3 text-sm ${
                  selected ? "border-indigo-600 bg-indigo-50" : "border-slate-200 opacity-60"
                }`}
              >
                <input type="radio" name="persona" value={p.id} checked={selected} disabled={!selected} readOnly />
                {p.label}
              </label>
            );
          })}
        </div>
        <p className="mt-2 text-xs text-slate-500">Your persona is fixed when the account is created.</p>
      </fieldset>

      <fieldset className="card">
        <legend className="h2 px-1">2. Marketplace</legend>
        <div className="grid gap-2 sm:grid-cols-2">
          <label className="flex items-center gap-2 rounded-md border border-indigo-600 bg-indigo-50 p-3 text-sm">
            <input type="radio" name="marketplace" value="gigsim" checked readOnly />
            GigSim (simulated marketplace)
          </label>
          <label className="flex items-center gap-2 rounded-md border border-slate-200 p-3 text-sm opacity-60">
            <input type="radio" name="marketplace" value="upwork" disabled />
            Upwork (live mode untested, disabled)
          </label>
        </div>
      </fieldset>

      <fieldset className="card">
        <legend className="h2 px-1">3. Rates, budget and filters</legend>
        <div className="grid gap-4 sm:grid-cols-2">
          <div>
            <label htmlFor="rate" className="label">
              Minimum hourly rate (USD)
            </label>
            <input
              id="rate"
              name="rate"
              type="number"
              min={0}
              className="input"
              value={rateVal}
              onChange={(e) => edit(setRate, e.target.value)}
            />
          </div>
          <div>
            <label htmlFor="budget" className="label">
              Weekly Connects budget
            </label>
            <input
              id="budget"
              name="budget"
              type="number"
              min={0}
              className="input"
              value={budgetVal}
              onChange={(e) => edit(setBudget, e.target.value)}
            />
          </div>
          <div className="sm:col-span-2">
            <label htmlFor="keywords" className="label">
              Keyword filters (comma separated)
            </label>
            <input
              id="keywords"
              name="keywords"
              className="input"
              placeholder="rag, langchain, fastapi"
              value={kwVal}
              onChange={(e) => edit(setKeywords, e.target.value)}
            />
          </div>
        </div>
      </fieldset>

      <fieldset className="card">
        <legend className="h2 px-1">4. Portfolio (optional)</legend>
        <label htmlFor="portfolio" className="label">
          Upload case studies, CV or READMEs
        </label>
        <input
          id="portfolio"
          name="portfolio"
          type="file"
          multiple
          className="block w-full text-sm"
          onChange={(e) => setFiles(e.target.files)}
        />
        {uploadNote && (
          <p role="status" className="mt-2 text-sm text-slate-600">
            {uploadNote}
          </p>
        )}
      </fieldset>

      {error && <ErrorBox message={error} />}
      <button type="submit" className="btn-primary" disabled={busy}>
        {busy ? "Saving..." : "Save and continue"}
      </button>
    </form>
  );
}
