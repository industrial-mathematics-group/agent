"""Turn a webhook event into at most one job. Pure functions, no network: easy to test."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

FORM_MARKER = "### What should be recorded?"   # issues made with the form "Signoff: declare or attest files"


@dataclass
class Job:
    kind: str                     # docs-ask | docs-write | signoff | signoff-form | help
    args: dict = field(default_factory=dict)

    def key(self, repo: str, number: int) -> str:
        """Jobs with the same key run one after the other."""
        return f"{repo}#docs-write" if self.kind == "docs-write" else f"{repo}#{number}"


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
            first_line = body.lstrip().split("\n", 1)[0]
            if [w.lower() for w in words[:2]] == ["docs", "ask"]:
                question = re.sub(r"^\s*@" + re.escape(handle) + r"\s+docs\s+ask\b", "", body, count=1,
                                  flags=re.I).strip()
                return Job("docs-ask", {"question": question})
            if len(words) >= 2 and words[0].lower() == "docs" and words[1].lower() in ("make", "update"):
                hint = re.sub(r"^\s*@" + re.escape(handle) + r"\s+docs\s+\S+\s*", "", first_line, count=1,
                              flags=re.I).strip()
                return Job("docs-write", {"command": words[1].lower(), "hint": hint})
            if words and words[0].lower() == "signoff":
                pass   # handled below, with the assistant's own rules
            else:
                unknown = " ".join(words[:2]) if words and words[0].lower() != "help" else ""
                return Job("help", {"unknown": unknown})
        if signoff.search(body) and not is_pr and issue.get("state") == "open" and not is_form:
            return Job("signoff")
        return None

    if event == "issues":
        title = issue.get("title") or ""
        if action == "opened":
            ask = re.compile(r"@" + _space(handle) + r"\s+docs\s+ask\b", re.I)
            if ask.search(title) or ask.search(issue_body):
                text = f"{title}\n\n{issue_body}"
                return Job("docs-ask", {"question": ask.sub("", text, count=1).strip()})
            if signoff.search(issue_body) and not is_form:
                return Job("signoff")
        if signoff_form and is_form and issue.get("state") == "open" and action in ("opened", "edited", "reopened"):
            if action != "edited" or "body" in (payload.get("changes") or {}):
                return Job("signoff-form")
    return None
