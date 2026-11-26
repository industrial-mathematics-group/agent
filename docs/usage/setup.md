# setup

`@IMGAgent setup <reuse|aisignoff|docs>` creates one configuration file of the repository from settings you write below the command, and opens a pull request for you to review. No AI is involved: IMGAgent reads your settings as they are, so the pull request is declared G0.

| Command | Creates | Settings |
|---|---|---|
| `setup reuse` | `REUSE.toml` | the annotations: required |
| `setup aisignoff` | `SIGNOFF.toml`, with `aisignoff init` | the default declaration: optional |
| `setup docs` | `zensical.toml` (and `docs/index.md` if missing) | the site's name, description and address: optional |

If the file already exists, IMGAgent says so and changes nothing. To change an existing file, use `@IMGAgent update REUSE.toml` (or `SIGNOFF.toml`, `zensical.toml`) and say what to change; `make docs` also rebuilds the nav of `zensical.toml`.

## Writing settings

Settings are `key: value` lines (`key = value` works too) after the command, on the same line or below it. Keys are case insensitive and may be written with spaces, `-` or `_` (`Human Review`, `human-review`). The lines may be in a code block or a list. Lines without a key are ignored.

A key that IMGAgent doesn't know is refused with a reply listing the known ones, so a typo never silently leaves a setting out. The same goes for a value that can't be used, such as a malformed license expression. Nothing is cloned or changed until the settings are read without problems.

## setup reuse

```
@IMGAgent setup reuse
path: **
copyright: 2026 Industrial Mathematics Group
license: MIT

path: docs/**, *.md
license: CC-BY-4.0
precedence: override
```

creates

```toml
version = 1

[[annotations]]
path = "**"
SPDX-FileCopyrightText = "2026 Industrial Mathematics Group"
SPDX-License-Identifier = "MIT"

[[annotations]]
path = ["docs/**", "*.md"]
precedence = "override"
SPDX-License-Identifier = "CC-BY-4.0"
```

Each group of lines is one `[[annotations]]` table of the [REUSE specification](https://reuse.software/spec/). A new `path` line, or a blank line after a group that has a copyright or a license, starts the next group.

| Key (and other names) | Value |
|---|---|
| `path` (`paths`, `files`) | comma-separated relative paths or globs. The first group may leave it out; it then means `**`. |
| `copyright` (`SPDX-FileCopyrightText`) | a copyright notice, such as `2026 Jane Doe`. Repeat the line for several. |
| `license` (`licence`, `SPDX-License-Identifier`) | an SPDX license expression, such as `MIT` or `MIT OR Apache-2.0`. Repeat the line for several. |
| `precedence` | `closest` (REUSE's default), `aggregate` or `override` |

Each group needs a copyright or a license. Instead of lines, a whole `REUSE.toml` in a code block (with `[[annotations]]` tables) is checked and used.

The pull request lists the licenses that have no text in `LICENSES/` yet, with the command that adds them (`reuse download`); `reuse lint` passes only once they are there.

## setup aisignoff

Without settings, `setup aisignoff` creates the commented template of `aisignoff init`, to which you add the declarations of the repository's files. With the three levels it also declares a default for every file:

```
@IMGAgent setup aisignoff
G0 H2 A0
reviewed-by: Jane Doe
```

| Key (and other names) | Value |
|---|---|
| `generation` (`AI-Generation`, `G`) | `G0` to `G3`, or `TODO` |
| `human` (`Human-Review`, `H`) | `H0` to `H3`, or `TODO` |
| `ai` (`AI-Review`, `A`) | `A0` to `A3`, or `TODO` |
| `reviewed-by` (`reviewer`, `responsible`) | the responsible person; comma-separated or repeated for several |
| `assisted-by` (`model`, `models`) | the AI models, for G1 to G3 |
| `ai-reviewed-by` | the reviewing models, for A1 to A3 |

The levels may also be written as words, such as `G2 H1 A0`. Give all three or none; names only go with the levels. `aisignoff init` checks the combination, and if it refuses, IMGAgent replies with its message.

Once `SIGNOFF.toml` is merged, [signoff](signoff.md) and the signoff form work in the repository.

## setup docs

```
@IMGAgent setup docs
name: My project
description: a tool for planning experiments
url: https://example.org/my-project/
```

creates the same `zensical.toml` as [make docs](make-docs.md) (site settings, theme, Markdown extensions), with a nav of the pages already in `docs/`: top-level pages first, then one section per folder, titled by each page's first heading. Without `docs/index.md`, a placeholder home page is added.

| Key (and other names) | Value | Default |
|---|---|---|
| `name` (`site name`, `project`, `title`) | the site name | `project` in `.github/imgagent.toml`, or the repository name |
| `description` (`about`) | one sentence on the project | `about` in `.github/imgagent.toml`, or the repository description |
| `url` (`site url`) | the published address, or `none` | `url` in `.github/imgagent.toml`, or `https://<owner>.github.io/<repo>/` |

To write the pages themselves from the code, use `@IMGAgent make docs`.
