"""Turn a webhook event into at most one job. Pure functions, no network: easy to test.

Commands are "@IMGAgent <action> <target> [text]":

    ask <path> <question>     answer from the files under <path> (any folder or file, e.g. docs or src)
    update <path> <task>      small edits to existing files under <path> and the top-level files
    make docs [hint]          build the docs from the code (only "docs" for now)
    signoff ...               the signoff assistant (anywhere in the text, see signoff_pattern)
    help
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

FORM_MARKER = "### What should be recorded?"   # issues made with the form "Signoff: declare or attest files"
MAKE_TARGETS = ("docs",)

# A path inside the repository: plain names separated by "/", no "..", no ".git", no glob characters.
_SEGMENT = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9._-]*$|^\.[A-Za-z0-9_][A-Za-z0-9._-]*$")


@dataclass
class Job:
    kind: str                     # ask | update | make | signoff | signoff-form | help
    args: dict = field(default_factory=dict)

    def key(self, repo: str, number: int) -> str:
        """Jobs with the same key run one after the other. Jobs that open pull requests share one per repository."""
        return f"{repo}#write" if self.kind in ("make", "update") else f"{repo}#{number}"


def clean_target(raw: str) -> str | None:
    """The target as a repository-relative path ("docs", "src/pkg"), or None if it isn't a safe one."""
    path = raw.strip().strip("`")
    while path.startswith("./"):
        path = path[2:]
    path = path.rstrip("/")
    if not path or len(path) > 200:
        return None
    parts = path.split("/")
    if any(p in ("", ".", "..") or p.lower() == ".git" or not _SEGMENT.match(p) for p in parts):
        return None
    return path


def _space(text: str) -> str:
    return re.escape(text).replace(r"\ ", r"\s+")


def signoff_pattern(handle: str) -> re.Pattern:
    # Same rule as the signoff assistant: not inside a longer word, an e-mail address, a path or code.
    return re.compile(r"(?<![\w@/`])@" + _space(handle) + r"\s+signoff\b(?!-)", re.I)


def leading_command(text: str, handle: str) -> list[str] | None:
    """The words after "@<handle>" when a comment starts with it, else None."""
    first = (text or "").lstrip().split("\n", 1)[0].strip()
    m = re.match(r"@" + re.escape(handle) + r"(?![\w-])\s*(.*)$", first, re.I)
    return m.group(1).split() if m else None


def _rest(text: str, handle: str, words: int) -> str:
    """The text after "@<handle>" and the next `words` words, across lines."""
    m = re.match(r"\s*@" + re.escape(handle) + r"(?![\w-])" + r"\s+\S+" * words, text, re.I)
    return text[m.end():].strip() if m else ""


def action_job(action: str, target_word: str | None, rest: str) -> Job:
    """The job for "<action> <target> <rest>", or help explaining what is wrong with it."""
    usage = {"ask": "ask <folder> <question>", "update": "update <folder> <task>", "make": "make docs [hint]"}
    if target_word is None:
        return Job("help", {"problem": f"`{action}` needs a target: `{usage[action]}`."})
    target = clean_target(target_word)
    if target is None:
        return Job("help", {"problem": f"`{target_word}` is not a path in this repository I can use: "
                                       f"`{usage[action]}`, e.g. `docs` or `src/package`."})
    if action == "make":
        if target not in MAKE_TARGETS:
            return Job("help", {"problem": f"`make` only knows `docs` for now, not `{target}`. "
                                           f"To change existing files, use `update {target} <task>`."})
        return Job("make", {"target": target, "hint": rest})
    if action == "ask":
        return Job("ask", {"target": target, "question": rest})
    return Job("update", {"target": target, "task": rest})


def route(event: str, payload: dict, handle: str = "IMGAgent", signoff_form: bool = True) -> Job | None:
    action = payload.get("action")
    sender = payload.get("sender") or {}
    if sender.get("type") == "Bot":
        return None   # never answer bots, so IMGAgent can't start itself
    issue = payload.get("issue") or {}
    issue_body = issue.get("body") or ""
    is_form = FORM_MARKER in issue_body
    is_pr = bool(issue.get("pull_request"))
    signoff = signoff_pattern(handle)

    if event == "issue_comment" and action == "created":
        body = (payload.get("comment") or {}).get("body") or ""
        words = leading_command(body, handle)
        if words is not None:
            verb = words[0].lower() if words else ""
            if verb in ("ask", "update", "make"):
                return action_job(verb, words[1] if len(words) > 1 else None, _rest(body, handle, 2))
            if verb == "docs" and len(words) > 1 and words[1].lower() in ("ask", "update", "make"):
                new = f"@{handle} {words[1].lower()} docs"
                return Job("help", {"problem": f"commands are now action then target: `{new} ...`."})
            if verb != "signoff":
                return Job("help", {"problem": f"I don't know `{' '.join(words[:2])}`." if verb not in ("", "help")
                                    else ""})
            # signoff: handled below, with the assistant's own rules
        if signoff.search(body) and not is_pr and issue.get("state") == "open" and not is_form:
            return Job("signoff")
        return None

    if event == "issues":
        title = issue.get("title") or ""
        if action == "opened":
            ask = re.compile(r"@" + _space(handle) + r"\s+ask\s+(\S+)", re.I)
            text = f"{title}\n\n{issue_body}"
            if m := ask.search(text):
                job = action_job("ask", m.group(1), (text[:m.start()] + text[m.end():].lstrip(" \t")).strip())
                return job if job.kind == "ask" else None
            if signoff.search(issue_body) and not is_form:
                return Job("signoff")
        if signoff_form and is_form and issue.get("state") == "open" and action in ("opened", "edited", "reopened"):
            if action != "edited" or "body" in (payload.get("changes") or {}):
                return Job("signoff-form")
    return None
