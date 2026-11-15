"""Messages: an approved reply is sent exactly once, policy violations are blocked, tenants are separated."""
import json

from tests.integration.api_helpers import (
    boot,
    client,
    find_bid_run,
    gigsim_up,  # noqa: F401  (fixture)
    make_user,
    set_env,
)


def _sent(gs, client_id):
    return [m for m in gs.store.messages[client_id] if m.get("from") == "freelancer"]


async def test_send_reply_once_and_blocked_cases(tmp_path, monkeypatch, gigsim_up):  # noqa: F811
    set_env(monkeypatch, tmp_path)
    app, cm = await boot()
    try:
        async with client(app) as c:
            h = await make_user(app, "send@example.com")
            run = await find_bid_run(c, h)
            tid = run["thread_id"]
            assert (await c.post(f"/api/approvals/{tid}", json={"action": "approve"}, headers=h)).status_code == 200
            cid = (await c.get(f"/api/runs/{tid}", headers=h)).json()["job"]["client_id"]
            gigsim_up.store.messages[cid].append(
                {"message_id": "m-q", "client_id": cid, "job_id": run["job_id"], "from": "client",
                 "text": "Could you share more about your experience?"})

            draft = (await c.post(f"/api/messages/{cid}/draft", json={}, headers=h)).json()
            assert draft["status"] == "awaiting_approval" and draft["draft"]

            # nothing is sent by drafting
            assert _sent(gigsim_up, cid) == []
            # approve and send: the user may edit the draft first
            text = draft["draft"] + " I can share two short case studies."
            ok = await c.post(f"/api/messages/{cid}/send", json={"text": text}, headers=h)
            assert ok.status_code == 200, ok.text
            assert ok.json()["status"] == "sent" and ok.json()["idempotent_replay"] is False
            assert [m["text"] for m in _sent(gigsim_up, cid)] == [text]

            # a double click or retry does not send it twice
            again = await c.post(f"/api/messages/{cid}/send", json={"text": text}, headers=h)
            assert again.status_code == 200 and again.json()["idempotent_replay"] is True
            assert len(_sent(gigsim_up, cid)) == 1

            # policy: an external link is refused and nothing is sent
            bad = await c.post(f"/api/messages/{cid}/send",
                               json={"text": "Please text me on whatsapp.com/xyz"}, headers=h)
            assert bad.status_code == 422
            assert len(_sent(gigsim_up, cid)) == 1

            # empty text is refused
            assert (await c.post(f"/api/messages/{cid}/send", json={"text": "   "}, headers=h)).status_code == 422

            # the reply went through the conversation graph: one thread per conversation, sent exactly once
            snap = await app.state.ctx.conv_graph.aget_state(
                {"configurable": {"thread_id": f"conv:{(await c.get('/api/auth/me', headers=h)).json()['id']}:{cid}"}})
            assert snap.values["status"] == "sent" and snap.values["draft"] == text and not snap.next

            # a new draft, then an edit that breaks the platform's link rule (policy v2): the graph's re-check refuses it
            pol_file = tmp_path / "policy_with_link_rule.json"
            pol_file.write_text(json.dumps({**json.loads(gigsim_up.POLICY.read_text(encoding="utf-8")),
                                            "banned_link_regex": r"https?://(?!portfolio\.)\S+"}), encoding="utf-8")
            monkeypatch.setattr(gigsim_up, "POLICY", pol_file)
            gigsim_up.store.messages[cid].append(
                {"message_id": "m-q2", "client_id": cid, "job_id": run["job_id"], "from": "client",
                 "text": "Thanks! What stack would you use?"})
            draft2 = (await c.post(f"/api/messages/{cid}/draft", json={}, headers=h)).json()
            refused = await c.post(f"/api/messages/{cid}/send",
                                   json={"text": draft2["draft"] + " See https://evil.example.com/pay"}, headers=h)
            assert refused.status_code == 422
            assert len(_sent(gigsim_up, cid)) == 1

            # another user cannot send to this user's client
            other = await make_user(app, "other@example.com")
            assert (await c.post(f"/api/messages/{cid}/send", json={"text": "hi"}, headers=other)).status_code == 404
    finally:
        await cm.__aexit__(None, None, None)
