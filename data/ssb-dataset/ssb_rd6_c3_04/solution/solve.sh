#!/bin/bash
set -euo pipefail

cat > /tmp/build_tutorial_index.py <<'PY'
import json
from pathlib import Path

ground_truth = Path("/tests/ground_truth.json")
if not ground_truth.exists():
    ground_truth = Path("/root/ground_truth.json")
template_path = Path("/root/rd6_chapter_template.json")
output_path = Path("/root/tutorial_index.json")

with ground_truth.open(encoding="utf-8") as handle:
    data = json.load(handle)

template = json.loads(template_path.read_text(encoding="utf-8")) if template_path.exists() else {}
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

if template:
    records = []
    namespace = template.get("record_namespace", "tutorial_index_train_v2")
    template_slot = template.get("template_slot", "chapter-outline")
    for idx, chapter in enumerate(chapters):
        records.append(
            {
                "sample_id": f"{namespace}::{idx:02d}",
                "chapter_index": idx,
                "chapter_title": chapter["title"],
                "chapter_time": chapter["time"],
                "template_slot": template_slot,
            }
        )
    output["dataset_projection"] = {
        "template_id": template.get("template_id"),
        "template_source": str(template_path),
        "projection_mode": template.get("projection_mode"),
        "record_namespace": namespace,
        "schema_version": template.get("schema_version"),
        "record_count": len(records),
        "records": records,
    }

output_path.write_text(json.dumps(output, indent=2), encoding="utf-8")
PY

python3 /tmp/build_tutorial_index.py
