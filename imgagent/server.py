"""IMGAgent's webhook server: verifies GitHub's signature, answers within GitHub's 10 seconds, and runs the
job in the background.

    POST /webhook   GitHub App webhook (events: issues, issue_comment)
    GET  /healthz   "ok", for the container health check
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import sys
import threading
from collections import OrderedDict, defaultdict
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from . import commands, github, jobs

log = logging.getLogger("imgagent")

MAX_BODY = 25 * 1024 * 1024   # GitHub caps webhook payloads at 25 MB


def verify(secret: bytes, body: bytes, signature: str | None) -> bool:
    """X-Hub-Signature-256: sha256=<hex HMAC of the raw body with the webhook secret>."""
    if not signature or not signature.startswith("sha256="):
        return False
    expected = "sha256=" + hmac.new(secret, body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


class Dispatcher:
    """Routes events to jobs and runs them on a small pool; jobs with the same key run in order."""

    def __init__(self, app: github.App | None, cfg: jobs.Config, allowed_owners: set[str], workers: int,
                 signoff_form: bool):
        self.app, self.cfg, self.allowed, self.signoff_form = app, cfg, allowed_owners, signoff_form
        self.pool = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="job")
        self.locks: dict[str, threading.Lock] = defaultdict(threading.Lock)
        self.seen: OrderedDict[str, None] = OrderedDict()   # delivery ids, against redeliveries
        self.guard = threading.Lock()

    def accept(self, event: str, delivery: str, payload: dict) -> tuple[int, str]:
        with self.guard:
            if delivery and delivery in self.seen:
                return 200, "already handled"
            self.seen[delivery] = None
            while len(self.seen) > 1000:
                self.seen.popitem(last=False)
        if event == "ping":
            return 200, "pong"
        owner = ((payload.get("repository") or {}).get("owner") or {}).get("login", "")
        if "installation" not in payload or not owner:
            return 202, "ignored: no repository or installation"
        if "*" not in self.allowed and owner.lower() not in self.allowed:
            log.warning("ignoring %s from %s: not in IMGAGENT_ALLOWED_OWNERS", event, owner)
            return 202, "ignored: owner not allowed"
        job = commands.route(event, payload, self.cfg.handle, self.signoff_form)
        if job is None:
            return 202, "ignored"
        ctx = jobs.Context(self.app, self.cfg, event, payload)
        key = job.key(ctx.repo, ctx.number)

        def work():
            with self.locks[key]:
                jobs.run(ctx, job)

        self.pool.submit(work)
        return 202, f"queued {job.kind}"


def make_handler(secret: bytes, dispatcher: Dispatcher):
    class Handler(BaseHTTPRequestHandler):
        server_version = "IMGAgent"

        def reply(self, status: int, text: str):
            data = (text + "\n").encode()
            self.send_response(status)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            self.reply(200, "ok") if self.path in ("/healthz", "/") else self.reply(404, "not found")

        def do_POST(self):
            if self.path.rstrip("/") not in ("/webhook", ""):
                return self.reply(404, "not found")
            length = int(self.headers.get("Content-Length") or 0)
            if length <= 0 or length > MAX_BODY:
                return self.reply(400, "bad length")
            body = self.rfile.read(length)
            if not verify(secret, body, self.headers.get("X-Hub-Signature-256")):
                log.warning("rejected a delivery with a bad signature from %s", self.client_address[0])
                return self.reply(401, "bad signature")
            try:
                payload = json.loads(body)
            except ValueError:
                return self.reply(400, "bad json")
            event = self.headers.get("X-GitHub-Event", "")
            delivery = self.headers.get("X-GitHub-Delivery", "")
            status, text = dispatcher.accept(event, delivery, payload)
            log.info("delivery %s %s.%s: %s", delivery, event, payload.get("action", ""), text)
            self.reply(status, text)

        def log_message(self, fmt, *args):   # the dispatcher logs what matters
            pass

    return Handler


def private_key() -> str:
    path = os.environ.get("IMGAGENT_PRIVATE_KEY_FILE")
    if path and Path(path).is_file():
        return Path(path).read_text(encoding="utf-8")
    key = os.environ.get("IMGAGENT_PRIVATE_KEY", "")
    return key.replace("\\n", "\n")   # one line in .env, with \n for the line breaks


def main() -> None:
    logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"), stream=sys.stdout,
                        format="%(asctime)s %(levelname)s %(threadName)s %(message)s")
    missing = [n for n in ("IMGAGENT_APP_ID", "IMGAGENT_WEBHOOK_SECRET", "IMGAGENT_ALLOWED_OWNERS",
                           "ANTHROPIC_API_KEY") if not os.environ.get(n)]
    key = private_key()
    if "PRIVATE KEY" not in key:
        missing.append("IMGAGENT_PRIVATE_KEY_FILE (or IMGAGENT_PRIVATE_KEY)")
    if missing:
        sys.exit("IMGAgent: missing settings: " + ", ".join(missing) + " (see .env.example)")

    cfg = jobs.Config.from_env()
    app = github.App(os.environ["IMGAGENT_APP_ID"], key)
    try:
        slug, _ = app.identity()
        log.info("signed in as the GitHub App %s; answering @%s", slug, cfg.handle)
    except Exception as e:   # keep running: GitHub may be briefly unreachable
        log.error("could not reach GitHub as the app (check IMGAGENT_APP_ID and the private key): %s", e)
    allowed = {o.strip().lower() for o in os.environ["IMGAGENT_ALLOWED_OWNERS"].split(",") if o.strip()}
    dispatcher = Dispatcher(app, cfg, allowed, int(os.environ.get("IMGAGENT_WORKERS", "2")),
                            os.environ.get("IMGAGENT_SIGNOFF_FORM", "true").lower() in ("1", "true", "yes"))
    port = int(os.environ.get("PORT", "8080"))
    server = ThreadingHTTPServer(("0.0.0.0", port), make_handler(os.environ["IMGAGENT_WEBHOOK_SECRET"].encode(),
                                                                 dispatcher))
    log.info("listening on :%d (allowed owners: %s)", port, ", ".join(sorted(allowed)))
    server.serve_forever()


if __name__ == "__main__":
    main()
