"""What ask.py and update.py share: which files of a target they read, and calling Claude."""

from __future__ import annotations

import json
import subprocess
import sys
from fnmatch import fnmatch
from pathlib import Path, PurePosixPath

import anthropic

# Not worth reading: binaries, images, vendored wheels, lock files and legal text.
SKIP_NAMES = ["*.whl", "*.png", "*.jpg", "*.jpeg", "*.gif", "*.svg", "*.ico", "*.pdf", "*.zip", "*.gz",
              "*.lock", "package-lock.json", "LICENSE", "NOTICE"]
MAX_FILE_BYTES = 200_000
# About 4 characters per token: 600k characters is about 150k tokens, well inside the models' context.
MAX_CONTEXT_CHARS = 600_000
# The App has no Workflows permission, so a push that touches these files would be refused.
NEVER_EDIT = (".github/workflows/",)


class TooLarge(Exception):
    pass


def tracked(root: Path) -> list[str]:
    out = subprocess.run(["git", "ls-files", "-z"], cwd=root, capture_output=True, text=True, check=True).stdout
    return sorted(p for p in out.split("\0") if p)


def in_target(rel: str, target: str) -> bool:
    return rel == target or rel.startswith(target.rstrip("/") + "/")


def read_text(root: Path, rel: str) -> str | None:
    """The file's text, or None for files that are missing, links, binary, too large or skipped."""
    path = root / rel
    if any(fnmatch(PurePosixPath(rel).name, p) for p in SKIP_NAMES):
        return None
    if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_FILE_BYTES:
        return None
    data = path.read_bytes()
    if b"\0" in data:
        return None
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return None


def select(root: Path, target: str, top_level: bool = False) -> dict[str, str]:
    """The tracked text files under target (and, with top_level, those in the repository root), in a stable
    order: the prompt cache matches byte for byte, so the same files must give the same text every time."""
    files = {}
    for rel in tracked(root):
        if in_target(rel, target) or (top_level and "/" not in rel):
            text = read_text(root, rel)
            if text is not None:
                files[rel] = text
    size = sum(len(t) for t in files.values())
    if size > MAX_CONTEXT_CHARS:
        raise TooLarge(f"`{target}` is too large to read at once: about {size // 4:,} tokens in {len(files)} "
                       f"files, the limit is about {MAX_CONTEXT_CHARS // 4:,}. Name a smaller folder.")
    return files


def as_xml(files: dict[str, str]) -> str:
    return "\n\n".join(f'<file path="{rel}">\n{text}\n</file>' for rel, text in files.items())


def apply_edits(text: str, edits: list[dict]) -> tuple[str, list[str]]:
    """Find-and-replace edits; an edit whose text isn't found exactly once is skipped and reported."""
    failed = []
    for edit in edits:
        if edit["find"] and text.count(edit["find"]) == 1:
            text = text.replace(edit["find"], edit["replace"])
        else:
            failed.append(edit["find"][:80])
    return text, failed


class Claude:
    """Calls with one shared system prompt (cached), counting the tokens used."""

    def __init__(self, model: str, effort: str, system: list[dict], client: anthropic.Anthropic | None = None):
        self.client = client or anthropic.Anthropic()  # reads ANTHROPIC_API_KEY
        self.model, self.effort, self.system = model, effort, system
        self.usage = {"input": 0, "cache_write": 0, "cache_read": 0, "output": 0}

    def call(self, prompt: str, schema: dict | None = None, max_tokens: int = 32000) -> str:
        output_config: dict = {"effort": self.effort}
        if schema:
            output_config["format"] = {"type": "json_schema", "schema": schema}
        extra: dict = {}
        # On a refusal by a safety classifier, let the API rerun the request on a fallback model.
        if self.model.startswith(("claude-opus-5", "claude-sonnet-5-5", "claude-fable-5")):
            extra = {"betas": ["server-side-fallback-2026-07-01"], "fallbacks": "default"}
        with self.client.beta.messages.stream(model=self.model, max_tokens=max_tokens, output_config=output_config,
                                              system=self.system, messages=[{"role": "user", "content": prompt}],
                                              **extra) as stream:
            response = stream.get_final_message()
        u = response.usage
        for key, value in (("input", u.input_tokens), ("cache_write", u.cache_creation_input_tokens),
                           ("cache_read", u.cache_read_input_tokens), ("output", u.output_tokens)):
            self.usage[key] += value or 0
        print(f"  model={response.model} stop={response.stop_reason} input={u.input_tokens} "
              f"cache_write={u.cache_creation_input_tokens} cache_read={u.cache_read_input_tokens} "
              f"output={u.output_tokens}", file=sys.stderr)
        if response.stop_reason == "refusal":
            raise RuntimeError("Claude declined this request.")
        if response.stop_reason == "max_tokens":
            raise RuntimeError(f"The answer hit max_tokens ({max_tokens}) and was cut off.")
        return "".join(b.text for b in response.content if b.type == "text").strip()

    def call_json(self, prompt: str, schema: dict, max_tokens: int = 16000) -> dict:
        return json.loads(self.call(prompt, schema, max_tokens))

    def usage_line(self) -> str:
        u = self.usage
        return (f"{self.model}, effort {self.effort}: {u['input']:,} input, {u['cache_write']:,} cache write, "
                f"{u['cache_read']:,} cache read, {u['output']:,} output tokens")


def system_blocks(*parts: str) -> list[dict]:
    blocks = [{"type": "text", "text": p} for p in parts]
    blocks[-1]["cache_control"] = {"type": "ephemeral"}   # every call in a run shares this prefix
    return blocks
