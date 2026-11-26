# Commands

You talk to IMGAgent by writing a command in an issue or a comment. This page covers how a command is written, where IMGAgent looks for it, and who gets an answer.

## Overview

| Command | What happens | Details |
|---|---|---|
| `@IMGAgent ask <folders> [with <folders>]` and a question | Claude answers from the files in those folders | [ask](ask.md) |
| `@IMGAgent update <folders> [with <folders>]` and a task | Claude edits existing files in the folders and at the top level, reading the `with` folders; IMGAgent opens a pull request | [update](update.md) |
| `@IMGAgent make docs [with <folders>]` and a hint | Claude rebuilds `docs/` from the code (or only from the `with` folders); IMGAgent opens a pull request | [make docs](make-docs.md) |
| `@IMGAgent review <folders> [with <folders>]` and an optional focus | a quick Claude review of the folders, checked against the `with` folders; IMGAgent records it as an aisignoff A1 attestation in a pull request | [review](review.md) |
| `@IMGAgent setup reuse\|aisignoff\|citation\|docs` | a template for `REUSE.toml`, `SIGNOFF.toml`, `CITATION.cff` or `zensical.toml` with defaults filled in; ticking **Done** opens a pull request, without AI | [setup](setup.md) |
| `@IMGAgent signoff` and your words | records how files were made and reviewed: a `SIGNOFF.toml` pull request | [signoff](signoff.md) |
| `@IMGAgent help` | the list of commands | |

The issue form *Signoff: declare or attest files* also leads to a `SIGNOFF.toml` pull request, without a command. See [signoff](signoff.md).

## Syntax

`ask`, `update`, `make` and `review` follow the same pattern: action, then folders, then text.

```
@IMGAgent <action> <folders> [with <folders>]
<question, task or hint>
```

For example:

```
@IMGAgent update docs with src
the docs still describe the old commands; bring them in line with the code
```

Action
:   `ask`, `update`, `make`, `review`, `setup` or `help`. Case does not matter. `setup` takes `reuse`, `aisignoff`, `citation` or `docs` instead of folders, and no text; see [setup](setup.md).

Folders
:   A comma-separated list of folders or files of the repository, as relative paths such as `docs`, `src/package` or `pyproject.toml`. Spaces around the commas are fine (`docs, src`). A path may be wrapped in backticks, and a leading `./` or trailing `/` is dropped. Duplicates are ignored.

`with <folders>`
:   Optional, and only on the same line as the command. These folders are read but never changed. For `ask` it makes no difference whether a folder comes before or after `with`. A folder that already appears before `with` is dropped from the `with` list.

Text
:   The question (`ask`), task (`update`) or hint (`make`). It may start on the same line as the command or on the next one, and may span several lines. Start it on the next line if its first word is "with", so it is not read as a `with` list.

Text written before the command in the same comment counts too: everything before and after the command becomes the question, task or hint.

The mention may also be written as `@IMGAgent[bot]`, in bold (`**@IMGAgent**`), or followed by a colon or comma (`@IMGAgent: ask docs`). The name is set by `IMGAGENT_HANDLE` (default `IMGAgent`); see [environment variables](../reference/index.md).

### Which paths are accepted

Each path is checked by name when the command is read. A path is refused when it:

- is empty or longer than 200 characters,
- is absolute (starts with `/`),
- contains `..` or `.` as a segment,
- contains a `.git` segment (in any case),
- contains glob characters, spaces or other characters outside letters, digits, `.`, `_` and `-`, or a segment that starts with `-`.

A refused path gets a help reply naming it. When the job runs, each path is checked again in the clone: it must exist and stay inside the repository, also through symlinks. A path that does not exist gets a reply such as "there is no `src2` in this repository".

### Limits per action

- `ask`, `update`, `make` and `review` all need at least one folder after the action. Without one, IMGAgent replies with help explaining the usage.
- `make` only knows `docs` for now. `make src` gets a help reply suggesting `update src` instead.
- `ask` without a question and `update` without a task get a reply asking for it. For `make` and `review`, the text is optional.

## Where commands are recognised

A command can stand anywhere in a comment or a new issue, not only at the start. For a new issue, the title and body are read together. Comments on pull requests arrive as issue comments, so commands work there too.

Some mentions do not count:

- inside fenced code blocks (```` ``` ```` or `~~~`),
- on quoted lines (starting with `>`),
- as part of a longer word, an e-mail address, a path, or after a backtick.

Zero-width characters are removed and non-breaking spaces are treated as plain spaces before the text is read.

!!! note "signoff"
    `@IMGAgent signoff` follows the signoff assistant's own rules: it is only answered in open issues, not in pull requests and not in issues made with the signoff form. See [signoff](signoff.md).

## Unknown commands and help

When a comment starts with `@IMGAgent` but no known command follows, IMGAgent replies with the command list, led by what went wrong:

- `@IMGAgent` followed by an unknown word: "I don't know ...".
- The old order, such as `@IMGAgent docs ask`: a reminder that commands are now action then target, e.g. `@IMGAgent ask docs ...`.
- `@IMGAgent` alone: just the list.

A mention of `@IMGAgent` that is not at the start of the text and has no command after it gets no reply. In a new issue, help replies for mistakes are not sent; only a correct command runs.

`@IMGAgent help` always replies with the list.

## Editing to run a command again

You can fix a command by editing instead of writing a new one.

Edited comment
:   The command runs when the edited text contains a command and the text before the edit had none, or only produced help. Editing a comment whose command already ran does not run it again; write a new comment instead.

Edited or reopened issue
:   When an open issue's title or body is edited, or the issue is reopened, a command in it runs, but only while IMGAgent has not commented on the issue yet (checked among the first 100 comments). This covers issues opened before IMGAgent was running, or whose first try failed.

## Who is answered

Only people with write, maintain or admin permission on the repository are answered. Accounts of type Bot are never answered, so IMGAgent cannot start itself.

| Command | Without write access |
|---|---|
| `ask`, `update`, `make`, `review`, `setup` | a reply that the command is only for people with write access |
| `help` and help replies for mistakes | no reply |

## What happens after a command

When `ask`, `update` or `make` starts from a comment, IMGAgent adds an :eyes: reaction to it. The answer or the link to the pull request comes as a new comment that mentions you. Pull requests opened by `update` and `make` are described in [pull requests](pull-requests.md).

If a job fails, IMGAgent comments that it couldn't finish, and the details are in the server log; see [troubleshooting](../operations/troubleshooting.md).

`update`, `make`, `review` and `setup` jobs in the same repository run one after the other. Other jobs run one after the other per issue. See [HTTP endpoints](../reference/http-endpoints.md).
