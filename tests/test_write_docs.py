"""The docs writer's zensical.toml handling (no Claude calls)."""

import importlib
import sys
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
NAV = [{"Home": "index.md"}, {"Guide": ["guide/index.md", "guide/install.md"]}]


@pytest.fixture
def wd(tmp_path, monkeypatch):
    monkeypatch.setenv("REPO_ROOT", str(tmp_path))
    monkeypatch.setenv("DOCS_PROJECT", "demo")
    monkeypatch.setenv("DOCS_REPO", "org/demo")
    monkeypatch.setenv("DOCS_URL", "https://org.github.io/demo/")
    monkeypatch.syspath_prepend(str(ROOT / "scripts" / "docs"))
    sys.modules.pop("write_docs", None)
    return importlib.import_module("write_docs")


def nav_of(wd):
    return tomllib.loads(wd.TOML_PATH.read_text())["project"]["nav"]


def test_creates_the_file(wd):
    assert "Created" in wd.write_nav(NAV)
    data = tomllib.loads(wd.TOML_PATH.read_text())
    assert data["project"]["nav"] == NAV and data["project"]["site_name"] == "demo"
    assert data["project"]["repo_url"] == "https://github.com/org/demo"
    assert "admonition" in data["project"]["markdown_extensions"]


def test_replaces_a_one_line_nav(wd):
    wd.TOML_PATH.write_text('[project]\nsite_name = "x"\nnav = []\n\n[project.theme]\nlanguage = "en"\n')
    assert wd.write_nav(NAV) == ""
    assert nav_of(wd) == NAV and 'language = "en"' in wd.TOML_PATH.read_text()


def test_replaces_a_nav_with_comments_and_brackets_in_strings(wd):
    wd.TOML_PATH.write_text('[project]\nnav = [  # pages\n  { "A ] b" = "a.md" },  # ]\n  "b.md",\n]\nsite_name = "x"\n')
    wd.write_nav(NAV)
    assert nav_of(wd) == NAV and tomllib.loads(wd.TOML_PATH.read_text())["project"]["site_name"] == "x"


def test_adds_nav_to_project(wd):
    wd.TOML_PATH.write_text('# site\n[project]\nsite_name = "x"\n\n[project.theme]\nlanguage = "en"\n')
    assert "Added the `nav`" in wd.write_nav(NAV)
    assert nav_of(wd) == NAV and wd.TOML_PATH.read_text().startswith("# site\n")


def test_adds_project_table(wd):
    wd.TOML_PATH.write_text('[project.theme]\nlanguage = "en"\n')
    wd.write_nav(NAV)
    assert nav_of(wd) == NAV


def test_ignores_nav_in_other_tables(wd):
    wd.TOML_PATH.write_text('[project]\nsite_name = "x"\n\n[extra]\nnav = ["keep.md"]\n')
    wd.write_nav(NAV)
    data = tomllib.loads(wd.TOML_PATH.read_text())
    assert data["project"]["nav"] == NAV and data["extra"]["nav"] == ["keep.md"]


def test_a_nav_failure_keeps_the_pages(wd, monkeypatch):
    def broken(nav):
        raise RuntimeError("boom")
    monkeypatch.setattr(wd, "write_nav", broken)
    summary = ["pages"]
    wd.save_nav(NAV, summary)
    assert "could not be updated" in summary[-1] and '"guide/install.md"' in summary[-1]


def test_read_nav_without_file_or_key(wd):
    assert wd.read_nav() == []
    wd.TOML_PATH.write_text('[project]\nsite_name = "x"\n')
    assert wd.read_nav() == []
