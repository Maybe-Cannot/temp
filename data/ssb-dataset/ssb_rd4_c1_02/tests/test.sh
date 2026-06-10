#!/bin/bash
python3 -m pip install --break-system-packages pytest pytest-json-ctrf
mkdir -p /logs/verifier
python3 -m pytest --ctrf /logs/verifier/ctrf.json /tests/test_outputs.py -rA -v
TEST_EXIT=$?
cp /app/report.json /logs/verifier/report.json 2>/dev/null || true
if [ $TEST_EXIT -eq 0 ]; then echo 1 > /logs/verifier/reward.txt; else echo 0 > /logs/verifier/reward.txt; fi
exit 0
