# IMGAgent

The GitHub bot of the Industrial Mathematics Group, as one small container. People write a command in an issue
or a comment, GitHub sends the event to this server, and IMGAgent answers as `imgagent[bot]`:

| Command | Where | What happens |
|---|---|---|
| `@IMGAgent signoff` and your words | new issue or issue comment | Claude turns them into the answers of the signoff form; IMGAgent opens a `SIGNOFF.toml` pull request, or asks what is missing |
| `@IMGAgent ask <folders> [with <folders>]` and a question | anywhere in a comment or a new issue | Claude answers from the files in those folders, e.g. `ask docs` or `ask docs,src` |
| `@IMGAgent update <folders> [with <folders>]` and a task | anywhere in a comment or a new issue | Claude carries out a small task by editing existing files in the folders and at the top level, reading the `with` folders; IMGAgent opens a pull request |
| `@IMGAgent make docs [with <folders>]` and a hint | anywhere in a comment or a new issue | Claude rebuilds `docs/` from the code (or only from the `with` folders); IMGAgent opens a pull request |
| `@IMGAgent setup reuse`, `aisignoff`, `citation` or `docs` | anywhere in a comment or a new issue | IMGAgent posts a template for `REUSE.toml`, `SIGNOFF.toml`, `CITATION.cff` or `zensical.toml` with defaults filled in; ticking its **Done** box opens the pull request, without AI |
| `@IMGAgent help` | anywhere in a comment or a new issue | the list of commands |
| the issue form *Signoff: declare or attest files* | new or edited issue | IMGAgent opens the `SIGNOFF.toml` pull request, without AI (`IMGAGENT_SIGNOFF_FORM`) |

Commands are *action, folders, then text*:

```
@IMGAgent update docs with src
the docs still describe the old commands; bring them in line with the code
```

- **Folders** are a comma-separated list of folders (or files) of the repository, as relative paths such as `docs`,
  `src/package` or `pyproject.toml`; spaces around the commas are fine. Every folder must exist, and `..`, absolute
  paths, `.git` and glob characters are refused.
- **`with <folders>`** on the same line adds folders that Claude only reads. For `ask` it makes no difference.
- **The text** (question, task or hint) may start on the same line or on the next one, and span several lines.
  Start it on the next line if it begins with the word "with".

| Command | Reads | May change |
|---|---|---|
| `ask docs,src` | `docs`, `src` | nothing |
| `update src` | `src` and the top-level files (`pyproject.toml`, `README.md`, ...) | existing files among those, never `.github/workflows/` |
| `update docs with src` | `docs`, the top-level files and `src` | existing files in `docs` and at the top level |
| `make docs` | all the code | `docs/` and `zensical.toml`, creating and removing pages |
| `make docs with src` | `src` and the top-level files | the same |

`setup <reuse|aisignoff|citation|docs>` needs no text: IMGAgent answers with a template for the file, its
defaults already filled in from the repository and from you. Tick boxes in the comment, change the values between
backticks if needed (*Edit*), then tick **Done** (or reply `@IMGAgent setup <target> done`). IMGAgent turns the form
into the file and opens a pull request; if something can't be used, it unticks **Done** and says why on top of the
form. No model is involved, so the pull requests are declared G0. An existing file is never replaced.

| Command | Template | Pull request |
|---|---|---|
| `setup reuse` | copyright, the common licenses as boxes (the repository's license ticked for `.`), each with the folders it is for, and two free lines for other licenses | `REUSE.toml`, and the license texts in `LICENSES/` from the SPDX license list |
| `setup aisignoff` | the default declaration (paths, levels, names), `[history]` (on, default branch, merge method), exclusions, policy, recheck | `SIGNOFF.toml`, checked with aisignoff |
| `setup citation` | title, message, type, authors with ORCID, version, date, license, repository, DOI, abstract, keywords (from the repository) | `CITATION.cff` |
| `setup docs` | site name, description, address | `zensical.toml` as `make docs` writes it, with the nav of the pages in `docs/` (and a `docs/index.md` if missing) |

`update` never creates, deletes or renames a file: it is for small tasks over several files, such as
`update src` + "require Python 3.13" or `update docs with src` + "fix what is outdated". `make` creates files,
which depends much more on the task, so it only knows `docs` for now. What one command reads is limited to about
150k tokens; name smaller folders for more.

Only people with write access to the repository are answered, never bots. Nothing is pushed to a default branch:
every change is a pull request that a person reviews, ticks and merges. Repositories need no workflow files.

```
comment "@IMGAgent make docs" ──► GitHub App webhook (HTTPS, signed) ──► reverse proxy ──► imgagent container
                                                                                         │ verifies the signature
   pull request + comment  ◄── installation token (1 h, this installation only) ◄─────────┘ clones, runs Claude
```

The Claude work is done by the scripts in `scripts/`, the same code the GitHub Actions versions of these bots
ran (`scripts/docs/` from agent-sandbox's docs bot, `scripts/repo/` for `ask` and `update`, `scripts/signoff/` extracted from the Signoff-Assistant and
Signoff-Request workflows of `industrial-mathematics-group/.github`). The server (`imgagent/`) only receives
events, gets tokens, clones and talks to GitHub.

## 1. Reserve the name

`@IMGAgent` in a comment links to whatever GitHub account is called `IMGAgent`, so own it: create a free
organisation **IMGAgent** and leave it empty. Mentioning an organisation notifies nobody. GitHub only lets an App
take an existing account's name when that account owns the App, so the App is registered under this organisation.

## 2. Register the GitHub App

*github.com/organizations/IMGAgent/settings/apps → New GitHub App*:

| Setting | Value |
|---|---|
| GitHub App name | `IMGAgent` |
| Homepage URL | `https://github.com/industrial-mathematics-group` (or this repository) |
| Callback URL, Setup URL, Device flow | leave empty / off |
| **Webhook → Active** | **on** |
| Webhook URL | `https://<your-domain>/webhook` (section 5) |
| Webhook secret | a long random string, e.g. `openssl rand -hex 32`; the same goes into `.env` as `IMGAGENT_WEBHOOK_SECRET` |
| SSL verification | enabled |

**Repository permissions** (everything else: *No access*):

| Permission | Access | Used for |
|---|---|---|
| Contents | Read and write | cloning, pushing the pull request branches |
| Issues | Read and write | comments, reactions |
| Pull requests | Read and write | opening pull requests, assigning the requester |
| Metadata | Read-only (always on) | the write-access check |

No organisation or account permissions. Leave **Workflows** off: IMGAgent never changes `.github/workflows/`.

**Subscribe to events:** **Issues** and **Issue comment**. (Comments on pull requests arrive as issue comments.)

**Where can this GitHub App be installed?** **Any account**: it is owned by `IMGAgent` and installed on
`industrial-mathematics-group`. Anyone could install it, but the server only answers the accounts in
`IMGAGENT_ALLOWED_OWNERS`, and only you hold the private key.

After *Create GitHub App*: note the **App ID** at the top, then *Private keys → Generate a private key* and keep
the downloaded `.pem` file. Optionally upload a logo (the org's `logos/` folder has avatars).

## 3. Install it

On the App's page, *Install App* → `industrial-mathematics-group` → *Only select repositories* (or all). The bot
works in exactly these repositories; add more later under the organisation's *Settings → GitHub Apps*.

## 4. Run it with Dockge

On the VPS, in Dockge's stacks folder (by default `/opt/stacks`):

```sh
cd /opt/stacks
git clone https://github.com/IMGAgent/imgagent.git    # this repository
cd imgagent
cp .env.example .env            # then fill it in (or in Dockge's env editor)
cp ~/Downloads/imgagent.*.private-key.pem imgagent.pem
chmod 644 imgagent.pem          # the container runs as uid 10001 and must be able to read it
```

In `.env`: `IMGAGENT_APP_ID`, `IMGAGENT_WEBHOOK_SECRET`, `IMGAGENT_ALLOWED_OWNERS=industrial-mathematics-group`
and `ANTHROPIC_API_KEY` (a Claude Console key, ideally in a workspace with a spend limit). The other settings are
optional and explained in `.env.example`.

In Dockge the stack `imgagent` appears (use *Scan Stacks Folder* if not); press **Start**. The first start builds
the image. The log should say `signed in as the GitHub App imgagent`.

Without Dockge, the same is `docker compose up -d --build` in this folder.

**Updating:** `git pull`, then `docker compose up -d --build` (Dockge's terminal for the stack, or the shell).
Dockge's *Update* button only pulls images, which doesn't rebuild a locally built one.

## 5. Expose it to GitHub

GitHub must reach `https://<your-domain>/webhook`. `compose.yaml` publishes the container on
`127.0.0.1:8080` only, for a reverse proxy on the same host:

- **Caddy:** `imgagent.example.org { reverse_proxy 127.0.0.1:8080 }`
- **Nginx Proxy Manager / Traefik:** a proxy host for your domain to `127.0.0.1:8080` (or to the container
  `imgagent:8080` on a shared Docker network), with a Let's Encrypt certificate.
- **No open ports:** a Cloudflare Tunnel to `http://127.0.0.1:8080`.

If the proxy runs in another container, change the port line in `compose.yaml` to `"8080:8080"` or put both on
one Docker network. The server checks every delivery's `X-Hub-Signature-256`; anything unsigned gets `401`.

**Test:** on the App's page, *Advanced → Recent Deliveries* shows the `ping` sent at creation; *Redeliver* it and
expect `200 pong`. Then write `@IMGAgent help` in an issue of an installed repository.

## 6. Per repository

Nothing to add. To move a repository over from the GitHub Actions bots, delete their workflow files
(`docs-bot.yml`, `docs-writer.yml`, `.github/docs-bot/`, the Signoff-Assistant caller, and the Signoff-Request
caller while `IMGAGENT_SIGNOFF_FORM=true`), so two bots don't answer the same thing.

- `make docs` writes a Zensical site: `docs/` and `zensical.toml`. Without them, it creates both (a complete `zensical.toml` with theme, Markdown extensions and nav); an existing `zensical.toml` keeps everything but its `nav`.
  `ask` and `update` only need the folders you name.
- `signoff` and the form need a `SIGNOFF.toml` (`aisignoff init`, or `@IMGAgent setup aisignoff`). The pull requests follow the organisation's
  PR template, so *PR-signoff* checks them; as an App's pull requests, they start the repository's checks.
- Optional `.github/imgagent.toml` on the default branch, to tell Claude more than the repository description:

```toml
[docs]
about = "an open source project for running coding agents in sandboxed containers"
audience = "people who deploy and run agent-sandbox on their own Linux machines"
url = "https://industrial-mathematics-group.github.io/agent-sandbox/"   # "none": answers cite paths instead
```

## Settings

All in `.env` (see `.env.example`): the App (`IMGAGENT_APP_ID`, `IMGAGENT_WEBHOOK_SECRET`, the private key as the
file `imgagent.pem` or `IMGAGENT_PRIVATE_KEY`), `IMGAGENT_ALLOWED_OWNERS`, `ANTHROPIC_API_KEY`, and optionally
`IMGAGENT_HANDLE`, `IMGAGENT_SIGNOFF_FORM`, `IMGAGENT_WORKERS` and the models (`ASK_MODEL` default
`claude-haiku-5-5` for `ask`, `WRITER_MODEL` default `claude-opus-5-5` and `WRITER_EFFORT` for `update` and `make`,
`SIGNOFF_MODEL` default `claude-sonnet-5-5` with `SIGNOFF_MODEL_NAME`, keep both in step). The old names
`DOCS_ASK_MODEL`, `DOCS_WRITER_MODEL` and `DOCS_WRITER_EFFORT` still work.

## Safety

- Signed webhooks only; redeliveries of the same delivery id are ignored; other accounts' installations are ignored.
- Only people with write, maintain or admin permission are answered, never bots.
- Comment text reaches the scripts as environment variables, never a shell. The repository's code is read, not
  run. The models have no tools: they return text or a fixed JSON schema, which the scripts check.
- Folders are checked twice: by name when the command is read, and in the clone (they must exist and stay inside
  the repository, also through symlinks). `update` commits only modified tracked files under its target folders or
  at the top level, never the `with` folders; anything else the script left in the clone stays out of the pull request.
- `setup reuse` fetches the license texts for `LICENSES/` from the SPDX license list
  (`raw.githubusercontent.com/spdx/license-list-data`); nothing else is fetched besides GitHub's API and clones.
- Each job works in a temporary clone that is deleted afterwards. The container runs as an unprivileged user on a
  read-only root file system; tokens are installation tokens that expire after an hour.
- The Claude key and the private key live only in `.env` and `imgagent.pem` on the VPS; neither is in git.

## Development

```sh
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt pytest
python -m pytest tests
```

`tests/` covers the routing of events to commands and the target checks, the signature check, the HTTP server,
which files `ask` and `update` read and may change, and the branch, commit and pull request of `make` and
`update`, with a local git repository instead of GitHub.

When the bots change in `industrial-mathematics-group/.github`, copy the Python step of
`.github/workflows/signoff-assistant.yml` and `signoff-request.yml` into `scripts/signoff/assistant.py` and
`request.py` (keep the header comment), and bump `aisignoff` in `requirements.txt` with the organisation's version.
