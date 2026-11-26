"""`@IMGAgent setup reuse|aisignoff|docs`: read the settings people write below the command. No AI, no network.

The text is read as "key: value" lines (or "key = value"); lines in a ``` block count as well. Keys are case
insensitive and may be written with spaces, "-" or "_". A key that isn't known is an error, so a typo never
silently leaves a setting out. Blank lines and lines without a key are ignored.

    setup reuse                     REUSE.toml (https://reuse.software/spec/), one [[annotations]] table per
    path: **                        group: a new "path" line or a blank line after a complete group starts
    copyright: 2026 Jane Doe        the next one. Repeat copyright or license lines for more than one; paths
    license: MIT                    are comma-separated. A whole REUSE.toml (with [[annotations]]) in a
                                    ```toml block is checked and used as it is.
    path: docs/**
    license: CC-BY-4.0

    setup aisignoff                 SIGNOFF.toml through `aisignoff init`: without settings the commented
    G2 H1 A0                        template; with the three levels (as "G2 H1 A0" or "generation: G2", ...)
    reviewed-by: Jane Doe           also a default annotation for every file.
    assisted-by: Claude Opus

    setup docs                      zensical.toml as `make docs` creates it, with the nav of the pages in
    name: My project                docs/ (and a docs/index.md if there is none). All settings are optional.
    description: what it is
    url: https://org.github.io/project/
"""

from __future__ import annotations

import json
import re
import tomllib


class SetupError(ValueError):
    """The text can't be used; the message says why, for the reply."""


def _key(raw: str) -> str:
    return re.sub(r"[\s_]+", "-", raw.strip().strip("*`").strip()).lower()


def fields(text: str, aliases: dict[str, str]) -> list[tuple[str, str] | None]:
    """The "key: value" lines of the text as (canonical key, value), with None for each blank line."""
    out: list[tuple[str, str] | None] = []
    for line in (text or "").splitlines():
        stripped = line.strip()
        if stripped.startswith(("```", "~~~")):
            continue
        stripped = re.sub(r"^[-*]\s+", "", stripped)   # list items: "- license: MIT"
        if not stripped:
            out.append(None)
            continue
        m = re.match(r"^([A-Za-z*`][\w *`-]{0,40}?)\s*[:=]\s*(.*)$", stripped)
        if not m or m[1].strip("*` ").lower() in ("http", "https"):
            continue
        key = _key(m[1])
        if key not in aliases:
            known = ", ".join(sorted({f"`{v}`" for v in aliases.values()}))
            raise SetupError(f"I don't know the setting `{m[1].strip()}`. Known settings: {known}.")
        value = m[2].strip().strip("`").strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        if not value:
            raise SetupError(f"`{m[1].strip()}` has no value.")
        if len(value) > 300 or any(ord(c) < 32 for c in value):
            raise SetupError(f"the value of `{m[1].strip()}` is too long or has control characters.")
        out.append((aliases[key], value))
    return out


def _string(value: str) -> str:
    """A TOML basic string (JSON's escapes are valid TOML)."""
    return json.dumps(value, ensure_ascii=False)


# ------------------------------------------------------------------------------------------ REUSE

REUSE_KEYS = {
    "path": "path", "paths": "path", "files": "path", "file": "path",
    "copyright": "copyright", "copyrights": "copyright", "copyright-text": "copyright",
    "spdx-filecopyrighttext": "copyright",
    "license": "license", "licence": "license", "licenses": "license", "licences": "license",
    "spdx-license-identifier": "license",
    "precedence": "precedence",
}
PRECEDENCE = ("closest", "aggregate", "override")
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
            ids.append(w.rstrip("+") if w.endswith("+") and len(w) > 1 else w)
            want_id = False
        else:
            raise SetupError(f"`{expression}` is not an SPDX license expression such as `MIT` or `MIT OR Apache-2.0`.")
    if want_id or depth:
        raise SetupError(f"`{expression}` is not a complete SPDX license expression.")
    return ids


def _check_annotation(a: dict, n: int) -> dict:
    """One annotation as REUSE.toml stores it, checked."""
    paths = a.get("path")
    paths = [paths] if isinstance(paths, str) else paths
    if not paths or not all(isinstance(p, str) and _PATH.match(p) and not p.startswith("/") and ".." not in p.split("/")
                            for p in paths):
        raise SetupError(f"annotation {n} needs one or more relative paths or globs, such as `**` or `src/**`.")
    out: dict = {"path": paths[0] if len(paths) == 1 else paths}
    if (prec := a.get("precedence")) is not None:
        if prec not in PRECEDENCE:
            raise SetupError(f"precedence is one of {', '.join(PRECEDENCE)}, not `{prec}`.")
        out["precedence"] = prec
    for key in ("SPDX-FileCopyrightText", "SPDX-License-Identifier"):
        value = a.get(key)
        values = [value] if isinstance(value, str) else value or []
        if not all(isinstance(v, str) and v.strip() for v in values):
            raise SetupError(f"`{key}` in annotation {n} must be text.")
        if key == "SPDX-License-Identifier":
            for v in values:
                license_ids(v)
        if values:
            out[key] = values[0] if len(values) == 1 else values
    if "SPDX-FileCopyrightText" not in out and "SPDX-License-Identifier" not in out:
        raise SetupError(f"annotation {n} (`{', '.join(paths)}`) needs a copyright or a license.")
    unknown = set(a) - {"path", "precedence", "SPDX-FileCopyrightText", "SPDX-License-Identifier"}
    if unknown:
        raise SetupError(f"REUSE.toml annotations don't know {', '.join(f'`{k}`' for k in sorted(unknown))}.")
    return out


def _from_toml(text: str) -> list[dict]:
    block = re.search(r"^[ \t]*(```|~~~)[^\n]*\n(.*?)^[ \t]*\1", text, re.M | re.S)
    try:
        data = tomllib.loads(block[2] if block else text)
    except tomllib.TOMLDecodeError as e:
        raise SetupError(f"the REUSE.toml in your comment isn't valid TOML ({e}).") from None
    if data.get("version", 1) != 1:
        raise SetupError("REUSE.toml has `version = 1`.")
    if set(data) - {"version", "annotations"}:
        raise SetupError("REUSE.toml only has `version` and `[[annotations]]` tables.")
    return data.get("annotations") or []


def _from_fields(text: str) -> list[dict]:
    groups: list[dict] = []
    current: dict | None = None
    for item in fields(text, REUSE_KEYS):
        if item is None:
            if current and current.get("SPDX-FileCopyrightText") or current and current.get("SPDX-License-Identifier"):
                current = None   # a blank line after a complete group ends it
            continue
        key, value = item
        if key == "path" and current is not None and current.get("path"):
            current = None
        if current is None:
            current = {}
            groups.append(current)
        if key == "path":
            current.setdefault("path", []).extend(p.strip() for p in value.split(",") if p.strip())
        elif key == "precedence":
            current["precedence"] = value.lower()
        else:
            name = "SPDX-FileCopyrightText" if key == "copyright" else "SPDX-License-Identifier"
            if key == "copyright":
                value = re.sub(r"^(SPDX-FileCopyrightText:\s*)", "", value)
            current.setdefault(name, []).append(value)
    for n, g in enumerate(groups):
        if not g.get("path"):
            if n:
                raise SetupError(f"annotation {n + 1} has no `path`; only the first one may leave it out (it then means `**`).")
            g["path"] = ["**"]
    return groups


def reuse_toml(text: str) -> tuple[str, list[str]]:
    """REUSE.toml from the text, and the license identifiers it uses (for LICENSES/)."""
    raw = _from_toml(text) if re.search(r"^\s*\[\[annotations\]\]", text or "", re.M) else _from_fields(text)
    if not raw:
        raise SetupError("there are no annotations yet.")
    annotations = [_check_annotation(a, n) for n, a in enumerate(raw, 1)]
    lines = ["# REUSE (https://reuse.software): the copyright and license of files that can't carry a header.",
             "# Check with: pipx run reuse lint", "version = 1"]
    used: list[str] = []
    for a in annotations:
        lines += ["", "[[annotations]]"]
        for key, value in a.items():
            if isinstance(value, list):
                lines.append(f"{key} = [{', '.join(_string(v) for v in value)}]")
            else:
                lines.append(f"{key} = {_string(value)}")
        licences = a.get("SPDX-License-Identifier", [])
        for expr in [licences] if isinstance(licences, str) else licences:
            used += [i for i in license_ids(expr) if i not in used]
    out = "\n".join(lines) + "\n"
    if [_check_annotation(a, n) for n, a in enumerate(tomllib.loads(out)["annotations"], 1)] != annotations:
        raise SetupError("the REUSE.toml doesn't read back as written")   # a bug, not the person's mistake
    return out, used


REUSE_EXAMPLE = """```
@{handle} setup reuse
path: **
copyright: 2026 Your Name
license: MIT

path: docs/**
license: CC-BY-4.0
```"""


# ------------------------------------------------------------------------------------- aisignoff

SIGNOFF_KEYS = {
    "generation": "generation", "ai-generation": "generation", "g": "generation",
    "human": "human", "human-review": "human", "h": "human", "review": "human",
    "ai": "ai", "ai-review": "ai", "a": "ai",
    "assisted-by": "assisted-by", "model": "assisted-by", "models": "assisted-by", "assistant": "assisted-by",
    "reviewed-by": "reviewed-by", "reviewer": "reviewed-by", "responsible": "reviewed-by",
    "ai-reviewed-by": "ai-reviewed-by", "ai-reviewer": "ai-reviewed-by",
}
_LEVEL = re.compile(r"(?<![\w-])([GHA][0-3])(?![\w-])")
_OPTION = {"generation": "--generation", "human": "--human", "ai": "--ai"}


def aisignoff_args(text: str) -> list[str]:
    """The options of `aisignoff init` for the text: [] for the commented template, or all three levels."""
    levels: dict[str, str] = {}
    lists: dict[str, list[str]] = {"assisted-by": [], "reviewed-by": [], "ai-reviewed-by": []}
    key_lines = set()
    for item in fields(text, SIGNOFF_KEYS):
        if item is None:
            continue
        key, value = item
        key_lines.add(key)
        if key in _OPTION:
            value = value.upper()
            if not re.fullmatch(r"[GHA][0-3]|TODO", value) or (value != "TODO" and value[0] != key[0].upper()):
                raise SetupError(f"`{key}` is a level from {key[0].upper()}0 to {key[0].upper()}3 (or TODO), not `{value}`.")
            levels[key] = value
        else:
            lists[key] += [v.strip() for v in value.split(",") if v.strip()]
    # Levels written as words of the text, e.g. "G2 H1 A0", on lines that aren't settings.
    plain = "\n".join(l for l in (text or "").splitlines() if not re.match(r"^\s*[-*]?\s*[\w *`-]{1,40}?\s*[:=]", l))
    for level in _LEVEL.findall(plain):
        key = {"G": "generation", "H": "human", "A": "ai"}[level[0]]
        if levels.get(key, level) != level:
            raise SetupError(f"two different levels for `{key}`: {levels[key]} and {level}.")
        levels[key] = level
    if levels and len(levels) < 3:
        need = ", ".join(k for k in _OPTION if k not in levels)
        raise SetupError(f"give all three levels (generation, human, ai), e.g. `G2 H1 A0`, or none for the "
                         f"commented template; missing: {need}.")
    if not levels and any(lists.values()):
        raise SetupError("names (reviewed-by, assisted-by, ai-reviewed-by) go with the three levels, e.g. `G2 H1 A0`.")
    args: list[str] = []
    for key, option in _OPTION.items():
        if key in levels:
            args += [option, levels[key]]
    for key, values in lists.items():
        for v in values:
            args += [f"--{key}", v]
    return args


SIGNOFF_EXAMPLE = """```
@{handle} setup aisignoff
G0 H2 A0
reviewed-by: Your Name
```"""


# ------------------------------------------------------------------------------------------ docs

DOCS_KEYS = {
    "name": "name", "site-name": "name", "project": "name", "title": "name",
    "description": "description", "site-description": "description", "about": "description",
    "url": "url", "site-url": "url",
}


def docs_settings(text: str) -> dict[str, str]:
    """name, description and url for the new zensical.toml, from the text (each optional)."""
    out: dict[str, str] = {}
    for item in fields(text, DOCS_KEYS):
        if item is not None:
            out[item[0]] = item[1]
    if (url := out.get("url")) and url.lower() != "none" and not re.fullmatch(r"https?://[^\s\"'<>]+", url):
        raise SetupError(f"`url` is the address of the site, such as `https://org.github.io/project/`, not `{url}`.")
    return out
