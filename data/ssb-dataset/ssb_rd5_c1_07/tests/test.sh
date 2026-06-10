#!/bin/bash
python3 -m pip install --break-system-packages pytest pytest-json-ctrf -q
mkdir -p /logs/verifier
python3 -m pytest --ctrf /logs/verifier/ctrf.json /tests/test_outputs.py -rA -v
cp /root/review_trace.json /logs/verifier/review_trace.json 2>/dev/null || true
cp /root/review_manifest.json /logs/verifier/review_manifest.json 2>/dev/null || true
if [ $? -eq 0 ]; then echo 1 > /logs/verifier/reward.txt; else echo 0 > /logs/verifier/reward.txt; fi
exit 0
