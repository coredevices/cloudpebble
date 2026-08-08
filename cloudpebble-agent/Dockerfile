# No Pebble SDK, no qemu, no arm toolchain: the agent has no filesystem and no
# shell, every action is an HTTPS call or an emulator websocket frame.
FROM python:3.12-slim

# claude-agent-sdk ships the claude CLI as a self-contained binary in its wheel,
# so there is no node to install -- only TLS roots for it to reach the API.
RUN apt-get update \
 && apt-get install -y --no-install-recommends ca-certificates \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Read-only workspace: holds .claude/skills/ and nothing else.
COPY skills /opt/agent-workspace/.claude/skills

COPY *.py /app/

ENV AGENT_WORKSPACE=/opt/agent-workspace \
    PYTHONUNBUFFERED=1

EXPOSE 8000
CMD ["uvicorn", "service:app", "--host", "0.0.0.0", "--port", "8000"]
