"""Turn a webhook event into at most one job. Pure functions, no network: easy to test.

Commands are "@IMGAgent <action> <paths> [with <paths>] [text]":

    ask <paths> [with <paths>]       answer from the files under the paths (folders or files, e.g. docs,src)
    update <paths> [with <paths>]    small edits to existing files under the first paths and the top-level
                                     files; the paths after "with" are read-only context
    make docs [with <paths>]         build the docs from the code (all of it, or only the "with" paths)
    review <paths> [with <paths>]    a quick AI review of the files under the first paths, checked against the
                                     "with" paths; recorded as an aisignoff A1 attestation in a pull request
    setup reuse|aisignoff|citation|docs
                                     post a template for REUSE.toml, SIGNOFF.toml, CITATION.cff or zensical.toml;
                                     ticking its "Done" box (or "setup <target> done") opens the pull request
                                     (no AI, see imgagent/setup.py)

<paths> is a comma-separated list. The question, task or hint follows on the same line or below.
    signoff ...               the signoff assistant (anywhere in the text, see signoff_pattern)
    help
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

FORM_MARKER = "### What should be recorded?"   # issues made with the form "Signoff: declare or attest files"
MAKE_TARGETS = ("docs",)
SETUP_TARGETS = ("reuse", "aisignoff", "citation", "docs")
SETUP_MARKER = re.compile(r"<!-- imgagent-setup:([a-z]+) -->")
SETUP_DONE = re.compile(r"\[[xX]\][^\n]*<!-- f:done -->")

# A path inside the repository: plain names separated by "/", no "..", no ".git", no glob characters.
_SEGMENT = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9._-]*$|^\.[A-Za-z0-9_][A-Za-z0-9._-]*$")


@dataclass
class Job:
    kind: str                     # ask | update | make | review | setup | setup-done | signoff | signoff-form | help
    args: dict = field(default_factory=dict)

    def key(self, repo: str, number: int) -> str:
        """Jobs with the same key run one after the other. Jobs that open pull requests share one per repository."""
        return f"{repo}#write" if self.kind in ("make", "update", "review", "setup", "setup-done") else f"{repo}#{number}"


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


# A comma-separated list of paths on one line ("docs", "docs,src", "docs, src/pkg"), and the whole spec:
# "<targets> [with <context>]". "with" must be on the first line; the text may start there or below.
_LIST = r"[^\s,]+(?:[ \t]*,[ \t]*[^\s,]+)*"
_SPEC = r"[ \t]+(?P<targets>" + _LIST + r")(?:[ \t]+with[ \t]+(?P<context>" + _LIST + r"))?"
USAGE = {"ask": "ask <folders> [with <folders>]", "update": "update <folders> [with <folders>]",
         "make": "make docs [with <folders>]", "review": "review <folders> [with <folders>]",
         "setup": "setup reuse|aisignoff|citation|docs"}


def _paths(raw: str | None) -> tuple[list[str], str | None]:
    """The cleaned paths of a comma-separated list (no duplicates), or the first bad entry."""
    out = []
    for word in (raw or "").split(","):
        word = word.strip()
        if not word:
            continue
        path = clean_target(word)
        if path is None:
            return [], word
        if path not in out:
            out.append(path)
    return out, None


def action_job(action: str, targets_raw: str | None, context_raw: str | None, rest: str) -> Job:
    """The job for "<action> <targets> [with <context>]" and its text, or help explaining what is wrong."""
    if action == "setup":
        target = (targets_raw or "").strip().strip("`").lower()
        if target not in SETUP_TARGETS or context_raw:
            what = f"not `{targets_raw}`" if targets_raw else "and nothing else"
            return Job("help", {"problem": f"`setup` knows `reuse` (REUSE.toml), `aisignoff` (SIGNOFF.toml), "
                                           f"`citation` (CITATION.cff) and `docs` (zensical.toml), {what}."})
        return Job("setup", {"target": target, "done": rest.strip().lower().rstrip(".!").startswith("done")})
    usage = f"`{USAGE[action]}`, then the {dict(ask='question', update='task', make='hint', review='focus (optional)')[action]}"
    if not targets_raw:
        return Job("help", {"problem": f"`{action}` needs a folder: {usage}."})
    targets, bad = _paths(targets_raw)
    context, bad2 = _paths(context_raw)
    if bad or bad2:
        return Job("help", {"problem": f"`{bad or bad2}` is not a path in this repository I can use: "
                                       f"{usage}, e.g. `docs` or `src/package`."})
    context = [c for c in context if c not in targets]
    if action == "make":
        if targets != list(MAKE_TARGETS):
            return Job("help", {"problem": f"`make` only knows `docs` for now, not `{', '.join(targets)}`. "
                                           f"To change existing files, use `update {','.join(targets)}`."})
        return Job("make", {"targets": targets, "context": context, "hint": rest})
    key = {"ask": "question", "update": "task", "review": "focus"}[action]
    return Job(action, {"targets": targets, "context": context, key: rest})


_INVISIBLE = dict.fromkeys(map(ord, "\u200b\u200c\u200d\u2060\ufeff"), None)
_FENCE = re.compile(r"^[ \t]*(```|~~~).*?^[ \t]*\1[^\n]*$", re.M | re.S)


def normalise(text: str) -> str:
    """Comment text as people meant it: no zero-width characters, plain spaces, \\n line ends."""
    text = (text or "").translate(_INVISIBLE).replace("\u00a0", " ").replace("\r\n", "\n")
    return text


def _searchable(text: str) -> str:
    """The text with code blocks and quoted lines blanked out (same length, so positions still match)."""
    text = _FENCE.sub(lambda m: re.sub(r"[^\n]", " ", m.group(0)), text)
    return re.sub(r"(?m)^[ \t]*>.*$", lambda m: " " * len(m.group(0)), text)


def find_command(text: str, handle: str) -> Job | None:
    """The command in a comment or a new issue, wherever it is: "@IMGAgent <action> <folders> [with ...]" with
    the rest of the text (before and after it) as the question, task or hint. Mentions in code or quotes don't
    count. None when there is no command; help when the text starts with "@IMGAgent" but no command follows."""
    text = normalise(text)
    search = _searchable(text)
    mention = r"(?<![\w@/`])\**@" + re.escape(handle) + r"(?:\[bot\])?(?![\w-])\**[:,]?"
    m = re.search(mention + r"[ \t]+(?P<verb>ask|update|make|review|setup|help)\b", search, re.I)
    if m:
        verb = m["verb"].lower()
        if verb == "help":
            return Job("help", {"problem": ""})
        spec = re.match(_SPEC, text[m.end():], re.I)
        if not spec:
            return action_job(verb, None, None, "")
        end = m.end() + spec.end()
        rest = "\n\n".join(t for t in (text[:m.start()].strip(), text[end:].strip()) if t)
        return action_job(verb, spec["targets"], spec["context"], rest)
    # "@IMGAgent" starting the text with something else after it: say what's wrong instead of staying silent.
    lead = re.match(r"\s*" + mention + r"\s*(.*)", search, re.I)
    if lead is None:
        return None
    words = lead.group(1).split("\n", 1)[0].split()
    verb = words[0].lower() if words else ""
    if verb == "signoff":
        return None   # the signoff assistant's own rules decide
    if verb == "docs" and len(words) > 1 and words[1].lower() in ("ask", "update", "make", "review"):
        return Job("help", {"problem": f"commands are now action then target: `@{handle} {words[1].lower()} docs ...`."})
    return Job("help", {"problem": f"I don't know `{' '.join(words[:2])}`." if verb else ""})


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

    if event == "issue_comment" and action == "edited":
        body = (payload.get("comment") or {}).get("body") or ""
        before = ((payload.get("changes") or {}).get("body") or {}).get("from")
        # A setup template of IMGAgent's whose "Done" box was just ticked (the job checks who wrote the comment).
        if (m := SETUP_MARKER.search(body)) and ((payload.get("comment") or {}).get("user") or {}).get("type") == "Bot":
            if m[1] in SETUP_TARGETS and SETUP_DONE.search(body) and not SETUP_DONE.search(before or ""):
                return Job("setup-done", {"target": m[1], "comment_id": payload["comment"]["id"]})
            return None
        # Fixing a command by editing the comment runs it, once: only when the old text had no command that ran.
        job = find_command(body, handle)
        if before is None or not job or job.kind == "help":
            return None
        old = find_command(before, handle)
        return job if old is None or old.kind == "help" else None

    if event == "issue_comment" and action == "created":
        body = (payload.get("comment") or {}).get("body") or ""
        if job := find_command(body, handle):
            return job
        if signoff.search(normalise(body)) and not is_pr and issue.get("state") == "open" and not is_form:
            return Job("signoff")
        return None

    if event == "issues":
        title = issue.get("title") or ""
        if action == "opened" and not is_form:
            job = find_command(f"{title}\n\n{issue_body}", handle)
            if job and job.kind != "help":
                return job
            if signoff.search(normalise(issue_body)):
                return Job("signoff")
        if action in ("edited", "reopened") and not is_form and issue.get("state") == "open":
            # The command in an issue that was opened before IMGAgent ran, or whose first try failed, runs when the
            # issue is edited or reopened, but only while IMGAgent hasn't commented on it yet (checked in the job).
            changed = set(payload.get("changes") or {})
            if action == "reopened" or changed & {"title", "body"}:
                job = find_command(f"{title}\n\n{issue_body}", handle)
                if job and job.kind != "help":
                    job.args["unanswered_only"] = True
                    return job
        if signoff_form and is_form and issue.get("state") == "open" and action in ("opened", "edited", "reopened"):
            if action != "edited" or "body" in (payload.get("changes") or {}):
                return Job("signoff-form")
    return None
