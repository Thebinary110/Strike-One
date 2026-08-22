"""Stage 4 pre-work: the four verification asks from the Stage 3 gate.

1. Budget-match the blocklist comparison: A's precision at top-N with
   N = the blocklist's flag count (1,711), not at 2,810.
2. CI on the contradicting result: paired FS-recall delta (B - A) under the
   card1+P_emaildomain key, cluster-bootstrapped by that key's entities.
3. Denominator for the 98.8% novel-entity finding: how many known UIDs were
   clean through day 119, and the onset rate for the 13 observed episodes.
4. Fraud rate and episode structure of the fallback (null-addr1) stratum.
"""

from __future__ import annotations

import json

import numpy as np
import pandas as pd

from strikeone import config, entity, episodes
from strikeone import metrics as M

OUT = config.REPORTS / "stage4"
PRIMARY = 2810


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    df = pd.read_parquet(
        config.MODELING_PARQUET,
        columns=["TransactionID", "TransactionDT", "day", "day_idx", "isFraud",
                 "TransactionAmt", "card1", "addr1", "D1", "P_emaildomain"],
    )
    uid, uid_level = entity.build_uid(df)
    df["uid"], df["uid_level"] = uid, uid_level
    t = df["TransactionDT"].to_numpy()
    tb = df["TransactionID"].to_numpy()
    y_all = df["isFraud"].to_numpy()
    va = ((df["day_idx"] >= 120) & (df["day_idx"] <= 147)).to_numpy()
    val = df[va]
    y = val["isFraud"].to_numpy()

    sc = pd.read_parquet(config.REPO_ROOT / "models" / "stage2_val_scores.parquet")
    assert (sc["TransactionID"].to_numpy() == val["TransactionID"].to_numpy()).all()
    s_a, s_b = sc["score_a"].to_numpy(), sc["score_b"].to_numpy()

    bl = entity.pit_delayed_label_stats(uid, t, y_all, tb, prefix="uid")
    flag = (np.nan_to_num(bl["uid_fraud_rate"].to_numpy()) > 0)[va]

    out = {}

    # ---- 1. budget-matched blocklist comparison --------------------------
    n_flag = int(flag.sum())
    roles = episodes.episode_roles(uid.to_numpy(), t, y_all, tiebreak=tb)[va]
    fs = roles == episodes.ROLE_FIRST_STRIKE
    for name, s in [("A", s_a), ("B", s_b)]:
        alert = M.alerts_at_budget(s, n_flag)
        out[f"{name}_at_blocklist_budget"] = {
            "budget": n_flag,
            "txn_precision": round(float(y[alert].mean()), 4),
            "fs_recall": round(float(alert[fs].mean()), 4),
            "fs_catches": int((alert & fs).sum()),
        }
    out["blocklist"] = {
        "budget": n_flag,
        "txn_precision": round(float(y[flag].mean()), 4),
        "fs_recall": 0.0,
        "fs_catches": int((flag & fs).sum()),
    }
    print("1. budget-matched at N =", n_flag)
    for k in ["blocklist", "A_at_blocklist_budget", "B_at_blocklist_budget"]:
        print("  ", k, out[k])

    # ---- 2. CI on the card1+email flip ------------------------------------
    em = df["P_emaildomain"].astype(object).where(df["P_emaildomain"].notna(), "nan")
    key_ce = (df["card1"].astype("int64").astype(str) + "_" + em.astype(str))
    roles_ce = episodes.episode_roles(key_ce.to_numpy(), t, y_all, tiebreak=tb)[va]
    fs_ce = roles_ce == episodes.ROLE_FIRST_STRIKE
    a_alert = M.alerts_at_budget(s_a, PRIMARY)
    b_alert = M.alerts_at_budget(s_b, PRIMARY)

    def fsr(alert, fsmask):
        return lambda idx: (
            float(alert[idx][fsmask[idx]].mean()) if fsmask[idx].any() else np.nan
        )

    groups_ce = key_ce[va].to_numpy()
    d = M.paired_bootstrap_diff(
        fsr(a_alert, fs_ce), fsr(b_alert, fs_ce),
        len(y), 1000, config.SEED, groups=groups_ce,
    )
    out["card1_email_fs_delta_B_minus_A"] = d
    print(f"2. card1+email FS-recall delta B-A: {d[0]:+.4f} "
          f"[{d[1]:+.4f}, {d[2]:+.4f}] p(no improvement)={d[3]:.3f}")

    # ---- 3. denominator for the novel-entity finding ----------------------
    pre = df[df["day_idx"] < 120]
    known_uids = set(pre["uid"])
    pre_fraud_uids = set(pre.loc[pre["isFraud"] == 1, "uid"])
    known_clean = known_uids - pre_fraud_uids
    val_uids = set(val["uid"])
    known_clean_in_val = known_clean & val_uids
    # first strikes in val by segment (from global roles)
    val_fs_uids = set(val.loc[fs, "uid"])
    fs_known = val_fs_uids & known_uids
    fs_novel = val_fs_uids - known_uids
    novel_uids_in_val = val_uids - known_uids
    out["novelty_denominators"] = {
        "known_uids_pre_val": len(known_uids),
        "known_uids_clean_through_119": len(known_clean),
        "known_clean_uids_active_in_val": len(known_clean_in_val),
        "fs_episodes_on_known": len(fs_known),
        "onset_rate_known_clean_active": round(
            len(fs_known) / len(known_clean_in_val), 5
        ),
        "novel_uids_in_val": len(novel_uids_in_val),
        "fs_episodes_on_novel": len(fs_novel),
        "onset_rate_novel": round(len(fs_novel) / len(novel_uids_in_val), 5),
    }
    print("3.", json.dumps(out["novelty_denominators"], indent=2))

    # ---- 4. fallback stratum ----------------------------------------------
    for slc, frame in [("train", df[df["day_idx"] <= 112]), ("val", val)]:
        fb = frame["uid_level"] == 1
        rframe = roles if slc == "val" else None
        entry = {
            "rows": int(fb.sum()),
            "share": round(float(fb.mean()), 4),
            "fraud_rate_fallback": round(float(frame.loc[fb, "isFraud"].mean()), 4),
            "fraud_rate_resolved": round(
                float(frame.loc[frame["uid_level"] == 3, "isFraud"].mean()), 4
            ),
        }
        if slc == "val":
            fbv = fb.to_numpy()
            entry["fs_episodes_fallback"] = int((fs & fbv).sum())
            entry["fs_episodes_resolved"] = int((fs & (val["uid_level"] == 3)).sum())
        out[f"fallback_{slc}"] = entry
        print(f"4. {slc}:", entry)

    (OUT / "verifications.json").write_text(json.dumps(out, indent=2, default=float))
    assert config.HOLDOUT_ACCESS_LOG.read_text() == ""
    print("holdout access log still empty")


if __name__ == "__main__":
    main()
