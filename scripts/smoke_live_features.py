"""Check the portfolio upload, the GitHub import answer and message drafting on a running GigBid URL.

Run: python scripts/smoke_live_features.py <base_url>
Reads REVIEWER_EMAIL and REVIEWER_PASSWORD from the environment (.env). It adds one small test item to the
reviewer's portfolio (remove it afterwards, see docs/RUNBOOK.md) and never sends a message.
"""
from __future__ import annotations

import io
import json
import os
import sys
import time
import urllib.error
import urllib.request as u
import uuid
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env")
BASE = (sys.argv[1] if len(sys.argv) > 1 else "http://localhost:7860").rstrip("/")


def call(path, data=None, token=None, raw=None, ctype="application/json"):
    body = raw if raw is not None else (json.dumps(data).encode() if data is not None else None)
    req = u.Request(BASE + path, data=body, headers={"Content-Type": ctype, **({"Authorization": "Bearer " + token} if token else {})})
    try:
        with u.urlopen(req, timeout=120) as r:
            return r.status, json.loads(r.read() or b"null")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"null")


def multipart(name: str, content: bytes) -> tuple[bytes, str]:
    b = uuid.uuid4().hex
    buf = io.BytesIO()
    buf.write(f'--{b}\r\nContent-Disposition: form-data; name="files"; filename="{name}"\r\nContent-Type: text/markdown\r\n\r\n'.encode())
    buf.write(content + f"\r\n--{b}--\r\n".encode())
    return buf.getvalue(), f"multipart/form-data; boundary={b}"


def main() -> int:
    ok = True
    _, tok = call("/api/auth/login", {"email": os.environ.get("REVIEWER_EMAIL", "reviewer@gigbid.demo"),
                                      "password": os.environ["REVIEWER_PASSWORD"]})
    t = tok["access_token"]
    s, p = call("/api/portfolio", token=t)
    print("GET /api/portfolio", s, p.get("seeded_items"), "built in,", len(p.get("uploaded", [])), "uploaded")
    ok &= s == 200
    marker = f"Smoke check {int(time.time())}"
    body, ctype = multipart("smoke_case_study.md", (
        f"# {marker}\nBuilt a small OCR and NLP pipeline in Python and FastAPI. Cut manual entry by 70% for a logistics client.").encode())
    s, up = call("/api/portfolio/upload", token=t, raw=body, ctype=ctype)
    print("POST /api/portfolio/upload", s, {k: up.get(k) for k in ("added", "chunks_embedded", "reindex_seconds", "user_items")})
    ok &= s == 200 and up.get("added") == 1 and up.get("chunks_embedded") == 1
    s, up2 = call("/api/portfolio/upload", token=t, raw=body, ctype=ctype)
    print("same file again", s, {k: up2.get(k) for k in ("added", "duplicates", "chunks_embedded")})
    ok &= s == 200 and up2.get("added") == 0 and up2.get("duplicates") == 1
    s, gh = call("/api/portfolio/github", {"repo": "mrayyan6/gigbid"}, token=t)
    print("POST /api/portfolio/github", s, gh)
    ok &= s in (200, 503)
    s, m = call("/api/messages", token=t)
    threads = (m or {}).get("threads", [])
    print("GET /api/messages", s, len(threads), "threads")
    for th in threads[:1]:
        s, d = call(f"/api/messages/{th['client_id']}/draft", {}, token=t)
        print("draft", s, d.get("intent"), "slots:", len(d.get("slots", [])), "|", str(d.get("draft"))[:90])
        ok &= s == 200
    print("RESULT", "ok" if ok else "FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
