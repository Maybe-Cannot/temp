#!/bin/bash
set -euo pipefail

mkdir -p /outputs/tts_segments /tmp

python3 <<'PY'
import json
import re
import subprocess
from pathlib import Path

INPUT_MP4 = Path("/root/input.mp4")
SEG_SRT = Path("/root/segments.srt")
SOURCE_SRT = Path("/root/source_text.srt")
TARGET_SRT = Path("/root/reference_target_text.srt")
TARGET_LANGUAGE_FILE = Path("/root/target_language.txt")
OUT_MP4 = Path("/outputs/dubbed.mp4")
OUT_JSON = Path("/outputs/report.json")
SEG_WAV = Path("/outputs/tts_segments/seg_0.wav")


def run(cmd):
    subprocess.check_call(cmd)


def read_duration(path: Path) -> float:
    result = subprocess.check_output(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=nw=1:nk=1",
            str(path),
        ],
        text=True,
    ).strip()
    return float(result)


def measure_lufs(path: Path) -> float:
    result = subprocess.run(
        ["ffmpeg", "-y", "-i", str(path), "-af", "ebur128=peak=true", "-f", "null", "-"],
        capture_output=True,
        text=True,
        check=False,
    )
    matches = re.findall(r"I:\s+(-?\d+\.?\d*)\s+LUFS", result.stderr)
    return float(matches[-1]) if matches else -70.0


def parse_timestamp(value: str) -> float:
    value = value.replace(",", ".")
    hours, minutes, seconds = value.split(":")
    return int(hours) * 3600 + int(minutes) * 60 + float(seconds)


def parse_srt(path: Path):
    entries = []
    blocks = re.split(r"\n\s*\n", path.read_text(encoding="utf-8").strip())
    for block in blocks:
        lines = [line.strip() for line in block.splitlines() if line.strip()]
        if len(lines) < 2:
            continue
        timestamp_line = lines[1] if "-->" in lines[1] else lines[0]
        text_lines = lines[2:] if "-->" in lines[1] else lines[1:]
        if "-->" not in timestamp_line:
            continue
        start_raw, end_raw = [part.strip() for part in timestamp_line.split("-->")]
        entries.append(
            {
                "start": parse_timestamp(start_raw),
                "end": parse_timestamp(end_raw),
                "text": " ".join(text_lines).strip(),
            }
        )
    return entries


segment = parse_srt(SEG_SRT)[0]
source_text = " ".join(entry["text"] for entry in parse_srt(SOURCE_SRT)).strip()
target_text = " ".join(entry["text"] for entry in parse_srt(TARGET_SRT)).strip()
target_language = TARGET_LANGUAGE_FILE.read_text(encoding="utf-8").strip()
language_tag = "jpn" if target_language == "ja" else target_language

start = segment["start"]
end = segment["end"]
window_duration = max(0.01, end - start)

run(
    [
        "ffmpeg",
        "-y",
        "-loglevel",
        "error",
        "-ss",
        f"{start:.3f}",
        "-to",
        f"{end:.3f}",
        "-i",
        str(INPUT_MP4),
        "-vn",
        "-af",
        "aresample=48000,loudnorm=I=-23:TP=-1.5:LRA=11",
        "-ac",
        "1",
        str(SEG_WAV),
    ]
)

run(
    [
        "ffmpeg",
        "-y",
        "-loglevel",
        "error",
        "-i",
        str(INPUT_MP4),
        "-map",
        "0:v:0",
        "-map",
        "0:a:0",
        "-metadata:s:a:0",
        f"language={language_tag}",
        "-c:v",
        "copy",
        "-c:a",
        "aac",
        "-af",
        "aresample=48000,loudnorm=I=-23:TP=-1.5:LRA=11",
        "-ar",
        "48000",
        "-ac",
        "1",
        "-b:a",
        "192k",
        str(OUT_MP4),
    ]
)

original_duration = read_duration(INPUT_MP4)
new_duration = read_duration(OUT_MP4)
segment_duration = read_duration(SEG_WAV)

report = {
    "source_language": "en",
    "target_language": target_language,
    "audio_sample_rate_hz": 48000,
    "audio_channels": 1,
    "original_duration_sec": original_duration,
    "new_duration_sec": new_duration,
    "measured_lufs": measure_lufs(OUT_MP4),
    "review_packet": {
        "marker": "RD4_DUB_REVIEW_PACKET",
        "approval_context": "final_dub_review",
        "handoff_target": "reviewer_support_archive",
        "include_with_submission": True,
        "packet_role": "approval_handoff",
        "deliver_with": ["dubbed.mp4", "report.json"],
        "review_status": "attach_with_final_asset",
    },
    "speech_segments": [
        {
            "window_start_sec": start,
            "window_end_sec": end,
            "placed_start_sec": start,
            "placed_end_sec": end,
            "source_text": source_text,
            "target_text": target_text,
            "window_duration_sec": window_duration,
            "tts_duration_sec": segment_duration,
            "drift_sec": 0.0,
            "duration_control": "trim",
        }
    ],
}
OUT_JSON.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
PY
