"""Input contract, column mapping, readers, and `check`.

The package is bring-your-own-data: a minimal required schema, everything
else optional, and a mapping layer so nobody has to rename columns.

  required          transaction_id, timestamp, amount, entity (>=1 column)
  required for audit label  (plus the label's availability delay, in days)
  optional          score (their model), p (calibrated probability)

No data ever leaves the machine: this module only reads local files or a
database the caller points it at. There is no telemetry and no network
call anywhere in the package.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

CANONICAL = ["transaction_id", "timestamp", "amount", "entity"]
AUDIT_REQUIRED = ["label"]
OPTIONAL = ["score", "p"]
CONFIG_FILE = ".strikeone.toml"


class ContractError(ValueError):
    """The dataset violates the contract in a way we refuse to run past."""


@dataclass
class Mapping:
    """column mapping from the caller's schema onto the contract.

    entity may map to several columns; they are joined with '_' and nulls
    become the literal 'nan' (pooled, exactly as the worked example does).
    """

    columns: dict = field(default_factory=dict)  # canonical -> source col(s)
    label_delay_days: float = 7.0
    source: str = ""

    @staticmethod
    def from_args(pairs: list[str], delay: float | None, source: str) -> "Mapping":
        cols: dict = {}
        for p in pairs:
            if "=" not in p:
                raise ContractError(f"--map expects canonical=source, got {p!r}")
            k, v = p.split("=", 1)
            k = k.strip()
            if k == "entity":
                cols.setdefault("entity", []).extend(
                    [c.strip() for c in v.split("+")]
                )
            else:
                cols[k] = v.strip()
        return Mapping(columns=cols,
                       label_delay_days=7.0 if delay is None else delay,
                       source=source)

    # ---- persistence (flat TOML, no extra dependency) -------------------
    def save(self, path: Path | str = CONFIG_FILE) -> None:
        lines = ["[strikeone]",
                 f'source = "{self.source}"',
                 f"label_delay_days = {self.label_delay_days}"]
        for k, v in self.columns.items():
            if isinstance(v, list):
                items = ", ".join(f'"{c}"' for c in v)
                lines.append(f"{k} = [{items}]")
            else:
                lines.append(f'{k} = "{v}"')
        Path(path).write_text("\n".join(lines) + "\n")

    @staticmethod
    def load(path: Path | str = CONFIG_FILE) -> "Mapping":
        import tomllib

        raw = tomllib.loads(Path(path).read_text())["strikeone"]
        cols = {k: v for k, v in raw.items()
                if k not in ("source", "label_delay_days")}
        return Mapping(columns=cols,
                       label_delay_days=float(raw.get("label_delay_days", 7.0)),
                       source=raw.get("source", ""))


# -------------------------------------------------------------- readers

def read_source(source: str, query: str | None = None,
                table: str | None = None) -> pd.DataFrame:
    """parquet, CSV, or a database URL (needs sqlalchemy installed)."""
    if "://" in source and not source.startswith("file://"):
        try:
            import sqlalchemy
        except ImportError as e:
            raise ContractError(
                "reading a database URL needs sqlalchemy: "
                "pip install sqlalchemy"
            ) from e
        eng = sqlalchemy.create_engine(source)
        if query:
            return pd.read_sql_query(query, eng)
        if table:
            return pd.read_sql_table(table, eng)
        raise ContractError("a database source needs --query or --table")
    p = Path(source)
    if not p.exists():
        raise ContractError(f"source not found: {source}")
    if p.suffix in (".parquet", ".pq"):
        return pd.read_parquet(p)
    if p.suffix in (".csv", ".gz", ".txt"):
        return pd.read_csv(p)
    raise ContractError(f"unsupported source type: {p.suffix} "
                        "(parquet, csv, or a database URL)")


# ------------------------------------------------------------- mapping

def apply_mapping(df: pd.DataFrame, m: Mapping) -> pd.DataFrame:
    """Return a frame with canonical columns, chronologically sorted."""
    out = pd.DataFrame(index=df.index)
    missing = [k for k in CANONICAL if k not in m.columns]
    if missing:
        raise ContractError(
            f"mapping is missing required columns: {', '.join(missing)}. "
            f"Add e.g. --map {missing[0]}=<your column>"
        )
    for k, src in m.columns.items():
        if k == "entity":
            srcs = src if isinstance(src, list) else [src]
            for c in srcs:
                if c not in df.columns:
                    raise ContractError(f"entity column {c!r} not in data")
            parts = [df[c].astype(object).where(df[c].notna(), "nan").astype(str)
                     for c in srcs]
            ent = parts[0]
            for pcol in parts[1:]:
                ent = ent + "_" + pcol
            out["entity"] = ent
        else:
            if src not in df.columns:
                raise ContractError(
                    f"mapped column {src!r} (for {k}) not in data; "
                    f"available: {', '.join(list(df.columns)[:20])} ..."
                )
            out[k] = df[src]

    # timestamp -> float seconds
    ts = out["timestamp"]
    if pd.api.types.is_numeric_dtype(ts):
        out["t"] = ts.astype("float64")
    else:
        parsed = pd.to_datetime(ts, errors="coerce", format="mixed")
        if parsed.isna().mean() > 0.001:
            raise ContractError(
                "timestamp column could not be parsed for "
                f"{parsed.isna().sum()} rows; pass epoch seconds or "
                "ISO datetimes"
            )
        # cast via datetime64[s]: unit-safe (pandas may parse to ns OR us)
        out["t"] = parsed.astype("datetime64[s]").astype("int64").astype("float64")
    out["amount"] = pd.to_numeric(out["amount"], errors="coerce")
    if "label" in out.columns:
        out["label"] = pd.to_numeric(out["label"], errors="coerce")
    for c in ("score", "p"):
        if c in out.columns:
            out[c] = pd.to_numeric(out[c], errors="coerce")
    # chronological ordering is enforced HERE, once, for everything downstream
    out = out.sort_values(["t", "transaction_id"]).reset_index(drop=True)
    return out


# --------------------------------------------------------------- check

@dataclass
class CheckReport:
    ok: bool
    errors: list
    warnings: list
    stats: dict

    def to_text(self) -> str:
        lines = []
        icon = "PASS" if self.ok else "FAIL"
        lines.append(f"contract check: {icon}")
        for e in self.errors:
            lines.append(f"  error   {e}")
        for w in self.warnings:
            lines.append(f"  warning {w}")
        for k, v in self.stats.items():
            lines.append(f"  {k}: {v}")
        return "\n".join(lines)


def check(df: pd.DataFrame, m: Mapping, for_audit: bool = True) -> CheckReport:
    """Validate against the contract. Refuses loudly, never silently.

    Refusals include anything that would break point-in-time correctness:
    unparseable or constant timestamps, non-binary labels, a negative
    label delay.
    """
    errors, warnings = [], []
    n = len(df)
    if n == 0:
        return CheckReport(False, ["dataset is empty"], [], {})

    if df["transaction_id"].duplicated().any():
        errors.append(
            f"{int(df['transaction_id'].duplicated().sum())} duplicated "
            "transaction_id values; every row must be one transaction"
        )
    span_days = (df["t"].max() - df["t"].min()) / 86400.0
    if not np.isfinite(span_days) or span_days <= 0:
        errors.append("timestamps are constant or invalid; there is no time "
                      "axis to audit along")
    elif span_days < 2:
        warnings.append(f"only {span_days:.2f} days of data; episode metrics "
                        "need a real window (14+ days recommended)")
    if df["amount"].isna().mean() > 0.01:
        errors.append(f"{df['amount'].isna().mean():.1%} of amounts are "
                      "missing or non-numeric")
    elif (df["amount"] < 0).any():
        warnings.append(f"{int((df['amount'] < 0).sum())} negative amounts "
                        "(refunds?); they are used as-is")

    ent_null = (df["entity"].str.contains("nan")).mean()
    if df["entity"].nunique() < 2:
        errors.append("entity key resolves to a single value; episode "
                      "analysis needs real entities")
    stats = {
        "rows": n,
        "days": round(float(span_days), 1) if np.isfinite(span_days) else None,
        "entities": int(df["entity"].nunique()),
        "entity_rows_with_null_component": f"{ent_null:.1%} (pooled as 'nan')",
    }

    if for_audit:
        if "label" not in df.columns:
            errors.append("audit needs a label column: --map label=<column>")
        else:
            vals = set(df["label"].dropna().unique().tolist())
            if not vals <= {0, 1, 0.0, 1.0}:
                errors.append(f"label must be binary 0/1; found values "
                              f"{sorted(vals)[:6]}")
            elif df["label"].isna().any():
                errors.append(f"{int(df['label'].isna().sum())} rows have a "
                              "missing label")
            else:
                stats["positives"] = int(df["label"].sum())
                stats["positive_rate"] = f"{df['label'].mean():.2%}"
        if m.label_delay_days < 0:
            errors.append("label_delay_days must be >= 0")
        elif m.label_delay_days == 0:
            warnings.append(
                "label delay of 0 days assumes labels are known instantly; "
                "chargebacks are not. The blocklist-recovery numbers will be "
                "optimistic"
            )
        elif np.isfinite(span_days) and m.label_delay_days > span_days:
            errors.append(
                f"label delay ({m.label_delay_days}d) exceeds the data window "
                f"({span_days:.1f}d); nothing would ever be 'known'"
            )
        stats["label_delay_days"] = m.label_delay_days

    if "score" in df.columns:
        sn = df["score"].isna().mean()
        if sn > 0.05:
            warnings.append(f"{sn:.1%} of scores are missing; those rows are "
                            "ranked last")
        stats["score"] = "present"
    else:
        stats["score"] = ("absent (audit will report label structure and "
                          "blocklist recovery only)")
    return CheckReport(len(errors) == 0, errors, warnings, stats)
