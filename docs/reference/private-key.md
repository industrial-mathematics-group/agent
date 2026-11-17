# The private key and secrets

IMGAgent signs its requests to GitHub with the private key of the GitHub App. It reads the key from a file or from an environment variable. The Claude key and the webhook secret are plain settings in `.env`.

## How the key is found

At start, `entrypoint.sh` and `imgagent/server.py` look for the key in this order:

1. **`IMGAGENT_PRIVATE_KEY_FILE`**: if set, the key is read from that path.
2. **The compose secret**: if `IMGAGENT_PRIVATE_KEY_FILE` is not set and the file `/run/secrets/imgagent_private_key` exists, the entrypoint sets `IMGAGENT_PRIVATE_KEY_FILE` to it.
3. **`IMGAGENT_PRIVATE_KEY`**: if no file is found, the key is read from this variable.

A file is preferred over the variable.

## Recommended: the compose secret

`compose.yaml` defines a secret `imgagent_private_key` that comes from `./imgagent.pem` next to the compose file. Docker mounts it in the container at `/run/secrets/imgagent_private_key`, so you set nothing else.

```bash
cp ~/Downloads/imgagent.*.private-key.pem imgagent.pem
chmod 644 imgagent.pem
```

The container runs as the unprivileged user with uid 10001, so the file must be readable by it. That is why the mode is `644`.

## Alternative: one line in `.env`

Without a key file, put the key in `.env` on a single line, with `\n` in place of each line break:

```ini
IMGAGENT_PRIVATE_KEY=-----BEGIN RSA PRIVATE KEY-----\nMIIE...\n-----END RSA PRIVATE KEY-----
```

The server turns every `\n` back into a real line break.

## Startup checks

| Situation | What happens |
|---|---|
| `IMGAGENT_PRIVATE_KEY_FILE` is set (or the secret was picked up) but the file can't be read | The entrypoint prints `IMGAgent: can't read the private key at <path>` and the container exits. |
| No key text containing `PRIVATE KEY` is found in the file or the variable | The server exits with `missing settings: IMGAGENT_PRIVATE_KEY_FILE (or IMGAGENT_PRIVATE_KEY)`. |
| The key is present but GitHub rejects it | The server keeps running and logs `could not reach GitHub as the app (check IMGAGENT_APP_ID and the private key)`. |

On success the log says `signed in as the GitHub App ...`.

!!! tip
    If the container exits with "can't read the private key", check the file's permissions first (`chmod 644 imgagent.pem`).

## Keeping secrets out of git and images

- `.gitignore` excludes `.env` and `*.pem`, so neither is committed.
- `.dockerignore` excludes `.env` and `*.pem` as well, so neither is copied into the image. `.env` reaches the container through `env_file` in `compose.yaml`, and the key through the secret.

!!! warning
    Anyone with the private key can act as your GitHub App on every installation. Keep `imgagent.pem` and `.env` only on the server, and generate a new key in the App's settings if one leaks.

See the [configuration reference](index.md) for all other settings.
