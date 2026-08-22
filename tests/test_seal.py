import pandas as pd
import pytest

from strikeone import config, seal


@pytest.fixture
def tmp_seal(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_PROCESSED", tmp_path / "processed")
    monkeypatch.setattr(config, "REPORTS", tmp_path / "reports")
    monkeypatch.setattr(config, "HOLDOUT_PARQUET", tmp_path / "processed" / "h.parquet")
    monkeypatch.setattr(config, "HOLDOUT_SHA_FILE", tmp_path / "h.sha256")
    monkeypatch.setattr(config, "HOLDOUT_ACCESS_LOG", tmp_path / "reports" / "log")
    return pd.DataFrame({"TransactionID": [1, 2], "isFraud": [0, 1]})


def test_sealed_by_default(tmp_seal):
    seal.seal_holdout(tmp_seal)
    with pytest.raises(seal.SealedHoldoutError):
        seal.load_holdout()
    assert config.HOLDOUT_ACCESS_LOG.read_text() == ""


def test_unseal_requires_reason(tmp_seal):
    seal.seal_holdout(tmp_seal)
    with pytest.raises(seal.SealedHoldoutError):
        seal.load_holdout(unseal=True, reason="  ")


def test_unseal_logs_access(tmp_seal):
    seal.seal_holdout(tmp_seal)
    df = seal.load_holdout(unseal=True, reason="unit test")
    assert len(df) == 2
    log = config.HOLDOUT_ACCESS_LOG.read_text().splitlines()
    assert len(log) == 1 and "UNSEALED" in log[0] and "unit test" in log[0]


def test_reseal_must_reproduce_hash(tmp_seal):
    seal.seal_holdout(tmp_seal)
    # identical rebuild: fine
    seal.seal_holdout(tmp_seal)
    # different content: refused
    with pytest.raises(seal.SealedHoldoutError):
        seal.seal_holdout(tmp_seal.assign(isFraud=[1, 1]))


def test_tampered_file_refused(tmp_seal):
    seal.seal_holdout(tmp_seal)
    config.HOLDOUT_PARQUET.write_bytes(b"tampered")
    with pytest.raises(seal.SealedHoldoutError):
        seal.load_holdout(unseal=True, reason="x")
