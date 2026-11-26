"""scripts/repo: which files ask and update read, and that update only edits what it may (no Claude calls)."""

import importlib
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def repo(tmp_path, monkeypatch):
    files = {"src/a.py": "PY = '3.12'\n", "src/sub/b.py": "x = 1\n", "srcx/c.py": "y\n", "docs/i.md": "# Hi\n",
             "pyproject.toml": "requires-python = '>=3.12'\n", "logo.png": "PNG\0", "LICENSE": "MIT\n",
             ".github/workflows/ci.yml": "python: 3.12\n"}
    for rel, text in files.items():
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_text(text)
    (tmp_path / "untracked.txt").write_text("no\n")
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "add", "--", *files], check=True)
    monkeypatch.setenv("REPO_ROOT", str(tmp_path))
    monkeypatch.syspath_prepend(str(ROOT / "scripts" / "repo"))
    for m in ("common", "update", "ask", "review"):
        sys.modules.pop(m, None)
    return tmp_path


def test_select(repo):
    common = importlib.import_module("common")
    assert list(common.select(repo, ["src"])) == ["src/a.py", "src/sub/b.py"]
    assert list(common.select(repo, ["src"], top_level=True)) == ["pyproject.toml", "src/a.py", "src/sub/b.py"]
    assert list(common.select(repo, ["docs", ".github"])) == [".github/workflows/ci.yml", "docs/i.md"]


def test_select_refuses_too_much(repo, monkeypatch):
    common = importlib.import_module("common")
    monkeypatch.setattr(common, "MAX_CONTEXT_CHARS", 10)
    with pytest.raises(common.TooLarge, match="Name smaller folders"):
        common.select(repo, ["src"])


def test_apply_edits(repo):
    common = importlib.import_module("common")
    text, failed = common.apply_edits("a b a c", [{"find": "b", "replace": "B"}, {"find": "a", "replace": "x"},
                                                  {"find": "", "replace": "y"}])
    assert text == "a B a c" and len(failed) == 2


class FakeClaude:
    def __init__(self, plan, edits):
        self.plan, self.edits = plan, edits

    def call_json(self, prompt, schema, max_tokens=16000):
        if "properties" in schema and "changes" in schema["properties"]:
            return self.plan
        path = prompt.split("Change the file ", 1)[1].split(" ", 1)[0]
        return {"edits": self.edits.get(path, [])}


def test_update_only_edits_files_it_may(repo, monkeypatch):
    monkeypatch.setenv("TARGETS", "src,.github")
    monkeypatch.setenv("CONTEXT", "docs,src")
    update = importlib.import_module("update")
    assert update.TARGETS == ["src", ".github"] and update.CONTEXT == ["docs"]
    files = update.select(repo, update.TARGETS + update.CONTEXT, top_level=True)
    editable, context = update.split(files, update.TARGETS)
    assert list(editable) == ["pyproject.toml", "src/a.py", "src/sub/b.py"]
    assert list(context) == [".github/workflows/ci.yml", "docs/i.md"]
    text = update.blocks(editable, context)
    assert text.index("src/a.py") < text.index("<context>") < text.index("docs/i.md")
    assert "for reading only" in update.role(update.TARGETS, update.CONTEXT)
    plan = {"changes": [{"path": "src/a.py", "reason": "bump"}, {"path": "pyproject.toml", "reason": "bump"},
                        {"path": "src/new.py", "reason": "create it"}, {"path": "docs/i.md", "reason": "bump"},
                        {"path": ".github/workflows/ci.yml", "reason": "bump"}],
            "note": "CI needs a change too."}
    edits = {"src/a.py": [{"find": "3.12", "replace": "3.13"}],
             "pyproject.toml": [{"find": ">=3.12", "replace": ">=3.13"}, {"find": "missing", "replace": "x"}]}
    summary = "\n".join(update.update(FakeClaude(plan, edits), files, editable, "require 3.13"))
    assert (repo / "src/a.py").read_text() == "PY = '3.13'\n"
    assert (repo / "pyproject.toml").read_text() == "requires-python = '>=3.13'\n"
    assert not (repo / "src/new.py").exists()
    assert (repo / ".github/workflows/ci.yml").read_text() == "python: 3.12\n"
    assert "**skipped** `src/new.py`: it is not one of the files I may change" in summary
    assert "**skipped** `.github/workflows/ci.yml`: it may not be changed" in summary
    assert "**skipped** `docs/i.md`: it may not be changed" in summary and (repo / "docs/i.md").read_text() == "# Hi\n"
    assert "1 edit(s) could not be applied" in summary and summary.endswith("CI needs a change too.")


def test_ask_cites_docs_pages_only_for_docs(repo, monkeypatch):
    monkeypatch.setenv("DOCS_URL", "https://o.github.io/r/")
    monkeypatch.setenv("TARGETS", "docs")
    ask = importlib.import_module("ask")
    assert "https://o.github.io/r/<path>/" in ask.instructions()
    sys.modules.pop("ask")
    monkeypatch.setenv("CONTEXT", "src")
    ask = importlib.import_module("ask")
    assert ask.PATHS == ["docs", "src"]
    assert "by their path in the repository" in ask.instructions() and "`docs`, `src`" in ask.instructions()
    assert ask.MODEL == "claude-haiku-5-5"


def test_review_keeps_findings_in_the_reviewed_files(repo, monkeypatch):
    import json
    from types import SimpleNamespace as NS
    monkeypatch.setenv("TARGETS", "src")
    monkeypatch.setenv("CONTEXT", "docs")
    review = importlib.import_module("review")
    seen = {}
    found = [{"severity": "minor", "path": "src/a.py", "where": "", "problem": "old", "fix": "bump"},
             {"severity": "critical", "path": "docs/i.md", "where": "", "problem": "context", "fix": ""},
             {"severity": "major", "path": "src/sub/b.py", "where": "line 1", "problem": "wrong", "fix": ""}]

    class Stream:
        def __init__(self, **kw):
            seen.update(kw)
        def __enter__(self):
            return self
        def __exit__(self, *a):
            return False
        def get_final_message(self):
            text = json.dumps({"summary": "Two problems.", "findings": found})
            return NS(content=[NS(type="text", text=text)], stop_reason="end_turn", model="m",
                      usage=NS(input_tokens=1, cache_creation_input_tokens=0, cache_read_input_tokens=0, output_tokens=1))

    client = NS(beta=NS(messages=NS(stream=lambda **kw: Stream(**kw))))
    result = review.review("", client)
    assert seen["model"] == "claude-sonnet-5-5" and seen["output_config"]["effort"] == "low"
    system = "".join(b["text"] for b in seen["system"])
    assert '<reviewed>\n<file path="src/a.py">' in system and '<context>\n<file path="docs/i.md">' in system
    assert result["findings"] == "major" and result["files"] == ["src/a.py", "src/sub/b.py"]
    assert result["per_file"] == {"src/a.py": "minor", "src/sub/b.py": "major"}
    assert result["markdown"].splitlines()[2].startswith("- **major** `src/sub/b.py` (line 1): wrong")
    assert "context" not in result["markdown"]
    assert review.highest([]) == "none" and "No findings." in review.markdown("Fine.", [])
