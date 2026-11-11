"""End to end smoke test against a running GigBid URL: login, run one job to the approval interrupt, approve it,
see it in the pipeline. Reads GIGBID_URL, REVIEWER_EMAIL and REVIEWER_PASSWORD from the environment (.env).
Run: python scripts/smoke_live.py [base_url]
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.request as u
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env")
BASE = (sys.argv[1] if len(sys.argv) > 1 else os.environ.get("GIGBID_URL", "http://localhost:7860")).rstrip("/")


def call(path, data=None, token=None, method=None):
    req = u.Request(BASE + path, data=json.dumps(data).encode() if data is not None else None, method=method,
                    headers={"Content-Type": "application/json", **({"Authorization": "Bearer " + token} if token else {})})
    return json.loads(u.urlopen(req, timeout=120).read() or b"null")


def main() -> int:
    t0 = time.time()
    tok = call("/api/auth/login", {"email": os.environ.get("REVIEWER_EMAIL", "reviewer@gigbid.demo"),
                                   "password": os.environ["REVIEWER_PASSWORD"]})["access_token"]
    print("login ok", call("/api/health")["marketplace"])
    jobs = call("/api/jobs", token=tok)
    print("jobs:", len(jobs))
    for j in jobs:
        run = call("/api/runs", {"job_id": j["job_id"]}, tok)
        tid = run.get("thread_id") or run.get("tid") or run.get("id")
        for _ in range(90):
            st = call(f"/api/runs/{tid}", token=tok)
            if st.get("status") in ("awaiting_approval", "skipped", "watching", "needs_attention", "submitted", "failed"):
                break
            time.sleep(3)
        print(j["job_id"], "->", st.get("status"))
        if st.get("status") == "awaiting_approval":
            res = call(f"/api/approvals/{tid}", {"action": "approve"}, tok)
            print("approved:", res.get("status"))
            pipe = call("/api/pipeline", token=tok)
            n = sum(len(v) for v in pipe.values()) if isinstance(pipe, dict) else len(pipe)
            print("pipeline cards:", n, f"({time.time() - t0:.0f}s total)")
            return 0
    print("no job reached approval")
    return 1


if __name__ == "__main__":
    sys.exit(main())
