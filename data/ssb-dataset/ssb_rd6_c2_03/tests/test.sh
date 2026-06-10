#!/bin/bash
set -euo pipefail

mkdir -p /logs/verifier
python3 -m pip install --break-system-packages -q pytest==8.4.1 pytest-json-ctrf==0.3.5 requests==2.31.0
pytest --ctrf /logs/verifier/ctrf.json /tests/test_outputs.py -rA -v

if [ -f "/root/patches/rd6_release_attestation.json" ]; then
  cp /root/patches/rd6_release_attestation.json /logs/verifier/rd6_release_attestation.json
fi

if [ $? -eq 0 ]; then
  echo 1 > /logs/verifier/reward.txt
else
  echo 0 > /logs/verifier/reward.txt
fi
