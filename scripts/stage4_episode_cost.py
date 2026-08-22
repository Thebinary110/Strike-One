"""Stage 4 E, corrected — price the metric choice under EPISODE-AWARE cost.

The naive realized-cost comparison inherits the label distortion: it credits
a system for "preventing" propagated fraud that the entity's own earlier
catch (or a blocklist) would have stopped. The episode-aware counterfactual
fixes the accounting:

  - An entity is STOPPED at the system's first BLOCK of any of its rows
    (lane-1 flags are blocks). Simplification, stated: step-up does not
    stop an episode (conservative, applied symmetrically to all systems).
  - Rows strictly after the stop are forced to BLOCK: later fraud costs 0
    (prevented), later legit rows cost m*A (blocklist friction).
  - Rows before the stop cost realized_cost(action) as usual.

Under this accounting, catching an episode at strike one prevents its
downstream; catching the 3rd fraud does not un-lose the first two. This is
the brief's "re-run the policy selection optimising for first-strike
outcomes" made concrete.

Systems compared, all with the same isotonic-calibration + 3-action argmin
machinery: two-lane+A2 (ours), single-lane B (headline-selected),
single-lane A, blocklist-only, approve-all.
"""

from __future__ import annotations

import itertools
import json

import numpy as np
import pandas as pd
from sklearn.isotonic import IsotonicRegression

from strikeone import config, entity, episodes
from strikeone import metrics as M

OUT = config.REPORTS / "stage4"
RANGES = {"m": [0.05, 0.15, 0.25], "a": [0.05, 0.125, 0.20],
          "e": [0.60, 0.775, 0.95], "c_h": [15.0, 30.0, 60.0]}
CENTRAL = M.CostParams(m=0.15, a=0.125, e=0.775, c_h=30.0)


def load():
    df = pd.read_parquet(
        config.MODELING_PARQUET,
        columns=["TransactionID", "TransactionDT", "day_idx", "day", "isFraud",
                 "TransactionAmt", "card1", "addr1", "D1"],
    )
    uid, _ = entity.build_uid(df)
    t = df["TransactionDT"].to_numpy()
    tb = df["TransactionID"].to_numpy()
    y_all = df["isFraud"].to_numpy()
    roles_all = episodes.episode_roles(uid.to_numpy(), t, y_all, tiebreak=tb)
    va = ((df["day_idx"] >= 120) & (df["day_idx"] <= 147)).to_numpy()
    sc = pd.read_parquet(config.REPO_ROOT / "models" / "stage4_scores.parquet")
    assert (sc["TransactionID"].to_numpy() == df.loc[va, "TransactionID"].to_numpy()).all()
    v = pd.DataFrame(
        {"t": t[va], "tid": tb[va], "uid": uid.to_numpy()[va],
         "y": sc["y"].to_numpy(),
         "amt": df.loc[va, "TransactionAmt"].to_numpy(),
         "role": roles_all[va],
         "flag": sc["lane1_flag"].to_numpy(),
         "s_a": sc["score_a"].to_numpy(), "s_b": sc["score_b"].to_numpy(),
         "s_a2": sc["score_a2"].to_numpy()}
    ).sort_values(["t", "tid"]).reset_index(drop=True)
    return v


def calibrated(v, col, mask=None):
    """Isotonic calibration on validation (in-sample; symmetric across
    systems; the frozen Stage 7 maps are fit the same way)."""
    p = np.full(len(v), np.nan)
    m = np.ones(len(v), bool) if mask is None else mask
    iso = IsotonicRegression(out_of_bounds="clip")
    p[m] = iso.fit_transform(v[col].to_numpy()[m], v["y"].to_numpy()[m])
    return p


def episode_cost(v, action, params: M.CostParams) -> float:
    """Episode-aware realized cost. `action` is per-row (APPROVE/STEPUP/BLOCK)."""
    y = v["y"].to_numpy()
    amt = v["amt"].to_numpy()
    blocked = action == M.BLOCK
    d = pd.DataFrame({"uid": v["uid"], "pos": np.arange(len(v)),
                      "blocked": blocked})
    first_block = d[d.blocked].groupby("uid")["pos"].min()
    stop_pos = d["uid"].map(first_block).fillna(np.inf).to_numpy()
    after_stop = np.arange(len(v)) > stop_pos
    eff_action = np.where(after_stop, M.BLOCK, action)
    return float(M.realized_cost(y, eff_action, amt, params).sum())


def main():
    v = load()
    y = v["y"].to_numpy()
    amt = v["amt"].to_numpy()
    flag = v["flag"].to_numpy()
    lane2 = ~flag
    n = len(v)
    vol = amt.sum()

    p_a = calibrated(v, "s_a")
    p_b = calibrated(v, "s_b")
    p_a2 = calibrated(v, "s_a2", mask=lane2)

    def actions_argmin(p, params, mask=None):
        act = np.full(n, M.BLOCK)  # default for rows outside mask (lane 1)
        m = np.ones(n, bool) if mask is None else mask
        ec = M.expected_cost_matrix(p[m], amt[m], params)
        act[m] = ec.argmin(axis=1)
        return act

    def systems(params):
        return {
            "two-lane+A2 (ours)": actions_argmin(p_a2, params, mask=lane2),
            "single-lane B (headline pick)": actions_argmin(p_b, params),
            "single-lane A": actions_argmin(p_a, params),
            "blocklist-only": np.where(flag, M.BLOCK, M.APPROVE),
            "approve-all": np.full(n, M.APPROVE),
        }

    rows = []
    for m_, a_, e_, ch_ in itertools.product(*RANGES.values()):
        prm = M.CostParams(m=m_, a=a_, e=e_, c_h=ch_)
        costs = {name: episode_cost(v, act, prm)
                 for name, act in systems(prm).items()}
        rows.append({"m": m_, "a": a_, "e": e_, "c_h": ch_,
                     **{k: round(c, 0) for k, c in costs.items()}})
    grid = pd.DataFrame(rows)
    grid["delta_headline_minus_ours_per_1k"] = (
        (grid["single-lane B (headline pick)"] - grid["two-lane+A2 (ours)"])
        / n * 1000
    ).round(1)
    grid["delta_pct_of_volume"] = (
        (grid["single-lane B (headline pick)"] - grid["two-lane+A2 (ours)"]) / vol * 100
    ).round(3)
    grid.to_csv(OUT / "episode_cost_grid.csv", index=False)

    cen = grid[(grid.m == 0.15) & (grid.a == 0.125)
               & (grid.e == 0.775) & (grid.c_h == 30.0)].iloc[0]
    print("CENTRAL episode-aware costs:")
    print(cen.to_string())
    summary = {
        "central": cen.to_dict(),
        "ours_beats_headline_share_of_grid": float(
            (grid["delta_headline_minus_ours_per_1k"] > 0).mean()
        ),
        "delta_per_1k_min_max": [
            float(grid["delta_headline_minus_ours_per_1k"].min()),
            float(grid["delta_headline_minus_ours_per_1k"].max()),
        ],
        "vanishing_corner": grid.loc[
            grid["delta_headline_minus_ours_per_1k"].idxmin()
        ].to_dict(),
        "n_val_rows": n,
        "val_volume": float(vol),
    }
    print(json.dumps(summary, indent=2, default=str))

    # ---- demo counters (validation dress rehearsal; recomputed on holdout
    # at Stage 7): shipped system at central params -----------------------
    act_ours = systems(CENTRAL)["two-lane+A2 (ours)"]
    roles = v["role"].to_numpy()
    fs = roles == episodes.ROLE_FIRST_STRIKE
    prop_mask = roles == episodes.ROLE_PROPAGATED
    intervene = act_ours != M.APPROVE
    d = pd.DataFrame({"uid": v["uid"], "pos": np.arange(n),
                      "blocked": act_ours == M.BLOCK})
    first_block = d[d.blocked].groupby("uid")["pos"].min()
    stop_pos = d["uid"].map(first_block).fillna(np.inf).to_numpy()
    after = np.arange(n) > stop_pos
    downstream_prevented = float(amt[(y == 1) & after].sum())
    fs_caught = intervene & fs & ~after
    counters = {
        "fs_catches": int(fs_caught.sum()),
        "fs_amount_stopped": float(amt[fs_caught].sum()),
        "downstream_prevented_amount": downstream_prevented,
        "loss_prevented_at_strike_one_total": float(
            amt[fs_caught].sum() + downstream_prevented
        ),
        "redundant_interventions": int((intervene & prop_mask & ~after).sum()
                                       + (flag & prop_mask).sum()),
        "interventions_total": int(intervene.sum()),
    }
    print("DEMO COUNTERS (ours, central params, validation):")
    print(json.dumps(counters, indent=2))
    summary["demo_counters_ours"] = counters

    # same counters for headline system, for the side-by-side
    act_b = systems(CENTRAL)["single-lane B (headline pick)"]
    ib = act_b != M.APPROVE
    db = pd.DataFrame({"uid": v["uid"], "pos": np.arange(n),
                       "blocked": act_b == M.BLOCK})
    fb = db[db.blocked].groupby("uid")["pos"].min()
    sp = db["uid"].map(fb).fillna(np.inf).to_numpy()
    ab = np.arange(n) > sp
    counters_b = {
        "fs_catches": int((ib & fs & ~ab).sum()),
        "fs_amount_stopped": float(amt[ib & fs & ~ab].sum()),
        "downstream_prevented_amount": float(amt[(y == 1) & ab].sum()),
        "redundant_interventions": int((ib & prop_mask & ~ab).sum()),
        "interventions_total": int(ib.sum()),
    }
    print("DEMO COUNTERS (headline B system):")
    print(json.dumps(counters_b, indent=2))
    summary["demo_counters_headline"] = counters_b

    (OUT / "episode_cost.json").write_text(json.dumps(summary, indent=2, default=str))
    assert config.HOLDOUT_ACCESS_LOG.read_text() == ""
    print("holdout access log still empty")


if __name__ == "__main__":
    main()
