# Repository settings file

A repository can hold an optional `.github/imgagent.toml` that tells Claude more about the project than the GitHub repository description does. IMGAgent reads its `[docs]` table and passes the values to the `ask`, `update` and `make docs` scripts.

## Where it goes

The file is `.github/imgagent.toml` in the repository, read from the default branch. Every job clones the repository, and IMGAgent reads the file from that clone. `ask` uses a sparse clone that contains only the named folders and `.github/imgagent.toml`.

If the file is missing, IMGAgent uses the defaults below. If the file is not valid TOML, IMGAgent logs a warning (`ignoring .github/imgagent.toml: ...`) and also uses the defaults.

The signoff assistant and the signoff issue form do not read this file.

## Example

```toml
[docs]
about = "an open source project for running coding agents in sandboxed containers"
audience = "people who deploy and run agent-sandbox on their own Linux machines"
url = "https://industrial-mathematics-group.github.io/agent-sandbox/"   # "none": answers cite paths instead
```

## Keys

All keys are optional and belong to the `[docs]` table.

| Key | Passed to the scripts as | Default when the key is missing or empty |
|---|---|---|
| `project` | `DOCS_PROJECT` | the repository name (without the owner) |
| `about` | `DOCS_ABOUT` | the repository description on GitHub, or nothing |
| `audience` | `DOCS_AUDIENCE` | empty; `make docs` then uses "people who use <project>" |
| `url` | `DOCS_URL` | `https://<owner>.github.io/<repository>/`, with the owner in lower case |

`project`
:   The project's name, as Claude uses it in prompts and as `site_name` when `make docs` creates a new `zensical.toml`.

`about`
:   One sentence on what the project is. Claude sees it as "<project>, <about>". `make docs` also uses it as `site_description` in a new `zensical.toml` (otherwise the project name).

`audience`
:   Who reads the documentation. Only `make docs` uses it, to decide how the pages are written.

`url`
:   The published documentation site. Set it to `"none"` (or `""`) when there is no site: `DOCS_URL` is then empty. If you leave the key out, IMGAgent assumes the GitHub Pages address of the repository.

Besides these, IMGAgent always sets `DOCS_REPO` to the repository's `owner/name`; it is not configurable in the file.

## What each command uses

| Command | `project` | `about` | `audience` | `url` |
|---|---|---|---|---|
| `ask` | yes | yes | no | yes |
| `update` | yes | yes | no | no |
| `make docs` | yes | yes | yes | yes |

With `ask`, the URL matters only when the question is about `docs` alone (`@IMGAgent ask docs`): Claude then names the pages it used as links of the form `<url>/<path>/`, where `<path>` is the page's path under `docs/` without `.md` (and without `/index` for index pages). With an empty URL, or with any other folders, answers cite file paths in the repository instead.

With `make docs`, the URL and `DOCS_REPO` are used only when the repository has no `zensical.toml` yet: the new file gets `site_url` from the URL (left out when it is empty), and `repo_url` and `repo_name` from the repository. An existing `zensical.toml` keeps everything except its `nav`. See [make docs](../usage/make-docs.md).

!!! note
    `about` falls back to the repository description, so setting a good description on GitHub already helps. Use the file when you want a different sentence for Claude, or an audience or URL.
