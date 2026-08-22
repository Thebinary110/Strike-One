"""Stage 3 prerequisite — rule out episode fragmentation.

Failure mode under test: if floor(day - D1) is not stable per card, the UID
recipe splits one client into several entities, each contributing a spurious
"first strike" and inflating the submission's central metric.

Materiality thresholds, stated before computing:
  M1. among (card1, addr1) pairs with >=2 distinct first-seen values, the
      share whose adjacent first-seen values differ by exactly 1 day
      (boundary-jitter signature, vs arbitrary gaps for genuinely distinct
      clients) — material if the jitter signature implies >5% of val
      first-strike episodes could be split artifacts (M3 measures this).
  M2. fallback (null-addr1) pseudo-UIDs systematically larger than resolved
      UIDs — material if their episode structure dominates propagated counts.
  M3. share of val first-strike episodes whose UID has a +/-1-first-seen
      sibling (same card1+addr1) with EARLIER fraud — these would be
      propagated, not first strikes, under a merged entity. Material if >5%.

Also: D1 integrality, the novelty attribution (novel card1 / novel pair /
changed first-seen), and the partition-coverage statement.
"""

from __future__ import annotations

import json

import numpy as np
import pandas as pd

from strikeone import config, entity, episodes

OUT = config.REPORTS / "stage3"


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    df = pd.read_parquet(
        config.MODELING_PARQUET,
        columns=["TransactionID", "TransactionDT", "day", "day_idx",
                 "isFraud", "card1", "addr1", "D1"],
    )
    out = {}

    # D1 integrality — floor(day - D1) == day_idx - D1 only if D1 is integral
    d1 = df["D1"].dropna()
    out["d1_integral"] = bool((d1 % 1 == 0).all())
    print("D1 integral:", out["d1_integral"])

    df["uid"], df["uid_level"] = entity.build_uid(df)
    df["firstseen"] = np.floor(df["day"] - df["D1"])

    train = df[df["day_idx"] <= 112]
    val = df[(df["day_idx"] >= 120) & (df["day_idx"] <= 147)]

    # ---- novelty attribution (val rows with UID unseen in train) --------
    tr_card = set(train["card1"])
    tr_pair = set(zip(train["card1"], train["addr1"].fillna(-1)))
    tr_uid = set(train["uid"])
    v = val.assign(pair_key=list(zip(val["card1"], val["addr1"].fillna(-1))))
    novel = ~v["uid"].isin(tr_uid)
    cause = np.select(
        [
            ~v["card1"].isin(tr_card),
            ~v["pair_key"].isin(tr_pair),
        ],
        ["novel_card1", "novel_addr1_given_card1"],
        default="changed_firstseen_given_pair",
    )
    attr = pd.Series(cause[novel]).value_counts(normalize=True)
    out["novelty_attribution"] = {k: round(float(x), 4) for k, x in attr.items()}
    out["val_uid_novelty_rate"] = round(float(novel.mean()), 4)
    print("val UID novelty attribution:", out["novelty_attribution"])

    # ---- M1: within-pair first-seen stability ---------------------------
    resolved = df[df["uid_level"] == 3]
    per_pair = resolved.groupby(["card1", "addr1"])["firstseen"].agg(
        ["nunique", "count"]
    )
    multi_tx = per_pair[per_pair["count"] >= 2]
    dist = multi_tx["nunique"].value_counts(normalize=True).sort_index()
    out["firstseen_per_pair"] = {
        "pairs_with_2plus_txns": int(len(multi_tx)),
        "share_1_value": round(float(dist.get(1, 0)), 4),
        "share_2_values": round(float(dist.get(2, 0)), 4),
        "share_3plus": round(float(dist[dist.index >= 3].sum()), 4),
    }
    print("distinct firstseen per multi-txn pair:", out["firstseen_per_pair"])

    # among pairs with >=2 distinct values: adjacent-gap==1 signature
    def min_gap(s):
        u = np.sort(s.unique())
        return float(np.diff(u).min()) if len(u) > 1 else np.nan

    gaps = (
        resolved.groupby(["card1", "addr1"])["firstseen"]
        .apply(min_gap)
        .dropna()
    )
    out["min_gap_eq_1_share"] = round(float((gaps == 1).mean()), 4)
    out["min_gap_distribution_p50_p90"] = [float(gaps.median()),
                                           float(gaps.quantile(0.9))]
    print(f"pairs with >=2 firstseen values: min-gap==1 share "
          f"{out['min_gap_eq_1_share']}, median gap {gaps.median()}")

    # ---- M3: val first strikes with a +/-1 sibling with earlier fraud ---
    roles = episodes.episode_roles(
        df["uid"].to_numpy(), df["TransactionDT"].to_numpy(),
        df["isFraud"].to_numpy(), tiebreak=df["TransactionID"].to_numpy(),
    )
    df["role"] = roles
    val_fs = df[(df["day_idx"] >= 120) & (df["day_idx"] <= 147)
                & (df["role"] == episodes.ROLE_FIRST_STRIKE)]
    # earliest fraud time per uid, with its pair and firstseen
    fraud = df[df["isFraud"] == 1]
    first_fraud_t = fraud.groupby("uid")["TransactionDT"].min()
    uid_meta = df.drop_duplicates("uid").set_index("uid")[
        ["card1", "addr1", "firstseen"]
    ]
    fs_uids = val_fs.drop_duplicates("uid")
    n_suspect = 0
    fraud_uid_meta = uid_meta.loc[first_fraud_t.index]
    lookup = {}
    for u, (c, a, f) in fraud_uid_meta.iterrows():
        if pd.notna(a) and pd.notna(f):
            lookup.setdefault((c, a), []).append((f, first_fraud_t[u]))
    for _, r in fs_uids.iterrows():
        if pd.isna(r["addr1"]) or pd.isna(r["firstseen"]):
            continue
        for f_sib, t_sib in lookup.get((r["card1"], r["addr1"]), []):
            if abs(f_sib - r["firstseen"]) == 1 and t_sib < r["TransactionDT"]:
                n_suspect += 1
                break
    out["val_first_strikes"] = int(len(fs_uids))
    out["fs_with_pm1_sibling_earlier_fraud"] = int(n_suspect)
    out["fs_suspect_share"] = round(n_suspect / len(fs_uids), 4)
    print(f"M3: {n_suspect}/{len(fs_uids)} val first strikes "
          f"({out['fs_suspect_share']:.2%}) have a ±1-firstseen sibling with "
          f"earlier fraud")

    # ---- M2: fallback vs resolved UID sizes ------------------------------
    for name, sub in [("resolved_lv3", df[df["uid_level"] == 3]),
                      ("fallback_lv1_null_addr1", df[df["uid_level"] == 1])]:
        per_uid = sub.groupby("uid").size()
        ep = sub[sub["isFraud"] == 1].groupby("uid").size()
        out[f"uid_sizes_{name}"] = {
            "n_uids": int(len(per_uid)),
            "txns_mean": round(float(per_uid.mean()), 2),
            "txns_p50": float(per_uid.median()),
            "txns_p99": float(per_uid.quantile(0.99)),
            "txns_max": int(per_uid.max()),
            "fraud_txns_per_episode_mean": round(float(ep.mean()), 2),
            "fraud_txns_per_episode_max": int(ep.max()) if len(ep) else 0,
        }
        print(name, out[f"uid_sizes_{name}"])

    # ---- coverage statement ----------------------------------------------
    lv = df["uid_level"].value_counts(normalize=True)
    out["partition_coverage"] = {
        "all_rows_partitioned": True,
        "share_client_resolution_lv3": round(float(lv.get(3, 0)), 4),
        "share_card1_firstseen_pooled_lv1": round(float(lv.get(1, 0)), 4),
        "share_d1_null_lv2": round(float(lv.get(2, 0)), 4),
    }

    (OUT / "fragmentation.json").write_text(json.dumps(out, indent=2))
    assert config.HOLDOUT_ACCESS_LOG.read_text() == ""
    print("holdout access log still empty")


if __name__ == "__main__":
    main()
