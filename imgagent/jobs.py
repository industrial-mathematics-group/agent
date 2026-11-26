"""What IMGAgent does for each command. Each job runs in its own temporary clone of the repository.

The Claude work is done by the scripts in scripts/ (the same code the GitHub Actions versions ran), started
as subprocesses with the environment they expect; this module fetches tokens, clones, and talks to GitHub.
"""

from __future__ import annotations

import json
import logging
import os
import re
import secrets
import subprocess
import sys
import tempfile
import tomllib
from dataclasses import dataclass
from pathlib import Path

from . import github, setup
from .commands import Job

log = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
FOOTER = "\n\n<sub>IMGAgent · {what}. An AI can be wrong.</sub>"


@dataclass
class Config:
    handle: str = "IMGAgent"
    anthropic_api_key: str = ""
    ask_model: str = "claude-haiku-5-5"
    writer_model: str = "claude-opus-5-5"
    writer_effort: str = "medium"
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
            # The DOCS_* names are the old ones, from when every command was about docs/.
            ask_model=e("ASK_MODEL") or e("DOCS_ASK_MODEL") or d.ask_model,
            writer_model=e("WRITER_MODEL") or e("DOCS_WRITER_MODEL") or d.writer_model,
            writer_effort=e("WRITER_EFFORT") or e("DOCS_WRITER_EFFORT") or d.writer_effort,
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

    def answered(self) -> bool:
        """Has IMGAgent commented on this issue already (the first 100 comments)?"""
        slug, _ = self.app.identity(self.token())
        comments = self.api("GET", f"/repos/{self.repo}/issues/{self.number}/comments?per_page=100") or []
        return any((c.get("user") or {}).get("login") == f"{slug}[bot]" for c in comments)

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
    return (f"Commands for @{handle} (people with write access), as `@{handle} <action> <folders> [with <folders>]` "
            f"and then the question, task or hint, on the same line or below. Folders are comma-separated "
            f"(`docs,src`); the ones after `with` are only read.\n\n"
            f"| Command | What happens |\n|---|---|\n"
            f"| `@{handle} ask docs,src` and a question | answers from the files in those folders |\n"
            f"| `@{handle} update docs with src` and a task | edits existing files in `docs` and at the top level (no new files), reading `src`, as a pull request |\n"
            f"| `@{handle} make docs [with src]` and a hint | rebuilds `docs/` from the code (or only from `src`), as a pull request |\n"
            f"| `@{handle} setup reuse` and `path:`, `copyright:`, `license:` lines | creates `REUSE.toml`, as a pull request (no AI) |\n"
            f"| `@{handle} setup aisignoff` [and `G2 H1 A0`, `reviewed-by:` ...] | creates `SIGNOFF.toml` with `aisignoff init`, as a pull request (no AI) |\n"
            f"| `@{handle} setup docs` [and `name:`, `description:`, `url:` lines] | creates `zensical.toml` for the pages in `docs/`, as a pull request (no AI) |\n"
            f"| `@{handle} signoff` and your words | records how files were made and reviewed: a `SIGNOFF.toml` pull request |\n"
            f"| `@{handle} help` | this list |")


def do_help(ctx: Context, job: Job) -> None:
    if not ctx.can_write(ctx.actor):
        return   # no reply: "@IMGAgent" in any comment by anyone shouldn't make the bot talk
    lead = f"{job.args['problem']}\n\n" if job.args.get("problem") else ""
    ctx.say(f"@{ctx.actor} {lead}{help_text(ctx.cfg.handle)}")


def missing(clone: Path, paths: list[str]) -> list[str]:
    """The paths that don't exist in the clone or lead outside it."""
    return [p for p in paths if find_target(clone, p) is None]


def find_target(clone: Path, target: str) -> Path | None:
    """The target inside the clone, or None when it doesn't exist or points outside it (a symlink)."""
    root = clone.resolve()
    path = (clone / target)
    if not path.exists() or not path.resolve().is_relative_to(root):
        return None
    return path


def in_scope(rel: str, targets: list[str]) -> bool:
    """May `update <targets>` change this file: under a target or at the top level, never a workflow."""
    if rel.startswith(".github/workflows/"):
        return False
    return "/" not in rel or any(rel == t or rel.startswith(t + "/") for t in targets)


def spec(job: Job) -> str:
    """"docs,src with tests" for messages."""
    text = ",".join(job.args["targets"])
    return text + (f" with {','.join(job.args['context'])}" if job.args.get("context") else "")


def no_such(ctx: Context, gone: list[str], usage: str) -> None:
    names = ", ".join(f"`{p}`" for p in gone)
    ctx.say(f"@{ctx.actor} there is no {names} in this repository. Write `@{ctx.cfg.handle} {usage}`.")


# -------------------------------------------------------------------------------------------- ask

def do_ask(ctx: Context, job: Job) -> None:
    paths = job.args["targets"] + job.args.get("context", [])
    command = f"@{ctx.cfg.handle} ask {spec(job)}"
    if not ctx.can_write(ctx.actor):
        return ctx.refuse(command)
    question = job.args.get("question", "").strip()
    if not question:
        ctx.say(f"@{ctx.actor} write your question after `{command}`.")
        return
    ctx.react()
    with tempfile.TemporaryDirectory(prefix="imgagent-") as tmp:
        clone = Path(tmp) / "repo"
        github.clone(ctx.repo, ctx.token(), clone, depth=1,
                     sparse=[f"/{p}" for p in paths] + ["/.github/imgagent.toml"])
        if gone := missing(clone, paths):
            return no_such(ctx, gone, "ask <folders>` and your question, e.g. `ask docs,src")
        answer = Path(tmp) / "answer.md"
        env = {**_docs_env(ctx, clone), "TARGETS": ",".join(paths), "QUESTION": question, "ANSWER_FILE": str(answer),
               "ASK_MODEL": ctx.cfg.ask_model}
        r = _run([sys.executable, str(SCRIPTS / "repo" / "ask.py")], clone, env, timeout=300)
        if r.returncode or not answer.is_file():
            raise RuntimeError("ask.py failed")
        ctx.say(answer.read_text(encoding="utf-8").strip()
                + FOOTER.format(what=f"answered with {ctx.cfg.ask_model} from {', '.join(f'`{p}`' for p in paths)} in this repository"))


# ------------------------------------------------------------------------------ make and update

def _family(model: str) -> str:
    for name in ("opus", "sonnet", "fable"):
        if name in model:
            return name.capitalize()
    return "Other"


def pr_body(actor: str, comment_url: str, command_text: str, summary: str, model: str | None, review: str) -> str:
    """The organisation's PR template, filled in for PR-signoff: G3 and the model (G0 without one), A0;
    the requester ticks H."""
    fam = _family(model) if model else ""
    box = lambda f: "x" if fam == f else " "
    g = lambda level: "x" if (level == "G3") == bool(model) else " "
    return f"""## What does this PR change?

Requested by @{actor} in {comment_url} (`{command_text}`).

{summary.strip()}

{review}

## AI declaration

<!-- Opened by IMGAgent; the person who asked for it is responsible. -->
Responsible person: @{actor}

Generation (tick exactly one: the highest level of any substantial part):
- [{g("G0")}] **G0** Written by a human, without AI
- [ ] **G1** AI-assisted: a human wrote it, AI suggested or edited parts
- [ ] **G2** AI-generated: AI wrote substantial parts, a human directed the work and edited the result
- [{g("G3")}] **G3** AI-autonomous: an agent produced it largely end to end

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


def _run_writer(ctx: Context, clone: Path, tmp: Path, script: Path, args: list[str], extra: dict) -> str:
    """Run a script that edits the clone and writes a summary; return the summary."""
    summary_file = tmp / "summary.md"
    env = {**_docs_env(ctx, clone), "WRITER_MODEL": ctx.cfg.writer_model, "WRITER_EFFORT": ctx.cfg.writer_effort,
           "SUMMARY_FILE": str(summary_file), **extra}
    r = _run([sys.executable, str(script), *args], clone, env, timeout=45 * 60)
    if r.returncode or not summary_file.is_file():
        raise RuntimeError(f"{script.name} failed")
    return summary_file.read_text(encoding="utf-8")


def _open_pr(ctx: Context, clone: Path, paths: list[str], *, slug: str, bot_id: int, branch: str, title: str,
             command_text: str, summary: str, review: str, ai: bool = True) -> None:
    """Commit `paths` on a new branch, push it, open the pull request and assign the requester.
    ai=False: IMGAgent wrote the files from the person's own settings, without a model (G0)."""
    git = lambda *a: subprocess.run(["git", "-C", str(clone), *a], check=True, capture_output=True, text=True)
    model = ctx.cfg.writer_model if ai else None
    bot = f"{slug}[bot]"
    comment_url = (ctx.comment or ctx.issue)["html_url"]   # a command in a new issue has no comment
    git("switch", "-c", branch)
    git("add", "-A", "--", *paths)
    git("-c", f"user.name={bot}", "-c", f"user.email={bot_id}+{bot}@users.noreply.github.com",
        "commit", "-q", "-m", title,
        "-m", f"Written by {model or 'IMGAgent from the settings in the request, without AI'} on "
              f"{ctx.default_branch}, requested by @{ctx.actor} in {comment_url}")
    github.set_token(clone, ctx.repo, ctx.token(fresh=True))   # the first token may be close to expiry
    git("push", "-q", "origin", branch)

    pr = ctx.api("POST", f"/repos/{ctx.repo}/pulls", {
        "title": title, "head": branch, "base": ctx.default_branch,
        "body": pr_body(ctx.actor, comment_url, command_text, summary, model, review)})
    try:
        ctx.api("POST", f"/repos/{ctx.repo}/issues/{pr['number']}/assignees", {"assignees": [ctx.actor]})
    except github.GitHubError as e:
        log.warning("could not assign %s: %s", ctx.actor, e)
    ctx.say(f"@{ctx.actor} `{command_text.split(' ', 1)[1]}` is ready for review: {pr['html_url']}")


def _first_line(summary: str, fallback: str) -> str:
    return summary.strip().splitlines()[0] if summary.strip() else fallback


def do_make(ctx: Context, job: Job) -> None:
    hint, context = job.args.get("hint", ""), job.args.get("context", [])
    command_text = f"@{ctx.cfg.handle} make {spec(job)}"
    if not ctx.can_write(ctx.actor):
        return ctx.refuse(command_text)
    ctx.react()
    # Who commits, before the long Claude run: a problem here should cost seconds, not the written pages.
    slug, bot_id = ctx.app.identity(ctx.token())
    with tempfile.TemporaryDirectory(prefix="imgagent-") as tmp:
        tmp = Path(tmp)
        clone = tmp / "repo"
        github.clone(ctx.repo, ctx.token(), clone, ref=ctx.default_branch)
        if gone := missing(clone, context):
            return no_such(ctx, gone, "make docs with <folders>")
        summary = _run_writer(ctx, clone, tmp, SCRIPTS / "docs" / "write_docs.py", ["make", hint],
                              {"CONTEXT": ",".join(context)})
        paths = ["docs", "zensical.toml"]
        status = subprocess.run(["git", "-C", str(clone), "status", "--porcelain", "--", *paths],
                                check=True, capture_output=True, text=True).stdout
        if not status.strip():
            ctx.say(f"@{ctx.actor} `make docs`: {_first_line(summary, 'nothing to change.')}")
            return
        _open_pr(ctx, clone, paths, slug=slug, bot_id=bot_id, branch=f"{slug}/make-docs-{secrets.token_hex(4)}",
                 title="docs: make documentation from the code", command_text=command_text, summary=summary,
                 review="Review every page before merging: Claude was told to document only what the code "
                        "shows, but it can still be wrong.")


def do_update(ctx: Context, job: Job) -> None:
    targets, context = job.args["targets"], job.args.get("context", [])
    task = job.args.get("task", "").strip()
    command_text = f"@{ctx.cfg.handle} update {spec(job)}"
    if not ctx.can_write(ctx.actor):
        return ctx.refuse(command_text)
    if not task:
        ctx.say(f"@{ctx.actor} write what to do after `{command_text}`, e.g. "
                f"`{command_text} require Python 3.13`.")
        return
    ctx.react()
    slug, bot_id = ctx.app.identity(ctx.token())
    with tempfile.TemporaryDirectory(prefix="imgagent-") as tmp:
        tmp = Path(tmp)
        clone = tmp / "repo"
        github.clone(ctx.repo, ctx.token(), clone, ref=ctx.default_branch)
        if gone := missing(clone, targets + context):
            return no_such(ctx, gone, "update <folders> [with <folders>]` and the task, e.g. `update docs with src")
        summary = _run_writer(ctx, clone, tmp, SCRIPTS / "repo" / "update.py", [],
                              {"TARGETS": ",".join(targets), "CONTEXT": ",".join(context), "TASK": task})
        git = lambda *a: subprocess.run(["git", "-C", str(clone), *a], check=True, capture_output=True,
                                        text=True).stdout
        # Only edits of tracked files in scope get into the pull request: never new, deleted or other files.
        changed = git("diff", "--name-only", "-z", "--diff-filter=M").split("\0")
        paths = [p for p in changed if p and in_scope(p, targets)]
        if stray := [p for p in git("diff", "--name-only", "-z").split("\0") if p and p not in paths]:
            log.warning("update %s: leaving out changes outside its scope: %s", spec(job), stray)
        if not paths:
            ctx.say(f"@{ctx.actor} `update {spec(job)}`: {_first_line(summary, 'nothing needed to change.')}")
            return
        short = " ".join(task.split())
        short = short if len(short) <= 60 else short[:57].rstrip() + "..."
        name = re.sub(r"[^a-z0-9]+", "-", "-".join(targets).lower()).strip("-")[:40] or "repo"
        _open_pr(ctx, clone, paths, slug=slug, bot_id=bot_id, branch=f"{slug}/update-{name}-{secrets.token_hex(4)}",
                 title=f"{', '.join(targets)}: {short}", command_text=command_text,
                 summary=f"Task: {task}\n\n{summary}",
                 review=f"Claude could only edit existing files in {', '.join(f'`{t}`' for t in targets)} and at the top level of the "
                        "repository. Review every change before merging: it can still be wrong.")


# ------------------------------------------------------------------------------------------ setup

SETUP_FILES = {"reuse": "REUSE.toml", "aisignoff": "SIGNOFF.toml", "docs": "zensical.toml"}


def do_setup(ctx: Context, job: Job) -> None:
    """Create REUSE.toml, SIGNOFF.toml or zensical.toml from the settings in the request; no AI."""
    target, text = job.args["target"], job.args.get("text", "")
    name = SETUP_FILES[target]
    command_text = f"@{ctx.cfg.handle} setup {target}"
    if not ctx.can_write(ctx.actor):
        return ctx.refuse(command_text)
    example = {"reuse": setup.REUSE_EXAMPLE, "aisignoff": setup.SIGNOFF_EXAMPLE}.get(target, "")
    example = f"\n\nFor example:\n\n{example.format(handle=ctx.cfg.handle)}" if example else ""
    try:   # read the settings before cloning: a typo costs a reply, not a clone
        if target == "reuse":
            if not text.strip():
                return ctx.say(f"@{ctx.actor} write the annotations for `REUSE.toml` after `{command_text}`.{example}")
            content, licences = setup.reuse_toml(text)
        elif target == "aisignoff":
            args = setup.aisignoff_args(text)
        else:
            settings = setup.docs_settings(text)
    except setup.SetupError as e:
        return ctx.say(f"@{ctx.actor} `{command_text}`: {e}{example}")
    ctx.react()
    slug, bot_id = ctx.app.identity(ctx.token())
    with tempfile.TemporaryDirectory(prefix="imgagent-") as tmp:
        tmp = Path(tmp)
        clone = tmp / "repo"
        github.clone(ctx.repo, ctx.token(), clone, ref=ctx.default_branch)
        if (clone / name).exists() or (clone / name).is_symlink():
            fix = f"To change it, use `@{ctx.cfg.handle} update {name}` and say what to change"
            fix += "; `make docs` also rebuilds its nav." if target == "docs" else "."
            return ctx.say(f"@{ctx.actor} this repository already has a `{name}`, so `setup {target}` leaves it "
                           f"as it is. {fix}")
        paths = [name]
        if target == "reuse":
            (clone / name).write_text(content, encoding="utf-8")
            summary = [f"Creates `REUSE.toml` from the annotations in the request, written by IMGAgent without AI."]
            if gone := [i for i in licences if not (clone / "LICENSES" / f"{i}.txt").exists()]:
                summary.append(f"\n`LICENSES/` has no text yet for {', '.join(f'`{i}`' for i in gone)}: add it with "
                               f"`pipx run reuse download {' '.join(gone)}` before `reuse lint` passes.")
            review = "Check every path, copyright and license before merging."
        elif target == "aisignoff":
            r = _run(["aisignoff", "init", *args], clone, {}, timeout=120)
            if r.returncode or not (clone / name).is_file():
                said = (r.stdout + r.stderr).strip()[-1500:] or "no output"
                return ctx.say(f"@{ctx.actor} `aisignoff init` refused these settings:\n\n```\n{said}\n```{example}")
            summary = [f"Creates `SIGNOFF.toml` with `aisignoff init {' '.join(args)}`".rstrip() + ", run by IMGAgent without AI."]
            if not args:
                summary.append("\nIt is the commented template: add the `[[annotations]]` for this repository's "
                               "files before `aisignoff lint` passes.")
            review = "Check the levels and names before merging: they are what the repository declares."
        else:
            env = {**_docs_env(ctx, clone), "SUMMARY_FILE": str(tmp / "summary.md")}
            env.pop("ANTHROPIC_API_KEY")
            for key, var in (("name", "DOCS_PROJECT"), ("description", "DOCS_ABOUT"), ("url", "DOCS_URL")):
                if key in settings:
                    env[var] = "" if key == "url" and settings[key].lower() == "none" else settings[key]
            r = _run([sys.executable, str(SCRIPTS / "docs" / "write_docs.py"), "setup"], clone, env, timeout=120)
            if r.returncode or not (tmp / "summary.md").is_file():
                raise RuntimeError("write_docs.py setup failed")
            summary = [(tmp / "summary.md").read_text(encoding="utf-8")]
            paths = ["docs", name]
            review = "Check the site name, description, address and nav before merging."
        _open_pr(ctx, clone, paths, slug=slug, bot_id=bot_id, branch=f"{slug}/setup-{target}-{secrets.token_hex(4)}",
                 title=f"Set up {name}", command_text=command_text, summary="\n".join(summary), review=review, ai=False)


# ---------------------------------------------------------------------------------------- signoff

def _actions_env(ctx: Context, tmp: Path, token: str) -> dict:
    """What a GitHub Actions run would give the signoff scripts."""
    event = tmp / "event.json"
    event.write_text(json.dumps(ctx.payload), encoding="utf-8")
    slug, _ = ctx.app.identity(token)
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


HANDLERS = {"help": do_help, "ask": do_ask, "update": do_update, "make": do_make, "setup": do_setup,
            "signoff": do_signoff, "signoff-form": do_signoff_form}


def run(ctx: Context, job: Job) -> None:
    log.info("%s %s#%s by %s: %s %s", ctx.event, ctx.repo, ctx.number, ctx.actor, job.kind,
             {k: str(v)[:80] for k, v in job.args.items()})
    if job.args.get("unanswered_only") and ctx.answered():
        log.info("%s for %s#%s: not run, IMGAgent already commented on this issue (write a new comment instead)",
                 job.kind, ctx.repo, ctx.number)
        return
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
