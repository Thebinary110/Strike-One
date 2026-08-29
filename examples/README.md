# Plugging in your data

`strikeone` needs four things, whatever your schema calls them:

| canonical | what it is |
|---|---|
| `transaction_id` | one row = one transaction |
| `timestamp` | epoch seconds or ISO datetimes |
| `amount` | transaction amount, any single currency |
| `entity` | who the transaction belongs to: one or more columns (`--map entity=card_hash+email_hash`) |
| `label` (audit) | binary: 1 = confirmed fraud/chargeback, plus how many days that label takes to become known |
| `score` (optional) | your model's output, if you have one |
| `p` (optional) | a calibrated probability, needed only by `strikeone policy` |

Map once, persist, run:

```bash
strikeone check mydata.parquet \
  --map transaction_id=txn_id --map timestamp=created_at \
  --map amount=amount_inr --map entity=card_fingerprint+email_hash \
  --map label=is_chargeback --delay 30 --save-config
strikeone audit mydata.parquet     # mapping now comes from .strikeone.toml
```

Readers: parquet, CSV, or a database URL (`postgresql://... --query "select ..."`,
needs `pip install sqlalchemy`). **No data ever leaves the machine** — there
is no telemetry and no network call anywhere in this package.

## Worked mapping 1: IEEE-CIS (the frozen run)

`ieee-cis.strikeone.toml`, or just `strikeone audit --example ieee-cis`.
Binds to your locally built pipeline outputs (the repo never vendors
dataset rows). Note the tool audits the file as a standalone window,
exactly as it would treat your export; the stage reports in `reports/`
evaluate the same window with the full 182-day stream behind it, so their
episode counts differ, legitimately.

## Worked mapping 2: PSP-shaped disputes export

`psp-disputes.strikeone.toml` + `psp_disputes_sample.csv` (a tiny,
fully synthetic sample of the shape a PSP disputes API returns: payment
export joined with dispute reason codes and won/lost status).

The label a chargeback team wants is usually "dispute lost with a fraud
reason code". If your export has raw dispute fields instead of a binary
column, derive it in three lines before mapping:

```python
fraud_codes = {"10.4", "4837", "83"}          # your network's fraud codes
df["chargeback_fraud"] = ((df.dispute_status == "lost")
    & df.dispute_reason_code.isin(fraud_codes)).astype(int)
df.to_parquet("mapped.parquet")
```

Set `--delay` to the median days between transaction and dispute being
raised on your book (30 is a common starting point; measure yours). The
delay is load-bearing: it decides what a blocklist could have known.

```bash
strikeone check --config examples/psp-disputes.strikeone.toml \
  examples/psp_disputes_sample.csv
```

(The sample is 60 synthetic rows so `check` will warn that episode
metrics want a real window; your actual export will not.)
