# Private key

IMGAgent signs in to GitHub as the App with the App's private key, the `.pem` file you download from the App's settings. This page covers the ways to give the key to the container, the order in which they are checked, and what the server does with the key.

## Ways to provide the key

There are three ways. In order of preference:

1. **The file `imgagent.pem` next to `compose.yaml`.** `compose.yaml` passes it to the container as the compose secret `imgagent_private_key`, mounted at `/run/secrets/imgagent_private_key`.
2. **`IMGAGENT_PRIVATE_KEY_FILE`**, the path of a key file inside the container.
3. **`IMGAGENT_PRIVATE_KEY`**, the key itself on one line in `.env`.

=== "Compose secret (recommended)"

    Save the downloaded key as `imgagent.pem` in the stack folder and make it readable for the container:

    ```bash
    cd /opt/stacks/imgagent
    cp ~/Downloads/imgagent.*.private-key.pem imgagent.pem
    chmod 644 imgagent.pem
    ```

    `compose.yaml` declares the secret:

    ```yaml
    services:
      imgagent:
        secrets:
          - imgagent_private_key

    secrets:
      imgagent_private_key:
        file: ./imgagent.pem
    ```

    You do not need to set any variable. The entry point finds the mounted file on its own.

=== "One line in .env"

    Paste the key into `.env` on a single line. Write each line break as the two characters `\n`:

    ```ini
    IMGAGENT_PRIVATE_KEY=-----BEGIN RSA PRIVATE KEY-----\nMIIE...\n-----END RSA PRIVATE KEY-----
    ```

    The server turns every `\n` back into a real line break before it uses the key.

!!! warning "File permissions"
    The container runs as the unprivileged user with uid `10001`, not as the owner of the file on the host. If that user cannot read `imgagent.pem`, the container stops at startup. Use `chmod 644 imgagent.pem`.

The key does not end up in git or in the image. `.gitignore` and `.dockerignore` both exclude `*.pem` and `.env`.

## How the key is found

`entrypoint.sh` runs before the server starts:

- If `IMGAGENT_PRIVATE_KEY_FILE` is not set and `/run/secrets/imgagent_private_key` exists, the entry point sets `IMGAGENT_PRIVATE_KEY_FILE` to that path. This is why the compose secret takes priority over `IMGAGENT_PRIVATE_KEY`.
- If `IMGAGENT_PRIVATE_KEY_FILE` is set but the file cannot be read, the container exits with:

    ```text
    IMGAgent: can't read the private key at /run/secrets/imgagent_private_key
    ```

The server then reads the key:

1. If `IMGAGENT_PRIVATE_KEY_FILE` names an existing file, the server uses that file's contents.
2. Otherwise it uses `IMGAGENT_PRIVATE_KEY` and replaces each literal `\n` with a line break.

At startup the server checks that the result contains the text `PRIVATE KEY`. If it does not, the server exits and names the key among the missing settings:

```text
IMGAgent: missing settings: IMGAGENT_PRIVATE_KEY_FILE (or IMGAGENT_PRIVATE_KEY) (see .env.example)
```

## What the key is used for

The private key never leaves the container. The server uses it only to sign short JWTs, and exchanges those JWTs for installation tokens that do the actual work.

```mermaid
sequenceDiagram
  participant S as IMGAgent server
  participant G as GitHub API
  S->>S: sign a JWT with the private key (RS256)
  S->>G: GET /app (JWT)
  G-->>S: the App's slug, events, permissions
  S->>G: POST /app/installations/{id}/access_tokens (JWT)
  G-->>S: installation token (valid 1 hour)
  S->>G: clone, push, comments, pull requests (installation token)
```

### JWTs

Each JWT is signed with RS256 and contains:

| Claim | Value |
|---|---|
| `iss` | `IMGAGENT_APP_ID` |
| `iat` | now minus 60 seconds, to allow for clock drift |
| `exp` | now plus 540 seconds |

The JWT authenticates only as the App itself. The server uses it at startup to log what GitHub knows about the App (`GET /app`, `GET /app/installations`), to look up the App's slug, and to request installation tokens.

If the startup check cannot reach GitHub as the App, the server logs the error below and keeps running:

```text
could not reach GitHub as the app (check IMGAGENT_APP_ID and the private key): ...
```

A wrong App ID or a key from another App usually shows up here. See [Troubleshooting](../operations/troubleshooting.md).

### Installation tokens

For each webhook delivery, the server requests a token for the installation that sent it (`POST /app/installations/{id}/access_tokens`). The token:

- is valid for one hour,
- covers only the repositories that installation was given access to,
- carries only the App's permissions (Contents, Issues and Pull requests with write access, plus Metadata; see [Register and install the GitHub App](../getting-started/github-app.md)).

The token is not narrowed to the single repository of the event, because the signoff scripts also read the organisation's pull request template from its `.github` repository.

The token is used to clone the repository (as `https://x-access-token:<token>@github.com/<owner>/<repo>.git`) and for all API calls of the job. `make docs` and `update` can run for a long time, so before they push their branch they get a fresh token and set it on the clone's `origin`. The signoff form job also gets a fresh token when it starts.

## Related settings

- `IMGAGENT_APP_ID`, the App ID shown at the top of the App's settings page. The key must belong to this App.
- All other settings are listed in [Environment variables](index.md).
