# Configuration reference

IMGAgent is configured through environment variables, normally set in the `.env` file next to `compose.yaml`. This page lists every setting the code reads, with its default.

## Required settings

The server refuses to start and names the missing settings if any of these is empty (see [Troubleshooting](../operations/troubleshooting.md)).

| Variable | What it is |
|---|---|
| `IMGAGENT_APP_ID` | The App ID shown at the top of the GitHub App's settings page. |
| `IMGAGENT_WEBHOOK_SECRET` | The webhook secret you entered in the App's settings, for example from `openssl rand -hex 32`. Every delivery's `X-Hub-Signature-256` is checked against it. |
| `IMGAGENT_ALLOWED_OWNERS` | Comma-separated account names. Only installations on these accounts are answered. `*` allows every account. See [Access control](allowed-owners.md). |
| `ANTHROPIC_API_KEY` | A Claude Console API key, ideally from a workspace with a spend limit. |
| The private key | The App's private key, as a file or a variable. See below. |

### The private key

Supply the key in one of these ways. The server needs a value containing `PRIVATE KEY`, otherwise it does not start.

| Source | Details |
|---|---|
| `./imgagent.pem` | Mounted by `compose.yaml` as a secret at `/run/secrets/imgagent_private_key`. `entrypoint.sh` uses it automatically. Preferred. |
| `IMGAGENT_PRIVATE_KEY_FILE` | Path to a key file inside the container. Takes precedence over the mounted secret. |
| `IMGAGENT_PRIVATE_KEY` | The key on one line, with `\n` for the line breaks. Used when no file is given. |

More detail is on [The private key and secrets](private-key.md).

## Optional settings

| Variable | Default | What it does |
|---|---|---|
| `IMGAGENT_HANDLE` | `IMGAgent` | The name people write after `@`. |
| `IMGAGENT_SIGNOFF_FORM` | `true` | Turns issues made with the form "Signoff: declare or attest files" into pull requests, without AI. Accepted true values are `1`, `true` and `yes`; anything else turns it off and leaves such issues to the repository's own workflow. |
| `IMGAGENT_WORKERS` | `2` | Number of jobs that run at the same time. Each job needs a clone of a repository and a few hundred MB at most. |
| `IMGAGENT_PORT` | `8080` | The host port that `compose.yaml` publishes on `127.0.0.1`. It does not change the port inside the container. |
| `PORT` | `8080` | The port the server listens on inside the container. The Dockerfile sets it to `8080`, and the health check uses it. |
| `LOG_LEVEL` | `INFO` | Python log level of the server log. |

## Model settings

These choose the Claude models used by each kind of job. Each has a default, so you only set them to change the model.

| Variable | Default | Used for |
|---|---|---|
| `ASK_MODEL` | `claude-haiku-5-5` | `ask` answers. The old name `DOCS_ASK_MODEL` works too. |
| `WRITER_MODEL` | `claude-opus-5-5` | `update` and `make docs`. The old name `DOCS_WRITER_MODEL` works too. |
| `WRITER_EFFORT` | `medium` | Effort level of `update` and `make docs` (`low`, `medium`, `high`, `xhigh` or `max`). The old name `DOCS_WRITER_EFFORT` works too. |
| `SIGNOFF_MODEL` | `claude-sonnet-5-5` | The signoff assistant that reads your words. |
| `SIGNOFF_MODEL_NAME` | `Claude Sonnet 5.5 (Anthropic)` | The name written into the signoff comment and pull request as the assistant. |
| `SIGNOFF_EFFORT` | `medium` | Effort level of the signoff assistant. |

!!! warning
    If you change `SIGNOFF_MODEL`, change `SIGNOFF_MODEL_NAME` to match. The name is recorded in the pull request as the model that read the request, so the two must stay in step.

## Example `.env`

```bash
IMGAGENT_APP_ID=123456
IMGAGENT_WEBHOOK_SECRET=0123456789abcdef
IMGAGENT_ALLOWED_OWNERS=industrial-mathematics-group
ANTHROPIC_API_KEY=sk-ant-...

# optional
IMGAGENT_WORKERS=2
SIGNOFF_MODEL=claude-sonnet-5-5
SIGNOFF_MODEL_NAME=Claude Sonnet 5.5 (Anthropic)
```

Never commit `.env` or `imgagent.pem`. Per-repository settings are not environment variables; they live in [`.github/imgagent.toml`](repo-config.md).
