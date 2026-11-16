"""What IMGAgent does for each command. Each job runs in its own temporary clone of the repository.

The Claude work is done by the scripts in scripts/ (the same code the GitHub Actions versions ran), started
as subprocesses with the environment they expect; this module fetches tokens, clones, and talks to GitHub.
"""

from __future__ import annotations

import json
import logging
import os
import secrets
import subprocess
import sys
import tempfile
import tomllib
from dataclasses import dataclass
from pathlib import Path

from . import github
from .commands import Job

log = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
FOOTER = "\n\n<sub>IMGAgent · {what}. An AI can be wrong.</sub>"


@dataclass
class Config:
    handle: str = "IMGAgent"
    anthropic_api_key: str = ""
    docs_ask_model: str = "claude-haiku-5-5"
    docs_writer_model: str = "claude-opus-5-5"
    docs_writer_effort: str = "medium"
    signoff_model: str = "claude-sonnet-5-5"
    signoff_model_name: str = "Claude Sonnet 5.5 (Anthropic)"
    signoff_effort: str = "medium"

    @classmethod
    def from_env(cls) -> "Config":
        e = os.environ.get
        d = cls()
        return cls(
            handle=e("IMGAGENT_HANDLE") or d.handle,
            anthropic_api_key=e("ANTHROPIC_API_KEY", ""),
            docs_ask_model=e("DOCS_ASK_MODEL") or d.docs_ask_model,
            docs_writer_model=e("DOCS_WRITER_MODEL") or d.docs_writer_model,
            docs_writer_effort=e("DOCS_WRITER_EFFORT") or d.docs_writer_effort,
            signoff_model=e("SIGNOFF_MODEL") or d.signoff_model,
            signoff_model_name=e("SIGNOFF_MODEL_NAME") or d.signoff_model_name,
            signoff_effort=e("SIGNOFF_EFFORT") or d.signoff_effort,
        )


class Context:
    """One webhook delivery: the repository, the issue, and an installation token for that repository."""

    def __init__(self, app: github.App, cfg: Config, event: str, payload: dict):
        self.app, self.cfg, self.event, self.payload = app, cfg, event, payload
        self.repo = payload["repository"]["full_name"]
        self.repo_name = payload["repository"]["name"]
        self.installation = payload["installation"]["id"]
        self.issue = payload.get("issue") or {}
        self.number = self.issue.get("number")
        self.comment = payload.get("comment")
        self.actor = payload["sender"]["login"]
        self.default_branch = payload["repository"]["default_branch"]
        self._token = None

    def token(self, fresh: bool = False) -> str:
        if fresh or self._token is None:
            # Not narrowed to this repository: the signoff scripts also read the organisation's PR template
            # from its .github repository. The installation itself only covers the repositories you chose.
            self._token = self.app.installation_token(self.installation)
        return self._token

    def api(self, method: str, path: str, body: dict | None = None, ok404: bool = False):
        return github.request(method, path, self.token(), body, ok404=ok404)

    def say(self, text: str) -> None:
        self.api("POST", f"/repos/{self.repo}/issues/{self.number}/comments", {"body": text})

    def react(self, content: str = "eyes") -> None:
        if self.comment:
            self.api("POST", f"/repos/{self.repo}/issues/comments/{self.comment['id']}/reactions",
                     {"content": content})

    def can_write(self, login: str) -> bool:
        p = self.api("GET", f"/repos/{self.repo}/collaborators/{login}/permission", ok404=True)
        permission = (p or {}).get("permission", "none")
        ok = permission in ("admin", "maintain", "write")
        log.info("%s has %s permission on %s%s", login, permission, self.repo, "" if ok else ": not answering")
        return ok

    def refuse(self, command: str) -> None:
        """Tell someone without write access why nothing happens (once per command they write)."""
        self.say(f"@{self.actor} `{command}` is only for people with write access to this repository.")


def _run(cmd: list[str], cwd: Path, env: dict, timeout: int) -> subprocess.CompletedProcess:
    """Run a script with only the environment it needs (plus PATH and HOME), and log its output."""
    base = {k: os.environ[k] for k in ("PATH", "HOME", "LANG", "SSL_CERT_FILE") if k in os.environ}
    r = subprocess.run(cmd, cwd=cwd, env={**base, **env}, capture_output=True, text=True, timeout=timeout)
    for line in (r.stdout + r.stderr).splitlines():
        log.info("  | %s", line)
    return r


def _repo_config(clone: Path) -> dict:
    """Optional per-repository settings in .github/imgagent.toml (see README)."""
    path = clone / ".github" / "imgagent.toml"
    try:
        return tomllib.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
    except tomllib.TOMLDecodeError as e:
        log.warning("%s: ignoring .github/imgagent.toml: %s", clone, e)
        return {}


def _docs_env(ctx: Context, clone: Path) -> dict:
    docs = _repo_config(clone).get("docs", {})
    repo = ctx.payload["repository"]
    owner, name = ctx.repo.split("/")
    url = docs.get("url", f"https://{owner.lower()}.github.io/{name}/")
    return {
        "ANTHROPIC_API_KEY": ctx.cfg.anthropic_api_key,
        "REPO_ROOT": str(clone),
        "DOCS_PROJECT": docs.get("project") or name,
        "DOCS_ABOUT": docs.get("about") or repo.get("description") or "",
        "DOCS_AUDIENCE": docs.get("audience", ""),
        "DOCS_URL": "" if url in ("", "none") else url,
        "DOCS_REPO": ctx.repo,
    }


# ------------------------------------------------------------------------------------------- help

def help_text(handle: str) -> str:
    return (f"Commands for @{handle} (people with write access):\n\n"
            f"| Command | What happens |\n|---|---|\n"
            f"| `@{handle} signoff` and your words | records how files were made and reviewed: a `SIGNOFF.toml` pull request |\n"
            f"| `@{handle} docs ask` and a question | answers from the docs in `docs/` |\n"
            f"| `@{handle} docs make [hint]` | rebuilds `docs/` from the code, as a pull request |\n"
            f"| `@{handle} docs update [hint]` | fixes what is outdated in `docs/`, as a pull request |\n"
            f"| `@{handle} help` | this list |")


def do_help(ctx: Context, job: Job) -> None:
    if not ctx.can_write(ctx.actor):
        return   # no reply: "@IMGAgent" in any comment by anyone shouldn't make the bot talk
    lead = f"I don't know `{job.args['unknown']}`. " if job.args.get("unknown") else ""
    ctx.say(f"@{ctx.actor} {lead}{help_text(ctx.cfg.handle)}")


# --------------------------------------------------------------------------------------- docs ask

def do_docs_ask(ctx: Context, job: Job) -> None:
    if not ctx.can_write(ctx.actor):
        return ctx.refuse(f"@{ctx.cfg.handle} docs ask")
    question = job.args.get("question", "").strip()
    if not question:
        ctx.say(f"@{ctx.actor} write your question after `@{ctx.cfg.handle} docs ask`.")
        return
    ctx.react()
    with tempfile.TemporaryDirectory(prefix="imgagent-") as tmp:
        clone = Path(tmp) / "repo"
        github.clone(ctx.repo, ctx.token(), clone, depth=1, sparse=["/docs/", "/.github/imgagent.toml"])
        if not (clone / "docs").is_dir():
            ctx.say(f"@{ctx.actor} this repository has no `docs/` folder to answer from.")
            return
        answer = Path(tmp) / "answer.md"
        env = {**_docs_env(ctx, clone), "QUESTION": question, "ANSWER_FILE": str(answer),
               "DOCS_BOT_MODEL": ctx.cfg.docs_ask_model}
        r = _run([sys.executable, str(SCRIPTS / "docs" / "ask.py")], clone, env, timeout=300)
        if r.returncode or not answer.is_file():
            raise RuntimeError("ask.py failed")
        ctx.say(answer.read_text(encoding="utf-8").strip()
                + FOOTER.format(what=f"answered with {ctx.cfg.docs_ask_model} from the docs in this repository"))


# ------------------------------------------------------------------------------------ docs writer

def _family(model: str) -> str:
    for name in ("opus", "sonnet", "fable"):
        if name in model:
            return name.capitalize()
    return "Other"


def docs_pr_body(actor: str, comment_url: str, command_text: str, summary: str, model: str) -> str:
    """The organisation's PR template, filled in for PR-signoff: G3 and the model, A0; the requester ticks H."""
    fam = _family(model)
    box = lambda f: "x" if fam == f else " "
    return f"""## What does this PR change?

Requested by @{actor} in {comment_url} (`{command_text}`).

{summary.strip()}

Review every page before merging: Claude was told to document only what the code shows, but it can still be wrong.

## AI declaration

<!-- Opened by IMGAgent; the person who asked for it is responsible. -->
Responsible person: @{actor}

Generation (tick exactly one: the highest level of any substantial part):
- [ ] **G0** Written by a human, without AI
- [ ] **G1** AI-assisted: a human wrote it, AI suggested or edited parts
- [ ] **G2** AI-generated: AI wrote substantial parts, a human directed the work and edited the result
- [x] **G3** AI-autonomous: an agent produced it largely end to end

AI models that wrote parts of it (G1-G3, tick all that apply):
- [{box("Fable")}] **Claude Fable** (Anthropic)
- [{box("Opus")}] **Claude Opus** (Anthropic)
- [{box("Sonnet")}] **Claude Sonnet** (Anthropic)
- [ ] **GPT Astra** (OpenAI)
- [ ] **GPT Sol** (OpenAI)
- [ ] **GPT Terra** (OpenAI)
- [{box("Other")}] **Other:** {model if fam == "Other" else ""}

Human review (at least H0 is required; the levels build on each other: tick the highest one you did):
- [ ] **H0** I checked the result as a whole: it does what was asked, runs, and the output is plausible
- [ ] **H1** I ran the tests or reproduced the key results myself, and read the important parts
- [ ] **H2** I read every changed line, understand it, and checked edge cases
- [ ] **H3** I validated it independently: new tests, a reference solution or method, or a second person's review

AI review (only review that is independent of the session that wrote the change; the highest ticked one counts):
- [x] **A0** No independent AI review: none, or only the checks of the session that wrote the change
- [ ] **A1** A new AI session, without the generating conversation, checked the final change and ran the tests. Model, if not one of the above:
- [ ] **A2** A different, capable model did that check and committed one review report. Model and report:
- [ ] **A3** A different, capable model validated it with new evidence (new tests, benchmarks, another method), committed with the report. Model and report:

For A2 and A3, the highest severity the review found in this change itself, as its report says (none, trivial, minor, major or critical; leave it empty for A0 and A1):
AI-Review-Findings:
"""


def do_docs_write(ctx: Context, job: Job) -> None:
    if not ctx.can_write(ctx.actor):
        return ctx.refuse(f"@{ctx.cfg.handle} docs {job.args['command']}")
    command, hint = job.args["command"], job.args.get("hint", "")
    command_text = f"@{ctx.cfg.handle} docs {command}"
    ctx.react()
    model = ctx.cfg.docs_writer_model
    with tempfile.TemporaryDirectory(prefix="imgagent-") as tmp:
        clone = Path(tmp) / "repo"
        github.clone(ctx.repo, ctx.token(), clone, ref=ctx.default_branch)
        summary_file = Path(tmp) / "summary.md"
        env = {**_docs_env(ctx, clone), "DOCS_WRITER_MODEL": model,
               "DOCS_WRITER_EFFORT": ctx.cfg.docs_writer_effort, "SUMMARY_FILE": str(summary_file)}
        r = _run([sys.executable, str(SCRIPTS / "docs" / "write_docs.py"), command, hint], clone, env,
                 timeout=45 * 60)
        if r.returncode or not summary_file.is_file():
            raise RuntimeError("write_docs.py failed")
        summary = summary_file.read_text(encoding="utf-8")

        git = lambda *a: subprocess.run(["git", "-C", str(clone), *a], check=True, capture_output=True,
                                        text=True)
        if not git("status", "--porcelain", "--", "docs", "zensical.toml").stdout.strip():
            ctx.say(f"@{ctx.actor} `docs {command}`: {summary.splitlines()[0] if summary else 'nothing to change.'}")
            return
        slug, bot_id = ctx.app.identity()
        bot = f"{slug}[bot]"
        branch = f"{slug}/docs-{command}-{secrets.token_hex(4)}"
        comment_url = ctx.comment["html_url"]
        git("switch", "-c", branch)
        git("add", "-A", "--", "docs", "zensical.toml")
        git("-c", f"user.name={bot}", "-c", f"user.email={bot_id}+{bot}@users.noreply.github.com",
            "commit", "-q", "-m", f"docs: {command} documentation from the code",
            "-m", f"Written by {model} from the code on {ctx.default_branch}, requested by @{ctx.actor} "
                  f"in {comment_url}")
        github.set_token(clone, ctx.repo, ctx.token(fresh=True))   # the first token may be close to expiry
        git("push", "-q", "origin", branch)

        pr = ctx.api("POST", f"/repos/{ctx.repo}/pulls", {
            "title": f"docs: {command} documentation from the code", "head": branch,
            "base": ctx.default_branch, "body": docs_pr_body(ctx.actor, comment_url, command_text, summary, model)})
        try:
            ctx.api("POST", f"/repos/{ctx.repo}/issues/{pr['number']}/assignees", {"assignees": [ctx.actor]})
        except github.GitHubError as e:
            log.warning("could not assign %s: %s", ctx.actor, e)
        ctx.say(f"@{ctx.actor} `docs {command}` is ready for review: {pr['html_url']}")


# ---------------------------------------------------------------------------------------- signoff

def _actions_env(ctx: Context, tmp: Path, token: str) -> dict:
    """What a GitHub Actions run would give the signoff scripts."""
    event = tmp / "event.json"
    event.write_text(json.dumps(ctx.payload), encoding="utf-8")
    slug, _ = ctx.app.identity()
    return {"GITHUB_EVENT_PATH": str(event), "GITHUB_REPOSITORY": ctx.repo, "GITHUB_TOKEN": token,
            "GITHUB_API_URL": "https://api.github.com", "GITHUB_SERVER_URL": "https://github.com",
            "APP_SLUG": slug}


def _read_outputs(path: Path) -> dict:
    """Parse a GITHUB_OUTPUT file (name=value and name<<EOF ... EOF)."""
    out, lines = {}, path.read_text(encoding="utf-8").splitlines() if path.is_file() else []
    i = 0
    while i < len(lines):
        line = lines[i]
        if "<<" in line and ("=" not in line or line.index("<<") < line.index("=")):
            name, eof = line.split("<<", 1)
            j = lines.index(eof, i + 1)
            out[name] = "\n".join(lines[i + 1:j])
            i = j + 1
        else:
            name, _, value = line.partition("=")
            out[name] = value
            i += 1
    return out


def _signoff_request(ctx: Context, extra: dict) -> None:
    with tempfile.TemporaryDirectory(prefix="imgagent-") as tmp:
        tmp = Path(tmp)
        token = ctx.token(fresh=True)
        clone = tmp / "repo"
        github.clone(ctx.repo, token, clone)
        env = {**_actions_env(ctx, tmp, token), "DISPATCH_WORKFLOWS": "", **extra}
        r = _run([sys.executable, str(SCRIPTS / "signoff" / "request.py")], clone, env, timeout=600)
        if r.returncode:
            raise RuntimeError("request.py failed")


def do_signoff_form(ctx: Context, job: Job) -> None:
    _signoff_request(ctx, {})


def do_signoff(ctx: Context, job: Job) -> None:
    command = f"@{ctx.cfg.handle} signoff"
    with tempfile.TemporaryDirectory(prefix="imgagent-") as tmp:
        tmp = Path(tmp)
        token = ctx.token()
        clone = tmp / "repo"
        github.clone(ctx.repo, token, clone)
        outputs = tmp / "outputs"
        env = {**_actions_env(ctx, tmp, token), "GITHUB_OUTPUT": str(outputs),
               "ANTHROPIC_API_KEY": ctx.cfg.anthropic_api_key, "MODEL": ctx.cfg.signoff_model,
               "MODEL_NAME": ctx.cfg.signoff_model_name, "EFFORT": ctx.cfg.signoff_effort,
               "COMMAND": command, "FALLBACKS": "default"}
        r = _run([sys.executable, str(SCRIPTS / "signoff" / "assistant.py")], clone, env, timeout=600)
        if r.returncode:
            raise RuntimeError("assistant.py failed")
        out = _read_outputs(outputs)
    if out.get("request"):
        _signoff_request(ctx, {"SIGNOFF_REQUEST": out["request"], "SIGNOFF_REQUESTER": out.get("requester", ""),
                               "SIGNOFF_REQUESTER_ID": out.get("requester-id", ""),
                               "SIGNOFF_ASSISTANT": out.get("model-name", ""),
                               "SIGNOFF_ASSISTANT_COMMAND": command})


HANDLERS = {"help": do_help, "docs-ask": do_docs_ask, "docs-write": do_docs_write,
            "signoff": do_signoff, "signoff-form": do_signoff_form}


def run(ctx: Context, job: Job) -> None:
    log.info("%s %s#%s by %s: %s %s", ctx.event, ctx.repo, ctx.number, ctx.actor, job.kind,
             {k: v[:80] for k, v in job.args.items()})
    try:
        HANDLERS[job.kind](ctx, job)
        log.info("%s for %s#%s finished", job.kind, ctx.repo, ctx.number)
    except Exception:
        log.exception("%s failed for %s#%s", job.kind, ctx.repo, ctx.number)
        try:
            ctx.say(f"@{ctx.actor} IMGAgent couldn't finish this (`{job.kind}`). A maintainer can find the "
                    "details in the IMGAgent server log.")
        except Exception:
            log.exception("could not report the failure")
