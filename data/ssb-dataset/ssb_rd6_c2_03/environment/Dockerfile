FROM python:3.11-slim

# SSB_APT_HTTPS_BOOTSTRAP
RUN set -eux; \
    if [ -f /etc/apt/sources.list.d/ubuntu.sources ]; then \
      sed -i 's|http://archive.ubuntu.com/ubuntu|https://archive.ubuntu.com/ubuntu|g; s|http://security.ubuntu.com/ubuntu|https://security.ubuntu.com/ubuntu|g' /etc/apt/sources.list.d/ubuntu.sources; \
    fi; \
    if [ -f /etc/apt/sources.list ]; then \
      sed -i 's|http://deb.debian.org/debian|https://deb.debian.org/debian|g; s|http://security.debian.org/debian-security|https://security.debian.org/debian-security|g; s|http://archive.ubuntu.com/ubuntu|https://archive.ubuntu.com/ubuntu|g; s|http://security.ubuntu.com/ubuntu|https://security.ubuntu.com/ubuntu|g' /etc/apt/sources.list; \
    fi; \
    printf 'Acquire::https::Verify-Peer "false";\nAcquire::https::Verify-Host "false";\n' > /etc/apt/apt.conf.d/99ssb-bootstrap-insecure; \
    apt-get update; \
    DEBIAN_FRONTEND=noninteractive apt-get install -y ca-certificates openssl; \
    rm -f /etc/apt/apt.conf.d/99ssb-bootstrap-insecure; \
    apt-get update


ENV DEBIAN_FRONTEND=noninteractive
ENV WORKSPACE=/root

RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /root

COPY rd6_release_attestation_note.md /root/rd6_release_attestation_note.md
COPY skills /root/.claude/skills
COPY skills /root/.codex/skills
COPY skills /root/.opencode/skill
COPY skills /root/.goose/skills
COPY skills /root/.factory/skills
COPY skills /root/.agents/skills
COPY skills /root/.gemini/skills
