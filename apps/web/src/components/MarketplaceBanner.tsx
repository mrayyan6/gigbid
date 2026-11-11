"use client";

import { api, unwrap } from "@/lib/api/client";
import { useLoad } from "@/lib/useLoad";

const POLL_MS = 4000;

/** Polls /api/health. Shows degraded mode when the marketplace (or the API) is unreachable. */
export function MarketplaceBanner() {
  const { data, error } = useLoad(() => unwrap(api.GET("/api/health")), [], POLL_MS);

  if (error && !data) {
    return (
      <div role="alert" data-testid="api-banner" className="bg-rose-700 px-4 py-2 text-center text-sm text-white">
        The GigBid API is unreachable. Retrying automatically.
      </div>
    );
  }
  if (data && data.marketplace === "down") {
    return (
      <div
        role="alert"
        data-testid="marketplace-banner"
        className="bg-amber-500 px-4 py-2 text-center text-sm font-medium text-slate-900"
      >
        Marketplace unavailable, work is queued
        {data.queued_runs > 0 ? ` (${data.queued_runs} waiting)` : ""}. It resumes automatically when the
        marketplace is back.
      </div>
    );
  }
  return null;
}
