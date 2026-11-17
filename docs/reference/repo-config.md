# Per-repository file .github/imgagent.toml

An optional file in a repository that tells IMGAgent more about the project when it answers questions from the docs or writes them. Without it, IMGAgent uses the repository's name and description.

## Where it is read

IMGAgent reads `.github/imgagent.toml` from its clone of the repository. For `ask` the clone is sparse and contains only the target folder and this file. For `update` and `make docs` it is a clone of the default branch. Only the `[docs]` table is used; other tables are ignored.

If the file is missing, IMGAgent uses the defaults below. If it is not valid TOML, IMGAgent logs a warning (`ignoring .github/imgagent.toml`) and uses the defaults.

## The `[docs]` table

```toml
[docs]
project = "agent-sandbox"
about = "an open source project for running coding agents in sandboxed containers"
audience = "people who deploy and run agent-sandbox on their own Linux machines"
url = "https://industrial-mathematics-group.github.io/agent-sandbox/"
```

| Key | Meaning | Default when missing or empty |
|---|---|---|
| `project` | The project's name, used in the prompts. | The repository name, without the owner. |
| `about` | One sentence on what the project is. | The repository's description on GitHub; empty if it has none. |
| `audience` | Who reads the docs. | The docs scripts use "people who use `<project>`". |
| `url` | The address of the published site. | `https://<owner>.github.io/<repo>/`, with the owner in lowercase. |

### `url`

`url` decides how answers to `ask docs` refer to pages:

- With a URL, the answer names the pages it used as links of the form `<url>/<path>/`, where `<path>` is the page path without `.md` (and without `/index` for index pages).
- With `url = "none"` or `url = ""`, no site address is passed on, and the answer names pages by their path under `docs/`.

Use `"none"` when the docs are not published, or not at the default GitHub Pages address and you do not want guessed links.

For `make docs`, the `url` is also written as `site_url` into a new `zensical.toml`. An existing `zensical.toml` keeps everything except its `nav`.

## How the values reach the scripts

IMGAgent does not pass the file itself to the scripts. It turns the values into environment variables when it starts them:

| Environment variable | Comes from |
|---|---|
| `DOCS_PROJECT` | `project`, else the repository name |
| `DOCS_ABOUT` | `about`, else the repository description |
| `DOCS_AUDIENCE` | `audience`, else empty |
| `DOCS_URL` | `url`; empty when it is `"none"` or `""` |
| `DOCS_REPO` | `owner/name` of the repository (not configurable) |

`ask` runs `scripts/repo/ask.py`, `update` runs `scripts/repo/update.py` and `make docs` runs `scripts/docs/write_docs.py`. All read these variables.

!!! note
    The scripts see only the variables IMGAgent gives them, plus `PATH`, `HOME`, `LANG` and `SSL_CERT_FILE`. Setting `DOCS_PROJECT` or the others in the server's `.env` has no effect; use `.github/imgagent.toml` instead.

The file is not used by `signoff` or the signoff form.
