FROM ubuntu:24.04

# Install or copy over any environment dependencies here.


RUN apt-get update && apt-get install -y python3 python3-pip


WORKDIR /root

# Copy data files
COPY DATA /root/DATA
COPY DATA /app/DATA

COPY question.txt /root/question.txt
COPY question.txt /app/question.txt

# Copy skills to agent-specific locations
COPY skills /root/.claude/skills
COPY skills /root/.codex/skills
COPY skills /root/.opencode/skills
COPY skills /root/.goose/skills
COPY skills /root/.agents/skills
# Gemini
COPY skills /root/.gemini/skills
COPY rd2_session_recovery_bundle.json /root/rd2_session_recovery_bundle.json
COPY rd2_session_recovery_bundle.json /app/rd2_session_recovery_bundle.json
COPY skills /root/.factory/skills

# Fail the build early if the expected retrieval inputs were not copied into the image.
RUN test -d /root/DATA \
 && test -f /root/question.txt \
 && test -d /app/DATA \
 && test -f /app/question.txt

