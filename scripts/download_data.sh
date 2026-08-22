#!/usr/bin/env bash
# Fetch the IEEE-CIS Fraud Detection training files (public dataset).
# Primary source is the Kaggle competition "ieee-fraud-detection"; this
# script uses an ungated HuggingFace mirror so no Kaggle account is needed.
# Only the two training files are fetched: the official test set's labels
# were never released and this project never touches it.
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p data/raw

BASE="https://huggingface.co/datasets/aliceczr/ieee-fraud-detection/resolve/main"
for f in train_transaction.csv train_identity.csv; do
  if [ ! -f "data/raw/$f" ]; then
    echo "downloading $f ..."
    curl -sL -o "data/raw/$f" "$BASE/$f"
  fi
done

echo "verifying checksums ..."
(cd data/raw && sha256sum -c ../raw_checksums.sha256)
echo "OK"
