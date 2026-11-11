"use client";

import { useState } from "react";
import { api, errorMessage, unwrap, type Schemas } from "@/lib/api/client";
import { useLoad } from "@/lib/useLoad";
import { Badge, Empty, ErrorBox, Loading, PageHeader } from "@/components/ui";

type Draft = Schemas["DraftOut"];

export default function MessagesPage() {
  const threads = useLoad(() => unwrap(api.GET("/api/messages")), [], 15000);
  const [drafts, setDrafts] = useState<Record<string, Draft>>({});
  const [busy, setBusy] = useState<string | null>(null);
  const [errors, setErrors] = useState<Record<string, string>>({});

  async function suggest(clientId: string) {
    setBusy(clientId);
    setErrors((e) => ({ ...e, [clientId]: "" }));
    try {
      const d = await unwrap(
        api.POST("/api/messages/{client_id}/draft", { params: { path: { client_id: clientId } }, body: {} }),
      );
      setDrafts((prev) => ({ ...prev, [clientId]: d }));
    } catch (e) {
      setErrors((prev) => ({ ...prev, [clientId]: errorMessage(e) }));
    } finally {
      setBusy(null);
    }
  }

  if (threads.loading && !threads.data) return <Loading label="Loading messages" />;
  if (threads.error && !threads.data) return <ErrorBox message={threads.error} onRetry={threads.reload} />;
  const list = threads.data?.threads ?? [];

  return (
    <div>
      <PageHeader title="Messages" />
      {list.length === 0 ? (
        <Empty title="No client conversations yet" hint="Clients reply here after your proposals are submitted." />
      ) : (
        <ul className="space-y-4">
          {list.map((t) => {
            const draft = drafts[t.client_id];
            return (
              <li key={t.client_id} className="card" data-testid="thread">
                <h2 className="h2">Client {t.client_id}</h2>
                <ul className="mb-3 space-y-2">
                  {t.messages.map((m, i) => {
                    const mine = m.from === "freelancer";
                    return (
                      <li
                        key={String(m.message_id ?? i)}
                        className={`max-w-prose rounded-md p-2 text-sm ${mine ? "ml-auto bg-indigo-50" : "bg-slate-100"}`}
                      >
                        <span className="block text-xs text-slate-500">{mine ? "You" : "Client"}</span>
                        {String(m.text ?? "")}
                      </li>
                    );
                  })}
                </ul>
                {errors[t.client_id] && <ErrorBox message={errors[t.client_id]} />}
                {draft ? (
                  <div className="rounded-md border border-indigo-200 bg-indigo-50 p-3" data-testid="suggested-reply">
                    <div className="mb-2 flex flex-wrap items-center gap-2">
                      <span className="text-sm font-medium">Suggested reply</span>
                      <Badge tone="indigo">{draft.intent.replace(/_/g, " ")}</Badge>
                      {draft.status === "flagged" && <Badge tone="red">flagged as possible scam</Badge>}
                    </div>
                    <label htmlFor={`reply-${t.client_id}`} className="sr-only">
                      Reply text
                    </label>
                    <textarea
                      id={`reply-${t.client_id}`}
                      className="input min-h-[6rem]"
                      value={draft.draft}
                      onChange={(e) => setDrafts((prev) => ({ ...prev, [t.client_id]: { ...draft, draft: e.target.value } }))}
                    />
                    {(draft.slots ?? []).length > 0 && (
                      <ul className="mt-2 text-sm">
                        {(draft.slots ?? []).map((s, i) => (
                          <li key={i}>Slot: {String((s as Record<string, unknown>).start ?? JSON.stringify(s))}</li>
                        ))}
                      </ul>
                    )}
                    <div className="mt-2 flex flex-wrap items-center gap-2">
                      <button type="button" className="btn-primary" disabled title="The send endpoint is not part of the API contract yet">
                        Approve and send
                      </button>
                      <p className="text-xs text-slate-600">
                        Sending is disabled: the API contract has no send endpoint yet. Nothing was sent.
                      </p>
                    </div>
                  </div>
                ) : (
                  <button type="button" className="btn" disabled={busy === t.client_id} onClick={() => suggest(t.client_id)}>
                    {busy === t.client_id ? "Drafting..." : "Suggest a reply"}
                  </button>
                )}
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
