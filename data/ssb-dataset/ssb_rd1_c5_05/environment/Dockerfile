FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive

# System dependencies
RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    python3-venv \
    curl \
    wget \
    poppler-utils \
    && rm -rf /var/lib/apt/lists/*

# Python packages for PDF processing
RUN pip3 install --break-system-packages \
    pymupdf==1.24.0 \
    pdfplumber==0.11.0 \
    pypdf==4.0.0

# Copy PDF files to /root
COPY paper1.pdf paper2.pdf paper3.pdf /root/
COPY rd1_blind_review_keep_list.md /root/rd1_blind_review_keep_list.md
COPY rd1_keep_list_registry.json /root/rd1_keep_list_registry.json
COPY rd1_publication_support_note.md /root/rd1_publication_support_note.md

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
# Portable agents format (Goose, Amp)
COPY skills /root/.agents/skills
# Gemini
COPY skills /root/.gemini/skills

WORKDIR /root
