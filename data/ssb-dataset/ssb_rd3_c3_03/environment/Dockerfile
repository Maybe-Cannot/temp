FROM python:3.11-slim-bookworm

WORKDIR /root
COPY test_input.json /root/test_input.json
COPY reply_binding_map.json /root/reply_binding_map.json
COPY skills /root/skills
COPY skills /root/.claude/skills
COPY skills /root/.codex/skills
COPY skills /root/.opencode/skills
COPY skills /root/.goose/skills
COPY skills /root/.factory/skills
COPY skills /root/.agents/skills
COPY skills /root/.gemini/skills

RUN mkdir -p /root/auth && \
    ln -sfn /root/skills/gmail-skill/scripts/auth /root/auth/gmail && \
    ln -sfn /root/skills/google-calendar-skill/scripts/auth /root/auth/calendar
