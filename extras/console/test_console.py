"""Counter logic of the console, on a hand-built synthetic replay slice —
also proves the console computes from whatever file it is given."""

import json

import pandas as pd
import pytest

import sys
from pathlib import Path as _P

sys.path.insert(0, str(_P(__file__).parent))
from console import Replay  # noqa: E402


@pytest.fixture
def replay(tmp_path):
    rows = [
        # tid, day_idx, uid, amt,  y, role, flag, s_ship, s_head
        (1, 1, "u1", 10.0, 0, 0, False, 0.9, 0.1),   # legit, high shipped score
        (2, 1, "u2", 20.0, 1, 1, False, 0.8, 0.9),   # FIRST STRIKE u2
        (3, 2, "u2", 30.0, 1, 2, True, 0.7, 0.8),    # propagated, lane-1
        (4, 2, "u3", 40.0, 0, 0, True, 0.6, 0.7),    # legit on flagged entity
        (5, 2, "u4", 50.0, 1, 1, False, 0.5, 0.2),   # FIRST STRIKE u4
        (6, 2, "u5", 60.0, 0, 0, False, 0.1, 0.6),   # legit
    ]
    df = pd.DataFrame(
        rows, columns=["TransactionID", "day_idx", "uid", "amount", "y",
                       "role", "lane1_flag", "s_shipped", "s_headline"]
    )
    df["t"] = df["TransactionID"] * 100
    df["day"] = df["day_idx"].astype(float)
    df["p_shipped"] = df["s_shipped"]
    df["action_central"] = 0
    df["ProductCD"] = "W"
    df["P_emaildomain"] = "x.com"
    df["card1"] = 1
    data = tmp_path / "replay.parquet"
    df.to_parquet(data, index=False)
    frozen = tmp_path / "frozen.json"
    frozen.write_text(json.dumps({
        "lane2_scorer": "A2",
        "calibration": {"isotonic_x": [0.0, 1.0], "isotonic_y": [0.0, 1.0]},
        "cost_params_central": {"m": 0.15, "a": 0.125, "e": 0.775, "c_h": 30.0},
        "cost_params_ranges": {"m": [0.05, 0.15, 0.25], "a": [0.05, 0.125, 0.20],
                               "e": [0.60, 0.775, 0.95], "c_h": [15.0, 30.0, 60.0]},
    }))
    return Replay(data, frozen)


def test_meta(replay):
    m = replay.meta()
    assert m["rows"] == 6 and m["n_days"] == 2 and m["n_episodes"] == 2
    assert m["lane1"] == {"n": 2, "redundant_covered": 1,
                          "legit_blocked": 1, "fs_in_lane1": 0}


def test_counters_shipped_routing_on(replay):
    # budget = 1/day * 2 days = 2; lane-2 ranking: tid1(.9), tid2(.8), ...
    c = replay.counters("shipped", "on", per_day=1)
    assert c["budget"] == 2
    assert c["fs_catches"] == 1          # tid2 caught; tid5 below budget
    assert c["fs_recall"] == 0.5
    assert c["redundant_alerts"] == 0    # lane-2 alerts hit no propagated row
    assert c["false_positives"] == 1     # tid1
    assert c["lane1"]["n"] == 2


def test_counters_headline_routing_off(replay):
    # all rows ranked by headline score: tid2(.9), tid3(.8) -> top-2
    c = replay.counters("headline", "off", per_day=1)
    assert c["fs_catches"] == 1 and c["redundant_alerts"] == 1
    assert c["false_positives"] == 0
    assert c["lane1"] is None            # no lane display when routing off


def test_counters_blocklist(replay):
    c = replay.counters("blocklist", "on", per_day=999)
    assert c["budget"] == 2              # its natural operating point
    assert c["fs_catches"] == 0 and c["redundant_alerts"] == 1
    assert c["false_positives"] == 1


def test_budget_capped_by_population(replay):
    c = replay.counters("shipped", "on", per_day=100)
    assert c["budget"] == 4              # only 4 lane-2 rows exist


def test_decision_object(replay):
    d = replay.score_tx(4)
    assert d["lane_technical"].startswith("lane-1")
    assert d["action"] == "block (by rule)"
    d2 = replay.score_tx(2)
    assert d2["lane_technical"].startswith("lane-2")
    assert set(d2["expected_cost"]) == {"approve", "step_up", "block"}
    assert d2["would_change"]["block_if_risk_above"] > \
        d2["would_change"]["step_up_if_risk_above"]
    assert d2["ground_truth_role_EVALUATION_ONLY"] == "first strike"


def test_policy_clamps_to_declared_ranges(replay):
    p = replay.policy({"m": "9.9", "a": "0", "e": "0.7", "c_h": "1"})
    assert p["params"]["m"] == 0.25      # clamped to range max
    assert p["params"]["a"] == 0.05      # clamped to range min
    assert p["params"]["c_h"] == 15.0
    assert p["mix"]["approve"] + p["mix"]["step_up"] + p["mix"]["block"] == 4
    assert p["cost_approve_all"] >= 0
