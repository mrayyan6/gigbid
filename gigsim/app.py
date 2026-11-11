"""GigSim: our own synthetic marketplace REST API. Run: uvicorn gigsim.app:app --port 9000.
Hidden gold labels and client preferences are never returned by any endpoint."""
from __future__ import annotations

import hashlib
import json
import re
import time
from collections import defaultdict, deque
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from gigsim import generate

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "processed" / "gigsim"
POLICY = ROOT / "data" / "policy_pack" / "gigsim_policy.json"
if not (DATA / "jobs.json").exists():  # fresh clone: data/processed is git-ignored
    generate.build()
TOKEN = "gigsim-dev-token"
RATE_OVERRIDE: int | None = None  # eval harness only

app = FastAPI(title="GigSim", version="0.1.0")
_hits: dict[str, deque] = defaultdict(deque)


def _load(name: str):
    return json.loads((DATA / f"{name}.json").read_text(encoding="utf-8"))


class Store:
    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self.jobs = {j["job_id"]: j for j in _load("jobs") + _load("dev_jobs")}
        self.clients = {c["client_id"]: c for c in _load("clients")}
        self.connects: dict[str, int] = defaultdict(lambda: 200)
        self.proposals: dict[str, dict] = {}
        self.idem: dict[str, str] = {}
        self.messages: dict[str, list[dict]] = defaultdict(list)


store = Store()


def policy() -> dict:
    """Re-read each call so the platform policy update (change request) takes effect live."""
    return json.loads(POLICY.read_text(encoding="utf-8"))


def auth(authorization: str = Header(default="")) -> str:
    if authorization != f"Bearer {TOKEN}":
        raise HTTPException(401, "bad token")
    now = time.time()
    q = _hits[authorization]
    while q and now - q[0] > 60:
        q.popleft()
    if len(q) >= (RATE_OVERRIDE or policy()["rate_limit_per_min"]):
        raise HTTPException(429, "rate limited", headers={"Retry-After": "5"})
    q.append(now)
    return "user"


def public_job(j: dict) -> dict:
    return {k: v for k, v in j.items() if k != "gold"}


def connects_cost(j: dict) -> int:
    p = policy()
    return round(j["connects_cost"] * p["connects_multiplier"]) + int(p.get("boost_fee_connects", 0))


@app.get("/health")
def health():
    return {"status": "ok", "service": "gigsim"}


@app.get("/policy")
def get_policy(_: str = Depends(auth)):
    """Current platform policy. Agents read this instead of hard-coding platform rules."""
    return policy()


@app.post("/admin/reset")
def reset(_: str = Depends(auth)):
    store.reset()
    return {"ok": True}


class JobIn(BaseModel):
    model_config = ConfigDict(extra="allow")
    job_id: str
    title: str
    description: str
    required_skills: list[str]
    budget: dict
    client_id: str
    connects_cost: int = 10


@app.post("/admin/jobs/load")
def load_jobs(jobs: list[JobIn], _: str = Depends(auth)):
    """Inject a batch of jobs (for example an instructor's hidden test batch). Unknown clients get
    a neutral stub. Missing gold fields default to a neutral label and the budget as fair band."""
    for jin in jobs:
        j = jin.model_dump()
        b = j["budget"]
        j.setdefault("duration_days", 14)
        j.setdefault("screening_questions", [])
        j.setdefault("warning_signals", [])
        j.setdefault("source", "admin_load")
        j["gold"] = {"action": "bid", "kind": "loaded", "scam": False, "injected": False,
                     "fair_price_band": [b.get("min", 0), b.get("max", 0)], "persona": "loaded",
                     **j.get("gold", {})}
        store.jobs[j["job_id"]] = j
        store.clients.setdefault(j["client_id"], {
            "client_id": j["client_id"], "name": j["client_id"], "industry": "other",
            "payment_verified": True, "total_spent": 0, "hire_rate": 0.0, "avg_rating": 0.0,
            "hidden_preference": "metrics", "source": "admin_load"})
    return {"loaded": len(jobs), "total_jobs": len(store.jobs)}


@app.get("/jobs")
def search_jobs(query: str = "", limit: int = 20, persona: str | None = None,
                _: str = Depends(auth)):
    q = query.lower()
    out = []
    for j in store.jobs.values():
        if persona and f"-{persona}-" not in j["job_id"]:
            continue
        if q and q not in (j["title"] + " " + j["description"] + " ".join(j["required_skills"])).lower():
            continue
        out.append({**public_job(j), "connects_cost": connects_cost(j)})
        if len(out) >= limit:
            break
    return out


@app.get("/jobs/{job_id}")
def get_job(job_id: str, _: str = Depends(auth)):
    j = store.jobs.get(job_id)
    if not j:
        raise HTTPException(404, "job not found")
    return {**public_job(j), "connects_cost": connects_cost(j)}


@app.get("/clients/{client_id}/history")
def client_history(client_id: str, _: str = Depends(auth)):
    c = store.clients.get(client_id)
    if not c:
        raise HTTPException(404, "client not found")
    return {k: v for k, v in c.items() if k != "hidden_preference"}


@app.get("/connects")
def connects(user: str = Depends(auth)):
    return {"balance": store.connects[user]}


class ProposalIn(BaseModel):
    job_id: str
    cover_letter: str = Field(min_length=1)
    bid_amount: float
    screening_answers: list[str] = []


def _reply_probability(job: dict, client: dict, p: dict) -> float:
    text = p["cover_letter"].lower()
    pref = client["hidden_preference"]
    keys = {"metrics": ["%", "percent", "accuracy", "reduced"], "speed": ["days", "deliver", "fast"],
            "communication": ["update", "weekly", "communicat"],
            "domain_expertise": [client["industry"]], "low_price": []}[pref]
    base = 0.08
    base += 0.15 if any(k in text for k in keys) else 0
    lo, hi = job["gold"]["fair_price_band"]
    base += 0.12 if lo <= p["bid_amount"] <= hi else -0.05
    base += 0.10 if job["title"].split()[0].lower() in text else 0
    if pref == "low_price" and p["bid_amount"] < (lo + hi) / 2:
        base += 0.15
    if job["gold"]["scam"]:
        base = 0.0
    return max(0.0, min(0.9, base))


def _draw(key: str) -> float:
    return int(hashlib.sha256(key.encode()).hexdigest()[:8], 16) / 0xFFFFFFFF


def _check_daily_cap(pol: dict, user: str) -> None:
    cap = pol.get("max_proposals_per_day")
    if cap is None:
        return
    recent = [p for p in store.proposals.values() if time.time() - p["created_at"] < 86400]
    if len(recent) >= cap:
        raise HTTPException(429, "daily proposal limit reached", headers={"Retry-After": "3600"})


@app.post("/proposals")
def create_proposal(body: ProposalIn, dry_run: bool = False,
                    idempotency_key: str = Header(default=""), user: str = Depends(auth)):
    job = store.jobs.get(body.job_id)
    if not job:
        raise HTTPException(404, "job not found")
    cost = connects_cost(job)
    pol = policy()
    if "min_budget_usd" in pol and job["budget"]["max"] < pol["min_budget_usd"]:
        raise HTTPException(422, f"job budget below platform minimum {pol['min_budget_usd']} USD")
    if pol.get("banned_link_regex") and re.search(pol["banned_link_regex"], body.cover_letter):
        raise HTTPException(422, "proposal contains a link that the platform policy forbids")
    if dry_run:
        _check_daily_cap(pol, user)
        return {"dry_run": True, "would_send": body.model_dump(), "connects_cost": cost,
                "balance_after": store.connects[user] - cost}
    if not idempotency_key:
        raise HTTPException(400, "Idempotency-Key header required")
    if idempotency_key in store.idem:
        return {**store.proposals[store.idem[idempotency_key]], "idempotent_replay": True}
    _check_daily_cap(pol, user)
    if store.connects[user] < cost:
        raise HTTPException(402, "not enough connects")
    store.connects[user] -= cost
    pid = f"prop-{len(store.proposals) + 1:05d}"
    client = store.clients[job["client_id"]]
    prob = _reply_probability(job, client, body.model_dump())
    replied = _draw(pid + body.job_id) < prob
    rec = {"proposal_id": pid, "job_id": body.job_id, "status": "replied" if replied else "submitted",
           "connects_spent": cost, "created_at": time.time(), **body.model_dump()}
    store.proposals[pid] = rec
    store.idem[idempotency_key] = pid
    if replied:
        store.messages[client["client_id"]].append(
            {"message_id": f"m-{pid}", "client_id": client["client_id"], "job_id": body.job_id,
             "from": "client", "text": f"Thanks for your proposal. Could you share more about {job['title']}?"})
    return rec


@app.get("/proposals")
def list_proposals(_: str = Depends(auth)):
    return list(store.proposals.values())


@app.get("/proposals/{pid}")
def get_proposal(pid: str, _: str = Depends(auth)):
    if pid not in store.proposals:
        raise HTTPException(404, "not found")
    return store.proposals[pid]


@app.get("/messages")
def list_messages(client_id: str | None = None, _: str = Depends(auth)):
    if client_id:
        return store.messages.get(client_id, [])
    return [m for ms in store.messages.values() for m in ms]


class MessageIn(BaseModel):
    client_id: str
    text: str


@app.post("/messages")
def send_message(body: MessageIn, idempotency_key: str = Header(default=""),
                 _: str = Depends(auth)):
    if not idempotency_key:
        raise HTTPException(400, "Idempotency-Key header required")
    if idempotency_key in store.idem:
        return {"idempotent_replay": True}
    m = {"message_id": f"m-{idempotency_key}", "client_id": body.client_id, "from": "freelancer",
         "text": body.text}
    store.messages[body.client_id].append(m)
    store.idem[idempotency_key] = m["message_id"]
    return m
