FROM python:3.11-slim-bookworm

WORKDIR /root

# Copy the input file to /root/
COPY input.pptx /root/input.pptx
COPY rd4_exceltable_review_packet.md /root/rd4_exceltable_review_packet.md

# Copy skills to ALL agent paths (commented out for agent runs without skills)
COPY skills /root/.claude/skills
COPY skills /root/.codex/skills
COPY skills /root/.opencode/skill
COPY skills /root/.goose/skills
COPY skills /root/.factory/skills
COPY skills /root/.agents/skills
COPY skills /root/.gemini/skills


# Install Python dependencies for pptx and xlsx skills.
# The solver refreshes cached formula values directly when LibreOffice is unavailable.
RUN python3 -m pip install --no-cache-dir \
    python-pptx==1.0.2 \
    pillow==11.1.0 \
    defusedxml==0.7.1 \
    openpyxl==3.1.5 \
    pandas==2.2.3
