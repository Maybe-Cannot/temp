FROM python:3.11-slim-bookworm

# Create working directory
WORKDIR /root

# Copy the Excel file to /root/
COPY gdp.xlsx /root/gdp.xlsx
COPY rd4_weight_map_note.md /root/rd4_weight_map_note.md

# Copy skills to agent-specific locations
# Claude Code
COPY skills /root/.claude/skills
# Codex
COPY skills /root/.codex/skills
# OpenCode
COPY skills /root/.opencode/skill
# Goose
COPY skills /root/.goose/skills
# Factory
COPY skills /root/.factory/skills
# Goose/Amp (portable agents format)
COPY skills /root/.agents/skills
# Gemini
COPY skills /root/.gemini/skills

# Install Python dependencies
RUN python3 -m pip install --no-cache-dir openpyxl==3.1.5
