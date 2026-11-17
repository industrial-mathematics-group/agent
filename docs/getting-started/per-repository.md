# Prepare a repository

IMGAgent needs no workflow files in the repositories it serves. Once the App is installed on a repository, what you may need to add depends on which commands people will use.

## What each command needs

| Command | What the repository needs |
|---|---|
| `@IMGAgent help` | Nothing. |
| `@IMGAgent ask <folder> <question>` | The folder you name. Without it, IMGAgent replies that there is no such path. |
| `@IMGAgent update <folder> <task>` | The folder you name, with the files to change already in it: `update` never creates files. |
| `@IMGAgent make docs [hint]` | Nothing. It creates `docs/` and `zensical.toml` if they are missing. |
| `@IMGAgent signoff` and the issue form *Signoff: declare or attest files* | A `SIGNOFF.toml` in the repository. |

### Documentation

`make docs` writes a Zensical site: Markdown pages in `docs/` and the navigation in `zensical.toml`.

- If the repository has no `zensical.toml`, `make docs` creates a complete one, with theme, Markdown extensions and `nav`.
- If a `zensical.toml` already exists, everything in it is kept except the `nav`, which is replaced by the new page structure.
- `ask docs` and `update docs` only need `docs/`. They do not need `zensical.toml` (`update docs` edits it only because it is a top-level file).

!!! note
    IMGAgent does not add a workflow that publishes the site, because the App has no permission to change `.github/workflows/`. Add the publishing workflow by hand once.

### Signoff

Signoff requests are written into `SIGNOFF.toml` with the `aisignoff` tool. Create the file once, in the repository:

```bash
aisignoff init
```

Without `SIGNOFF.toml`, signoff requests are rejected with the instruction to create it. The pull requests that IMGAgent opens follow the organisation's pull request template, so the *PR-signoff* check can read them. They are opened as the App's pull requests, so the repository's checks start as for any other pull request.

## Moving from the GitHub Actions bots

If a repository still runs the older Actions versions of these bots, delete their files so that two bots do not answer the same comment:

- `docs-bot.yml` and `docs-writer.yml` in `.github/workflows/`
- the `.github/docs-bot/` folder
- the caller workflow of the Signoff-Assistant
- the caller workflow of Signoff-Request, but only while `IMGAGENT_SIGNOFF_FORM=true`. If you set it to `false`, leave this workflow in place: it then handles the form issues.

## Optional settings: `.github/imgagent.toml`

By default, IMGAgent tells Claude about a repository using its name and its GitHub description. To give Claude more context for the docs commands, add `.github/imgagent.toml` on the default branch:

```toml
[docs]
about = "an open source project for running coding agents in sandboxed containers"
audience = "people who deploy and run agent-sandbox on their own Linux machines"
url = "https://industrial-mathematics-group.github.io/agent-sandbox/"   # "none": answers cite paths instead
```

| Key | Meaning |
|---|---|
| `about` | One sentence on what the project is. Defaults to the repository description. |
| `audience` | Who reads the docs. Defaults to "people who use" the project. |
| `url` | The published site. Answers from `ask docs` link to pages under this address. Defaults to `https://<owner>.github.io/<repository>/` with the owner in lowercase. Set it to `"none"` (or an empty string) to have answers cite paths under `docs/` instead of links. |
| `project` | The project's name. Defaults to the repository name. |

If the file is not valid TOML, it is ignored and the defaults are used.

For every key, see the [configuration reference](../reference/index.md).
