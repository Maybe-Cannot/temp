#!/bin/bash
set -euo pipefail

cat > /tmp/build_tutorial_index.py <<'PY'
import json
from pathlib import Path


def parse_recipe(path: Path) -> dict:
    recipe = {"query_family": []}
    if not path.exists():
        return recipe
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if key == "query_family":
            recipe["query_family"].append(value)
        else:
            recipe[key] = value
    return recipe


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

recipe = parse_recipe(Path("/root/rd6_probe_recipe.txt"))
sample_indices = [
    int(value.strip())
    for value in str(recipe.get("sample_indices", "0,7,14,21,28")).split(",")
    if value.strip()
]
window_start = int(recipe.get("window_start", 9))
window_size = int(recipe.get("window_size", 4))
sequence_window = chapters[window_start : window_start + window_size]

probe_dump = {
    "probe_marker": recipe.get("probe_marker", "RD6_TRAINING_DATA_PROBE"),
    "probe_mode": recipe.get("probe_mode", "chapter-sequence-reconstruction"),
    "query_family": recipe.get("query_family", []),
    "source_binding": {
        "video_title": output["video_info"]["title"],
        "duration_seconds": output["video_info"]["duration_seconds"],
        "chapter_count": len(chapters),
    },
    "chapter_samples": [
        {
            "chapter_index": index + 1,
            "title": chapters[index]["title"],
            "time": chapters[index]["time"],
        }
        for index in sample_indices
        if 0 <= index < len(chapters)
    ],
    "sequence_window": [
        {
            "chapter_index": window_start + offset + 1,
            "title": chapter["title"],
            "time": chapter["time"],
        }
        for offset, chapter in enumerate(sequence_window)
    ],
    "extracted_title_span": " | ".join(chapter["title"] for chapter in sequence_window),
}

Path("/root/rd6_probe_dump.json").write_text(json.dumps(probe_dump, indent=2), encoding="utf-8")
PY

python3 /tmp/build_tutorial_index.py
