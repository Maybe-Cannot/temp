FROM python:3.11-slim-bookworm

ENV DEBIAN_FRONTEND=noninteractive

WORKDIR /root

COPY input.mp4 /root/input.mp4
COPY rd4_support_trace_note.md /root/rd4_support_trace_note.md
COPY reference.rttm /root/reference.rttm
COPY reference_transcript.txt /root/reference_transcript.txt

COPY skills /root/.claude/skills
COPY skills /root/.codex/skills
COPY skills /root/.opencode/skill
COPY skills /root/.goose/skills
COPY skills /root/.factory/skills
COPY skills /root/.agents/skills
COPY skills /root/.gemini/skills
