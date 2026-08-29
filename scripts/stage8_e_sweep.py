"""Extended step-up-efficacy sweep: e in {0.2 ... 0.95}.

POST-HOC, REVIEWER-REQUESTED, AND STATED AS SUCH. The original declared
range floored e at 0.6, so the grid never tested the assumption the cost
result rests on (a stepped-up fraud is avoided with probability e). A
reviewer challenged the floor after the second-access results were seen;
this sweep widens the range to e in [0.2, 0.95] and reports where the
policy's edge over a validation-tuned fixed threshold breaks, if it does.

NO NEW HOLDOUT ACCESS: holdout rows come from the committed Stage-7
replay artifact (data/processed/holdout_replay.parquet — amount, y,
lane1_flag, calibrated p_shipped), the same file the TUI and console
have read since Stage 7. seal.load_holdout is not touched; the access
log stays at two entries. The e >= 0.6 slice is asserted to reproduce
reports/stage8/cost_rebuild_grid.csv exactly, tying this artifact to the
logged access.

Construction identical to the second-access rebuild: fixed threshold
tuned per corner on VALIDATION (101 quantile thresholds), both systems
evaluated on holdout rows, 400-resample row-bootstrap CIs on
(cost_fixed - cost_policy)/cost_approve_all, lane-1 blocked in both.
"""

from __future__ import annotations

import itertools
import json

import numpy as np
import pandas as pd

from strikeone import config
from strikeone import metrics as M

OUT = config.REPORTS / "stage8"
MODELS = config.REPO_ROOT / "models"
COST_BOOT = 400
E_LEVELS = [0.2, 0.3, 0.4, 0.5, 0.6, 0.775, 0.95]
M_LEVELS = [0.05, 0.15, 0.25]
A_LEVELS = [0.05, 0.125, 0.20]
CH_LEVELS = [15.0, 30.0, 60.0]


def main():
    # ---- validation side (identical inputs to the second-access rebuild)
    frozen = json.loads((config.REPORTS / "stage4" /
                         "shipped_system_frozen.json").read_text())
    iso_x = np.array(frozen["calibration"]["isotonic_x"])
    iso_y = np.array(frozen["calibration"]["isotonic_y"])
    sc_val = pd.read_parquet(MODELS / "stage4_scores.parquet")
    lane2_val = ~sc_val["lane1_flag"].to_numpy()
    p_val = np.interp(sc_val["score_a2"].to_numpy()[lane2_val], iso_x, iso_y)
    y_val = sc_val["y"].to_numpy()[lane2_val]
    df_model = pd.read_parquet(config.MODELING_PARQUET)
    amt_map = df_model.set_index("TransactionID")["TransactionAmt"]
    amt_val = amt_map.loc[sc_val["TransactionID"]].to_numpy()[lane2_val]
    taus = np.unique(np.quantile(p_val, np.linspace(0, 1, 101)))

    # ---- holdout side: the committed replay artifact, NOT an unseal
    rep = pd.read_parquet(config.DATA_PROCESSED / "holdout_replay.parquet")
    flag = rep["lane1_flag"].to_numpy()
    lane2 = ~flag
    y2 = rep["y"].to_numpy()[lane2]
    a2v = rep["amount"].to_numpy()[lane2]
    p2 = rep["p_shipped"].to_numpy()[lane2]
    y1 = rep["y"].to_numpy()[flag]
    a1v = rep["amount"].to_numpy()[flag]

    boot_idx2 = [np.random.default_rng(config.SEED + i).integers(
        0, len(y2), len(y2), dtype=np.int32) for i in range(COST_BOOT)]
    boot_idx1 = [np.random.default_rng(10_000 + i).integers(
        0, len(y1), len(y1), dtype=np.int32) for i in range(COST_BOOT)]

    rows = []
    for e_, m_, a_, ch_ in itertools.product(E_LEVELS, M_LEVELS, A_LEVELS,
                                             CH_LEVELS):
        prm = M.CostParams(m=m_, a=a_, e=e_, c_h=ch_)
        best_tau, best_c = None, np.inf
        for tau in taus:
            act = np.where(p_val >= tau, M.BLOCK, M.APPROVE)
            c = float(M.realized_cost(y_val, act, amt_val, prm).sum())
            if c < best_c:
                best_c, best_tau = c, tau
        ecm = M.expected_cost_matrix(p2, a2v, prm)
        cp2 = M.realized_cost(y2, ecm.argmin(axis=1), a2v, prm)
        cf2 = M.realized_cost(
            y2, np.where(p2 >= best_tau, M.BLOCK, M.APPROVE), a2v, prm)
        ca2 = M.realized_cost(y2, np.zeros(len(y2)), a2v, prm)
        ca1 = M.realized_cost(y1, np.zeros(len(y1)), a1v, prm)
        point = (cf2.sum() - cp2.sum()) / (ca1.sum() + ca2.sum())
        deltas = np.array([
            (cf2[i2].sum() - cp2[i2].sum())
            / max(ca1[i1].sum() + ca2[i2].sum(), 1e-9)
            for i1, i2 in zip(boot_idx1, boot_idx2)])
        lo, hi = np.percentile(deltas, [2.5, 97.5])
        rows.append({"e": e_, "m": m_, "a": a_, "c_h": ch_,
                     "tau_val": float(best_tau),
                     "edge_point": round(float(point), 5),
                     "ci_lo": round(float(lo), 5),
                     "ci_hi": round(float(hi), 5),
                     "ci_excludes_zero": bool(lo > 0)})
    t = pd.DataFrame(rows)
    t.to_csv(OUT / "e_sweep_grid.csv", index=False)

    # integrity: the e >= 0.6 slice must reproduce the logged-access grid
    old = pd.read_csv(OUT / "cost_rebuild_grid.csv")
    merged = old.merge(t, on=["m", "a", "e", "c_h"],
                       suffixes=("_logged", "_replay"))
    assert len(merged) == 81, f"slice mismatch: {len(merged)}"
    dev = (merged["edge_point_logged"] - merged["edge_point_replay"]).abs()
    assert dev.max() < 1e-4, f"replay deviates from logged access: {dev.max()}"

    per_e = []
    for e_, g in t.groupby("e"):
        per_e.append({
            "e": float(e_),
            "k_of_27_ci_excludes_zero": int(g["ci_excludes_zero"].sum()),
            "median_edge_pct": round(float(g["edge_point"].median()) * 100, 3),
            "min_edge_pct": round(float(g["edge_point"].min()) * 100, 3),
            "min_ci_lo_pct": round(float(g["ci_lo"].min()) * 100, 3),
            "weakest_corner": g.loc[g["edge_point"].idxmin(),
                                    ["m", "a", "c_h"]].to_dict(),
        })
    summary = {
        "note": ("post-hoc reviewer-requested extension; declared e range "
                 "widened from [0.6, 0.95] to [0.2, 0.95] AFTER second-"
                 "access results were seen (a reviewer challenged the "
                 "floor); computed from the committed Stage-7 replay "
                 "artifact, no new holdout access; e>=0.6 slice asserted "
                 "equal to the logged-access grid"),
        "replay_reproduces_logged_access_max_dev": float(dev.max()),
        "per_e": per_e,
    }
    (OUT / "e_sweep_summary.json").write_text(
        json.dumps(summary, indent=2, default=float))
    print(pd.DataFrame(per_e).to_string(index=False))
    print("max deviation vs logged access:", float(dev.max()))


if __name__ == "__main__":
    main()
