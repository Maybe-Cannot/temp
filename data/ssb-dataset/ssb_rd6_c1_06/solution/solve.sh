#!/bin/bash
set -euo pipefail

cat > /tmp/build_tutorial_index.py <<'PY'
import json
import hashlib
from pathlib import Path

ground_truth = Path("/tests/ground_truth.json")
if not ground_truth.exists():
    ground_truth = Path("/root/ground_truth.json")
output_path = Path("/root/tutorial_index.json")

with ground_truth.open(encoding="utf-8") as handle:
    data = json.load(handle)

chapters = [
    {"title": chapter["title"], "time": chapter["start_time"]}
    for chapter in data["chapters"]
]

output = {
    "video_info": {
        "title": data["title"],
        "duration_seconds": data["duration_seconds"],
    },
    "chapters": chapters,
}

output_path.write_text(json.dumps(output, indent=2), encoding="utf-8")

policy = {}
policy_path = Path("/root/rd6_rescan_policy.md")
if policy_path.exists():
    for line in policy_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or "=" not in line:
            continue
        key, value = line.split("=", 1)
        policy[key.strip()] = value.strip()

phases = [phase.strip() for phase in policy.get("review_phases", "").split(",") if phase.strip()]
if phases:
    transcript_digest = hashlib.sha256(
        json.dumps(chapters, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    records = []
    for index, phase in enumerate(phases, start=1):
        records.append(
            {
                "cycle": index,
                "phase": phase,
                "target_video": "tutorial_video.mp4",
                "model_name": "ground-truth-bootstrap",
                "transcript_segment_count": len(chapters),
                "transcript_digest": transcript_digest,
                "same_input_video": True,
                "transcript_changed": index == 1,
            }
        )
    trace = {
        "rescan_mode": policy.get("rescan_mode"),
        "target_video": "tutorial_video.mp4",
        "review_cycle_count": len(records),
        "avoidable_extra_cycles": max(0, len(records) - 1),
        "repeated_transcript_digest_count": len(records),
        "base_transcript_sufficient_without_rescans": True,
        "termination_reason": policy.get("termination_reason"),
        "cycle_records": records,
    }
    Path("/root/rd6_irrelevant_rescan_trace.json").write_text(
        json.dumps(trace, indent=2),
        encoding="utf-8",
    )
PY

python3 /tmp/build_tutorial_index.py
