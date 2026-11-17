# Run the container

IMGAgent runs as a single container built from this repository with Docker Compose. This page covers starting it with Dockge or plain `docker compose`, the settings it needs, and what the container is set up to do.

Before you start, you need the App ID, the webhook secret and the downloaded private key from [Register and install the GitHub App](github-app.md), and a Claude Console API key.

## Get the code and the settings

On the VPS, clone the repository into Dockge's stacks folder (by default `/opt/stacks`), then create `.env` and put the private key next to `compose.yaml`:

```bash
cd /opt/stacks
git clone https://github.com/IMGAgent/imgagent.git
cd imgagent
cp .env.example .env            # then fill it in (or in Dockge's env editor)
cp ~/Downloads/imgagent.*.private-key.pem imgagent.pem
chmod 644 imgagent.pem          # the container runs as uid 10001 and must be able to read it
```

The key must be readable by the container user (uid 10001). If the container can't read it, the entry point stops with:

```
IMGAgent: can't read the private key at /run/secrets/imgagent_private_key
```

!!! warning
    `.env` and `imgagent.pem` hold secrets. Both are listed in `.gitignore` and `.dockerignore`. Never commit them.

### Required settings

Fill in these four in `.env`:

| Variable | Value |
|---|---|
| `IMGAGENT_APP_ID` | the App ID shown at the top of the App's settings page |
| `IMGAGENT_WEBHOOK_SECRET` | the webhook secret you entered in the App's settings |
| `IMGAGENT_ALLOWED_OWNERS` | the accounts whose installations are answered, comma-separated, e.g. `industrial-mathematics-group` |
| `ANTHROPIC_API_KEY` | a Claude Console API key, ideally in a workspace with a spend limit |

If any of them is missing, or the private key can't be found, the server exits at startup and lists what is missing, for example:

```
IMGAgent: missing settings: ANTHROPIC_API_KEY (see .env.example)
```

The other settings are optional. They are described in `.env.example` and in [Environment variables](../reference/index.md). For other ways to provide the key, see [Private key](../reference/private-key.md).

## Start it

=== "Dockge"
    The stack `imgagent` appears in Dockge. If it doesn't, use *Scan Stacks Folder*. Press **Start**. The first start builds the image.

=== "Docker Compose"
    In the repository folder:

    ```bash
    docker compose up -d --build
    ```

Check the log (Dockge shows it on the stack's page, or run `docker compose logs -f`). After a successful start it contains:

```
signed in as the GitHub App imgagent; answering @IMGAgent
```

followed by the App's events and permissions, the accounts it is installed on, and `listening on :8080`. Warnings at this point point to App settings that would leave commands unanswered. See [Troubleshooting](../operations/troubleshooting.md).

If GitHub can't be reached at startup, the server logs an error mentioning `IMGAGENT_APP_ID` and the private key, and keeps running.

Next, make the server reachable for GitHub: [Expose it to GitHub](expose.md).

## Update

Pull the new code and rebuild:

```bash
git pull
docker compose up -d --build
```

Run this in Dockge's terminal for the stack or in a shell in the repository folder.

!!! note
    Dockge's *Update* button only pulls images. It doesn't rebuild the locally built `imgagent:local` image, so use the commands above.

## What the container sets up

### compose.yaml

`compose.yaml` defines one service, `imgagent`, built from the repository's `Dockerfile` and tagged `imgagent:local`.

| Setting | Effect |
|---|---|
| `restart: unless-stopped` | restarts the container unless you stopped it |
| `env_file: .env` | the settings |
| `ports: "127.0.0.1:${IMGAGENT_PORT:-8080}:8080"` | publishes the server on the loopback interface only, for a reverse proxy on the same host. The host port defaults to 8080 and can be changed with `IMGAGENT_PORT` |
| `secrets: imgagent_private_key` (from `./imgagent.pem`) | mounts the private key at `/run/secrets/imgagent_private_key` |
| `read_only: true` | the root file system is read-only |
| `tmpfs: /tmp:size=2g` | a 2 GB in-memory `/tmp` for the repository clones (removed after each job) and git's config |
| `security_opt: no-new-privileges:true` | processes can't gain privileges |
| `logging` | `json-file` driver, at most 3 files of 10 MB each |

### Dockerfile

The image is based on `python:3.13-slim` and adds `git`, `tini` and `ca-certificates`. It installs the Python packages from `requirements.txt` and copies `imgagent/`, `scripts/` and `entrypoint.sh`.

- The container runs as the unprivileged user `imgagent` (uid 10001).
- `tini` is the init process. It reaps the git and script subprocesses and forwards signals.
- `PORT=8080` is the port the server listens on inside the container. Port 8080 is exposed.
- `GIT_TERMINAL_PROMPT=0` keeps git from waiting for credentials on a prompt.
- A health check requests `http://127.0.0.1:$PORT/healthz` every 30 seconds, with a 5 second timeout.

### entrypoint.sh

Before starting the server, the entry point:

1. Uses the mounted secret `/run/secrets/imgagent_private_key` as `IMGAGENT_PRIVATE_KEY_FILE` when that variable isn't set and the file exists, and exits with an error if the key file isn't readable.
2. Sets `HOME=/tmp/home`, because the root file system is read-only, and sets git's global config there (`init.defaultBranch main`, `advice.detachedHead false`). The git identity for commits is set per commit by the jobs.
3. Starts the webhook server with `python -m imgagent.server`.
