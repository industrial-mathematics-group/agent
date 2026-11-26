"""`@IMGAgent setup reuse|aisignoff|citation|docs`: a template to fill in, then the file. No AI, no network.

`setup <target>` posts a comment with a form whose defaults are already filled in: tick boxes, change the values
between backticks (Edit the comment), then tick "Done". IMGAgent turns the form into the file and opens a pull
request (or, if something can't be used, unticks "Done" and says why). Replying `setup <target> done` does the same
as ticking it.

Each line of the form ends with an invisible marker, so people may change the wording around the values:

    - **Default path:** `**` <!-- f:path -->                 a text field: the values between backticks
    - [x] Use the git history <!-- f:history -->             a checkbox (with or without values)
    - [x] G0 Written by a human <!-- f:generation=G0 -->     one choice of a group: tick exactly one
"""

from __future__ import annotations

import datetime
import json
import re
import tomllib
from dataclasses import dataclass, field
from pathlib import PurePosixPath

TARGETS = {"reuse": "REUSE.toml", "aisignoff": "SIGNOFF.toml", "citation": "CITATION.cff", "docs": "zensical.toml"}
MARKER = "<!-- imgagent-setup:{target} -->"
_MARKER = re.compile(r"<!-- imgagent-setup:([a-z]+) -->")
DONE = "<!-- f:done -->"
_PROBLEM = re.compile(r"<!-- problem -->.*?<!-- /problem -->\n*", re.S)
_LINE = re.compile(r"^(?P<lead>\s*[-*+]\s+)?(?:\[(?P<box>[ xX])\]\s*)?(?P<text>.*?)\s*<!-- f:(?P<key>[\w.+-]+)(?:=(?P<choice>[\w.+-]+))? -->\s*$")


class SetupError(ValueError):
    """The form can't be used; the message says why, for the reply."""


def target_of(body: str) -> str | None:
    """The target of a setup template comment, or None for any other comment."""
    m = _MARKER.search(body or "")
    return m[1] if m and m[1] in TARGETS else None


def is_done(body: str) -> bool:
    """Is "Done" ticked in the template?"""
    return any(f.key == "done" and f.checked for f in read_form(body).lines)


# ------------------------------------------------------------------------------------------ forms

@dataclass
class Line:
    key: str
    checked: bool | None          # None: a text field without a box
    values: list[str]
    choice: str | None = None


@dataclass
class Form:
    lines: list[Line] = field(default_factory=list)

    def text(self, key: str, default: str = "") -> str:
        line = self.line(key)
        return line.values[0] if line and line.values else default

    def line(self, key: str) -> Line | None:
        return next((l for l in self.lines if l.key == key and l.choice is None), None)

    def checked(self, key: str) -> bool:
        line = self.line(key)
        return bool(line and line.checked)

    def choice(self, key: str, label: str) -> str:
        ticked = [l.choice for l in self.lines if l.key == key and l.choice is not None and l.checked]
        if len(ticked) != 1:
            raise SetupError(f"tick exactly one box under **{label}** ({'none' if not ticked else ', '.join(ticked)} is ticked).")
        return ticked[0]

    def items(self, prefix: str) -> list[Line]:
        return [l for l in self.lines if l.key.startswith(prefix) and l.choice is None]


def read_form(body: str) -> Form:
    form = Form()
    for raw in (body or "").replace("\r\n", "\n").splitlines():
        m = _LINE.match(raw)
        if not m:
            continue
        values = [v.strip() for v in re.findall(r"`([^`\n]*)`", m["text"])]
        if not values and m["box"] is None and ":" in m["text"]:
            values = [m["text"].rsplit(":", 1)[1].strip(" *")]   # backticks deleted while editing
        for v in values:
            if len(v) > 300:
                raise SetupError("a value is longer than 300 characters.")
        form.lines.append(Line(m["key"], None if m["box"] is None else m["box"] != " ", values, m["choice"]))
    return form


def _code(value: str) -> str:
    return f"`{value}`" if value else "` `"


def text_field(key: str, label: str, value: str, hint: str = "") -> str:
    return f"- **{label}:** {_code(value)}{f' <sub>{hint}</sub>' if hint else ''} <!-- f:{key} -->"


def box(key: str, label: str, checked: bool) -> str:
    return f"- [{'x' if checked else ' '}] {label} <!-- f:{key} -->"


def choices(key: str, title: str, options: list[tuple[str, str]], default: str) -> list[str]:
    return [f"**{title}** (tick one)", ""] + [f"- [{'x' if v == default else ' '}] {label} <!-- f:{key}={v} -->"
                                              for v, label in options] + [""]


def frame(target: str, actor: str, intro: str, body: list[str], handle: str) -> str:
    name = TARGETS[target]
    return "\n".join([
        MARKER.format(target=target),
        f"@{actor} here is the template for `{name}`, with defaults filled in. {intro}".rstrip(),
        "",
        f"Change what you need (*⋯ → Edit* this comment: tick boxes and change the values between backticks), "
        f"then tick **Done**, or reply `@{handle} setup {target} done`. IMGAgent then opens a pull request with "
        f"`{name}`, written from this form without AI.",
        "", *body, "---", "",
        f"- [ ] **Done: create the pull request** {DONE}",
    ])


def with_problem(body: str, problem: str) -> str:
    """The template with "Done" unticked and the problem on top (replacing an earlier one)."""
    body = _PROBLEM.sub("", body)
    body = re.sub(r"\[[xX]\](?=[^\n]*" + re.escape(DONE) + ")", "[ ]", body)
    head, _, rest = body.partition("\n")
    return f"{head}\n<!-- problem -->\n> [!WARNING]\n> {problem}\n<!-- /problem -->\n\n{rest}"


def finished(body: str, pr_url: str) -> str:
    """The template after its pull request: no problem, and no "Done" box that could run it again."""
    body = _PROBLEM.sub("", body)
    return re.sub(r"^.*" + re.escape(DONE) + r".*$", f"**Done:** {pr_url}", body, flags=re.M)


def _string(value: str) -> str:
    """A TOML or YAML double-quoted string (JSON's escapes are valid in both)."""
    return json.dumps(value, ensure_ascii=False)


def _list(raw: str) -> list[str]:
    return [v.strip() for v in re.split(r"[,;]", raw or "") if v.strip()]


# ------------------------------------------------------------------------------------------ REUSE

COMMON_LICENSES = [
    ("MIT", "MIT"), ("Apache-2.0", "Apache 2.0"), ("BSD-3-Clause", "BSD 3-Clause"),
    ("GPL-3.0-or-later", "GPL 3.0 or later"), ("LGPL-3.0-or-later", "LGPL 3.0 or later"),
    ("AGPL-3.0-or-later", "AGPL 3.0 or later"), ("MPL-2.0", "Mozilla Public License 2.0"), ("EUPL-1.2", "EUPL 1.2"),
    ("CC-BY-4.0", "CC BY 4.0 (texts, figures)"), ("CC-BY-SA-4.0", "CC BY-SA 4.0"), ("CC0-1.0", "CC0 1.0 (public domain)"),
]
_LICENSE_ID = re.compile(r"^(LicenseRef-[A-Za-z0-9.-]+|[A-Za-z0-9][A-Za-z0-9.+-]*)$")
_PATH = re.compile(r"^[^\s\"'\\]+$")


def license_ids(expression: str) -> list[str]:
    """The license identifiers of an SPDX expression ("MIT OR Apache-2.0" -> both); SetupError if malformed."""
    words = expression.replace("(", " ( ").replace(")", " ) ").split()
    ids, depth, want_id = [], 0, True
    for w in words:
        if w == "(" and want_id:
            depth += 1
        elif w == ")" and not want_id and depth:
            depth -= 1
        elif w in ("AND", "OR", "WITH") and not want_id:
            want_id = True
        elif want_id and _LICENSE_ID.match(w) and w.upper() not in ("AND", "OR", "WITH"):
            ids.append(w)
            want_id = False
        else:
            raise SetupError(f"`{expression}` is not an SPDX license expression such as `MIT` or `MIT OR Apache-2.0`.")
    if want_id or depth:
        raise SetupError(f"`{expression}` is not a complete SPDX license expression.")
    return ids


def reuse_template(actor: str, handle: str, *, holder: str, license: str | None) -> str:
    year = datetime.date.today().year
    known = {i for i, _ in COMMON_LICENSES}
    body = [text_field("copyright", "Copyright", f"{year} {holder}", "for every file below"), "",
            "**Licenses** (tick the ones to use, and the folders each is for: comma-separated, `.` is everything; "
            "IMGAgent adds their texts to `LICENSES/`)", ""]
    body += [box(f"license-{i}", f"{label} for {_code('.' if i == license else '')}", i == license)
             for i, label in COMMON_LICENSES]
    other = license if license and license not in known else ""
    body += [box("other-1", f"Other license {_code(other)} for {_code('.' if other else '')}", bool(other)),
             box("other-2", f"Other license {_code('')} for {_code('')}", False),
             "", "<sub>Other license: an SPDX identifier from https://spdx.org/licenses/ or an expression such as "
             "`MIT OR Apache-2.0`. A folder may also be a file or a glob such as `docs/**/*.png`.</sub>", ""]
    intro = ("Which licenses apply to which folders?" if not license else
             f"The repository's license `{license}` is already ticked for everything.")
    return frame("reuse", actor, intro, body, handle)


def reuse_annotations(form: Form, is_dir) -> tuple[str, list[str]]:
    """REUSE.toml from the form, and the license identifiers it uses. is_dir(path): True for a folder, False for
    a file, None when the path doesn't exist."""
    copyright = form.text("copyright")
    picked: list[tuple[str, str]] = []
    for line in form.items("license-") + form.items("other-"):
        if not line.checked:
            continue
        if line.key.startswith("license-"):
            expr, folders = line.key[len("license-"):], (line.values[0] if line.values else "")
        else:
            expr, folders = (line.values + ["", ""])[:2]
            if not expr:
                raise SetupError("a ticked *Other license* has no license.")
        license_ids(expr)
        if not folders:
            raise SetupError(f"`{expr}` is ticked but has no folders: write `.` for everything.")
        picked += [(f, expr) for f in _list(folders)]
    if not picked:
        raise SetupError("tick at least one license.")
    by_path: dict[str, list[str]] = {}
    for folder, expr in picked:
        by_path.setdefault(_reuse_path(folder, is_dir), []).append(expr)
    # The last matching annotation wins: everything first, then the more specific paths.
    order = sorted(by_path, key=lambda p: (p != "**", p.count("/"), p))
    lines = ["# REUSE (https://reuse.software): the copyright and license of files that can't carry a header.",
             "# Check with: pipx run reuse lint", "version = 1"]
    used: list[str] = []
    for path in order:
        exprs = by_path[path]
        expr = exprs[0] if len(exprs) == 1 else " AND ".join(f"({e})" if " " in e else e for e in exprs)
        lines += ["", "[[annotations]]", f"path = {_string(path)}"]
        if copyright:
            lines.append(f"SPDX-FileCopyrightText = {_string(copyright)}")
        lines.append(f"SPDX-License-Identifier = {_string(expr)}")
        used += [i for i in license_ids(expr) if i not in used]
    out = "\n".join(lines) + "\n"
    tomllib.loads(out)
    return out, used


def _reuse_path(folder: str, is_dir) -> str:
    folder = folder.strip().strip("`")
    while folder.startswith("./"):
        folder = folder[2:]
    folder = folder.rstrip("/")
    if folder in ("", ".", "*", "**"):
        return "**"
    if not _PATH.match(folder) or folder.startswith("/") or ".." in PurePosixPath(folder).parts:
        raise SetupError(f"`{folder}` is not a folder of this repository; write e.g. `.`, `src` or `docs/**`.")
    if any(c in folder for c in "*?["):
        return folder
    kind = is_dir(folder)
    if kind is None:
        raise SetupError(f"there is no `{folder}` in this repository.")
    return f"{folder}/**" if kind else folder


# ------------------------------------------------------------------------------------- aisignoff

GENERATION = [("G0", "G0 written by people, without AI"), ("G1", "G1 AI-assisted"), ("G2", "G2 AI-generated"),
              ("G3", "G3 AI-autonomous"), ("TODO", "TODO: left for a person")]
HUMAN = [("H0", "H0 checked as a whole"), ("H1", "H1 tested"), ("H2", "H2 read line by line"),
         ("H3", "H3 independently validated"), ("TODO", "TODO: left for a person")]
AI_REVIEW = [("A0", "A0 no independent AI review"), ("A1", "A1 context-free check"),
             ("A2", "A2 check by a different model"), ("A3", "A3 validated by a different model"),
             ("TODO", "TODO: left for a person")]


def signoff_template(actor: str, handle: str, *, reviewer: str, branch: str) -> str:
    body = ["**Default declaration** (for the files that match, unless the git history says more)", "",
            text_field("path", "Paths", "**", "comma-separated globs; `**` is every file"),
            text_field("reviewed-by", "Reviewed-by", reviewer, "the responsible people, comma-separated"),
            text_field("assisted-by", "Assisted-by", "", "the AI models, for G1 to G3"),
            text_field("ai-reviewed-by", "AI-Reviewed-by", "", "the reviewing models, for A1 to A3"), ""]
    body += choices("generation", "AI-Generation", GENERATION, "G0")
    body += choices("human", "Human-Review", HUMAN, "H2")
    body += choices("ai", "AI-Review", AI_REVIEW, "A0")
    body += ["**History** (line-level declarations from the commits' trailers)", "",
             box("history", "Use the git history (`[history]`)", True),
             text_field("default-branch", "Default branch", branch)]
    body += [""] + choices("merge-method", "How pull requests are merged", [("merge", "merge commit"),
                                                                           ("squash", "squash"), ("rebase", "rebase")], "merge")
    body += choices("undeclared", "Commits that declare nothing", [
        ("baseline", "count with the default declaration above"), ("error", "are an error")], "baseline")
    body += ["**More** (optional)", "",
             text_field("exclude", "Files that need no declaration", "", "comma-separated globs, e.g. `reviews/**`"),
             box("policy-all", "Every file needs at least human review `H1`", False),
             box("policy-g3", "G3 files need at least human review `H2` and AI review `A1`", False), ""]
    body += choices("recheck", "AI review findings that need a new review, from", [
        (s, s) for s in ("trivial", "minor", "major", "critical")], "major")
    return frame("aisignoff", actor, "", body, handle)


def signoff_toml(form: Form) -> str:
    from aisignoff import config as aiconfig, model

    paths = _list(form.text("path")) or ["**"]
    values = {"AI-Generation": form.choice("generation", "AI-Generation"),
              "Human-Review": form.choice("human", "Human-Review"),
              "AI-Review": form.choice("ai", "AI-Review")}
    for key, field_ in (("Assisted-by", "assisted-by"), ("AI-Reviewed-by", "ai-reviewed-by"), ("Reviewed-by", "reviewed-by")):
        if names := _list(form.text(field_)):
            values[key] = names
    lines = ["# AI declarations for this repository: generation (G0-G3), human review (H0-H3)",
             "# and AI review (A0-A3). Set up by IMGAgent; check with: aisignoff lint",
             "# The LAST annotation that matches a file wins.", f"version = {aiconfig.VERSION}"]
    if exclude := _list(form.text("exclude")):
        lines.append(f"exclude = [{', '.join(_string(e) for e in exclude)}]")
    policy = []
    if (line := form.line("policy-all")) and line.checked:
        policy.append(f'"*" = {{ human = {_string((line.values or ["H1"])[0].upper())} }}')
    if (line := form.line("policy-g3")) and line.checked:
        human, ai = (line.values + ["H2", "A1"])[:2]
        policy.append(f"G3 = {{ human = {_string(human.upper())}, ai = {_string(ai.upper())} }}")
    if policy:
        lines += ["", "[policy]", *policy]
    recheck = form.choice("recheck", "AI review findings")
    if recheck != model.RECHECK:
        lines += ["", "[review]", f"recheck = {_string(recheck)}"]
    lines += ["", "[[annotations]]",
              f"path = {_string(paths[0]) if len(paths) == 1 else '[' + ', '.join(_string(p) for p in paths) + ']'}"]
    for key, value in values.items():
        lines.append(f"{key} = {_string(value) if isinstance(value, str) else '[' + ', '.join(_string(v) for v in value) + ']'}")
    if form.checked("history"):
        lines += ["", "[history]", "enabled = true"]
        if branch := form.text("default-branch"):
            lines.append(f"default-branch = {_string(branch)}")
        lines.append(f"merge-method = {_string(form.choice('merge-method', 'How pull requests are merged'))}")
        lines.append(f"undeclared = {_string(form.choice('undeclared', 'Commits that declare nothing'))}")
    out = "\n".join(lines) + "\n"
    try:
        cfg = aiconfig.load_text(out, PurePosixPath(aiconfig.FILENAME))
    except (aiconfig.ConfigError, ValueError) as e:
        raise SetupError(f"aisignoff can't read the result: {e}") from None
    problems = model.validate(cfg.annotations[0].declaration(), cfg.policy, allow_todo=True)
    if problems:
        raise SetupError("the default declaration doesn't fit together: " + "; ".join(problems) + ".")
    return out


# ------------------------------------------------------------------------------------- citation

def citation_template(actor: str, handle: str, *, title: str, author: str, license: str | None, url: str,
                      abstract: str, keywords: list[str]) -> str:
    body = [text_field("title", "Title", title),
            text_field("message", "Message", "If you use this software, please cite it as below."),
            ""] + choices("type", "Type", [("software", "software"), ("dataset", "dataset")], "software")
    body += ["**Authors** (as `Given Family` or `Family, Given`, optionally with an ORCID; add lines as you need)", ""]
    body += [f"- **Author:** {_code(a)} ORCID {_code('')} <!-- f:author-{n} -->" for n, a in
             enumerate([author, "", ""], 1)]
    body += ["", text_field("version", "Version", "", "e.g. `1.0.0`"),
             text_field("date-released", "Date released", "", "YYYY-MM-DD"),
             text_field("license", "License", license or "", "SPDX identifier"),
             text_field("repository-code", "Repository", url),
             text_field("url", "Website", ""),
             text_field("doi", "DOI", "", "e.g. `10.5281/zenodo.1234567`"),
             text_field("abstract", "Abstract", abstract),
             text_field("keywords", "Keywords", ", ".join(keywords), "comma-separated"), ""]
    return frame("citation", actor, "", body, handle)


def _author(raw: str, orcid: str) -> list[str]:
    raw = " ".join(raw.split())
    if "," in raw:
        family, given = (p.strip() for p in raw.split(",", 1))
    elif " " in raw:
        given, family = raw.rsplit(" ", 1)
    else:
        given, family = "", raw
    out = [f"  - family-names: {_string(family)}"]
    if given:
        out.append(f"    given-names: {_string(given)}")
    if orcid:
        orcid = orcid.removeprefix("https://orcid.org/")
        if not re.fullmatch(r"\d{4}-\d{4}-\d{4}-\d{3}[\dX]", orcid):
            raise SetupError(f"`{orcid}` is not an ORCID such as `0000-0002-1825-0097`.")
        out.append(f"    orcid: {_string('https://orcid.org/' + orcid)}")
    return out


def citation_cff(form: Form) -> str:
    title = form.text("title")
    if not title:
        raise SetupError("the citation needs a **Title**.")
    lines = ["# How to cite this repository: https://citation-file-format.github.io", "cff-version: 1.2.0",
             f"message: {_string(form.text('message') or 'If you use this software, please cite it as below.')}",
             f"type: {form.choice('type', 'Type')}", f"title: {_string(title)}", "authors:"]
    authors = [l for l in form.items("author-") if l.values and l.values[0]]
    if not authors:
        raise SetupError("the citation needs at least one **Author**.")
    for line in authors:
        lines += _author(line.values[0], line.values[1] if len(line.values) > 1 else "")
    if version := form.text("version"):
        lines.append(f"version: {_string(version)}")
    if date := form.text("date-released"):
        try:
            datetime.date.fromisoformat(date)
        except ValueError:
            raise SetupError(f"**Date released** is a date such as `2026-11-26`, not `{date}`.") from None
        lines.append(f"date-released: {_string(date)}")
    if license := form.text("license"):
        license_ids(license)
        lines.append(f"license: {_string(license)}")
    for key in ("repository-code", "url"):
        if value := form.text(key):
            if not re.fullmatch(r"https?://[^\s\"'<>]+", value):
                raise SetupError(f"`{value}` is not a web address.")
            lines.append(f"{key}: {_string(value)}")
    if doi := form.text("doi").removeprefix("https://doi.org/"):
        if not re.fullmatch(r"10\.\d{4,9}/\S+", doi):
            raise SetupError(f"`{doi}` is not a DOI such as `10.5281/zenodo.1234567`.")
        lines.append(f"doi: {_string(doi)}")
    if abstract := form.text("abstract"):
        lines.append(f"abstract: {_string(abstract)}")
    if keywords := _list(form.text("keywords")):
        lines += ["keywords:"] + [f"  - {_string(k)}" for k in keywords]
    return "\n".join(lines) + "\n"


# ------------------------------------------------------------------------------------------ docs

def docs_template(actor: str, handle: str, *, name: str, description: str, url: str) -> str:
    body = [text_field("name", "Site name", name),
            text_field("description", "Description", description),
            text_field("url", "Address", url, "where the site is published; empty for none"), "",
            "<sub>The nav lists the pages already in `docs/`; without `docs/index.md`, a placeholder home page is "
            "added. `make docs` writes the pages from the code.</sub>", ""]
    return frame("docs", actor, "", body, handle)


def docs_settings(form: Form) -> dict[str, str]:
    url = form.text("url")
    if url and not re.fullmatch(r"https?://[^\s\"'<>]+", url):
        raise SetupError(f"**Address** is a web address such as `https://org.github.io/project/`, not `{url}`.")
    if not form.text("name"):
        raise SetupError("the site needs a **Site name**.")
    return {"DOCS_PROJECT": form.text("name"), "DOCS_ABOUT": form.text("description"), "DOCS_URL": url}
