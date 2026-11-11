"""Tests run against a fixed baseline platform policy (v1), not whatever data/policy_pack currently holds.

The live policy file is changed by the platform policy update (see test_change_request.py, which opts out with
the `live_policy` marker and reads the real file). Without this, every test that picks an arbitrary job would
depend on the current minimum budget and Connects multiplier.
"""
import json

import pytest

BASELINE = {"version": 1, "connects_multiplier": 1.0, "min_budget_usd": 0, "max_proposals_per_day": 20,
            "rate_limit_per_min": 120, "rules": ["human approval required"]}


def pytest_configure(config):
    config.addinivalue_line("markers", "live_policy: use the real data/policy_pack policy, not the baseline")


@pytest.fixture(autouse=True)
def baseline_policy(request, monkeypatch, tmp_path):
    if request.node.get_closest_marker("live_policy"):
        return
    from gigsim import app as gapp
    f = tmp_path / "baseline_policy.json"
    f.write_text(json.dumps(BASELINE), encoding="utf-8")
    monkeypatch.setattr(gapp, "POLICY", f)
