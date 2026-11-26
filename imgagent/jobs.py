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
import urllib.request
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
    review_model: str = "claude-sonnet-5-5"
    review_model_name: str = "Claude Sonnet 5.5 (Anthropic)"
    review_effort: str = "low"

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
            review_model=e("REVIEW_MODEL") or d.review_model,
            review_model_name=e("REVIEW_MODEL_NAME") or d.review_model_name,
            review_effort=e("REVIEW_EFFORT") or d.review_effort,
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

    def say(self, text: str) -> dict:
        return self.api("POST", f"/repos/{self.repo}/issues/{self.number}/comments", {"body": text})

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
            f"| `@{handle} review docs [with src]` and an optional focus | a quick AI review of `docs`, checked against `src`; recorded as an aisignoff A1 attestation in a pull request |\n"
            f"| `@{handle} setup reuse`, `aisignoff`, `citation` or `docs` | a template for `REUSE.toml` (and `LICENSES/`), `SIGNOFF.toml`, `CITATION.cff` or `zensical.toml` with defaults filled in; ticking its **Done** opens the pull request (no AI) |\n"
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
             command_text: str, summary: str, review: str, ai: bool = True, model: str | None = None,
             body: str | None = None, announce: bool = True) -> str:
    """Commit `paths` on a new branch, push it, open the pull request and assign the requester.
    ai=False: IMGAgent wrote the files from the person's own settings, without a model (G0).
    body: the whole description instead of the template (a review record needs no declaration);
    announce=False: the caller says it is ready, in its own comment."""
    git = lambda *a: subprocess.run(["git", "-C", str(clone), *a], check=True, capture_output=True, text=True)
    model = (model or ctx.cfg.writer_model) if ai else None
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
        "body": body or pr_body(ctx.actor, comment_url, command_text, summary, model, review)})
    try:
        ctx.api("POST", f"/repos/{ctx.repo}/issues/{pr['number']}/assignees", {"assignees": [ctx.actor]})
    except github.GitHubError as e:
        log.warning("could not assign %s: %s", ctx.actor, e)
    if announce:
        ctx.say(f"@{ctx.actor} `{command_text.split(' ', 1)[1]}` is ready for review: {pr['html_url']}")
    return pr["html_url"]


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



# ----------------------------------------------------------------------------------------- review

# aisignoff's findings levels, as the lines of the reviewed files show them once the record is merged
FINDINGS_LEVEL = {"none": "F0", "trivial": "F0", "minor": "F1", "major": "F2", "critical": "F3"}


def _record_review(ctx: Context, clone: Path, per_file: dict[str, str], reviewed_by: str) -> tuple[list[str], str]:
    """Attest each reviewed file at A1 with its own findings, with aisignoff, in one new record file of the review
    folder. The new files, and a note for the person (why nothing was recorded, or what aisignoff remarked)."""
    if not (clone / "SIGNOFF.toml").is_file():
        return [], (f"This repository has no `SIGNOFF.toml`, so the review isn't recorded: "
                    f"`@{ctx.cfg.handle} setup aisignoff` sets it up.")
    try:
        from aisignoff.project import Project
        project = Project(clone)
        declared, folder = set(project.files()), project.config.review_dir
    except Exception as e:   # ConfigError, ProjectError: a SIGNOFF.toml aisignoff can't read
        return [], f"aisignoff can't read `SIGNOFF.toml`, so the review isn't recorded: {e}"
    if not folder:
        return [], '`SIGNOFF.toml` sets no review folder (`[review] dir = ""`), so the review isn\'t recorded.'
    groups: dict[str, list[str]] = {}
    for rel, level in per_file.items():
        if rel in declared and level in FINDINGS_LEVEL:
            groups.setdefault(level, []).append(rel)
    if not groups:
        return [], "None of the reviewed files needs a declaration in `SIGNOFF.toml`, so there is nothing to record."
    # aisignoff attest takes one --findings per call: one call per level, each into a part file, joined afterwards.
    tag, parts, notes = secrets.token_hex(4), [], set()
    for i, (level, files) in enumerate(groups.items()):
        part = clone / folder / f"imgagent-{tag}-{i}.toml"
        r = _run([sys.executable, "-m", "aisignoff", "--root", str(clone), "attest", "-a", "A1", "--findings", level,
                  "--ai-reviewed-by", reviewed_by, "--to", str(part), "--", *files], clone, {}, timeout=300)
        if r.returncode:
            for p in parts:
                p.unlink()
            why = (r.stderr.strip().splitlines() or ["no reason given"])[-1]
            return [], f"aisignoff couldn't record the review: {why}"
        parts.append(part)
        notes |= {line.removeprefix("note: ") for line in r.stdout.splitlines() if line.startswith("note: ")}
    texts = [p.read_text(encoding="utf-8") for p in parts]
    head = "".join(line for line in texts[0].splitlines(keepends=True) if line.startswith("#"))
    body = "".join("".join(l for l in t.splitlines(keepends=True) if not l.startswith("#")) for t in texts)
    for p in parts:
        p.unlink()
    import datetime
    stem = f"{datetime.date.today().isoformat()}-review-" + (
        re.sub(r"[^A-Za-z0-9._-]+", "-", "-".join(sorted({f.split('/')[0] for f in per_file})))[:40].strip("-") or "files")
    target, n = clone / folder / f"{stem}.toml", 1
    while target.exists():
        n += 1
        target = clone / folder / f"{stem}-{n}.toml"
    target.write_text(head + body, encoding="utf-8")
    try:
        from aisignoff.config import load
        load(clone)
    except Exception as e:
        target.unlink()
        return [], f"aisignoff can't read the joined record, so the review isn't recorded: {e}"
    return [target.relative_to(clone).as_posix()], " ".join(n[0].upper() + n[1:] + "." for n in sorted(notes))


def _per_file_lines(per_file: dict[str, str]) -> str:
    """"- **F2** (major): `a.md`" per findings level, highest first, for the comment and the pull request."""
    order = ["critical", "major", "minor", "trivial", "none"]
    out = []
    for level in order:
        files = [f"`{rel}`" for rel, lv in per_file.items() if lv == level]
        if files:
            shown = ", ".join(files[:20]) + (f" and {len(files) - 20} more" if len(files) > 20 else "")
            out.append(f"- **{FINDINGS_LEVEL[level]}** ({level}): {shown}")
    return "\n".join(out)


def do_review(ctx: Context, job: Job) -> None:
    targets, context = job.args["targets"], job.args.get("context", [])
    focus = job.args.get("focus", "").strip()
    command_text = f"@{ctx.cfg.handle} review {spec(job)}"
    if not ctx.can_write(ctx.actor):
        return ctx.refuse(command_text)
    ctx.react()
    slug, bot_id = ctx.app.identity(ctx.token())
    comment_url = (ctx.comment or ctx.issue)["html_url"]
    model, name = ctx.cfg.review_model, ctx.cfg.review_model_name
    with tempfile.TemporaryDirectory(prefix="imgagent-") as tmp:
        tmp = Path(tmp)
        clone = tmp / "repo"
        github.clone(ctx.repo, ctx.token(), clone, ref=ctx.default_branch)
        if gone := missing(clone, targets + context):
            return no_such(ctx, gone, "review <folders> [with <folders>]`, e.g. `review docs with src")
        out = tmp / "review.json"
        env = {**_docs_env(ctx, clone), "TARGETS": ",".join(targets), "CONTEXT": ",".join(context),
               "FOCUS": focus, "REVIEW_FILE": str(out), "REVIEW_MODEL": model, "REVIEW_EFFORT": ctx.cfg.review_effort}
        r = _run([sys.executable, str(SCRIPTS / "repo" / "review.py")], clone, env, timeout=15 * 60)
        if r.returncode or not out.is_file():
            raise RuntimeError("review.py failed")
        result = json.loads(out.read_text(encoding="utf-8"))
        findings = result.get("findings")
        if findings not in FINDINGS_LEVEL:
            return ctx.say(f"@{ctx.actor} `review {spec(job)}`: {result.get('markdown', 'nothing to review.')}")
        reviewed_by = f"{name}, new session without the generating conversation, quick review requested in {comment_url}"
        per_file = result.get("per_file") or {f: findings for f in result.get("files", [])}
        record, note = _record_review(ctx, clone, per_file, reviewed_by)
        url = None
        if record:
            sha = subprocess.run(["git", "-C", str(clone), "rev-parse", "--short", "HEAD"], check=True,
                                 capture_output=True, text=True).stdout.strip()
            body = (f"## What does this PR change?\n\nRecords the quick AI review that @{ctx.actor} asked for in "
                    f"{comment_url} (`{command_text}`) as an aisignoff **A1** attestation of the files in "
                    f"{', '.join(f'`{t}`' for t in targets)} as of {sha}: {', '.join(f'`{p}`' for p in record)}.\n\n"
                    f"Each file is attested with its own highest finding, so once this is merged their lines show, "
                    f"until they change:\n\n{_per_file_lines(per_file)}\n\n{result['markdown']}\n\n"
                    f"{note}\n\nThis pull request only adds a record to the review folder, so it needs no AI "
                    f"declaration. Check that the findings above are fair before merging.").replace("\n\n\n\n", "\n\n")
            name_ = re.sub(r"[^a-z0-9]+", "-", "-".join(targets).lower()).strip("-")[:40] or "repo"
            url = _open_pr(ctx, clone, record, slug=slug, bot_id=bot_id, model=model, announce=False,
                           branch=f"{slug}/review-{name_}-{secrets.token_hex(4)}",
                           title=f"Record a quick review of {', '.join(targets)} (A1, highest finding: {findings})",
                           command_text=command_text, summary="", review="", body=body)
    lines = f"AI-Review: A1\nAI-Reviewed-by: {reviewed_by}\nAI-Review-Findings: {findings}"
    with_ = f", checked against {', '.join(f'`{c}`' for c in context)}" if context else ""
    recorded = (f"Recorded as an A1 attestation of each file with its own findings in {url}; merging it marks "
                f"their lines:\n\n{_per_file_lines(per_file)}" if url else note)
    ctx.say(f"@{ctx.actor} quick review of {', '.join(f'`{t}`' for t in targets)}{with_}: highest finding **{findings}**"
            f"\n\n{result['markdown']}\n\n```\n{lines}\n```\n\n{recorded}"
            + FOOTER.format(what=f"reviewed with {model}, effort {ctx.cfg.review_effort}; a quick check, not a full review"))


# ------------------------------------------------------------------------------------------ setup

LICENSE_TEXT = "https://raw.githubusercontent.com/spdx/license-list-data/main/text/{id}.txt"


def fetch_license(spdx_id: str) -> str | None:
    """The text of an SPDX license (for LICENSES/), or None if it can't be fetched."""
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9.+-]*", spdx_id):
        return None
    try:
        with urllib.request.urlopen(LICENSE_TEXT.format(id=spdx_id), timeout=30) as r:
            return r.read().decode("utf-8")
    except (OSError, UnicodeDecodeError) as e:
        log.warning("could not fetch the license text of %s: %s", spdx_id, e)
        return None


def _name_of(ctx: Context, login: str) -> str:
    """A GitHub account's display name, or its login."""
    try:
        return (ctx.api("GET", f"/users/{login}", ok404=True) or {}).get("name") or login
    except github.GitHubError:
        return login


def setup_template(ctx: Context, target: str) -> str:
    """The template comment for a target, with defaults from the repository and the requester."""
    repo = ctx.payload["repository"]
    owner, name = ctx.repo.split("/")
    license = ((repo.get("license") or {}).get("spdx_id") or "").strip()
    license = None if license in ("", "NOASSERTION", "NONE") else license
    h, a = ctx.cfg.handle, ctx.actor
    if target == "reuse":
        return setup.reuse_template(a, h, holder=_name_of(ctx, owner), license=license)
    if target == "aisignoff":
        return setup.signoff_template(a, h, reviewer=_name_of(ctx, a), branch=ctx.default_branch)
    if target == "citation":
        return setup.citation_template(a, h, title=name, author=_name_of(ctx, a), license=license,
                                       url=repo.get("html_url") or f"https://github.com/{ctx.repo}",
                                       abstract=repo.get("description") or "", keywords=repo.get("topics") or [])
    return setup.docs_template(a, h, name=name, description=repo.get("description") or "",
                               url=repo.get("homepage") or f"https://{owner.lower()}.github.io/{name}/")


def _exists(ctx: Context, path: str) -> bool:
    return ctx.api("GET", f"/repos/{ctx.repo}/contents/{path}?ref={ctx.default_branch}", ok404=True) is not None


def _already(ctx: Context, target: str) -> None:
    name = setup.TARGETS[target]
    fix = f"To change it, use `@{ctx.cfg.handle} update {name}` and say what to change"
    ctx.say(f"@{ctx.actor} this repository already has a `{name}`, so `setup {target}` leaves it as it is. "
            f"{fix}{'; `make docs` also rebuilds its nav.' if target == 'docs' else '.'}")


def do_setup(ctx: Context, job: Job) -> None:
    """Post the template for REUSE.toml, SIGNOFF.toml, CITATION.cff or zensical.toml, or finish an open one."""
    target = job.args["target"]
    command_text = f"@{ctx.cfg.handle} setup {target}"
    if not ctx.can_write(ctx.actor):
        return ctx.refuse(command_text)
    if job.args.get("done"):
        slug, _ = ctx.app.identity(ctx.token())
        comments = ctx.api("GET", f"/repos/{ctx.repo}/issues/{ctx.number}/comments?per_page=100") or []
        open_ = [c for c in comments if (c.get("user") or {}).get("login") == f"{slug}[bot]"
                 and setup.target_of(c.get("body")) == target and setup.DONE in c.get("body", "")]
        if not open_:
            return ctx.say(f"@{ctx.actor} there is no open `setup {target}` template here. "
                           f"Write `{command_text}` to get one.")
        return _finish_setup(ctx, target, open_[-1])
    if _exists(ctx, setup.TARGETS[target]):
        return _already(ctx, target)
    ctx.react()
    ctx.say(setup_template(ctx, target))


def do_setup_done(ctx: Context, job: Job) -> None:
    """The "Done" box of a template was ticked: check that the template is IMGAgent's, then finish it."""
    target = job.args["target"]
    if not ctx.can_write(ctx.actor):
        return ctx.refuse(f"@{ctx.cfg.handle} setup {target}")
    slug, _ = ctx.app.identity(ctx.token())
    comment = ctx.api("GET", f"/repos/{ctx.repo}/issues/comments/{job.args['comment_id']}", ok404=True)
    if not comment or (comment.get("user") or {}).get("login") != f"{slug}[bot]" \
            or setup.target_of(comment.get("body")) != target or not setup.is_done(comment["body"]):
        log.info("setup-done: comment %s is not a ticked %s template of IMGAgent's", job.args["comment_id"], target)
        return
    _finish_setup(ctx, target, comment)


def _kind_in(clone: Path):
    def kind(path: str) -> bool | None:
        found = find_target(clone, path)
        return None if found is None else found.is_dir()
    return kind


def _finish_setup(ctx: Context, target: str, comment: dict) -> None:
    body, name = comment["body"], setup.TARGETS[target]
    edit = lambda text: ctx.api("PATCH", f"/repos/{ctx.repo}/issues/comments/{comment['id']}", {"body": text})

    def problem(text: str) -> None:
        edit(setup.with_problem(body, text))
        ctx.say(f"@{ctx.actor} the `setup {target}` template above has a problem: {text} I unticked **Done**: "
                f"fix it and tick **Done** again.")

    form = setup.read_form(body)
    ctx.react()
    slug, bot_id = ctx.app.identity(ctx.token())
    with tempfile.TemporaryDirectory(prefix="imgagent-") as tmp:
        tmp = Path(tmp)
        clone = tmp / "repo"
        github.clone(ctx.repo, ctx.token(), clone, ref=ctx.default_branch)
        if (clone / name).exists() or (clone / name).is_symlink():
            edit(setup.finished(body, f"not needed, `{name}` exists now"))
            return _already(ctx, target)
        paths, notes = [name], []
        try:
            if target == "reuse":
                content, licences = setup.reuse_annotations(form, _kind_in(clone))
                (clone / name).write_text(content, encoding="utf-8")
                for spdx in licences:
                    dest = clone / "LICENSES" / f"{spdx}.txt"
                    if dest.exists():
                        continue
                    text = None if spdx.startswith("LicenseRef-") else fetch_license(spdx)
                    if text is None:
                        notes.append(f"- `LICENSES/{spdx}.txt` is missing: add the license text by hand.")
                        continue
                    dest.parent.mkdir(exist_ok=True)
                    dest.write_text(text, encoding="utf-8")
                    notes.append(f"- Added `LICENSES/{spdx}.txt` from the SPDX license list.")
                if (clone / "LICENSES").is_dir():
                    paths.append("LICENSES")
            elif target == "aisignoff":
                (clone / name).write_text(setup.signoff_toml(form), encoding="utf-8")
            elif target == "citation":
                (clone / name).write_text(setup.citation_cff(form), encoding="utf-8")
            else:
                settings = setup.docs_settings(form)
        except setup.SetupError as e:
            return problem(str(e))
        if target == "docs":
            env = {**_docs_env(ctx, clone), **settings, "SUMMARY_FILE": str(tmp / "summary.md")}
            env.pop("ANTHROPIC_API_KEY")
            r = _run([sys.executable, str(SCRIPTS / "docs" / "write_docs.py"), "setup"], clone, env, timeout=120)
            if r.returncode or not (tmp / "summary.md").is_file():
                raise RuntimeError("write_docs.py setup failed")
            notes.append((tmp / "summary.md").read_text(encoding="utf-8"))
            paths = ["docs", name]
        summary = "\n".join([f"Creates `{name}` from the [`setup {target}` template]({comment['html_url']}) that "
                             f"@{ctx.actor} filled in. IMGAgent wrote it from the form, without AI.", "", *notes])
        url = _open_pr(ctx, clone, paths, slug=slug, bot_id=bot_id,
                       branch=f"{slug}/setup-{target}-{secrets.token_hex(4)}", title=f"Set up {name}",
                       command_text=f"@{ctx.cfg.handle} setup {target}", summary=summary, ai=False,
                       review=f"Check `{name}` before merging: it is what the repository will declare.")
    edit(setup.finished(body, url))



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


HANDLERS = {"help": do_help, "ask": do_ask, "update": do_update, "make": do_make, "review": do_review, "setup": do_setup, "setup-done": do_setup_done,
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
