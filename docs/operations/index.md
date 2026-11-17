# Operating IMGAgent

This page describes what the IMGAgent server does while it runs: what it checks at startup, how it runs jobs, how it handles tokens and temporary files, and which limits keep it safe. For symptoms and fixes, see [Troubleshooting](troubleshooting.md).

## Startup

On start, the server (`python -m imgagent.server`) refuses to run unless these are set: `IMGAGENT_APP_ID`, `IMGAGENT_WEBHOOK_SECRET`, `IMGAGENT_ALLOWED_OWNERS`, `ANTHROPIC_API_KEY` and a private key. It exits with a list of the missing settings. See the [configuration reference](../reference/index.md).

Then it signs in as the GitHub App and logs what GitHub knows about it. If GitHub can't be reached, the server logs an error and keeps running.

The log shows:

- `signed in as the GitHub App <slug>; answering @<handle>`
- the events and permissions the App has
- the accounts the App is installed on

It also logs warnings for settings that make commands go unanswered:

| Warning | Meaning |
|---|---|
| The App is not subscribed to `issues` or `issue_comment` events | Tick these under the App's *Subscribe to events*. |
| The App lacks `contents`, `issues` or `pull_requests` with write access | Set these permissions to *Read and write*. |
| `IMGAGENT_ALLOWED_OWNERS` names an account where the App isn't installed | Install the App there, or fix the name. |
| An installation doesn't receive `issues` or `issue_comment` yet | An owner of that account must accept the App's updated permissions. |

## Handling a delivery

The server answers GitHub within its time limit and does the work in the background:

1. It checks the `X-Hub-Signature-256` header against the webhook secret. Unsigned or wrongly signed requests get `401`.
2. It ignores deliveries whose delivery id it has already seen (the last 1000 ids are remembered) and from accounts outside `IMGAGENT_ALLOWED_OWNERS`.
3. It routes the event to a command, or answers `202` with the reason nothing was started.
4. It queues the job and returns `202 queued <job>`.

The job then checks whether the person who wrote the command has write access. See [Access control](../reference/allowed-owners.md).

## Workers

Jobs run on a pool of threads. `IMGAGENT_WORKERS` sets how many run at the same time (default `2`). Each running job needs a clone of a repository and some disk space in `/tmp`, so raise it only if the host has room.

Jobs with the same key run one after the other, even when workers are free:

- `make` and `update` in the same repository share one key.
- Everything else is keyed by repository and issue number.

## Temporary clones

Each job works in its own temporary directory with a fresh clone of the repository, and the directory is deleted when the job ends. `ask` uses a shallow, sparse clone of only the target and `.github/imgagent.toml`. The other commands clone the repository fully.

In the container, `/tmp` is a tmpfs of 2 GB and the root file system is read-only. See [Run the container](../getting-started/deploy.md).

## Installation tokens

IMGAgent never stores a long-lived GitHub credential besides the private key. For each delivery it asks GitHub for an installation token, which covers only the repositories of that installation and expires after an hour. The token is put into the clone's `origin` URL so the scripts can push.

The docs writer can run long, so before pushing it swaps in a fresh token.

Pull requests are opened and commits are made as `<slug>[bot]`.

## Timeouts

Each script has a time limit. When it is exceeded, the job fails.

| Job | Limit |
|---|---|
| `ask` | 5 minutes |
| `make`, `update` | 45 minutes |
| `signoff` (the assistant, then the request script) | 10 minutes each |
| signoff issue form | 10 minutes |

When a job fails, IMGAgent comments that it couldn't finish and names the command. The details are in the server log. Set `LOG_LEVEL` (default `INFO`) to change how much is logged.

## Safety model

- **Signed requests only.** Every webhook is verified with the shared secret.
- **Who is answered.** Only people with `admin`, `maintain` or `write` permission, and never bots, so IMGAgent can't start itself.
- **No shell.** Comment text reaches the scripts as environment variables, never through a shell.
- **Minimal environment.** Scripts start with only `PATH`, `HOME`, `LANG`, `SSL_CERT_FILE` and the variables the job needs. The private key and webhook secret are not passed to them.
- **Code is read, not run.** The cloned repository is only read.
- **Models have no tools.** Claude returns text or JSON in a fixed schema, which the scripts check. It cannot run commands or change files itself.
- **Nothing reaches a default branch directly.** Changes go to a new branch and a pull request that a person reviews and merges.
- **Unprivileged container.** It runs as user 10001 on a read-only root file system with `no-new-privileges`.

!!! note
    An AI can be wrong. Every answer says so, and every pull request needs a human review before it is merged.
