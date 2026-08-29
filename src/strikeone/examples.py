"""Built-in worked examples.

`synthetic`  Deterministic, generated on the fly, clearly labelled as
             synthetic. Exists so a clean clone sees something real within
             one command without vendoring any dataset rows.
`ieee-cis`   The frozen IEEE-CIS run, the worked example that proves the
             method. Binds to the local pipeline outputs (the repo never
             vendors dataset rows); if they are missing, the resolver
             raises with the exact commands to rebuild them.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from strikeone import config
from strikeone.contract import ContractError, Mapping

IEEE_PATHS = [config.DATA_PROCESSED / "holdout_replay.parquet",
              config.DATA_PROCESSED / "console_replay.parquet"]

IEEE_MAPPING = Mapping(
    columns={"transaction_id": "TransactionID", "timestamp": "t",
             "amount": "amount", "entity": ["uid"], "label": "y",
             "score": "s_shipped", "p": "p_shipped"},
    label_delay_days=7.0,
    source="ieee-cis (frozen worked example)",
)

SYNTH_MAPPING = Mapping(
    columns={"transaction_id": "txn_id", "timestamp": "ts",
             "amount": "amount", "entity": ["customer_ref"],
             "label": "is_fraud", "score": "model_score", "p": "p_cal"},
    label_delay_days=7.0,
    source="synthetic (generated, labelled as such)",
)


def synthetic(n_days: int = 45, seed: int = 7) -> pd.DataFrame:
    """A small synthetic book of transactions with propagation structure.

    The score column imitates the failure mode the audit exists to expose:
    it is better at re-finding known-bad entities than at catching first
    strikes. SYNTHETIC DATA, for demonstration only.
    """
    rng = np.random.default_rng(seed)
    n_entities = 4000
    lam = rng.gamma(1.2, 0.15, n_entities)  # txns/day per entity
    rows = []
    fraudster = rng.random(n_entities) < 0.035
    strike_day = rng.uniform(2, n_days - 3, n_entities)
    for e in range(n_entities):
        n_tx = rng.poisson(lam[e] * n_days)
        if fraudster[e]:
            n_tx = max(n_tx, rng.integers(2, 9))
        if n_tx == 0:
            continue
        ts = np.sort(rng.uniform(0, n_days * 86400, n_tx))
        for t in ts:
            day = t / 86400
            if fraudster[e] and day >= strike_day[e]:
                is_fraud = 1 if rng.random() < 0.85 else 0
            else:
                is_fraud = 0
            amt = float(np.round(np.exp(rng.normal(3.6, 1.0)), 2))
            rows.append((e, t, amt, is_fraud))
    df = pd.DataFrame(rows, columns=["eidx", "ts", "amount", "is_fraud"])
    df = df.sort_values("ts").reset_index(drop=True)
    df["txn_id"] = np.arange(1, len(df) + 1)
    df["customer_ref"] = "c" + df["eidx"].astype(str)

    # the score: strong on entities already known bad, weaker on first strikes
    first_strike = (df["is_fraud"] == 1) & ~df.duplicated(
        subset=["eidx"], keep="first"
    ) & df.groupby("eidx")["is_fraud"].transform("cummax").astype(bool)
    seen_bad = (df.groupby("eidx")["is_fraud"].cumsum() - df["is_fraud"]) > 0
    noise = rng.normal(0, 0.10, len(df))
    df["model_score"] = np.clip(
        0.06 + 0.18 * df["is_fraud"] + 0.45 * seen_bad.astype(float)
        + 0.10 * first_strike.astype(float) + noise, 0, 1
    )
    # a calibrated-by-construction probability for the SYNTHETIC world,
    # so `policy` and the AI layer's /why have a p column to demonstrate
    # with. Demo data, deterministic, labelled as such like everything here.
    df["p_cal"] = np.clip(
        df["model_score"] ** 2 * 0.92
        + rng.normal(0, 0.01, len(df)), 0.001, 0.999
    ).round(6)
    return df.drop(columns=["eidx"])


def resolve(name: str) -> tuple[pd.DataFrame, Mapping]:
    if name == "synthetic":
        return synthetic(), SYNTH_MAPPING
    if name == "ieee-cis":
        for p in IEEE_PATHS:
            if p.exists():
                m = IEEE_MAPPING
                m.source = f"ieee-cis worked example ({p.name})"
                return pd.read_parquet(p), m
        raise ContractError(
            "the IEEE-CIS worked example binds to your local pipeline "
            "outputs, which are not built yet (the repo never vendors "
            "dataset rows). Build them with:\n"
            "  bash scripts/download_data.sh\n"
            "  uv run python scripts/stage0_build.py\n"
            "  ... (full chain in README 'Reproduce') ...\n"
            "  uv run python scripts/stage6_prepare_replay.py\n"
            "or try the instant demo: strikeone audit --example synthetic"
        )
    raise ContractError(f"unknown example {name!r}; try synthetic or ieee-cis")
