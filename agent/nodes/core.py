"""Bid graph nodes. Rules and thresholds come from agent/config.yaml (+ config_extra.yaml), prompts from
agent/prompts, platform rules from the marketplace policy (get_policy), never from literals here.

Dependencies (marketplace port, retriever, memory) arrive via config['configurable'] so tests can inject
fakes and the live adapter can swap in without touching nodes.

Every node is wrapped by `guarded()`: it counts a step, accumulates tokens, retries transient errors,
and turns a failure into a visible terminal status (queued, dead_letter) instead of an exception.
`gated()` wraps routers: over the step or token budget the thread goes to `needs_attention`.
"""
from __future__ import annotations

import asyncio
import inspect
import json
import re

import httpx
from langgraph.errors import GraphBubbleUp

from agent import handoffs as h
from agent import llm
from agent.marketplace_port import MarketplaceUnavailable
from agent.nodes.config import CFG, REPO_ROOT, deep_merge, load_prompt

TERMINAL = {"needs_attention", "dead_letter", "queued"}
TRANSIENT = (MarketplaceUnavailable, httpx.TransportError, TimeoutError, ConnectionError)
END = "__end__"


def _t(node: str, **kw) -> dict:
    return {"trace": [{"node": node, **kw}]}


def deps(config) -> dict:
    return config["configurable"]


def budgets(config=None) -> dict:
    over = ((config or {}).get("configurable") or {}).get("budgets") or {}
    return deep_merge(CFG["budgets"], over)


def defences_on() -> bool:
    """security.defences in config_extra.yaml; the injection eval flips it to measure attack success."""
    return bool(CFG.get("security", {}).get("defences", True))


def untrusted(tag: str, text: str) -> str:
    """Delimit untrusted text (job posts) so prompts can tell data from instructions. No-op when defences are off."""
    return f"<{tag}>\n{text}\n</{tag}>" if defences_on() else text


def llm_fields(node: str, res: llm.LLMResult) -> dict:
    """State update for one LLM call: tokens, cost and a trace entry (no prompt or output text)."""
    return {"tokens": res.tokens, "cost_usd": res.cost_usd,
            "trace": [{"node": node, "llm": res.trace()}]}


# ---------------------------------------------------------------- failure handling and budgets
def guarded(name: str, fn):
    """Wrap a node: step counting, bounded retries for transient errors, queue or dead letter."""

    async def run(state, config):
        if state.get("status") in TERMINAL:
            return {}
        b = budgets(config)
        attempts = (b["node_retries"] if name in b["retry_nodes"] else 0) + 1
        last: Exception | None = None
        for i in range(attempts):
            try:
                if inspect.iscoroutinefunction(fn):
                    out = await fn(state, config)
                else:
                    out = await asyncio.to_thread(fn, state, config)
                out = dict(out or {})
                out["steps"] = 1
                return out
            except GraphBubbleUp:  # interrupt() must reach the runtime
                raise
            except TRANSIENT as e:
                last = e
                if i < attempts - 1:
                    await asyncio.sleep(b["retry_backoff_s"] * 2 ** i)
            except Exception as e:
                last = e
                break
        reason = f"{type(last).__name__}: {last}"
        if isinstance(last, MarketplaceUnavailable):
            return {"status": "queued", "steps": 1, "errors": [f"{name}: {reason}"],
                    "queue": [{"node": name, "reason": reason}], **_t(name, error=reason)}
        return {"status": "dead_letter", "steps": 1, "errors": [f"{name}: {reason}"],
                **_t(name, error=reason)}

    run.__name__ = name
    return run


def gated(router):
    """Wrap a router. Terminal status ends the thread, an exhausted budget routes to needs_attention."""

    def route(state, config=None):
        if state.get("status") in TERMINAL:
            return END
        b = budgets(config) if config else CFG["budgets"]
        if state.get("steps", 0) > b["max_steps_per_thread"] or \
                state.get("tokens", 0) > b["max_tokens_per_thread"]:
            return "needs_attention"
        return router(state)

    return route


def needs_attention(state, config=None):
    b = budgets(config)
    why = (f"steps {state.get('steps', 0)}/{b['max_steps_per_thread']}, "
           f"tokens {state.get('tokens', 0)}/{b['max_tokens_per_thread']}")
    return {"status": "needs_attention", "errors": [f"budget exceeded: {why}"],
            **_t("needs_attention", reason=why)}


# ---------------------------------------------------------------- policy and compliance
def agent_mp(config, agent: str):
    """The marketplace port restricted to one agent's tool allowlist (config mcp.allowlists).

    Ports without allowlists (the direct GigSim adapter used by fast tests) are returned unchanged."""
    mp = deps(config)["marketplace"]
    return mp.as_agent(agent) if hasattr(mp, "as_agent") else mp


async def get_policy(config, agent: str = "scout") -> dict:
    """Platform policy through the given agent's allowlist; falls back to the policy pack file when the port
    cannot answer, which includes an agent that has no marketplace tools (Compliance Guard)."""
    try:
        return await agent_mp(config, agent).get_policy()
    except Exception:
        try:
            return json.loads((REPO_ROOT / CFG["policy"]["pack_path"]).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}


def violations(text: str, policy: dict | None = None, check_length: bool = False) -> list[str]:
    """Deterministic compliance: banned phrases, regex patterns, platform link rule, length."""
    low, c, out = text.lower(), CFG["compliance"], []
    out += [p for p in c.get("banned_phrases", []) if p.lower() in low]
    for pat in c.get("banned_patterns", []):
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            out.append(m.group(0).lower())
    link = (policy or {}).get("banned_link_regex")
    if link:
        m = re.search(link, text)
        if m:
            out.append(f"external link: {m.group(0)}")
    if check_length and len(text.split()) > c["max_words"]:
        out.append(f"over {c['max_words']} words")
    return list(dict.fromkeys(out))


# ---------------------------------------------------------------- nodes
async def policy_of(state, config, agent: str) -> dict:
    """Policy the scout stored in state when the run started, so downstream agents (and the Compliance Guard,
    which has no marketplace tools) never need the marketplace. Falls back to a lookup through `agent`."""
    return state.get("policy") or await get_policy(config, agent)


async def scout(state, config):
    mp = agent_mp(config, "scout")
    job = await mp.get_job(state["job_id"])
    client = {}
    if job.get("client_id"):
        client = await mp.get_client_history(job["client_id"])
    return {"job": {**job, "client": client}, "policy": await get_policy(config, "scout"), "status": "running",
            **_t("scout", tool="get_job", args={"job_id": state["job_id"]})}


def analyst(state, config):
    j, a = state["job"], CFG["analyst"]
    deliverables, extra = None, {}
    if llm.enabled() and CFG["llm"]["llm_analyst"]:
        res = llm.complete("analyst", load_prompt("analyst"),
                           untrusted("job_post", f"{j['title']}\n{j['description']}"), json_mode=True)
        obj = llm.parse_json(res.text)
        if obj and isinstance(obj.get("deliverables"), list):
            deliverables = [str(x).strip() for x in obj["deliverables"] if str(x).strip()]
            deliverables = deliverables[:a["max_deliverables"]]
        extra = llm_fields("analyst", res)
    if not deliverables:
        deliverables = [s.strip() for s in j["description"].split(".")[:a["template_sentences"]]
                        if s.strip()]
    spec = h.JobSpec(job_id=j["job_id"], title=j["title"], deliverables=deliverables,
                     required_skills=j["required_skills"], budget_min=j["budget"]["min"],
                     budget_max=j["budget"]["max"], connects_cost=j["connects_cost"])
    return {"job_spec": spec.model_dump(), "tokens": extra.get("tokens", 0),
            "cost_usd": extra.get("cost_usd", 0.0),
            "trace": [{"node": "analyst", **({"llm": extra["trace"][0]["llm"]} if extra else {})}]}


def risk(state, config):
    j = state["job"]
    text = (j["title"] + " " + j["description"]).lower()
    flags = set(j.get("warning_signals", []))
    for flag, pats in CFG["risk"]["patterns"].items():
        if flag == "injection" and not defences_on():
            continue
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


async def decide(state, config):
    d, rk, ft = CFG["decision"], state["risk_report"], state["fit_report"]
    pol = await policy_of(state, config, "decide")
    floor = pol.get("min_budget_usd", 0)
    if floor and state["job"]["budget"]["max"] < floor:
        dec = h.BidDecision(action="skip", reason=f"below platform minimum budget {floor} USD")
    elif rk["score"] >= d["risk_skip"]:
        dec = h.BidDecision(action="skip", reason=f"risk {rk['score']:.2f}: {rk['flags']}")
    elif ft["score"] >= d["fit_bid"]:
        dec = h.BidDecision(action="bid", reason=f"fit {ft['score']:.2f}")
    elif ft["score"] >= d["fit_watch"]:
        dec = h.BidDecision(action="watch", reason=f"borderline fit {ft['score']:.2f}")
    else:
        dec = h.BidDecision(action="skip", reason=f"low fit {ft['score']:.2f}")
    status = {"bid": "running", "watch": "watching", "skip": "skipped"}[dec.action]
    return {"decision": dec.model_dump(), "status": status, **_t("decide", action=dec.action)}


def route_decision(state):
    return "pricing" if state["decision"]["action"] == "bid" else "end"


async def pricing(state, config):
    p, b, j = CFG["pricing"], state["job"]["budget"], state["job"]
    pol = await policy_of(state, config, "pricing")
    lo, hi = b["min"], b["max"]
    amt = lo + (hi - lo) * p["target_position"]
    # j["connects_cost"] is the effective platform cost (multiplier and boost fee already applied by the
    # marketplace), so policy values are recorded for the rationale and never applied twice.
    rationale = (f"midpoint of client budget {lo}-{hi}; connects {j['connects_cost']} "
                 f"(policy x{pol.get('connects_multiplier', 1)}, boost fee {pol.get('boost_fee_connects', 0)})")
    q = h.PriceQuote(amount=round(amt), band_low=lo, band_high=hi, rationale=rationale,
                     connects_cost=j["connects_cost"], policy_version=pol.get("version"))
    return {"price_quote": q.model_dump(), **_t("pricing")}


def _sentences(text: str) -> list[str]:
    """Split into sentences. An evidence tag written after the full stop stays with the sentence it
    supports, so a claim and its [ev:id] are always verified together."""
    text = re.sub(r"(?<=[.!?])\s+((?:\[ev:[^\]]*\]\s*)+)",
                  lambda m: " " + m.group(1).strip() + "<<SPLIT>>", text)
    return [s.strip() for s in re.split(r"<<SPLIT>>|(?<=[.!?])\s+(?!\[ev:)", text) if s.strip()]


def style_lines(notes: list[dict]) -> list[str]:
    out = []
    for n in notes:
        out.append(f'Never say "{n["text"]}".' if n.get("kind") == "avoid_phrase" else n["text"])
    return out


def apply_style(text: str, notes: list[dict]) -> str:
    """Deterministic application of promoted style notes (template path and a safety net)."""
    for n in notes:
        if n.get("kind") == "avoid_phrase":
            text = re.sub(r"(?i)(?<!\[ev:)\b" + re.escape(n["text"]) + r"\b", "", text)
    text = re.sub(r"[ \t]{2,}", " ", text).replace(" ,", ",").replace(" .", ".").strip()
    if any(n.get("kind") == "cut_first_sentence" for n in notes):
        sents = _sentences(text)
        if len(sents) > 2:
            text = " ".join(sents[1:])
    return text


def _style_notes(config) -> list[dict]:
    mem = deps(config).get("memory")
    if mem is None:
        return []
    try:
        return mem.style_notes(config["configurable"].get("user_id", "default"))
    except Exception:
        return []


def _template_letter(strategy: str, j: dict, ev: list[dict], price: dict, crit: dict) -> str:
    skills = ", ".join(sum([e["skills"][:1] for e in ev], [])[:4])
    lines = []
    evid = [f"On {e['title']}, I used {', '.join(e['skills'][:3])} and the outcome was: "
            f"{e['outcome'].rstrip('.')}. [ev:{e['evidence_id']}]" for e in ev]
    if strategy == "writer_b":
        lines.append(f"I can deliver {j['title'].lower()} for {price['amount']} USD within "
                     f"{j['duration_days']} days.")
        lines += evid
        lines.append("Which part of the scope should I tackle first?")
        return " ".join(lines)
    lines.append(f"Your {j['title'].lower()} needs {skills}, and here is the closest evidence from my portfolio.")
    lines += evid
    if "no concrete outcome" in " ".join(crit.get("issues", [])):
        lines.append("I will share weekly updates and a clear delivery plan.")
    lines.append(f"I can deliver for {price['amount']} USD within {j['duration_days']} days.")
    return " ".join(lines)


def writer(state, config):
    j, crit = state["job"], state.get("critique", {})
    ev = state["evidence"][:CFG["writer"]["max_evidence"]]
    notes = _style_notes(config)
    strategy = deps(config).get("writer_strategy") or CFG["writer"]["strategy"]
    try:
        system = load_prompt(strategy)
    except OSError:
        strategy, system = "writer", load_prompt("writer")
    text, extra = None, {}
    if llm.enabled():
        facts = "\n".join(f"- id={e['evidence_id']} | {e['title']} | skills: {', '.join(e['skills'])} | "
                          f"outcome: {e['outcome']}" for e in ev)
        user = (untrusted("job_post", f"Title: {j['title']}\n{j['description']}") + "\n"
                f"Evidence (the only facts you may claim):\n{facts}\n"
                f"Price: {state['price_quote']['amount']} USD. Timeline: {j['duration_days']} days.\n"
                f"Style notes:\n" + ("\n".join(f"- {s}" for s in style_lines(notes)) or "- none") +
                "\nCritique issues to fix:\n" + ("\n".join(f"- {i}" for i in crit.get("issues", []))
                                                 or "- none"))
        res = llm.complete("writer", system, user)
        text, extra = res.text, llm_fields("writer", res)
    if not text:
        text = _template_letter(strategy, j, ev, state["price_quote"], crit)
    text = apply_style(text, notes)
    draft = h.ProposalDraft(job_id=j["job_id"], cover_letter=text,
                            evidence_ids=[e["evidence_id"] for e in ev])
    out = {"proposal_draft": draft.model_dump(), "memory_notes": style_lines(notes),
           "strategy": strategy}
    out["tokens"], out["cost_usd"] = extra.get("tokens", 0), extra.get("cost_usd", 0.0)
    out["trace"] = [{"node": "writer", "strategy": strategy, "style_notes": len(notes),
                     **({"llm": extra["trace"][0]["llm"]} if extra else {})}]
    return out


def rewrite_paragraph(state: dict, index: int, policy: dict | None = None) -> dict:
    """Regenerate one paragraph of the pending draft with the writer model, then run the same claim verifier and
    compliance rules the graph uses. Returns {regenerated, cover_letter, message, removed}. When the model is off
    or the new text breaks policy, the draft is returned unchanged with regenerated False and a message.
    The verifier joins sentences with spaces, so a verified draft is usually one block and index 0 is the whole body."""
    j, text = state["job"], state["proposal_draft"]["cover_letter"]
    paras = [p for p in re.split(r"\n\s*\n", text) if p.strip()]
    same = {"regenerated": False, "cover_letter": text, "removed": []}
    if not llm.enabled():
        return {**same, "message": "paragraph regeneration needs the language model, which is off in this profile"}
    ev = state["evidence"][:CFG["writer"]["max_evidence"]]
    facts = "\n".join(f"- id={e['evidence_id']} | {e['title']} | skills: {', '.join(e['skills'])} | "
                      f"outcome: {e['outcome']}" for e in ev)
    limit = max(30, CFG["compliance"]["max_words"] // max(len(paras), 1))
    user = (untrusted("job_post", f"Title: {j['title']}\n{j['description']}") + "\n"
            f"Evidence (the only facts you may claim):\n{facts}\n"
            f"Full letter:\n{text}\n\nParagraph to replace:\n{paras[index]}\n\nWord limit: {limit}")
    res = llm.complete("writer", load_prompt("rewrite_paragraph"), user)
    if not res.text:
        return {**same, "message": f"the model returned nothing ({res.error or 'empty'}), draft unchanged"}
    new_paras = list(paras)
    new_paras[index] = " ".join(res.text.split())
    checked = verifier({"proposal_draft": {**state["proposal_draft"], "cover_letter": "\n\n".join(new_paras)},
                        "evidence": state["evidence"]}, {})
    removed = [r["claim"] for r in checked["claim_verification"] if r["status"] == "unsupported"]
    letter = checked["proposal_draft"]["cover_letter"]
    bad = violations(letter, policy, check_length=True)
    if bad:
        return {**same, "removed": removed, "message": f"the new paragraph breaks platform rules {bad}, draft unchanged"}
    if letter.strip() == text.strip():
        return {**same, "removed": removed, "message": "the model produced the same text, draft unchanged"}
    msg = "paragraph regenerated" + (f", {len(removed)} unsupported claim(s) removed" if removed else "")
    return {"regenerated": True, "cover_letter": letter, "removed": removed, "message": msg}


def _llm_claim_status(sentence: str, ev: dict[str, dict]) -> tuple[str, dict]:
    tags = re.findall(r"\[ev:([^\]]+)\]", sentence)
    facts = "\n".join(f"{t}: {ev[t]['title']} | {', '.join(ev[t]['skills'])} | {ev[t]['outcome']}"
                      for t in tags if t in ev)
    res = llm.complete("verifier", load_prompt("verifier"),
                       f"Evidence:\n{facts}\nSentence:\n{sentence}", json_mode=True, max_tokens=120)
    obj = llm.parse_json(res.text) or {}
    status = obj.get("status") if obj.get("status") in ("supported", "partly_supported",
                                                        "unsupported") else "supported"
    return status, llm_fields("verifier", res)


def verifier(state, config):
    """Claim verification: sentences about past work must cite real evidence, else removed.
    With llm.verify_partial a model also flags partly supported claims."""
    v = CFG["verifier"]
    ev = {e["evidence_id"]: e for e in state["evidence"]}
    past = re.compile(v["past_claim_regex"], re.IGNORECASE)
    kept, report, tokens, cost, traces = [], [], 0, 0.0, []
    for s in _sentences(state["proposal_draft"]["cover_letter"]):
        tags = re.findall(r"\[ev:([^\]]+)\]", s)
        if tags and all(t in ev for t in tags):
            status = "supported"
            if llm.enabled() and CFG["llm"]["verify_partial"]:
                status, f = _llm_claim_status(s, ev)
                tokens, cost = tokens + f["tokens"], cost + f["cost_usd"]
                traces += f["trace"]
        elif past.search(s) or tags:
            status = "unsupported"
        else:
            status = "no_claim"
        report.append({"claim": s, "status": status})
        if status != "unsupported" and not (status == "partly_supported" and v["drop_partial"]):
            kept.append(s)
    d = dict(state["proposal_draft"], cover_letter=" ".join(kept))
    return {"proposal_draft": d, "claim_verification": report, "tokens": tokens, "cost_usd": cost,
            "trace": [{"node": "verifier", "unsupported": sum(r["status"] == "unsupported" for r in report)},
                      *traces]}


def critic(state, config):
    j, d, issues = state["job"], state["proposal_draft"], []
    text = d["cover_letter"]
    if re.match(r"(?i)\s*(hi|hello|dear)\b", text):
        issues.append("generic opening")
    if len(text.split()) > CFG["compliance"]["max_words"]:
        issues.append("too long")
    if "[ev:" not in text:
        issues.append("no concrete outcome with evidence")
    tokens, cost, traces = 0, 0.0, []
    if llm.enabled() and CFG["llm"]["llm_critic"]:
        res = llm.complete("critic", load_prompt("critic"),
                           untrusted("job_post", f"{j['title']}\n{j['description']}") + "\n"
                           f"<draft>\n{text}\n</draft>\nWord limit: {CFG['compliance']['max_words']}",
                           json_mode=True, max_tokens=300)
        obj = llm.parse_json(res.text) or {}
        extra = [str(i).strip() for i in obj.get("issues", []) if str(i).strip()] \
            if isinstance(obj.get("issues"), list) else []
        issues += [i for i in extra[:CFG["llm"]["max_critic_issues"]] if i not in issues]
        f = llm_fields("critic", res)
        tokens, cost, traces = f["tokens"], f["cost_usd"], f["trace"]
    c = h.Critique(ok=not issues, issues=issues)
    return {"critique": c.model_dump(), "revisions": state.get("revisions", 0) + (0 if c.ok else 1),
            "tokens": tokens, "cost_usd": cost, "trace": [{"node": "critic", "ok": c.ok}, *traces]}


def route_critic(state):
    if state["critique"]["ok"] or state.get("revisions", 0) > CFG["budgets"]["critic_max_revisions"]:
        return "compliance"
    return "writer"


async def compliance(state, config):
    pol = await policy_of(state, config, "compliance")
    bad = violations(state["proposal_draft"]["cover_letter"], pol, check_length=True)
    v = h.ComplianceVerdict(allowed=not bad, violations=bad)
    out = {"compliance_verdict": v.model_dump(), **_t("compliance", allowed=v.allowed)}
    if bad:
        out["status"] = "blocked"
    return out
