# Environment variables

IMGAgent reads its settings from environment variables, which `compose.yaml` loads from the `.env` file next to it. This page lists every variable the server and the container read, with defaults and what each one changes.

## Where the settings live

`compose.yaml` passes the whole `.env` file to the container (`env_file: .env`). Start from the template:

```bash
cp .env.example .env
```

In Dockge, the same file is the stack's *env* editor. Never commit `.env` or `imgagent.pem`; both are listed in `.gitignore` and `.dockerignore`.

At startup the server checks the required settings. If any is missing, it exits with a message such as:

```text
IMGAgent: missing settings: IMGAGENT_APP_ID, ANTHROPIC_API_KEY (see .env.example)
```

For the optional settings, an empty value counts as unset and the default applies.

## Required

| Variable | What it is |
|---|---|
| `IMGAGENT_APP_ID` | The GitHub App's ID, shown at the top of the App's settings page. |
| `IMGAGENT_WEBHOOK_SECRET` | The webhook secret entered in the App's settings, e.g. from `openssl rand -hex 32`. Every delivery's `X-Hub-Signature-256` is checked against it. |
| `IMGAGENT_ALLOWED_OWNERS` | The accounts whose installations are answered, comma-separated. |
| `ANTHROPIC_API_KEY` | A Claude Console API key, ideally in a workspace with a spend limit. |
| The private key | Either the file `imgagent.pem` (mounted as a compose secret) or `IMGAGENT_PRIVATE_KEY`. See below and [Private key](private-key.md). |

### IMGAGENT_ALLOWED_OWNERS

The App can be installed by any account, so this list keeps other accounts from spending your Claude credit. Each entry is trimmed and compared case-insensitively with the owner of the repository in the event:

```ini
IMGAGENT_ALLOWED_OWNERS=industrial-mathematics-group
```

The entry `*` allows every owner. Events from other owners get `202 ignored: owner <name> is not in IMGAGENT_ALLOWED_OWNERS` and a warning in the log. At startup, the server also warns about every listed owner the App isn't installed on.

## The private key

| Variable | Default | What it does |
|---|---|---|
| `IMGAGENT_PRIVATE_KEY_FILE` | `/run/secrets/imgagent_private_key` when that file exists | Path of the App's private key inside the container. |
| `IMGAGENT_PRIVATE_KEY` | none | The key itself, on one line, with `\n` for the line breaks. Used when no key file is found. |

`compose.yaml` mounts `./imgagent.pem` as the secret `imgagent_private_key`, and `entrypoint.sh` sets `IMGAGENT_PRIVATE_KEY_FILE` to it unless the variable is already set. A mounted file is therefore preferred over the one-line variable. If `IMGAGENT_PRIVATE_KEY_FILE` names a file the container can't read, it stops with:

```text
IMGAgent: can't read the private key at <path>
```

Without a key file, paste the key into `.env`:

```ini
IMGAGENT_PRIVATE_KEY=-----BEGIN RSA PRIVATE KEY-----\n...\n-----END RSA PRIVATE KEY-----
```

The key must contain `PRIVATE KEY`, or the server reports it as a missing setting. Details are on [Private key](private-key.md).

## Optional

| Variable | Default | What it does |
|---|---|---|
| `IMGAGENT_HANDLE` | `IMGAgent` | The name people write after `@`. It should be the organisation you reserved for it. |
| `IMGAGENT_SIGNOFF_FORM` | `true` | `1`, `true` or `yes` (any case): issues made with the form *Signoff: declare or attest files* become `SIGNOFF.toml` pull requests. Any other value leaves them to the Signoff-Request workflow in each repository. |
| `IMGAGENT_WORKERS` | `2` | How many jobs run at the same time. Each job needs a clone of a repository. |
| `IMGAGENT_PORT` | `8080` | The host port that `compose.yaml` publishes, on `127.0.0.1` only. |
| `LOG_LEVEL` | `INFO` | The Python log level of the server, e.g. `DEBUG` or `WARNING`. |

`IMGAGENT_PORT` is only read by `compose.yaml`, in the port line:

```yaml
ports:
  - "127.0.0.1:${IMGAGENT_PORT:-8080}:8080"
```

See [Expose it to GitHub](../getting-started/expose.md) for when to change that line.

!!! note "IMGAGENT_SIGNOFF_FORM and the workflows"
    With `IMGAGENT_SIGNOFF_FORM=true`, remove the Signoff-Request caller workflow from the repositories, so that two bots don't answer the same issue. See [signoff](../usage/signoff.md).

## Models

| Variable | Old name | Default | Used by |
|---|---|---|---|
| `ASK_MODEL` | `DOCS_ASK_MODEL` | `claude-haiku-5-5` | `ask` |
| `WRITER_MODEL` | `DOCS_WRITER_MODEL` | `claude-opus-5-5` | `update` and `make` |
| `WRITER_EFFORT` | `DOCS_WRITER_EFFORT` | `medium` | `update` and `make` |
| `SIGNOFF_MODEL` | | `claude-sonnet-5-5` | `signoff` |
| `SIGNOFF_MODEL_NAME` | | `Claude Sonnet 5.5 (Anthropic)` | `signoff` |
| `SIGNOFF_EFFORT` | | `medium` | `signoff` |
| `REVIEW_MODEL` | | `claude-sonnet-5-5` | `review` |
| `REVIEW_MODEL_NAME` | | `Claude Sonnet 5.5 (Anthropic)` | `review` |
| `REVIEW_EFFORT` | | `low` | `review` |

The old `DOCS_*` names date from when every command was about `docs/`. They still work; the new name wins when both are set.

`WRITER_EFFORT` takes `low`, `medium`, `high`, `xhigh` or `max`. `ask` always runs at low effort.

Where the model names show up:

- `ASK_MODEL` is named in the footer of every answer.
- `WRITER_MODEL` is named in the commit message of `make` and `update` pull requests. The pull request's AI declaration ticks *Claude Opus*, *Claude Sonnet* or *Claude Fable* when the model id contains `opus`, `sonnet` or `fable`; otherwise it ticks *Other* with the model id. See [Pull requests](../usage/pull-requests.md).
- `SIGNOFF_MODEL_NAME` is the human-readable name of `SIGNOFF_MODEL`, shown in the assistant's comments and recorded in the signoff pull request. Change both together.

## Set by the image

These are set by the `Dockerfile` and `entrypoint.sh`. You normally leave them alone.

| Variable | Value | Purpose |
|---|---|---|
| `PORT` | `8080` | The port the server listens on inside the container, and the one the health check calls (`/healthz`). `compose.yaml` maps the host port to container port `8080`. |
| `PYTHONUNBUFFERED` | `1` | Log lines appear immediately. |
| `GIT_TERMINAL_PROMPT` | `0` | git never waits for a password prompt. |
| `HOME` | `/tmp/home` | git's global config goes to the `/tmp` tmpfs, since the root file system is read-only. |

## Example

```ini
IMGAGENT_APP_ID=123456
IMGAGENT_WEBHOOK_SECRET=0f3c...e9
IMGAGENT_ALLOWED_OWNERS=industrial-mathematics-group
ANTHROPIC_API_KEY=sk-ant-...

# optional
IMGAGENT_WORKERS=2
WRITER_MODEL=claude-opus-5-5
WRITER_EFFORT=medium
```

After changing `.env`, recreate the container (`docker compose up -d`, or *Restart* in Dockge) so it reads the new values. If commands go unanswered after a change, see [Troubleshooting](../operations/troubleshooting.md).
