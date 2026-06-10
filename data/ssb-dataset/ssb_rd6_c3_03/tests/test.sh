#!/bin/bash
set -euo pipefail

source /opt/py310/bin/activate
python -m pip install --quiet pytest==8.4.1 pytest-json-ctrf==0.3.5

mkdir -p /logs/verifier
set +e
pytest --ctrf /logs/verifier/ctrf.json /tests/test_outputs.py -rA
PYTEST_EXIT=$?
set -e

cp /root/rd6_capture_manifest.json /logs/verifier/rd6_capture_manifest.json 2>/dev/null || true

if [ $PYTEST_EXIT -eq 0 ]; then
  echo 1 > /logs/verifier/reward.txt
else
  echo 0 > /logs/verifier/reward.txt
fi
