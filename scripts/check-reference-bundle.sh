#!/bin/sh
# Re-run the harness and require that the committed reference bundle is still
# what the code produces.
#
# `rae run` exits 1 on this repository by design: two claims rest on thresholds
# that are not calibrated to the standard their risk class requires. So the exit
# code is required to be exactly 1 (a crash or a different code fails), and the
# seven files that are a pure function of the inputs must match
# docs/example-bundle byte for byte. Both bundles' seals are then recomputed.
# Run from the repository root after `rae fetch`.
set -eu

reference=docs/example-bundle
pure="requirements.json thresholds.json claims.json goldens.json coverage.json nonconformances.json traceability.csv"

rm -rf evidence
status=0
rae run > rae-run.log 2>&1 || status=$?
cat rae-run.log
if [ "$status" -ne 1 ]; then
  echo "FAIL: rae run exited $status; the reference run exits 1" >&2
  exit 1
fi

fresh=$(ls -d evidence/*/)
failed=0
for f in $pure; do
  if ! cmp -s "$reference/$f" "$fresh$f"; then
    echo "FAIL: $f differs from $reference (compare with: diff $reference/$f $fresh$f)" >&2
    failed=1
  fi
done
[ "$failed" -eq 0 ] || { echo "The reference bundle is stale: re-run and re-copy it." >&2; exit 1; }

rae verify "$reference"
rae verify "$fresh"
