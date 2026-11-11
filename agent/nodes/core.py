"""Bid graph nodes. Rules and thresholds come from agent/config.yaml, prompts from agent/prompts.

Dependencies (marketplace port, retriever) arrive via config['configurable'] so tests can inject
fakes and the live adapter can swap in without touching nodes.
"""
from __future__ import annotations

import re
from pathlib import Path

import yaml

from agent import handoffs as h

ROOT = Path(__file__).resolve().parents[1]
CFG = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))


def load_prompt(name: str) -> str:
    return (ROOT / "prompts" / f"{name}.md").read_text(encoding="utf-8")


def _t(node: str, **kw) -> dict:
    return {"trace": [{"node": node, **kw}]}


def deps(config) -> dict:
    return config["configurable"]


async def scout(state, config):
    job = await deps(config)["marketplace"].get_job(state["job_id"])
    client = {}
    if job.get("client_id"):
        client = await deps(config)["marketplace"].get_client_history(job["client_id"])
    return {"job": {**job, "client": client}, "steps": 1, **_t("scout", tool="get_job",
            args={"job_id": state["job_id"]})}


def analyst(state, config):
    j = state["job"]
    spec = h.JobSpec(job_id=j["job_id"], title=j["title"],
                     deliverables=[s.strip() for s in j["description"].split(".")[:2] if s.strip()],
                     required_skills=j["required_skills"], budget_min=j["budget"]["min"],
                     budget_max=j["budget"]["max"], connects_cost=j["connects_cost"])
    return {"job_spec": spec.model_dump(), **_t("analyst")}


def risk(state, config):
    j = state["job"]
    text = (j["title"] + " " + j["description"]).lower()
    flags = set(j.get("warning_signals", []))
    for flag, pats in CFG["risk"]["patterns"].items():
        if any(p in text for p in pats):
            flags.add(flag)
    cl = j.get("client", {})
    if cl and not cl.get("payment_verified", True):
        flags.add("payment_unverified")
    if j["budget"]["max"] == 0:
        flags.add("zero_budget")
    score = min(1.0, 0.35 * len(flags & {"unpaid_work", "unpaid", "off_platform_contact",
                                         "off_platform", "payment_fraud", "zero_budget"})
                + 0.2 * ("payment_unverified" in flags) + 0.3 * ("injection" in flags
                                                                or "prompt_injection" in flags))
    r = h.RiskReport(score=score, flags=sorted(flags), explanation=f"{len(flags)} risk flags")
    return {"risk_report": r.model_dump(), **_t("risk", flags=sorted(flags))}


async def matcher(state, config):
    retr = deps(config)["retriever"]
    matched, missing, ev = [], [], []
    for skill in state["job"]["required_skills"]:
        hits = retr.search(skill, k=3)
        good = [x for x in hits if skill.lower() in [s.lower() for s in x["skills"]]]
        if good:
            matched.append(skill)
            ev.extend(good[:1])
        else:
            missing.append(skill)
    uniq = {e["evidence_id"]: e for e in ev}
    n = max(1, len(state["job"]["required_skills"]))
    f = h.FitReport(score=len(matched) / n, matched_skills=matched, missing_skills=missing,
                    evidence_ids=list(uniq))
    return {"fit_report": f.model_dump(), "evidence": list(uniq.values()),
            **_t("matcher", tool="search_evidence", n=n)}


def decide(state, config):
    d, rk, ft = CFG["decision"], state["risk_report"], state["fit_report"]
    if rk["score"] >= d["risk_skip"]:
        dec = h.BidDecision(action="skip", reason=f"risk {rk['score']:.2f}: {rk['flags']}")
    elif ft["score"] >= d["fit_bid"]:
        dec = h.BidDecision(action="bid", reason=f"fit {ft['score']:.2f}")
    elif ft["score"] >= d["fit_watch"]:
        dec = h.BidDecision(action="watch", reason=f"borderline fit {ft['score']:.2f}")
    else:
        dec = h.BidDecision(action="skip", reason=f"low fit {ft['score']:.2f}")
    return {"decision": dec.model_dump(), **_t("decide", action=dec.action)}


def route_decision(state):
    return "pricing" if state["decision"]["action"] == "bid" else "end"


def pricing(state, config):
    p, b = CFG["pricing"], state["job"]["budget"]
    lo, hi = b["min"], b["max"]
    amt = lo + (hi - lo) * p["target_position"]
    q = h.PriceQuote(amount=round(amt), band_low=lo, band_high=hi,
                     rationale=f"midpoint of client budget {lo}-{hi}")
    return {"price_quote": q.model_dump(), **_t("pricing")}


def _sentences(text: str) -> list[str]:
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()]


def writer(state, config):
    j, ev = state["job"], state["evidence"]
    crit = state.get("critique", {})
    skills = ", ".join(state["fit_report"]["matched_skills"][:4])
    lines = [f"Your {j['title'].lower()} needs {skills}, and I have shipped closely related work."]
    for e in ev[:3]:
        lines.append(f"On {e['title']}, I used {', '.join(e['skills'][:3])} and the outcome was: "
                     f"{e['outcome']}. [ev:{e['evidence_id']}]")
    if "no concrete outcome" in " ".join(crit.get("issues", [])):
        lines.append("I will share weekly updates and a clear delivery plan.")
    lines.append(f"I can deliver for {state['price_quote']['amount']} USD within "
                 f"{j['duration_days']} days.")
    draft = h.ProposalDraft(job_id=j["job_id"], cover_letter=" ".join(lines),
                            evidence_ids=[e["evidence_id"] for e in ev[:3]])
    return {"proposal_draft": draft.model_dump(), "steps": 1, **_t("writer")}


def verifier(state, config):
    """Claim verification: sentences about past work must cite real evidence, else removed."""
    ev = {e["evidence_id"]: e for e in state["evidence"]}
    kept, report = [], []
    for s in _sentences(state["proposal_draft"]["cover_letter"]):
        tags = re.findall(r"\[ev:([^\]]+)\]", s)
        past_claim = bool(re.search(r"\b(I used|I have shipped|I built|my outcome|outcome was)\b", s))
        if tags and all(t in ev for t in tags):
            status = "supported"
        elif past_claim or tags:
            status = "unsupported"
        else:
            status = "no_claim"
        report.append({"claim": s, "status": status})
        if status != "unsupported":
            kept.append(s)
    d = dict(state["proposal_draft"], cover_letter=" ".join(kept))
    return {"proposal_draft": d, "claim_verification": report, **_t("verifier")}


def critic(state, config):
    d, issues = state["proposal_draft"], []
    text = d["cover_letter"]
    if re.match(r"(?i)\s*(hi|hello|dear)\b", text):
        issues.append("generic opening")
    if len(text.split()) > CFG["compliance"]["max_words"]:
        issues.append("too long")
    if "[ev:" not in text:
        issues.append("no concrete outcome with evidence")
    c = h.Critique(ok=not issues, issues=issues)
    return {"critique": c.model_dump(), "revisions": state.get("revisions", 0) + (0 if c.ok else 1),
            **_t("critic", ok=c.ok)}


def route_critic(state):
    if state["critique"]["ok"] or state.get("revisions", 0) > CFG["budgets"]["critic_max_revisions"]:
        return "compliance"
    return "writer"


def compliance(state, config):
    text = state["proposal_draft"]["cover_letter"].lower()
    bad = [p for p in CFG["compliance"]["banned_phrases"] if p in text]
    v = h.ComplianceVerdict(allowed=not bad, violations=bad)
    return {"compliance_verdict": v.model_dump(), **_t("compliance", allowed=v.allowed)}
