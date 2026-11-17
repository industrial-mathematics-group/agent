# Run the container

IMGAgent runs as one container, built from this repository. This page covers starting it with Dockge or plain Docker Compose, what `compose.yaml` and the image do, and how to update it.

Before you start, you need the App's ID, its webhook secret and its private key from [Register the GitHub App](github-app.md), and a Claude Console API key.

## Set up the stack folder

On the server, go to Dockge's stacks folder (by default `/opt/stacks`) and clone the repository:

```bash
cd /opt/stacks
git clone https://github.com/IMGAgent/imgagent.git
cd imgagent
cp .env.example .env
cp ~/Downloads/imgagent.*.private-key.pem imgagent.pem
chmod 644 imgagent.pem
```

The container runs as the unprivileged user with uid 10001. It must be able to read `imgagent.pem`, which is why the file needs mode 644.

Fill in `.env` with an editor, or with the env editor of the stack in Dockge. These four are required:

| Variable | Value |
|---|---|
| `IMGAGENT_APP_ID` | the App ID from the App's settings page |
| `IMGAGENT_WEBHOOK_SECRET` | the webhook secret you entered in the App's settings |
| `IMGAGENT_ALLOWED_OWNERS` | comma-separated accounts that are answered, e.g. `industrial-mathematics-group` |
| `ANTHROPIC_API_KEY` | a Claude Console API key, ideally in a workspace with a spend limit |

The other variables are optional. See the [configuration reference](../reference/index.md).

!!! warning
    Never commit `.env` or `imgagent.pem`. Both are listed in `.gitignore` and `.dockerignore`.

## Start it

=== "Dockge"
    The stack `imgagent` appears in Dockge. If it does not, use *Scan Stacks Folder*. Press **Start**. The first start builds the image.

=== "Compose"
    ```bash
    docker compose up -d --build
    ```

Check the log. A working start contains this line:

```text
signed in as the GitHub App imgagent
```

The server then logs the App's events and permissions, the accounts it is installed on, and `listening on :8080`. If it logs warnings instead, see [troubleshooting](../operations/troubleshooting.md).

## What compose.yaml sets

| Setting | Effect |
|---|---|
| `build: .` and `image: imgagent:local` | the image is built locally from the `Dockerfile` |
| `restart: unless-stopped` | the container comes back after a reboot or crash |
| `env_file: .env` | the settings come from `.env` |
| `secrets: imgagent_private_key` | `./imgagent.pem` is mounted at `/run/secrets/imgagent_private_key` |
| `ports` | `127.0.0.1:${IMGAGENT_PORT:-8080}:8080`, reachable only from the host itself |
| `read_only: true` | the root file system of the container cannot be written |
| `tmpfs: /tmp:size=2g` | the clones of repositories (removed after each job) and git's config live here |
| `no-new-privileges:true` | processes in the container cannot gain more privileges |
| `logging` | `json-file`, at most 10 MB per file and 3 files |

Because the port is bound to `127.0.0.1`, GitHub cannot reach it directly. See [Expose the webhook to GitHub](expose.md).

## What the image does

The `Dockerfile` starts from `python:3.13-slim` and installs `git`, `tini` and `ca-certificates`. It installs the packages from `requirements.txt`, copies `imgagent/`, `scripts/` and `entrypoint.sh`, and switches to the user `imgagent` (uid 10001). It sets `PORT=8080` and has a health check that requests `/healthz`. `tini` is the first process: it forwards signals and reaps the git and script subprocesses.

`entrypoint.sh` runs before the server:

1. If `IMGAGENT_PRIVATE_KEY_FILE` is not set and `/run/secrets/imgagent_private_key` exists, it uses that file.
2. If a key file is set but cannot be read, it prints an error and exits.
3. It sets `HOME` to `/tmp/home`, because the root file system is read-only, and sets two global git options there.
4. It starts `python -m imgagent.server`.

## Update

```bash
git pull
docker compose up -d --build
```

In Dockge, run the second command in the terminal of the stack.

!!! note
    Dockge's *Update* button only pulls images. It does not rebuild an image that was built locally.

## Prebuilt image

The workflow `.github/workflows/docker.yml` builds the image and pushes it to `ghcr.io/<owner>/<repository>`. It runs on pushes to `main`, on tags starting with `v`, and on manual dispatch. The tags are `latest` (from the default branch), the version for `v*` tags, and the commit SHA.

`compose.yaml` does not use this image; it builds locally. To use the prebuilt image instead, you would have to replace `build: .` and `image:` in `compose.yaml` yourself.
