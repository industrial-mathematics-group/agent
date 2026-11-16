FROM python:3.13-slim

# git for the clones; tini reaps the git and script subprocesses and forwards signals
RUN apt-get update \
 && apt-get install -y --no-install-recommends git tini ca-certificates \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY imgagent/ imgagent/
COPY scripts/ scripts/
COPY entrypoint.sh /entrypoint.sh

# run as an unprivileged user; clones go to /tmp inside the container
RUN useradd --create-home --uid 10001 imgagent && chmod +x /entrypoint.sh
USER imgagent
ENV PYTHONUNBUFFERED=1 PORT=8080 GIT_TERMINAL_PROMPT=0
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s CMD python -c "import urllib.request,os; urllib.request.urlopen(f'http://127.0.0.1:{os.environ.get(\"PORT\",\"8080\")}/healthz', timeout=4)"
ENTRYPOINT ["/usr/bin/tini", "--", "/entrypoint.sh"]
