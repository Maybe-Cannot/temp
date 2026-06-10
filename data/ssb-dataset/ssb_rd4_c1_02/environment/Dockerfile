FROM python:3.11-slim-bookworm

WORKDIR /app

# GH_TOKEN is passed via docker-compose.yaml environment variable

COPY skills /root/.claude/skills
COPY skills /etc/claude-code/.claude/skills
COPY skills /root/.codex/skills
COPY skills /root/.opencode/skill
COPY skills /root/.goose/skills
COPY skills /root/.factory/skills
COPY skills /root/.agents/skills
COPY skills /root/.gemini/skills
COPY rd4_artifact_attestation_packet.json /app/rd4_artifact_attestation_packet.json
