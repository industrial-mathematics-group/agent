# Per-repository setup

A repository needs no workflow files or other setup for IMGAgent to work in it. This page lists what individual commands expect to find, the optional settings file, and how to move a repository over from the older GitHub Actions bots.

## What each command needs

| Command | What the repository needs |
|---|---|
| `ask`, `update` | Only the folders or files you name. Each one must exist in the repository. |
| `make docs` | Nothing. It creates `docs/` and `zensical.toml` if they are missing. |
| `signoff` and the signoff issue form | A `SIGNOFF.toml`, created once with `aisignoff init`. |
| `help` | Nothing. |

### `make docs` and Zensical

`make docs` writes a [Zensical](https://zensical.org) site, which consists of the Markdown pages in `docs/` and the configuration file `zensical.toml`.

- **Without `zensical.toml`:** IMGAgent creates a complete file with the site settings, theme, Markdown extensions and `nav`.
- **With an existing `zensical.toml`:** IMGAgent keeps everything in it and replaces only `nav`.

!!! warning
    `make docs` is a full rebuild. Every Markdown page under `docs/` is rewritten, and pages that are not in the new plan are removed. Other files in `docs/`, such as images, stay. If you want to keep hand-written pages, restore them during review of the pull request. For small changes to existing pages, use `@IMGAgent update docs with src` instead.

See [make docs](../usage/make-docs.md) for details.

### `signoff` and `SIGNOFF.toml`

The signoff assistant and the issue form *Signoff: declare or attest files* both record their results in `SIGNOFF.toml`. If the file is missing, IMGAgent refuses the request and asks a maintainer to create the file once:

```bash
aisignoff init
```

The resulting pull requests follow the organisation's PR template, so the *PR-signoff* check runs on them. They are opened by a GitHub App, so they trigger the repository's checks like any other pull request. See [signoff](../usage/signoff.md).

## Optional: `.github/imgagent.toml`

To give Claude more context than the repository description, add `.github/imgagent.toml` to the default branch:

```toml
[docs]
about = "an open source project for running coding agents in sandboxed containers"
audience = "people who deploy and run agent-sandbox on their own Linux machines"
url = "https://industrial-mathematics-group.github.io/agent-sandbox/"   # "none": answers cite paths instead
```

Every key is optional. If a key is missing:

- `about` falls back to the repository description.
- `url` falls back to `https://<owner>.github.io/<repository>/`.

If the file is not valid TOML, IMGAgent logs a warning and ignores the file. All keys, including `project`, are described in [Repository settings file](../reference/repo-config.md).

## Moving over from the GitHub Actions bots

If IMGAgent and the old workflows both run in a repository, both bots answer the same commands. Delete these files from the repository:

- `docs-bot.yml`
- `docs-writer.yml`
- `.github/docs-bot/`
- the workflow that calls Signoff-Assistant
- the workflow that calls Signoff-Request, if `IMGAGENT_SIGNOFF_FORM` is on (the default `true`). With `IMGAGENT_SIGNOFF_FORM=false`, IMGAgent leaves issue forms alone, and that workflow keeps handling them.

## Publishing the docs on GitHub Pages

The GitHub App has no *Workflows* permission, and IMGAgent never changes `.github/workflows/`. Neither `make docs` nor `update` can add a Pages workflow, so add one by hand once.

1. In the repository, open *Settings → Pages* and set *Source* to *GitHub Actions*.
2. Add a workflow such as `.github/workflows/docs.yml`:

    ```yaml
    on: { push: { branches: [main] } }
    permissions: { contents: read, pages: write, id-token: write }
    jobs:
      deploy:
        environment: { name: github-pages, url: "${{ steps.deployment.outputs.page_url }}" }
        runs-on: ubuntu-latest
        steps:
          - uses: actions/configure-pages@v6
          - uses: actions/checkout@v7
          - uses: actions/setup-python@v6
            with: { python-version: 3.x }
          - run: pip install zensical      # pin it, e.g. zensical==0.1.1, so a release can't break the build
          - run: zensical build --clean
          - uses: actions/upload-pages-artifact@v5
            with: { path: site }
          - uses: actions/deploy-pages@v5
            id: deployment
    ```

The site is then published at `https://<owner>.github.io/<repo>/`. Use that address as `site_url` in `zensical.toml`. This matches the default `url` that IMGAgent uses when `.github/imgagent.toml` does not set one.

To preview the site locally:

```bash
pip install zensical
zensical serve              # http://localhost:8000
zensical build --clean      # static site in site/
```
