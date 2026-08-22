"""Stage 4 — decision engine: two-lane routing, formal model selection,
calibration, cost-derived actions, sensitivity grid, metric-choice pricing,
review queue, freeze.

Selection rule, stated before results are read: lane 2 ships A2 only if its
paired first-strike-recall delta over A at the primary budget excludes zero
in A2's favour; otherwise the already-frozen A ships (fewer moving parts).
B appears in every table as the model headline AP selects.

Cost parameters (declared ranges, never point facts):
  m   contribution margin lost on a rejected good order   [0.05, 0.25]
  a   step-up abandonment rate                            [0.05, 0.20]
  e   step-up efficacy against a fraud attempt            [0.60, 0.95]
  c_h chargeback handling cost, in dataset amount units   [15, 60]
      (public sources: card-network chargeback fees commonly $15-$50 per
      dispute, operational handling estimates higher; this dataset's
      amounts are dollar-scale, median 68)
Central point for the shipped default: m=0.15, a=0.125, e=0.775, c_h=30.
All economics are reported in dataset amount units and as % of processed
volume; no conversion to INR is asserted.
"""

from __future__ import annotations

import hashlib
import itertools
import json

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from sklearn.isotonic import IsotonicRegression
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import brier_score_loss

from strikeone import config, entity, episodes
from strikeone import metrics as M

OUT = config.REPORTS / "stage4"
PRIMARY = 2810
BUDGETS = [500, 1000, 1500, 2000, 2810, 4000]
N_BOOT = 1000

RANGES = {"m": [0.05, 0.15, 0.25], "a": [0.05, 0.125, 0.20],
          "e": [0.60, 0.775, 0.95], "c_h": [15.0, 30.0, 60.0]}
CENTRAL = M.CostParams(m=0.15, a=0.125, e=0.775, c_h=30.0)


def load_all():
    df = pd.read_parquet(
        config.MODELING_PARQUET,
        columns=["TransactionID", "TransactionDT", "day", "day_idx", "isFraud",
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
    val = pd.DataFrame(
        {"y": sc["y"].to_numpy(),
         "amt": df.loc[va, "TransactionAmt"].to_numpy(),
         "day_idx": df.loc[va, "day_idx"].to_numpy(),
         "card1": df.loc[va, "card1"].to_numpy(),
         "uid": uid.to_numpy()[va],
         "role": roles_all[va],
         "flag": sc["lane1_flag"].to_numpy(),
         "s_a": sc["score_a"].to_numpy(),
         "s_b": sc["score_b"].to_numpy(),
         "s_a2": sc["score_a2"].to_numpy()}
    )
    return val


def fsr_fn(alert, fs):
    return lambda idx: (
        float(alert[idx][fs[idx]].mean()) if fs[idx].any() else np.nan
    )


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    val = load_all()
    y = val["y"].to_numpy()
    amt = val["amt"].to_numpy()
    fs = (val["role"] == episodes.ROLE_FIRST_STRIKE).to_numpy()
    prop = (val["role"] == episodes.ROLE_PROPAGATED).to_numpy()
    flag = val["flag"].to_numpy()
    lane2 = ~flag
    out = {}

    # ================= C. formal model selection =========================
    y2, fs2 = y[lane2], fs[lane2]
    uid2 = val.loc[lane2, "uid"].to_numpy()
    cand = {"A": val["s_a"].to_numpy()[lane2],
            "A2": val["s_a2"].to_numpy()[lane2],
            "B": val["s_b"].to_numpy()[lane2]}
    sel_rows = []
    for name, s in cand.items():
        for b in BUDGETS:
            al = M.alerts_at_budget(s, b)
            sel_rows.append({"model": name, "budget": b,
                             "fs_recall": round(float(al[fs2].mean()), 4),
                             "friction_eff": round(float((al & fs2).sum() / b), 4)})
    sel = pd.DataFrame(sel_rows)
    sel.to_csv(OUT / "model_selection_curve.csv", index=False)
    print(sel.pivot_table(index="budget", columns="model",
                          values="fs_recall").round(4).to_string())

    al_a = M.alerts_at_budget(cand["A"], PRIMARY)
    al_a2 = M.alerts_at_budget(cand["A2"], PRIMARY)
    d_sel = M.paired_bootstrap_diff(
        fsr_fn(al_a, fs2), fsr_fn(al_a2, fs2), len(y2), N_BOOT, config.SEED,
        groups=uid2,
    )
    out["selection_delta_A2_minus_A_fs_recall"] = d_sel
    a2_wins = d_sel[1] > 0  # CI excludes zero in A2's favour
    scorer = "A2" if a2_wins else "A"
    out["selected_scorer"] = scorer
    out["selection_rule"] = ("A2 iff paired FS-recall delta CI at primary "
                             "budget excludes zero in its favour; else A")
    print(f"SELECTED lane-2 scorer: {scorer} "
          f"(delta {d_sel[0]:+.4f} [{d_sel[1]:+.4f},{d_sel[2]:+.4f}])")
    # headline contrast on full validation
    out["headline_ap_full_val"] = {
        n: round(M.average_precision(y, val[f"s_{n.lower()}"].to_numpy()), 4)
        for n in ["A", "B"]
    }

    s2 = cand[scorer]  # lane-2 scores of the shipped scorer

    # ================= A. two-lane vs single-lane =========================
    n_l1 = int(flag.sum())
    tl_rows = []
    for T in [2000, 2810, 4000, 6000]:
        # single-lane: top-T anywhere, per candidate full-val scorer
        for name, s_full in [("single:A", val["s_a"].to_numpy()),
                             ("single:B", val["s_b"].to_numpy())]:
            al = M.alerts_at_budget(s_full, T)
            tl_rows.append({
                "system": name, "total_interventions": T,
                "fs_recall": round(float(al[fs].mean()), 4),
                "prop_recall": round(float(al[prop].mean()), 4),
                "txn_precision": round(float(y[al].mean()), 4),
                "friction_eff": round(float((al & fs).sum() / T), 4),
                "fraud_amt_intercepted": round(float(amt[al & (y == 1)].sum()), 0),
            })
        # two-lane at total parity: lane-1 blocks + top-(T-n_l1) of lane 2
        al2 = M.alerts_at_budget(s2, T - n_l1)
        al_sys = flag.copy()
        al_sys[lane2] |= al2
        tl_rows.append({
            "system": f"two-lane:{scorer}", "total_interventions": T,
            "fs_recall": round(float(al_sys[fs].mean()), 4),
            "prop_recall": round(float(al_sys[prop].mean()), 4),
            "txn_precision": round(float(y[al_sys].mean()), 4),
            "friction_eff": round(float((al_sys & fs).sum() / int(al_sys.sum())), 4),
            "fraud_amt_intercepted": round(float(amt[al_sys & (y == 1)].sum()), 0),
        })
    tl = pd.DataFrame(tl_rows)
    tl.to_csv(OUT / "two_lane_vs_single.csv", index=False)
    print(tl.to_string(index=False))
    out["lane1_size"] = n_l1

    # ================= D. calibration ======================================
    p_raw = s2
    iso = IsotonicRegression(out_of_bounds="clip")
    p_iso = iso.fit_transform(p_raw, y2)
    platt = LogisticRegression(C=1e6, max_iter=1000)
    logit = np.log(np.clip(p_raw, 1e-7, 1 - 1e-7) / (1 - np.clip(p_raw, 1e-7, 1 - 1e-7)))
    platt.fit(logit.reshape(-1, 1), y2)
    p_platt = platt.predict_proba(logit.reshape(-1, 1))[:, 1]
    out["brier"] = {
        "raw": float(brier_score_loss(y2, p_raw)),
        "isotonic": float(brier_score_loss(y2, p_iso)),
        "platt": float(brier_score_loss(y2, p_platt)),
    }
    print("brier:", {k: round(v, 5) for k, v in out["brier"].items()})

    fig, ax = plt.subplots(figsize=(5.5, 5))
    for name, p in [("raw", p_raw), ("isotonic", p_iso), ("platt", p_platt)]:
        bins = pd.qcut(p, 20, duplicates="drop")
        g = pd.DataFrame({"p": p, "y": y2}).groupby(bins, observed=True).mean()
        ax.plot(g["p"], g["y"], marker="o", ms=3, label=name)
    ax.plot([0, 1], [0, 1], "k--", lw=0.7)
    ax.set_xlabel("predicted probability")
    ax.set_ylabel("observed fraud rate")
    ax.set_title(f"Reliability, lane-2 scorer {scorer} (validation)")
    ax.legend()
    fig.tight_layout()
    fig.savefig(OUT / "fig_reliability.png", dpi=150)

    # calibration choice: isotonic unless Platt materially better
    p_cal = p_iso if out["brier"]["isotonic"] <= out["brier"]["platt"] else p_platt
    out["calibration_choice"] = (
        "isotonic" if out["brier"]["isotonic"] <= out["brier"]["platt"] else "platt"
    )
    # calibrate B the same way for the headline-selected system (E)
    s_b_full = val["s_b"].to_numpy()
    iso_b = IsotonicRegression(out_of_bounds="clip")
    p_b_full = iso_b.fit_transform(s_b_full, y)

    # ================= D. cost policy + grid ================================
    amt2 = amt[lane2]

    def system_cost(params: M.CostParams):
        """Two-lane: lane-1 blocked by rule; lane-2 three-action argmin."""
        ec = M.expected_cost_matrix(p_cal, amt2, params)
        act2 = ec.argmin(axis=1)
        cost2 = M.realized_cost(y2, act2, amt2, params).sum()
        y1, a1 = y[flag], amt[flag]
        cost1 = M.realized_cost(y1, np.full(len(y1), M.BLOCK), a1, params).sum()
        return cost1 + cost2, act2

    def fixed_threshold_cost(params: M.CostParams):
        """Best single p-threshold (block/approve only), oracle-picked on val."""
        best = np.inf
        for tau in np.unique(np.quantile(p_cal, np.linspace(0, 1, 201))):
            act = np.where(p_cal >= tau, M.BLOCK, M.APPROVE)
            c = M.realized_cost(y2, act, amt2, params).sum()
            best = min(best, c)
        y1, a1 = y[flag], amt[flag]
        return best + M.realized_cost(
            y1, np.full(len(y1), M.BLOCK), a1, params).sum()

    def amount_blind_cost(params: M.CostParams):
        """Same 3-action argmin but decisions use the median amount."""
        med = np.full(len(p_cal), np.median(amt2))
        act = M.expected_cost_matrix(p_cal, med, params).argmin(axis=1)
        c2 = M.realized_cost(y2, act, amt2, params).sum()
        y1, a1 = y[flag], amt[flag]
        return c2 + M.realized_cost(
            y1, np.full(len(y1), M.BLOCK), a1, params).sum()

    def headline_system_cost(params: M.CostParams):
        """Single-lane system with calibrated B deciding everything."""
        ec = M.expected_cost_matrix(p_b_full, amt, params)
        act = ec.argmin(axis=1)
        return M.realized_cost(y, act, amt, params).sum()

    def trivial(params: M.CostParams):
        ap = M.realized_cost(y, np.full(len(y), M.APPROVE), amt, params).sum()
        bl = M.realized_cost(y, np.full(len(y), M.BLOCK), amt, params).sum()
        return min(ap, bl), ("approve-all" if ap <= bl else "block-all")

    grid_rows = []
    for m_, a_, e_, ch_ in itertools.product(*RANGES.values()):
        prm = M.CostParams(m=m_, a=a_, e=e_, c_h=ch_)
        c_sys, act2 = system_cost(prm)
        c_ft = fixed_threshold_cost(prm)
        c_ab = amount_blind_cost(prm)
        c_hl = headline_system_cost(prm)
        c_triv, triv_name = trivial(prm)
        n_val = len(y)
        mix = np.bincount(act2, minlength=3) / len(act2)
        grid_rows.append({
            "m": m_, "a": a_, "e": e_, "c_h": ch_,
            "cost_policy": round(c_sys, 0),
            "cost_fixed_threshold": round(c_ft, 0),
            "cost_amount_blind": round(c_ab, 0),
            "cost_headline_B_system": round(c_hl, 0),
            "cost_trivial": round(c_triv, 0), "trivial": triv_name,
            "savings_vs_trivial": round((c_triv - c_sys) / c_triv, 4),
            "gap_vs_fixed": round((c_ft - c_sys) / c_triv, 4),
            "gap_vs_amount_blind": round((c_ab - c_sys) / c_triv, 4),
            "delta_headline_minus_ours_per_1k_txn": round(
                (c_hl - c_sys) / n_val * 1000, 1
            ),
            "mix_approve": round(mix[0], 3), "mix_stepup": round(mix[1], 3),
            "mix_block": round(mix[2], 3),
        })
    grid = pd.DataFrame(grid_rows)
    grid.to_csv(OUT / "sensitivity_grid.csv", index=False)

    cen = grid[(grid.m == 0.15) & (grid.a == 0.125)
               & (grid.e == 0.775) & (grid.c_h == 30.0)].iloc[0]
    print("central:", cen.to_dict())
    out["central_point"] = cen.to_dict()
    out["grid_summary"] = {
        "savings_vs_trivial_min_max": [float(grid.savings_vs_trivial.min()),
                                       float(grid.savings_vs_trivial.max())],
        "policy_beats_fixed_threshold_share": float((grid.gap_vs_fixed > 0).mean()),
        "policy_beats_amount_blind_share": float((grid.gap_vs_amount_blind > 0).mean()),
        "delta_per_1k_min_max": [float(grid.delta_headline_minus_ours_per_1k_txn.min()),
                                 float(grid.delta_headline_minus_ours_per_1k_txn.max())],
        "worst_corner_vs_fixed": grid.loc[grid.gap_vs_fixed.idxmin()].to_dict(),
        "worst_corner_headline_delta": grid.loc[
            grid.delta_headline_minus_ours_per_1k_txn.idxmin()].to_dict(),
    }
    print(json.dumps(out["grid_summary"], indent=2, default=str))

    # ================= review queue (outside the argmin) ==================
    _, act2_central = system_cost(CENTRAL)
    not_blocked = act2_central != M.BLOCK
    exp_loss = p_cal * (amt2 + CENTRAL.c_h)
    q_rows = []
    for per_day in [5, 20, 50]:
        k = per_day * 28
        qidx = np.argsort(-np.where(not_blocked, exp_loss, -np.inf))[:k]
        qmask = np.zeros(len(y2), dtype=bool)
        qmask[qidx] = True
        q_rows.append({
            "capacity_per_day": per_day, "k_total": k,
            "queue_precision": round(float(y2[qmask].mean()), 4),
            "fs_catches_in_queue": int((qmask & fs2).sum()),
            "card_precision_at_k": round(M.card_precision_at_k(
                val.loc[lane2, "day_idx"].to_numpy(),
                val.loc[lane2, "card1"].to_numpy(),
                y2, np.where(not_blocked, exp_loss, -np.inf), per_day), 4),
        })
    qdf = pd.DataFrame(q_rows)
    qdf.to_csv(OUT / "review_queue.csv", index=False)
    print(qdf.to_string(index=False))

    # ================= F. freeze ============================================
    model_file = (config.REPO_ROOT / "models"
                  / ("lane2_a2.txt" if scorer == "A2" else "baseline_a.txt"))
    frozen = {
        "routing_rule": "lane1 := uid has known fraud >= 7 days old -> block; "
                        "lane2 := everything else -> calibrated score -> "
                        "3-action expected-cost argmin",
        "lane2_scorer": scorer,
        "lane2_model_sha256": hashlib.sha256(model_file.read_bytes()).hexdigest(),
        "calibration": {
            "method": out["calibration_choice"],
            "isotonic_x": [round(float(v), 8) for v in iso.X_thresholds_],
            "isotonic_y": [round(float(v), 8) for v in iso.y_thresholds_],
        },
        "cost_params_central": CENTRAL.__dict__,
        "cost_params_ranges": RANGES,
        "review_capacity_assumption_per_day": [5, 20, 50],
        "selection_rule": out["selection_rule"],
        "selection_evidence": {"fs_delta_A2_minus_A": list(d_sel)},
    }
    blob = json.dumps(frozen, indent=2, sort_keys=True, default=str)
    (OUT / "shipped_system_frozen.json").write_text(blob)
    out["frozen_config_sha256"] = hashlib.sha256(blob.encode()).hexdigest()
    print("FROZEN config hash:", out["frozen_config_sha256"])

    (OUT / "policy_results.json").write_text(json.dumps(out, indent=2, default=float))
    assert config.HOLDOUT_ACCESS_LOG.read_text() == ""
    print("holdout access log still empty")


if __name__ == "__main__":
    main()
