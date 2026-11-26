"""`@IMGAgent setup reuse|aisignoff|docs`: reading the settings, and the pull requests (no network, no AI)."""

import subprocess
import tomllib

import pytest

from imgagent import commands, jobs, setup
from test_imgagent import branch_files, comment, fake_context, make_origin

C = "IMGAgent"


@pytest.mark.parametrize("body,target,text", [
    ("@IMGAgent setup reuse\nlicense: MIT", "reuse", "license: MIT"),
    ("@IMGAgent SETUP AISignoff G2 H1 A0", "aisignoff", "G2 H1 A0"),
    ("@IMGAgent setup docs", "docs", ""),
    ("@IMGAgent setup `docs`\nname: x", "docs", "name: x"),
])
def test_setup_commands(body, target, text):
    job = commands.find_command(body, C)
    assert job.kind == "setup" and job.args == {"target": target, "text": text}
    assert job.key("o/r", 7) == "o/r#write"


@pytest.mark.parametrize("body", ["@IMGAgent setup", "@IMGAgent setup ci", "@IMGAgent setup reuse,docs",
                                  "@IMGAgent setup docs with src"])
def test_setup_help(body):
    job = commands.find_command(body, C)
    assert job.kind == "help" and "`setup` knows `reuse`" in job.args["problem"]


def test_reuse_from_lines():
    text = ("- path: **\ncopyright: 2026 Jane Doe\nCopyright: SPDX-FileCopyrightText: 2025 Acme\nlicense: MIT\n\n"
            "```\npath: docs/**, *.md\nSPDX-License-Identifier: CC-BY-4.0 OR (MIT AND Apache-2.0)\n"
            "precedence: Override\n```")
    out, used = setup.reuse_toml(text)
    data = tomllib.loads(out)
    assert data["version"] == 1
    assert data["annotations"] == [
        {"path": "**", "SPDX-FileCopyrightText": ["2026 Jane Doe", "2025 Acme"], "SPDX-License-Identifier": "MIT"},
        {"path": ["docs/**", "*.md"], "precedence": "override",
         "SPDX-License-Identifier": "CC-BY-4.0 OR (MIT AND Apache-2.0)"}]
    assert used == ["MIT", "CC-BY-4.0", "Apache-2.0"]


def test_reuse_without_path_means_everything_and_toml_is_taken_as_is():
    out, _ = setup.reuse_toml("license: MIT")
    assert tomllib.loads(out)["annotations"] == [{"path": "**", "SPDX-License-Identifier": "MIT"}]
    out, used = setup.reuse_toml('```toml\nversion = 1\n[[annotations]]\npath = "src/**"\n'
                                 'SPDX-FileCopyrightText = "2026 X"\nSPDX-License-Identifier = "LicenseRef-Own"\n```')
    assert tomllib.loads(out)["annotations"][0]["path"] == "src/**" and used == ["LicenseRef-Own"]


@pytest.mark.parametrize("text,problem", [
    ("licnse: MIT", "I don't know the setting `licnse`"),
    ("path: src/**", "needs a copyright or a license"),
    ("license: MIT\n\nlicense: Apache-2.0", "annotation 2 has no `path`"),
    ("license: MIT OR", "not a complete SPDX"),
    ("license: MIT and Apache", "not an SPDX license expression"),
    ("path: ../x\nlicense: MIT", "relative paths"),
    ("path: **\nlicense: MIT\nprecedence: first", "precedence is one of"),
    ('[[annotations]]\npath = "**"\nSPDX-License-Identifier = "MIT"\nfoo = 1', "don't know `foo`"),
    ('[[annotations]]\npath = "**', "isn't valid TOML"),
    ("", "no annotations"),
])
def test_reuse_mistakes(text, problem):
    with pytest.raises(setup.SetupError, match=__import__("re").escape(problem)):
        setup.reuse_toml(text)


def test_aisignoff_args():
    assert setup.aisignoff_args("") == [] and setup.aisignoff_args("please set this up") == []
    assert setup.aisignoff_args("G2 H1 A0\nreviewed-by: Jane Doe, Max\nassisted-by: Claude Opus") == [
        "--generation", "G2", "--human", "H1", "--ai", "A0",
        "--assisted-by", "Claude Opus", "--reviewed-by", "Jane Doe", "--reviewed-by", "Max"]
    assert setup.aisignoff_args("generation: g0\nhuman review: todo\nAI-Review: A0") == [
        "--generation", "G0", "--human", "TODO", "--ai", "A0"]
    for text, problem in [("G2 H1", "missing: ai"), ("G2 G3 H1 A0", "two different levels"),
                          ("generation: H1\nH1 A0", "G0 to G3"), ("reviewed-by: Jane", "go with the three levels")]:
        with pytest.raises(setup.SetupError, match=problem):
            setup.aisignoff_args(text)


def test_docs_settings():
    assert setup.docs_settings("Name: Demo\nsite url: https://x.org/demo/") == {"name": "Demo", "url": "https://x.org/demo/"}
    with pytest.raises(setup.SetupError, match="address of the site"):
        setup.docs_settings("url: example")


def run_setup(monkeypatch, tmp_path, files, target, text):
    origin = make_origin(tmp_path, files)
    payload = comment(f"@IMGAgent setup {target}\n{text}")
    payload["comment"]["html_url"] = "https://github.com/o/r/issues/7#c1"
    ctx, calls = fake_context(monkeypatch, tmp_path, payload, origin)
    jobs.do_setup(ctx, commands.Job("setup", {"target": target, "text": text}))
    return origin, calls


def show(origin, branch, path):
    return subprocess.run(["git", "-C", str(origin), "show", f"{branch}:{path}"], capture_output=True, text=True).stdout


def test_setup_reuse_opens_a_pull_request(monkeypatch, tmp_path):
    origin, calls = run_setup(monkeypatch, tmp_path, {"LICENSES/MIT.txt": "MIT\n", "a.py": "x\n"}, "reuse",
                              "path: **\ncopyright: 2026 Jane\nlicense: MIT OR Apache-2.0")
    branch, changed = branch_files(origin, "imgagent/setup-reuse-")
    assert [c for c in changed if c] == ["A\tREUSE.toml"]
    assert tomllib.loads(show(origin, branch, "REUSE.toml"))["annotations"][0]["SPDX-FileCopyrightText"] == "2026 Jane"
    pr = next(b for m, p, b in calls if p.endswith("/pulls"))
    assert pr["title"] == "Set up REUSE.toml" and "`Apache-2.0`" in pr["body"] and "MIT`" not in pr["body"]
    assert "- [x] **G0**" in pr["body"] and "- [ ] **G3**" in pr["body"] and "- [x] **Claude" not in pr["body"]
    assert calls[-1][2]["body"].endswith("`setup reuse` is ready for review: https://github.com/o/r/pull/9")


def test_setup_refuses_mistakes_and_existing_files(monkeypatch, tmp_path):
    origin, calls = run_setup(monkeypatch, tmp_path, {"REUSE.toml": "version = 1\n"}, "reuse", "license: MIT")
    assert "already has a `REUSE.toml`" in calls[-1][2]["body"] and "update REUSE.toml" in calls[-1][2]["body"]
    _, calls = run_setup(monkeypatch, tmp_path / "2", {"a": "x"}, "reuse", "")
    assert "write the annotations" in calls[-1][2]["body"] and "license: MIT" in calls[-1][2]["body"]
    _, calls = run_setup(monkeypatch, tmp_path / "3", {"a": "x"}, "aisignoff", "G2")
    assert "give all three levels" in calls[-1][2]["body"]
    assert not any(p.endswith("/pulls") for m, p, b in calls)


def test_setup_aisignoff_runs_aisignoff_init(monkeypatch, tmp_path):
    origin, calls = run_setup(monkeypatch, tmp_path, {"a.py": "x\n"}, "aisignoff", "G0 H2 A0\nreviewed-by: Jane Doe")
    branch, changed = branch_files(origin, "imgagent/setup-aisignoff-")
    assert [c for c in changed if c] == ["A\tSIGNOFF.toml"]
    data = tomllib.loads(show(origin, branch, "SIGNOFF.toml"))
    assert data["annotations"][0]["path"] == "**" and data["annotations"][0]["Human-Review"] == "H2"
    pr = next(b for m, p, b in calls if p.endswith("/pulls"))
    assert "aisignoff init --generation G0 --human H2 --ai A0 --reviewed-by Jane Doe" in pr["body"]


def test_setup_aisignoff_template(monkeypatch, tmp_path):
    origin, calls = run_setup(monkeypatch, tmp_path, {"a.py": "x\n"}, "aisignoff", "")
    branch, _ = branch_files(origin, "imgagent/setup-aisignoff-")
    assert "# [[annotations]]" in show(origin, branch, "SIGNOFF.toml")
    assert "commented template" in next(b for m, p, b in calls if p.endswith("/pulls"))["body"]


def test_setup_docs_creates_zensical_toml(monkeypatch, tmp_path):
    files = {"docs/guide/install.md": "# Install it\n", "docs/guide/index.md": "# Guide\n", "docs/faq.md": "# FAQ\n"}
    origin, calls = run_setup(monkeypatch, tmp_path, files, "docs", "name: Demo\nurl: none")
    branch, changed = branch_files(origin, "imgagent/setup-docs-")
    assert sorted(c for c in changed if c) == ["A\tdocs/index.md", "A\tzensical.toml"]
    data = tomllib.loads(show(origin, branch, "zensical.toml"))["project"]
    assert data["site_name"] == "Demo" and "site_url" not in data and data["repo_name"].endswith("/agent-sandbox")
    assert data["nav"] == [{"Demo": "index.md"}, {"FAQ": "faq.md"},
                           {"Guide": ["guide/index.md", "guide/install.md"]}]
    assert "placeholder" in next(b for m, p, b in calls if p.endswith("/pulls"))["body"]
