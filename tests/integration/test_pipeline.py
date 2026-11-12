"""Pipeline board: a client message asking for a call moves the card to the interview column."""
from tests.integration.api_helpers import (
    boot,
    client,
    find_bid_run,
    gigsim_up,  # noqa: F401  (fixture)
    make_user,
    set_env,
)


def _stage_of(board, tid):
    for stage, cards in board["columns"].items():
        if any(c["thread_id"] == tid for c in cards):
            return stage
    return None


async def test_interview_request_moves_card_to_interview(tmp_path, monkeypatch, gigsim_up):  # noqa: F811
    set_env(monkeypatch, tmp_path)
    app, cm = await boot()
    try:
        async with client(app) as c:
            h = await make_user(app, "pipe@example.com")
            run = await find_bid_run(c, h)
            tid = run["thread_id"]
            assert _stage_of((await c.get("/api/pipeline", headers=h)).json(), tid) == "drafted"
            done = await c.post(f"/api/approvals/{tid}", json={"action": "approve"}, headers=h)
            assert done.status_code == 200
            board = (await c.get("/api/pipeline", headers=h)).json()
            assert _stage_of(board, tid) in ("submitted", "replied")
            client_id = (await c.get(f"/api/runs/{tid}", headers=h)).json()["job"]["client_id"]
            gigsim_up.store.messages[client_id].append(
                {"message_id": "m-int", "client_id": client_id, "job_id": run["job_id"], "from": "client",
                 "text": "Looks good, are you free for a video call tomorrow?"})
            board = (await c.get("/api/pipeline", headers=h)).json()
            assert _stage_of(board, tid) == "interview"
            assert board["columns"]["hired"] == [] and board["columns"]["viewed"] == []
    finally:
        await cm.__aexit__(None, None, None)
