# Troubleshooting

This page lists what IMGAgent does when something is wrong, which message you will see, and what to change. Most problems show up in the container log or in the App's *Advanced → Recent Deliveries* list on GitHub.

## Where to look

**The container log.** The server logs to standard output. In Dockge, open the stack's log; without Dockge, run `docker compose logs -f imgagent`. The log level comes from `LOG_LEVEL` (default `INFO`). Set `LOG_LEVEL=DEBUG` in `.env` and restart the stack for more detail.

**Recent Deliveries.** On the App's settings page, *Advanced → Recent Deliveries* shows each webhook GitHub sent and the response text the server returned. Most of the messages below appear there.

At startup the server logs what GitHub knows about the App. A healthy start includes these lines:

```text
signed in as the GitHub App imgagent; answering @IMGAgent
app events: ...; permissions: ...
installed on: industrial-mathematics-group
listening on :8080 (allowed owners: industrial-mathematics-group)
```

## The container does not start

### `IMGAgent: missing settings: ...`

The server exits at once if a required setting is empty. The message names what is missing:

| Name in the message | Set this in `.env` |
|---|---|
| `IMGAGENT_APP_ID` | the App ID shown at the top of the App's settings page |
| `IMGAGENT_WEBHOOK_SECRET` | the webhook secret you entered in the App's settings |
| `IMGAGENT_ALLOWED_OWNERS` | the accounts that may use the bot, comma-separated |
| `ANTHROPIC_API_KEY` | a Claude Console API key |
| `IMGAGENT_PRIVATE_KEY_FILE (or IMGAGENT_PRIVATE_KEY)` | see the next entry |

The last entry is also reported when a private key was found but does not contain `PRIVATE KEY`, for example when the wrong file was copied or the one-line variable lost its `\n` line breaks. See [the private key](../reference/private-key.md).

### `IMGAgent: can't read the private key at ...`

`entrypoint.sh` checks that the key file can be read before starting. The container runs as the unprivileged user with uid 10001, so the file on the host must be readable by others:

```bash
chmod 644 imgagent.pem
```

Also check that `imgagent.pem` exists next to `compose.yaml`, because the compose secret is read from `./imgagent.pem`.

### `could not reach GitHub as the app`

If this error appears in the log, the server keeps running but the startup check failed. Check `IMGAGENT_APP_ID` and the private key: the key must belong to this App. GitHub may also have been briefly unreachable; restart the stack to repeat the check.

## GitHub cannot deliver

### `401 bad signature`

The server verifies the `X-Hub-Signature-256` header of every delivery against `IMGAGENT_WEBHOOK_SECRET`. A delivery that fails gets `401`, and the log says `rejected a delivery with a bad signature`. Make the secret in `.env` identical to the one in the App's settings, restart the stack, and redeliver from *Recent Deliveries*. Requests that do not come from GitHub, or are unsigned, get the same answer.

### `400 bad length` or `400 bad json`

The body was empty, larger than 25 MB, or not JSON. GitHub does not normally send such deliveries; a misconfigured reverse proxy that alters the request is the likely cause.

## Deliveries arrive but nothing happens

A delivery that is accepted but starts no job gets status `202`, and the response text says why. The same text goes into the log.

| Response text | Cause and fix |
|---|---|
| `ignored: owner <name> is not in IMGAGENT_ALLOWED_OWNERS` | The repository's owner is not in the allowlist. Add it to `IMGAGENT_ALLOWED_OWNERS` and restart. See [access control](../reference/allowed-owners.md). |
| `ignored: <event> has no repository or installation` | The event is not tied to an installation, for example one sent from outside the App. Nothing to fix. |
| `ignored: ... no @IMGAgent in '...'` | The comment or issue does not contain the handle. Check the spelling; the handle is set by `IMGAGENT_HANDLE`. |
| `ignored: ... @IMGAgent found but no command ...`, `... only read when it is opened`, `... the edit didn't turn ...` | The handle is there but no command follows it, the issue event isn't `opened`, or an edit changed a command that had already run. See below. |
| `ignored: sent by the bot <login>` | Bots are never answered. |
| `ignored: IMGAgent doesn't use <event> events` | The App sends event types other than `issues` and `issue_comment`. Unsubscribe from them; they are harmless. |
| `already handled` (status `200`) | The delivery id was seen before. Redelivering the same delivery does nothing; write a new comment instead. |
| `pong` (status `200`) | The answer to GitHub's `ping`. This means the connection works. |
| `queued <kind>` (status `202`) | A job was started. Its result appears as a comment or pull request. |

### The handle is there but no command is recognised

- `ask`, `update`, `make` and `help` must follow `@IMGAgent` directly (`@IMGAgent ask docs`), on any line, but not inside code or a quoted line (`> ...`).
- Commands in an issue are read when the issue is opened, not when it is edited later; write a comment instead.
- Editing a comment runs its command only if it had no command that ran before.
- `signoff` can appear anywhere in the text, but only in an **open issue** (not a pull request, not a closed issue), and not in an issue made with the signoff form.
- A mention inside a longer word, an e-mail address, a path or inline code (`` `@IMGAgent signoff` ``) is not a command.

See [commands](../reference/commands.md) for the full rules.

## Startup warnings about the App

After signing in, the server compares the App's settings with what it needs and logs a warning for each gap. Warnings do not stop the server, but the commands they affect will not work.

### `the App is not subscribed to 'issues' (or 'issue_comment') events`

Open the App's settings, *Permissions & events → Subscribe to events*, and tick **Issues** and **Issue comment**.

### `the App lacks contents: write (has ...)`

The same warning exists for `issues` and `pull_requests`. In the App's repository permissions, set **Contents**, **Issues** and **Pull requests** to *Read and write*.

### `IMGAGENT_ALLOWED_OWNERS names <owner>, but the App isn't installed there`

The allowlist contains an account that has no installation of the App. Install the App on that account, or remove the name from the allowlist.

### `the installation on <account> doesn't receive ... yet`

After you change an App's permissions or events, each installation owner must accept the change. An owner of the account opens *Settings → GitHub Apps → IMGAgent* and chooses *Review request*. Until then, GitHub does not send the new events to that installation.

## The bot replies, but not as expected

### `<command> is only for people with write access to this repository.`

The person who wrote the command has no write, maintain or admin permission on the repository. Only such people are answered. For `help`, nobody without write access gets a reply at all, so that a stray `@IMGAgent` in a comment does not make the bot talk. For the signoff assistant, the same restriction is stated in its own wording.

### `there is no <folder> in this repository.`

Every folder you name, also after `with`, needs to exist on the default branch. Check the spelling (paths are case sensitive), or run `@IMGAgent make docs` first for `docs`.

### `IMGAgent couldn't finish this (<kind>). A maintainer can find the details in the IMGAgent server log.`

A job raised an error, for example a failed clone, a failed script, a Claude API error or a refused push. The comment names only the kind of job (`ask`, `update`, `make`, `signoff`, `signoff-form`). Find the cause in the container log: look for the line `<kind> failed for <repo>#<number>` and the traceback after it. Output of the scripts is logged line by line with a `|` prefix. Set `LOG_LEVEL=DEBUG` if the default log is not enough.

### `make docs` or `update` made no pull request

If nothing needed to change, the bot replies in a comment with the first line of the summary instead of opening a pull request. This is not an error. For `update`, the summary also says when Claude wanted a file it may not change, such as a new file or one outside the target.

### Signoff: `This repository has no SIGNOFF.toml yet`

`signoff` and the signoff form need a `SIGNOFF.toml`. A maintainer creates it once with `aisignoff init`. See [preparing a repository](../getting-started/per-repository.md).

## Still stuck

1. Redeliver the latest delivery from *Recent Deliveries* and read the response text.
2. Read the log around that time; every delivery is logged as `delivery <id> <event>.<action>: <result>`.
3. Run the checks in [Operating IMGAgent](index.md) against your setup.
