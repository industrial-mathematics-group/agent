"""GitHub App authentication and a small REST client (standard library + PyJWT)."""

from __future__ import annotations

import json
import logging
import subprocess
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

import jwt

log = logging.getLogger(__name__)

API = "https://api.github.com"


class GitHubError(RuntimeError):
    def __init__(self, status: int, message: str):
        super().__init__(f"GitHub API {status}: {message}")
        self.status = status


def request(method: str, path: str, token: str, body: dict | None = None, *, auth: str = "Bearer",
            ok404: bool = False):
    url = path if path.startswith("http") else API + path
    req = urllib.request.Request(url, method=method,
                                 data=json.dumps(body).encode() if body is not None else None)
    req.add_header("Authorization", f"{auth} {token}")
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("X-GitHub-Api-Version", "2022-11-28")
    req.add_header("User-Agent", "IMGAgent")
    if body is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            data = r.read()
            return json.loads(data) if data else None
    except urllib.error.HTTPError as e:
        if ok404 and e.code == 404:
            return None
        raise GitHubError(e.code, f"{method} {path}: {e.read().decode(errors='replace')[:500]}") from None


class App:
    """The GitHub App: signs JWTs and hands out installation tokens."""

    def __init__(self, app_id: str, private_key: str):
        self.app_id = str(app_id)
        self.private_key = private_key
        self._lock = threading.Lock()
        self._slug: str | None = None
        self._bot_id: int | None = None

    def jwt(self) -> str:
        now = int(time.time())
        # iat 60 s in the past against clock drift; GitHub allows at most 10 minutes of validity.
        return jwt.encode({"iat": now - 60, "exp": now + 540, "iss": self.app_id},
                          self.private_key, algorithm="RS256")

    def installation_token(self, installation_id: int, repository: str | None = None) -> str:
        """A token for one installation, limited to one repository (name without owner) if given."""
        body = {"repositories": [repository]} if repository else {}
        r = request("POST", f"/app/installations/{installation_id}/access_tokens", self.jwt(), body)
        return r["token"]

    def identity(self) -> tuple[str, int]:
        """The app's slug and the numeric id of its bot user, for commits as <slug>[bot]."""
        with self._lock:
            if self._slug is None:
                self._slug = request("GET", "/app", self.jwt())["slug"]
                self._bot_id = request("GET", f"/users/{self._slug}%5Bbot%5D", self.jwt())["id"]
            return self._slug, self._bot_id


def clone(repo: str, token: str, dest: Path, *, ref: str | None = None, depth: int | None = None,
          sparse: list[str] | None = None) -> None:
    """Clone github.com/<repo> into dest; origin keeps the token so the scripts can push."""
    url = f"https://x-access-token:{token}@github.com/{repo}.git"
    cmd = ["git", "clone", "-q"]
    if ref:
        cmd += ["--branch", ref]
    if depth:
        cmd += ["--depth", str(depth)]
    if sparse is not None:
        cmd += ["--filter=blob:none", "--sparse"]
    subprocess.run(cmd + [url, str(dest)], check=True, capture_output=True, text=True)
    if sparse:
        subprocess.run(["git", "-C", str(dest), "sparse-checkout", "set", "--no-cone", *sparse],
                       check=True, capture_output=True, text=True)


def set_token(dest: Path, repo: str, token: str) -> None:
    """Swap a fresh token into origin (installation tokens last an hour; the docs writer can take long)."""
    subprocess.run(["git", "-C", str(dest), "remote", "set-url", "origin",
                    f"https://x-access-token:{token}@github.com/{repo}.git"], check=True)
