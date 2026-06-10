FROM python:3.11-slim-bookworm

WORKDIR /root
ENV PYTHONPATH=/root

# Copy data files
COPY DATA /root/DATA

COPY question.txt /root/question.txt
COPY rd4_sitecustomize.py /root/sitecustomize.py

# Copy skills to agent-specific locations
COPY skills /root/.claude/skills
COPY skills /root/.codex/skills
COPY skills /root/.opencode/skills
COPY skills /root/.goose/skills
COPY skills /root/.agents/skills
# Gemini
COPY skills /root/.gemini/skills
COPY skills /root/.factory/skills
