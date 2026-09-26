FROM python:3.12-slim

ENV TZ=Asia/Manila \
    PYTHONUNBUFFERED=1 \
    TFS_DATA_DIR=/data \
    PATH=/root/.local/bin:$PATH

RUN apt-get update \
 && apt-get install -y --no-install-recommends ffmpeg cron tzdata fonts-dejavu-core util-linux curl ca-certificates \
 && rm -rf /var/lib/apt/lists/*

# Claude Code CLI: the agents run through it on the Claude Max subscription (CLAUDE_CODE_OAUTH_TOKEN)
RUN curl -fsSL https://claude.ai/install.sh | bash && claude --version

WORKDIR /app
COPY pyproject.toml ./
COPY src ./src
RUN pip install --no-cache-dir -e .

COPY . .
COPY deploy/crontab /etc/cron.d/tfs
RUN chmod 0644 /etc/cron.d/tfs

# cron runs the jobs; `tail` keeps their output (sent to PID 1's stdout) visible in `docker logs`
CMD ["sh", "-c", "cron && tail -f /dev/null"]
