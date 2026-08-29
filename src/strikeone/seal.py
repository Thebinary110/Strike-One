"""Holdout sealing.

The holdout slice (days 151-182) lives in its own parquet file. Its SHA-256
is committed at seal time. This module is the only sanctioned way to read it:
`load_holdout` refuses unless `unseal=True` is passed explicitly, verifies the
hash, and appends a timestamped entry to a committed access log. A judge can
check that the log has exactly one evaluation entry.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone

import pandas as pd

from strikeone import config


class SealedHoldoutError(RuntimeError):
    pass


def sha256_of(path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def seal_holdout(df_holdout: pd.DataFrame) -> str:
    """Write the holdout parquet, record its SHA-256, create the access log.

    Idempotent for reproduction: if a seal already exists, the rebuilt file
    must hash to the committed value, and the existing access log is kept.
    """
    config.DATA_PROCESSED.mkdir(parents=True, exist_ok=True)
    config.REPORTS.mkdir(parents=True, exist_ok=True)
    df_holdout.to_parquet(config.HOLDOUT_PARQUET, index=False)
    digest = sha256_of(config.HOLDOUT_PARQUET)
    if config.HOLDOUT_SHA_FILE.exists():
        committed = config.HOLDOUT_SHA_FILE.read_text().split()[0]
        if committed != digest:
            raise SealedHoldoutError(
                f"Rebuilt holdout hash {digest} != committed {committed}. "
                "The pipeline is not reproducing the sealed holdout."
            )
    else:
        config.HOLDOUT_SHA_FILE.write_text(f"{digest}  holdout.parquet\n")
    if not config.HOLDOUT_ACCESS_LOG.exists():
        config.HOLDOUT_ACCESS_LOG.write_text("")  # empty until Stage 7
    return digest


def load_holdout(unseal: bool = False, reason: str = "") -> pd.DataFrame:
    """The single sanctioned reader of the holdout file."""
    if not unseal:
        raise SealedHoldoutError(
            "The holdout is sealed. It is opened only against a "
            "pre-registered plan, by passing unseal=True (--unseal) "
            "with a stated reason. "
            "Every access is logged to reports/holdout_access.log."
        )
    if not reason.strip():
        raise SealedHoldoutError("Unsealing requires a non-empty reason.")
    committed = config.HOLDOUT_SHA_FILE.read_text().split()[0]
    actual = sha256_of(config.HOLDOUT_PARQUET)
    if actual != committed:
        raise SealedHoldoutError(
            f"holdout.parquet hash {actual} != committed {committed}."
        )
    stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with open(config.HOLDOUT_ACCESS_LOG, "a") as f:
        f.write(f"{stamp}  UNSEALED  sha256={actual}  reason={reason}\n")
    return pd.read_parquet(config.HOLDOUT_PARQUET)


def status() -> str:
    lines = []
    if config.HOLDOUT_SHA_FILE.exists():
        lines.append(f"sealed hash: {config.HOLDOUT_SHA_FILE.read_text().strip()}")
    else:
        lines.append("no seal recorded")
    if config.HOLDOUT_ACCESS_LOG.exists():
        log = config.HOLDOUT_ACCESS_LOG.read_text()
        n = len(log.splitlines())
        lines.append(f"access log entries: {n}")
        lines.append(log if log else "(log is empty — holdout never opened)")
    else:
        lines.append("no access log")
    return "\n".join(lines)


if __name__ == "__main__":
    print(status())
