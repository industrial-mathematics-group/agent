# Commands

IMGAgent reacts to commands written in GitHub issues and comments. This page lists each command, where IMGAgent recognises it, and what it does.

The name after `@` is `IMGAgent` by default and can be changed with `IMGAGENT_HANDLE`. Matching is not case sensitive, so `@imgagent help` works as well.

## Who is answered

Only people with admin, maintain or write permission on the repository get an answer. Comments and issues from bots are always ignored, so IMGAgent cannot trigger itself.

- For `ask`, `update` and `make`, a person without write access gets a short comment saying the command needs write access.
- For `help`, a person without write access gets no reply at all.
- For `signoff`, the signoff assistant script checks the permission and replies in the issue.

See [access control](allowed-owners.md) for the other checks that happen before a command runs.

## Overview

Commands are written as `@IMGAgent <action> <folders> [with <folders>]`, followed by your question, task or hint.

| Command | Recognised | What happens |
|---|---|---|
| `@IMGAgent signoff <your words>` | Anywhere in a new issue or in a comment on an open issue; not in pull requests | Claude turns your words into the answers of the signoff form. IMGAgent opens a `SIGNOFF.toml` pull request, or asks what is missing |
| `@IMGAgent ask <folders> [with <folders>]` and a question | Start of a comment, or in the title or body of a new issue | Claude answers from the files in those folders, for example `docs` or `docs,src` |
| `@IMGAgent update <folders> [with <folders>]` and a task | Start of a comment | Claude edits existing files in the folders and at the top level of the repository, reading the `with` folders; IMGAgent opens a pull request |
| `@IMGAgent make docs [with <folders>]` and a hint | Start of a comment | Claude rebuilds `docs/` from the code, or only from the `with` folders; IMGAgent opens a pull request |
| `@IMGAgent help` | Start of a comment | Lists the commands |
| Issue form *Signoff: declare or attest files* | New, edited or reopened issue | IMGAgent opens the `SIGNOFF.toml` pull request without AI |

"Start of a comment" means the first line of the comment begins with `@IMGAgent`. A mention further down is not a command, except for `signoff`.

## Folders, `with` and the text

```text
@IMGAgent update docs with src
The docs still describe the old commands. Bring them in line with the code.
```

- **Folders** come right after the action, as a comma-separated list on the first line: `docs`, `docs,src` or `docs, src/package`. An entry can also be a file, such as `pyproject.toml`. A leading `./` and a trailing `/` are ignored, and duplicates are dropped.
- **`with <folders>`**, on the same line, adds folders that Claude reads but may not change. For `ask` there is no difference between the two lists.
- **The text**, which is the question, task or hint, follows on the same line or on the next lines. If it begins with the word "with", start it on the next line so it is not read as a list of folders.

IMGAgent refuses folders with `..`, an absolute path, `.git` or glob characters, and answers with the list of commands and what is wrong. After cloning, every folder must exist and must not lead outside the repository through a symlink; otherwise IMGAgent names the folders it could not find.

Only tracked text files are read. Binary files, images, lock files, `LICENSE` and files over 200 kB are left out. If the files of one command add up to more than about 150k tokens, IMGAgent says so instead of answering: name smaller folders.

## `help`

`@IMGAgent help` posts the table of commands. A comment that starts with `@IMGAgent` followed by anything that is not a known command also gets this list, with a line saying what is wrong. A bare `@IMGAgent` shows the list too. The old form `@IMGAgent docs ask` (or `docs make`, `docs update`) gets the list with a hint at the new order.

## `ask`

```text
@IMGAgent ask docs How do I add a host to the allowlist?
@IMGAgent ask docs,src
Where is the webhook signature checked, and is that documented?
```

In a new issue, the title and body are sent together as the question, and `@IMGAgent ask <folders>` can appear anywhere in them.

IMGAgent adds an `eyes` reaction to your comment, takes a shallow clone of the repository containing only the folders and `.github/imgagent.toml`, and posts Claude's answer as a comment. Claude only sees those folders. Answers from `docs` alone link to the published pages when a site URL is known; other answers name the files they used. The model is set by `ASK_MODEL`. If the question is empty, IMGAgent asks you to write one.

## `update`

```text
@IMGAgent update src,tests require Python 3.13 instead of 3.12
@IMGAgent update docs with src
Fix what is outdated or missing compared with the code.
```

`update` is for small tasks that touch several existing files. The task is required.

| | Claude reads | Claude may change |
|---|---|---|
| The folders before `with` | yes | existing files |
| The text files at the top level of the repository, such as `pyproject.toml` and `README.md` | yes | existing files |
| The folders after `with` | yes | no |
| Files under `.github/workflows/` | when listed | no, the App may not push them |

Claude is told never to create, delete or rename files, and the script can only apply find-and-replace edits to the files it may change, so it cannot. If the task needs a new file or a file it may not change, the pull request says what is left to do.

IMGAgent reacts with `eyes`, works in a clone of the default branch, and commits only the modified files it may change on a new branch named `<app-slug>/update-<folders>-<random>`. It opens a pull request against the default branch, with the task and a list of the changed files and why, and posts the link where you asked. If nothing changed, it only comments with the summary.

The model is set by `WRITER_MODEL` and `WRITER_EFFORT`.

## `make docs`

```text
@IMGAgent make docs
@IMGAgent make docs with src,examples focus on deployment and operations
```

`make` creates files, which depends much more on the task than `update`, so `docs` is the only target for now. An optional hint is passed to Claude as guidance.

Claude rebuilds the documentation from the code: it plans the pages, then writes each one. Without `with`, it reads all tracked code outside `docs/`; with `with`, only those folders and the top-level files. Markdown pages under `docs/` that are not in the new plan are removed, and the nav in `zensical.toml` follows (a complete `zensical.toml` is created when there is none).

IMGAgent reacts with `eyes`, works in a full clone of the default branch, and commits changes to `docs/` and `zensical.toml` on a new branch named `<app-slug>/make-docs-<random>`. It opens a pull request against the default branch and posts the link in the issue or pull request where you asked. If nothing changed, it only comments with the summary and opens no pull request.

The model is set by `WRITER_MODEL` and `WRITER_EFFORT`.

## `signoff`

```text
@IMGAgent signoff I wrote results/ with Claude Opus 5.5 and checked every line myself.
```

`signoff` is recognised anywhere in the text of a new issue or of a comment on an open issue, but not inside a longer word, an e-mail address, a path or code. It is not recognised in pull requests, and not in issues made with the signoff form. If several comments are involved, the assistant reads the whole conversation, so you can answer its questions by writing `@IMGAgent signoff` again with the missing details.

Claude turns your words into the answers of the signoff form. IMGAgent then checks them. If something is missing, IMGAgent asks in a comment. If they are complete, it opens a pull request that records them in `SIGNOFF.toml`. The repository needs a `SIGNOFF.toml`; see [preparing a repository](../getting-started/per-repository.md).

The model is set by `SIGNOFF_MODEL`, `SIGNOFF_MODEL_NAME` and `SIGNOFF_EFFORT`.

## The signoff issue form

An issue made with the form *Signoff: declare or attest files* (recognised by its heading "What should be recorded?") is turned into a `SIGNOFF.toml` pull request without AI. This runs when the issue is opened or reopened, and when its body is edited; edits to other things, such as the title, are ignored. Editing the issue again updates the pull request.

This is on by default. Set `IMGAGENT_SIGNOFF_FORM=false` to leave these issues to a workflow in the repository.

## Pull requests and ordering

IMGAgent never pushes to a default branch. Every change arrives as a pull request.

- For `make docs` and `update`, the requester is assigned to the pull request. The description is the organisation's pull request template, filled in: AI generation G3, the writing model ticked, AI review A0, and the requester named as the responsible person. The requester ticks their own human review before merging.
- For signoff, the pull request description follows the organisation's template as well, and the requester is assigned and asked for review.

Jobs for the same issue run one after another. All `make` and `update` jobs of a repository also share one queue, so two jobs that open pull requests never run at the same time. Jobs for different issues and repositories run in parallel, up to `IMGAGENT_WORKERS`.

If a job fails, IMGAgent comments that it could not finish and points to the server log. See [troubleshooting](../operations/troubleshooting.md).
