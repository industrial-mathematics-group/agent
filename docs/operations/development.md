# Development and updating the scripts

This page covers running the test suite and refreshing the signoff scripts when the organisation's bots change. The tests need no network access and no GitHub App.

## Run the tests

Create a virtual environment, install the dependencies plus `pytest`, and run the suite from the repository root:

```bash
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt pytest
python -m pytest tests
```

## Pinned dependencies

`requirements.txt` pins exact versions:

| Package | Version | Used for |
|---|---|---|
| `anthropic` | `==2.8.0` | Claude calls in `scripts/docs/`, `scripts/repo/` and `scripts/signoff/` |
| `aisignoff` | `==1.0.0rc8` | the `aisignoff` command that the signoff scripts run to edit and lint `SIGNOFF.toml` |
| `PyJWT[crypto]` | `==2.15.1` | signing the GitHub App's JWT in `imgagent/github.py` |

The Docker image installs the same file, so a changed pin takes effect after `docker compose up -d --build`.

## What the tests cover

The tests live in `tests/`.

| File | What it checks |
|---|---|
| `tests/test_imgagent.py` | Routing of events to commands (`imgagent/commands.py`): which comments and issues start a job, how targets are checked (`..`, absolute paths, `.git`, glob characters, `make` other than `docs`), and which are ignored (bots, code, part of a word, pull requests, closed issues, form issues). Job keys. The webhook signature check. Parsing of `GITHUB_OUTPUT` files. The pull request body that the docs writer fills in. The HTTP server end to end: `ping`, bad signature (`401`), queued jobs, repeated delivery ids, owners outside the allowlist, and `/healthz`. The messages that explain why an event started nothing. That the bot user lookup never sends the App's JWT to `/users/...`. |
| `tests/test_imgagent.py` (`make` and `update` jobs) | `do_make` and `do_update` against a local git repository instead of GitHub: the branch, the commit by `<slug>[bot]`, the pull request request that is sent, and that `update` commits only modified files under its target or at the top level (no new, deleted or workflow files). Targets that don't exist or lead outside the clone. |
| `tests/test_repo_scripts.py` | Which files `scripts/repo/` reads for a target (tracked text files only, plus top-level files for `update`), the size limit, and that `update.py` only edits files it may, with a fake Claude. |
| `tests/test_write_docs.py` | How `scripts/docs/write_docs.py` handles `zensical.toml`: creating the file, replacing a `nav` (one line, with comments, with brackets in strings), adding `nav` to `[project]`, adding a `[project]` table, leaving other tables alone, and keeping the written pages when the nav update fails. No Claude calls are made. |

The signoff scripts (`scripts/signoff/`) and the Claude calls themselves are not covered by these tests.

## Refresh the signoff scripts

`scripts/signoff/assistant.py` and `scripts/signoff/request.py` are the Python steps of two workflows in the `industrial-mathematics-group/.github` repository, copied out unchanged. IMGAgent runs them in a clone of the repository with the environment GitHub Actions would provide (see `_actions_env` in `imgagent/jobs.py`).

When those workflows change:

1. Copy the Python step of `.github/workflows/signoff-assistant.yml` into `scripts/signoff/assistant.py`.
2. Copy the Python step of `.github/workflows/signoff-request.yml` into `scripts/signoff/request.py`.
3. Keep the header comment at the top of each file.
4. In `requirements.txt`, change the `aisignoff` pin to the version the organisation uses.
5. Run the tests, then rebuild and restart the container:

```bash
python -m pytest tests
docker compose up -d --build
```

!!! note
    Do not edit the logic in these two files by hand. Changes belong in the organisation's workflows, so that the GitHub Actions version and IMGAgent stay the same code.

The scripts in `scripts/docs/` (`write_docs.py`) and `scripts/repo/` (`ask.py`, `update.py` and their shared `common.py`) are not copied from elsewhere; they are changed in this repository.
