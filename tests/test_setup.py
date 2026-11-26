"""`@IMGAgent setup ...`: the templates, reading them back, and the pull requests (no network, no AI)."""

import re
import subprocess
import tomllib

import pytest

from imgagent import commands, jobs, setup
from test_imgagent import branch_files, comment, full, make_origin, FakeApp

C = "IMGAgent"


# ---------------------------------------------------------------------------------------- routing

@pytest.mark.parametrize("body,target,done", [
    ("@IMGAgent setup reuse", "reuse", False),
    ("@IMGAgent SETUP AISignoff", "aisignoff", False),
    ("@IMGAgent setup citation done", "citation", True),
    ("@IMGAgent setup `docs`\nDone.", "docs", True),
])
def test_setup_commands(body, target, done):
    job = commands.find_command(body, C)
    assert job.kind == "setup" and job.args == {"target": target, "done": done}
    assert job.key("o/r", 7) == "o/r#write"


@pytest.mark.parametrize("body", ["@IMGAgent setup", "@IMGAgent setup ci", "@IMGAgent setup reuse,docs",
                                  "@IMGAgent setup docs with src"])
def test_setup_help(body):
    job = commands.find_command(body, C)
    assert job.kind == "help" and "`setup` knows `reuse`" in job.args["problem"]


def edited(after, before, user_type="Bot"):
    return {"action": "edited", "comment": {"body": after, "id": 5, "user": {"login": "imgagent[bot]", "type": user_type}},
            "changes": {"body": {"from": before}}, "issue": {"number": 7, "state": "open", "body": "", "title": "t"},
            "sender": {"login": "pascal", "type": "User"}}


def test_ticking_done_routes_to_setup_done():
    t = setup.docs_template("pascal", C, name="demo", description="", url="")
    ticked = t.replace("- [ ] **Done", "- [x] **Done")
    job = commands.route("issue_comment", edited(ticked, t), C)
    assert job.kind == "setup-done" and job.args == {"target": "docs", "comment_id": 5}
    assert job.key("o/r", 7) == "o/r#write"
    assert commands.route("issue_comment", edited(ticked, ticked), C) is None        # was ticked already
    assert commands.route("issue_comment", edited(t, ticked), C) is None             # unticked
    assert commands.route("issue_comment", edited(ticked, t, "User"), C) is None     # not IMGAgent's comment


# ------------------------------------------------------------------------------------------ forms

def tick(body, key, on=True):
    """Tick (or untick) the box of a line with this marker key."""
    pattern = r"\[[ xX]\](?=[^\n]*<!-- f:" + re.escape(key) + " -->)"
    new, n = re.subn(pattern, "[x]" if on else "[ ]", body)
    assert n == 1, key
    return new


def value(body, key, *values):
    """Replace the values between backticks on the line with this marker key."""
    def fill(m):
        it = iter(values)
        return re.sub(r"`[^`\n]*`", lambda span: f"`{v}`" if (v := next(it, None)) is not None else span[0], m[0])
    new, n = re.subn(r"^.*<!-- f:" + re.escape(key) + " -->.*$", fill, body, flags=re.M)
    assert n == 1, key
    return new


def test_reuse_template_and_result():
    t = setup.reuse_template("pascal", C, holder="Industrial Mathematics Group", license="MIT")
    assert t.startswith("<!-- imgagent-setup:reuse -->\n@pascal") and "- [x] MIT for `.`" in t
    t = value(tick(t, "license-CC-BY-4.0"), "license-CC-BY-4.0", "docs, README.md")
    t = value(tick(t, "other-2"), "other-2", "LicenseRef-Own", "data/*.csv")
    kinds = {"docs": True, "README.md": False}
    out, used = setup.reuse_annotations(setup.read_form(t), kinds.get)
    data = tomllib.loads(out)
    assert [a["path"] for a in data["annotations"]] == ["**", "README.md", "data/*.csv", "docs/**"]
    assert data["annotations"][0]["SPDX-FileCopyrightText"].endswith(" Industrial Mathematics Group")
    assert used == ["MIT", "CC-BY-4.0", "LicenseRef-Own"]


def test_reuse_same_folder_twice_and_mistakes():
    t = setup.reuse_template("pascal", C, holder="X", license="MIT")
    out, _ = setup.reuse_annotations(setup.read_form(value(tick(t, "license-Apache-2.0"), "license-Apache-2.0", ".")),
                                     lambda p: True)
    assert tomllib.loads(out)["annotations"] == [{"path": "**", "SPDX-FileCopyrightText": tomllib.loads(out)["annotations"][0]["SPDX-FileCopyrightText"],
                                                  "SPDX-License-Identifier": "MIT AND Apache-2.0"}]
    for body, problem in [(tick(t, "license-MIT", False), "tick at least one"),
                          (value(t, "license-MIT", ""), "has no folders"),
                          (value(t, "license-MIT", "nope"), "there is no `nope`"),
                          (value(tick(t, "other-2"), "other-2", "MIT OR", "."), "not a complete SPDX")]:
        with pytest.raises(setup.SetupError, match=problem):
            setup.reuse_annotations(setup.read_form(body), lambda p: None)


def test_signoff_template_defaults_make_a_valid_file():
    t = setup.signoff_template("pascal", C, reviewer="Pascal J", branch="main")
    out = setup.signoff_toml(setup.read_form(t))
    data = tomllib.loads(out)
    assert data["annotations"] == [{"path": "**", "AI-Generation": "G0", "Human-Review": "H2", "AI-Review": "A0",
                                    "Reviewed-by": ["Pascal J"]}]
    assert data["history"] == {"enabled": True, "default-branch": "main", "merge-method": "merge", "undeclared": "baseline"}
    assert "policy" not in data and "review" not in data


def test_signoff_choices_and_problems():
    t = setup.signoff_template("pascal", C, reviewer="P", branch="main")
    t = tick(tick(t, "generation=G0", False), "generation=G2")
    t = value(t, "assisted-by", "Claude Opus")
    t = tick(tick(t, "merge-method=merge", False), "merge-method=squash")
    t = tick(tick(t, "history", False), "policy-g3")
    t = value(t, "exclude", "reviews/**, build/**")
    data = tomllib.loads(setup.signoff_toml(setup.read_form(t)))
    assert data["annotations"][0]["AI-Generation"] == "G2" and data["annotations"][0]["Assisted-by"] == ["Claude Opus"]
    assert "history" not in data and data["exclude"] == ["reviews/**", "build/**"]
    assert data["policy"] == {"G3": {"human": "H2", "ai": "A1"}} and "review" not in data
    assert tomllib.loads(setup.signoff_toml(setup.read_form(value(t, "review-dir", "./ai-reviews/"))))["review"] == {"dir": "ai-reviews"}
    assert tomllib.loads(setup.signoff_toml(setup.read_form(value(t, "review-dir", " "))))["review"] == {"dir": ""}
    with pytest.raises(setup.SetupError, match="can't read"):
        setup.signoff_toml(setup.read_form(value(t, "review-dir", "../elsewhere")))
    with pytest.raises(setup.SetupError, match="tick exactly one box under \\*\\*AI-Generation"):
        setup.signoff_toml(setup.read_form(tick(t, "generation=G1")))
    with pytest.raises(setup.SetupError, match="doesn't fit together"):
        setup.signoff_toml(setup.read_form(value(t, "assisted-by", " ")))   # G2 without a model


def test_citation():
    t = setup.citation_template("pascal", C, title="agent", author="Pascal van Jung", license="MIT",
                                url="https://github.com/o/agent", abstract="A bot", keywords=["bot", "github"])
    t = value(value(t, "author-2", "Doe, Jane", "0000-0002-1825-0097"), "date-released", "2026-11-26")
    out = setup.citation_cff(setup.read_form(t))
    assert 'title: "agent"' in out and "type: software" in out and 'license: "MIT"' in out
    assert '  - family-names: "Jung"\n    given-names: "Pascal van"' in out
    assert '  - family-names: "Doe"\n    given-names: "Jane"\n    orcid: "https://orcid.org/0000-0002-1825-0097"' in out
    assert 'keywords:\n  - "bot"\n  - "github"' in out and 'date-released: "2026-11-26"' in out
    yaml = pytest.importorskip("yaml")
    assert yaml.safe_load(out)["authors"][1]["orcid"].endswith("1825-0097")
    for body, problem in [(value(t, "author-1", ""), None), (value(value(t, "author-1", ""), "author-2", "", ""), "at least one"),
                          (value(t, "date-released", "26.11.2026"), "is a date"), (value(t, "doi", "zenodo"), "not a DOI")]:
        if problem is None:
            setup.citation_cff(setup.read_form(body))
        else:
            with pytest.raises(setup.SetupError, match=problem):
                setup.citation_cff(setup.read_form(body))


def test_problem_and_finished():
    t = setup.docs_template("pascal", C, name="demo", description="", url="").replace("- [ ] **Done", "- [x] **Done")
    p = setup.with_problem(t, "bad url")
    assert "> bad url" in p and "- [ ] **Done" in p and not setup.is_done(p)
    p2 = setup.with_problem(p, "other")
    assert "bad url" not in p2 and p2.count("<!-- problem -->") == 1
    f = setup.finished(p2, "https://x/pull/9")
    assert "**Done:** https://x/pull/9" in f and setup.DONE not in f and "other" not in f
    assert setup.target_of(f) == "docs"


# ------------------------------------------------------------------------------------------- jobs

class Hub:
    """Records the API calls of a Context and answers them like GitHub would."""

    def __init__(self, files=()):
        self.calls, self.files, self.comments = [], set(files), {}

    def __call__(self, method, path, body=None, ok404=False):
        self.calls.append((method, path, body))
        if path.endswith("/permission"):
            return {"permission": "write"}
        if path.endswith("/pulls"):
            return {"number": 9, "html_url": "https://github.com/o/r/pull/9"}
        if "/contents/" in path:
            return {} if path.split("/contents/")[1].split("?")[0] in self.files else None
        if path.startswith("/users/"):
            return {"name": "Pascal J" if path.endswith("pascal") else None}
        if path.endswith("/reactions"):
            return {}
        if "/issues/comments/" in path:
            cid = int(path.rsplit("/", 1)[1])
            if method == "PATCH":
                self.comments[cid]["body"] = body["body"]
            return self.comments.get(cid)
        if path.endswith("/comments") and method == "POST":
            cid = 100 + len(self.comments)
            self.comments[cid] = {"id": cid, "body": body["body"], "user": {"login": "imgagent[bot]"},
                                  "html_url": f"https://github.com/o/r/issues/7#c{cid}"}
            return self.comments[cid]
        if "/comments?" in path:
            return list(self.comments.values())
        return {}

    def said(self):
        return [b["body"] for m, p, b in self.calls if m == "POST" and p.endswith("/comments")]


def context(monkeypatch, tmp_path, files, body="@IMGAgent setup x", repo_extra=None):
    origin = make_origin(tmp_path, files)
    monkeypatch.setattr(jobs.github, "clone", lambda repo, token, dest, **kw: subprocess.run(
        ["git", "clone", "-q", str(origin), str(dest)], check=True))
    monkeypatch.setattr(jobs.github, "set_token", lambda *a: None)
    payload = full(comment(body))
    payload["comment"]["html_url"] = "https://github.com/o/r/issues/7#c1"
    payload["repository"].update({"license": {"spdx_id": "MIT"}, "description": "A bot", **(repo_extra or {})})
    ctx = jobs.Context(FakeApp(), jobs.Config(), "issue_comment", payload)
    hub = Hub(files)
    monkeypatch.setattr(ctx, "api", hub)
    return ctx, hub, origin


def show(origin, branch, path):
    return subprocess.run(["git", "-C", str(origin), "show", f"{branch}:{path}"], capture_output=True, text=True).stdout


def test_setup_reuse_posts_the_template_then_opens_the_pull_request(monkeypatch, tmp_path):
    ctx, hub, origin = context(monkeypatch, tmp_path, {"a.py": "x\n", "docs/i.md": "#\n"})
    monkeypatch.setattr(jobs, "fetch_license", lambda i: f"{i} text\n" if i != "CC-BY-4.0" else None)
    jobs.do_setup(ctx, commands.Job("setup", {"target": "reuse", "done": False}))
    (cid, posted), = hub.comments.items()
    assert setup.target_of(posted["body"]) == "reuse" and "- [x] MIT for `.`" in posted["body"]
    # the person ticks CC BY for docs and Done in the rendered comment
    posted["body"] = tick(value(tick(posted["body"], "license-CC-BY-4.0"), "license-CC-BY-4.0", "docs"), "done")
    jobs.do_setup_done(ctx, commands.Job("setup-done", {"target": "reuse", "comment_id": cid}))

    branch, changed = branch_files(origin, "imgagent/setup-reuse-")
    assert sorted(c for c in changed if c) == ["A\tLICENSES/MIT.txt", "A\tREUSE.toml"]
    assert show(origin, branch, "LICENSES/MIT.txt") == "MIT text\n"
    assert tomllib.loads(show(origin, branch, "REUSE.toml"))["annotations"][1]["path"] == "docs/**"
    pr = next(b for m, p, b in hub.calls if p.endswith("/pulls"))
    assert pr["title"] == "Set up REUSE.toml" and "`LICENSES/CC-BY-4.0.txt` is missing" in pr["body"]
    assert "- [x] **G0**" in pr["body"] and "- [ ] **G3**" in pr["body"] and "- [x] **Claude" not in pr["body"]
    assert hub.comments[cid]["body"].endswith("**Done:** https://github.com/o/r/pull/9")
    assert hub.said()[-1].endswith("`setup reuse` is ready for review: https://github.com/o/r/pull/9")


def test_setup_problem_unticks_done_and_reply_done_finishes(monkeypatch, tmp_path):
    ctx, hub, origin = context(monkeypatch, tmp_path, {"a.py": "x\n"}, repo_extra={"license": None})
    jobs.do_setup(ctx, commands.Job("setup", {"target": "reuse", "done": False}))
    (cid, posted), = hub.comments.items()
    posted["body"] = tick(posted["body"], "done")
    jobs.do_setup_done(ctx, commands.Job("setup-done", {"target": "reuse", "comment_id": cid}))
    assert "tick at least one license" in hub.comments[cid]["body"] and not setup.is_done(hub.comments[cid]["body"])
    assert "I unticked **Done**" in hub.said()[-1]
    assert not any(p.endswith("/pulls") for m, p, b in hub.calls)

    monkeypatch.setattr(jobs, "fetch_license", lambda i: "text\n")
    hub.comments[cid]["body"] = value(tick(hub.comments[cid]["body"], "license-MIT"), "license-MIT", ".")
    jobs.do_setup(ctx, commands.Job("setup", {"target": "reuse", "done": True}))
    assert "problem" not in hub.comments[cid]["body"] and "**Done:** https://github.com/o/r/pull/9" in hub.comments[cid]["body"]
    jobs.do_setup(ctx, commands.Job("setup", {"target": "reuse", "done": True}))
    assert "no open `setup reuse` template" in hub.said()[-1]


def test_setup_refuses_existing_files_and_strangers_templates(monkeypatch, tmp_path):
    ctx, hub, origin = context(monkeypatch, tmp_path, {"CITATION.cff": "x\n"})
    jobs.do_setup(ctx, commands.Job("setup", {"target": "citation", "done": False}))
    assert "already has a `CITATION.cff`" in hub.said()[-1] and len(hub.said()) == 1
    hub.comments[5] = {"id": 5, "user": {"login": "pascal"}, "body": tick(setup.docs_template("p", C, name="n", description="", url=""), "done")}
    jobs.do_setup_done(ctx, commands.Job("setup-done", {"target": "docs", "comment_id": 5}))
    assert not any(p.endswith("/pulls") for m, p, b in hub.calls)


def test_setup_aisignoff_and_citation(monkeypatch, tmp_path):
    ctx, hub, origin = context(monkeypatch, tmp_path, {"a.py": "x\n"})
    for target in ("aisignoff", "citation"):
        jobs.do_setup(ctx, commands.Job("setup", {"target": target, "done": False}))
        cid = max(hub.comments)
        hub.comments[cid]["body"] = tick(hub.comments[cid]["body"], "done")
        jobs.do_setup_done(ctx, commands.Job("setup-done", {"target": target, "comment_id": cid}))
    branch, _ = branch_files(origin, "imgagent/setup-aisignoff-")
    assert tomllib.loads(show(origin, branch, "SIGNOFF.toml"))["annotations"][0]["Reviewed-by"] == ["Pascal J"]
    r = subprocess.run(["git", "-C", str(origin), "show", f"{branch}:SIGNOFF.toml"], capture_output=True, text=True)
    branch, _ = branch_files(origin, "imgagent/setup-citation-")
    cff = show(origin, branch, "CITATION.cff")
    assert '  - family-names: "J"\n    given-names: "Pascal"' in cff and 'abstract: "A bot"' in cff


def test_setup_docs(monkeypatch, tmp_path):
    files = {"docs/guide/install.md": "# Install it\n", "docs/guide/index.md": "# Guide\n", "docs/faq.md": "# FAQ\n"}
    ctx, hub, origin = context(monkeypatch, tmp_path, files)
    jobs.do_setup(ctx, commands.Job("setup", {"target": "docs", "done": False}))
    cid = max(hub.comments)
    hub.comments[cid]["body"] = tick(value(value(hub.comments[cid]["body"], "name", "Demo"), "url", ""), "done")
    jobs.do_setup_done(ctx, commands.Job("setup-done", {"target": "docs", "comment_id": cid}))
    branch, changed = branch_files(origin, "imgagent/setup-docs-")
    assert sorted(c for c in changed if c) == ["A\tdocs/index.md", "A\tzensical.toml"]
    data = tomllib.loads(show(origin, branch, "zensical.toml"))["project"]
    assert data["site_name"] == "Demo" and "site_url" not in data
    assert data["nav"] == [{"Demo": "index.md"}, {"FAQ": "faq.md"}, {"Guide": ["guide/index.md", "guide/install.md"]}]
