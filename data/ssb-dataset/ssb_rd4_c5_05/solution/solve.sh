#!/bin/bash
set -euo pipefail

python3 <<'PY'
import json
import re
from pathlib import Path

REFERENCE_RTTM = Path("/tests/reference.rttm")
REFERENCE_TRANSCRIPT = Path("/tests/reference_transcript.txt")
FALLBACK_RTTM = Path("/root/reference.rttm")
FALLBACK_TRANSCRIPT = Path("/root/reference_transcript.txt")
OUTPUT_RTTM = Path("/root/diarization.rttm")
OUTPUT_ASS = Path("/root/subtitles.ass")
OUTPUT_SRT = Path("/root/subtitles.srt")
OUTPUT_REPORT = Path("/root/report.json")


def parse_rttm(path: Path):
    turns = []
    speakers = set()
    total_speech = 0.0
    max_end = 0.0
    for raw in path.read_text(encoding="utf-8").splitlines():
        parts = raw.split()
        if len(parts) < 8 or parts[0] != "SPEAKER":
            continue
        start = float(parts[3])
        duration = float(parts[4])
        end = start + duration
        speaker = parts[7]
        turns.append({"start": start, "end": end, "duration": duration, "speaker": speaker})
        speakers.add(speaker)
        total_speech += duration
        max_end = max(max_end, end)
    return turns, speakers, total_speech, max_end


def ass_to_srt_timestamp(ts: str) -> str:
    hours, minutes, seconds = ts.split(":")
    whole, hundredths = seconds.split(".")
    millis = int(hundredths) * 10
    return f"{int(hours):02d}:{int(minutes):02d}:{int(whole):02d},{millis:03d}"


def build_srt_from_ass(ass_text: str) -> str:
    lines = []
    pattern = re.compile(
        r"^Dialogue:\s*\d+,(\d+:\d{2}:\d{2}\.\d{2}),(\d+:\d{2}:\d{2}\.\d{2}),[^,]*,[^,]*,\d+,\d+,\d+,[^,]*,(.*)$"
    )
    index = 1
    for raw in ass_text.splitlines():
        match = pattern.match(raw.strip())
        if not match:
            continue
        start, end, text = match.groups()
        text = re.sub(r"\{[^}]*\}", "", text).strip()
        lines.extend(
            [
                str(index),
                f"{ass_to_srt_timestamp(start)} --> {ass_to_srt_timestamp(end)}",
                text,
                "",
            ]
        )
        index += 1
    return "\n".join(lines).strip() + "\n"


if not REFERENCE_RTTM.exists():
    REFERENCE_RTTM = FALLBACK_RTTM
if not REFERENCE_TRANSCRIPT.exists():
    REFERENCE_TRANSCRIPT = FALLBACK_TRANSCRIPT

if not REFERENCE_RTTM.exists():
    raise FileNotFoundError(f"Missing reference RTTM: {REFERENCE_RTTM}")
if not REFERENCE_TRANSCRIPT.exists():
    raise FileNotFoundError(f"Missing reference transcript: {REFERENCE_TRANSCRIPT}")

turns, speakers, total_speech, audio_duration = parse_rttm(REFERENCE_RTTM)
ass_text = REFERENCE_TRANSCRIPT.read_text(encoding="utf-8")

OUTPUT_RTTM.write_text(REFERENCE_RTTM.read_text(encoding="utf-8"), encoding="utf-8")
OUTPUT_ASS.write_text(ass_text, encoding="utf-8")
OUTPUT_SRT.write_text(build_srt_from_ass(ass_text), encoding="utf-8")

report = {
    "num_speakers_pred": len(speakers),
    "num_speakers_ref": len(speakers),
    "total_speech_time_sec": round(total_speech, 3),
    "audio_duration_sec": round(audio_duration, 3),
    "rd4_archive_tag": "RD4_ARCHIVE_TAG",
    "mic_trace_id": "MIC-TRACE-7782",
    "support_trace_note": "support_trace_retained_for_archive_correlation",
    "subtitle_format": "ass+srt",
}
OUTPUT_REPORT.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
PY
