"""Run with: python -m pytest tests (no network, no GitHub App needed)."""

import hashlib
import hmac
import json
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

from imgagent import commands, jobs, server

C = "IMGAgent"


def comment(body, sender_type="User", pr=False, state="open", issue_body="text"):
    issue = {"number": 7, "state": state, "body": issue_body, "title": "t"}
    if pr:
        issue["pull_request"] = {"url": "x"}
    return {"action": "created", "comment": {"body": body, "id": 1}, "issue": issue,
            "sender": {"login": "pascal", "type": sender_type}}


@pytest.mark.parametrize("body,kind,args", [
    ("@IMGAgent docs ask How do I add a host?", "docs-ask", {"question": "How do I add a host?"}),
    ("@imgagent docs  ASK what?\nmore", "docs-ask", {"question": "what?\nmore"}),
    ("@IMGAgent docs make", "docs-write", {"command": "make", "hint": ""}),
    ("@IMGAgent docs update the slurm add-on gained options\nignored", "docs-write",
     {"command": "update", "hint": "the slurm add-on gained options"}),
    ("@IMGAgent help", "help", {"unknown": ""}),
    ("@IMGAgent", "help", {"unknown": ""}),
    ("@IMGAgent deploy now", "help", {"unknown": "deploy now"}),
    ("@IMGAgent signoff I wrote results/ with Claude", "signoff", {}),
    ("Thanks! @IMGAgent signoff: and I checked it", "signoff", {}),
])
def test_routes_comments(body, kind, args):
    job = commands.route("issue_comment", comment(body), C)
    assert job is not None and job.kind == kind and job.args == args


@pytest.mark.parametrize("payload", [
    comment("@IMGAgent docs make", sender_type="Bot"),          # never bots
    comment("just text"),
    comment("mail me at x@IMGAgent signoff"),                   # part of a word
    comment("`@IMGAgent signoff`"),                             # in code
    comment("@IMGAgent signoff", pr=True),                      # signoff is for issues
    comment("@IMGAgent signoff", state="closed"),
    comment("@IMGAgent signoff", issue_body="### What should be recorded?\n\nDeclare files"),
    comment("@IMGAgentX docs make"),
])
def test_ignores(payload):
    assert commands.route("issue_comment", payload, C) is None


def issue_event(action, title="t", body="b", changes=None):
    p = {"action": action, "issue": {"number": 3, "state": "open", "title": title, "body": body},
         "sender": {"login": "pascal", "type": "User"}}
    if changes is not None:
        p["changes"] = changes
    return p


def test_routes_issues():
    j = commands.route("issues", issue_event("opened", "@IMGAgent docs ask install?", "on arm64"), C)
    assert j.kind == "docs-ask" and j.args["question"] == "install?\n\non arm64"
    assert commands.route("issues", issue_event("opened", body="@IMGAgent signoff I wrote x"), C).kind == "signoff"
    form = "### What should be recorded?\n\nDeclare files"
    assert commands.route("issues", issue_event("opened", body=form), C).kind == "signoff-form"
    assert commands.route("issues", issue_event("edited", body=form, changes={"body": {}}), C).kind == "signoff-form"
    assert commands.route("issues", issue_event("edited", body=form, changes={"title": {}}), C) is None
    assert commands.route("issues", issue_event("opened", body=form), C, signoff_form=False) is None


def test_job_keys():
    assert commands.Job("docs-write").key("o/r", 7) == "o/r#docs-write"
    assert commands.Job("signoff").key("o/r", 7) == "o/r#7"


def test_signature():
    body = b'{"a": 1}'
    sig = "sha256=" + hmac.new(b"s3cret", body, hashlib.sha256).hexdigest()
    assert server.verify(b"s3cret", body, sig)
    assert not server.verify(b"other", body, sig)
    assert not server.verify(b"s3cret", body, None)
    assert not server.verify(b"s3cret", body, "sha1=abc")


def test_read_outputs(tmp_path):
    f = tmp_path / "out"
    f.write_text("a=1\nrequest<<EOF_x\n### Q\n\nanswer\nEOF_x\nrequester<<EOF_y\npascal\nEOF_y\n")
    assert jobs._read_outputs(f) == {"a": "1", "request": "### Q\n\nanswer", "requester": "pascal"}
    assert jobs._read_outputs(tmp_path / "missing") == {}


def test_pr_body_ticks_the_model():
    body = jobs.docs_pr_body("pascal", "https://x", "@IMGAgent docs make", "Rebuilt.", "claude-opus-5-5")
    assert "- [x] **Claude Opus**" in body and "- [ ] **Claude Sonnet**" in body
    assert "Responsible person: @pascal" in body and "- [x] **G3**" in body and "- [x] **A0**" in body


@pytest.fixture
def running(monkeypatch):
    ran = []
    monkeypatch.setattr(jobs, "run", lambda ctx, job: ran.append((ctx.repo, job.kind)))
    d = server.Dispatcher(None, jobs.Config(), {"industrial-mathematics-group"}, 1, True)
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.make_handler(b"s3cret", d))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield httpd.server_address[1], ran, d
    httpd.shutdown()


def post(port, payload, event="issue_comment", secret=b"s3cret", delivery="d1"):
    body = json.dumps(payload).encode()
    req = urllib.request.Request(f"http://127.0.0.1:{port}/webhook", data=body, method="POST", headers={
        "X-GitHub-Event": event, "X-GitHub-Delivery": delivery, "Content-Type": "application/json",
        "X-Hub-Signature-256": "sha256=" + hmac.new(secret, body, hashlib.sha256).hexdigest()})
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, r.read().decode().strip()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode().strip()


def full(payload, owner="industrial-mathematics-group"):
    return {**payload, "installation": {"id": 1},
            "repository": {"full_name": f"{owner}/agent-sandbox", "name": "agent-sandbox",
                           "owner": {"login": owner}, "default_branch": "main"}}


def test_server_end_to_end(running):
    port, ran, d = running
    assert post(port, {"zen": "hi"}, event="ping", delivery="p") == (200, "pong")
    assert post(port, full(comment("@IMGAgent docs make")), secret=b"wrong") == (401, "bad signature")
    assert post(port, full(comment("@IMGAgent docs make")), delivery="a") == (202, "queued docs-write")
    assert post(port, full(comment("@IMGAgent docs make")), delivery="a") == (200, "already handled")
    assert post(port, full(comment("@IMGAgent docs make"), owner="stranger"), delivery="b")[1] == \
        "ignored: owner stranger is not in IMGAGENT_ALLOWED_OWNERS"
    assert post(port, full(comment("hello")), delivery="c") == (202, "ignored: issue_comment.created by pascal: no @IMGAgent in 'hello'")
    d.pool.shutdown(wait=True)
    assert ran == [("industrial-mathematics-group/agent-sandbox", "docs-write")]
    with urllib.request.urlopen(f"http://127.0.0.1:{port}/healthz") as r:
        assert r.read() == b"ok\n"


class FakeApp:
    def installation_token(self, installation, repo=None):
        return "tok"

    def identity(self, token=None):
        return "imgagent", 42


def fake_context(monkeypatch, tmp_path, payload, origin):
    """A Context whose clones come from a local repository and whose API calls are recorded."""
    calls = []
    monkeypatch.setattr(jobs.github, "clone", lambda repo, token, dest, **kw: __import__("subprocess").run(
        ["git", "clone", "-q", str(origin), str(dest)], check=True))
    monkeypatch.setattr(jobs.github, "set_token", lambda *a: None)
    ctx = jobs.Context(FakeApp(), jobs.Config(anthropic_api_key="k"), "issue_comment", full(payload))

    def api(method, path, body=None, ok404=False):
        calls.append((method, path, body))
        if path.endswith("/permission"):
            return {"permission": "write"}
        if path.endswith("/pulls"):
            return {"number": 9, "html_url": "https://github.com/o/r/pull/9"}
        return {}
    monkeypatch.setattr(ctx, "api", api)
    return ctx, calls


def test_docs_write_opens_a_pull_request(monkeypatch, tmp_path):
    import subprocess
    origin = tmp_path / "origin"
    work = tmp_path / "work"
    subprocess.run(["git", "init", "-q", "-b", "main", str(work)], check=True)
    (work / "docs").mkdir()
    (work / "docs" / "index.md").write_text("# Home\n")
    (work / "zensical.toml").write_text('[project]\nnav = [\n  "index.md",\n]\n')
    g = ["git", "-C", str(work), "-c", "user.name=t", "-c", "user.email=t@t"]
    subprocess.run(g + ["add", "-A"], check=True)
    subprocess.run(g + ["commit", "-qm", "init"], check=True)
    subprocess.run(["git", "clone", "-q", "--bare", str(work), str(origin)], check=True)

    scripts = tmp_path / "scripts" / "docs"
    scripts.mkdir(parents=True)
    (scripts / "write_docs.py").write_text(
        "import os, sys, pathlib\n"
        "root = pathlib.Path(os.environ['REPO_ROOT'])\n"
        "(root / 'docs' / 'new.md').write_text('# New\\n')\n"
        "pathlib.Path(os.environ['SUMMARY_FILE']).write_text(f'{sys.argv[1]}: added docs/new.md\\n')\n")
    monkeypatch.setattr(jobs, "SCRIPTS", tmp_path / "scripts")

    payload = comment("@IMGAgent docs make")
    payload["comment"]["html_url"] = "https://github.com/o/r/issues/7#c1"
    ctx, calls = fake_context(monkeypatch, tmp_path, payload, origin)
    jobs.do_docs_write(ctx, commands.Job("docs-write", {"command": "make", "hint": ""}))

    branches = subprocess.run(["git", "-C", str(origin), "branch", "--list", "imgagent/*"],
                              capture_output=True, text=True).stdout.split()
    assert len(branches) == 1 and branches[0].startswith("imgagent/docs-make-")
    author = subprocess.run(["git", "-C", str(origin), "log", "-1", "--format=%an <%ae>", branches[0]],
                            capture_output=True, text=True).stdout.strip()
    assert author == "imgagent[bot] <42+imgagent[bot]@users.noreply.github.com>"
    pr = next(b for m, p, b in calls if p.endswith("/pulls"))
    assert pr["head"] == branches[0] and pr["base"] == "main" and "make: added docs/new.md" in pr["body"]
    assert calls[-1][2]["body"].endswith("is ready for review: https://github.com/o/r/pull/9")


def test_describe_says_why_nothing_happened():
    d = server.describe
    assert "no @IMGAgent" in d("issue_comment", comment("thanks"), C)
    assert "found but no command" in d("issue_comment", comment("ping @IMGAgent docs make"), C)
    assert "sent by the bot" in d("issue_comment", {**comment("x"), "sender": {"login": "b[bot]", "type": "Bot"}}, C)
    assert "doesn't use push" in d("push", {"sender": {"login": "p", "type": "User"}}, C)


def test_identity_never_sends_the_jwt_to_users(monkeypatch):
    from imgagent import github
    seen = []

    def fake(method, path, token, body=None, **kw):
        seen.append((path, token))
        return {"slug": "img-agent"} if path == "/app" else {"id": 7}
    monkeypatch.setattr(github, "request", fake)
    app = github.App("1", "key")
    monkeypatch.setattr(app, "jwt", lambda: "JWT")
    assert app.identity("INST") == ("img-agent", 7)
    assert seen == [("/app", "JWT"), ("/users/img-agent%5Bbot%5D", "INST")]
    assert app.identity() == ("img-agent", 7) and len(seen) == 2   # cached
