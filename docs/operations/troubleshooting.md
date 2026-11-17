# Troubleshooting

This page covers the cases where IMGAgent does not start, stays silent, or replies that it could not finish a command. Most problems show up in one of three places: the container log, the App's *Recent Deliveries* page on GitHub, or a comment from `imgagent[bot]` in the issue.

## Where to look

| Place | What it tells you |
|---|---|
| Container log | Startup checks, every delivery and its outcome, the output of the scripts, and tracebacks of failed jobs |
| *Recent Deliveries* (App settings → *Advanced*) | The HTTP status and one-line reason the server returned for each event |
| The issue itself | Replies about wrong commands, missing paths, missing access, and failed jobs |

The container is called `imgagent` in `compose.yaml`, so you can read its log with:

```bash
docker logs -f imgagent
```

You can also run `docker compose logs -f` in the stack folder, or open the stack's log in Dockge. Each delivery produces a line like `delivery <id> issue_comment.created: queued ask`. Script output appears indented as `  | ...` lines.

## The container does not start

`entrypoint.sh` and the server check the settings before anything else, and exit with a message if one is missing.

`IMGAgent: can't read the private key at /run/secrets/imgagent_private_key`
:   The key file exists but the container cannot read it. The container runs as uid 10001. Make the file readable with `chmod 644 imgagent.pem` in the stack folder. If you set `IMGAGENT_PRIVATE_KEY_FILE` yourself, the path in the message is that one. See [Private key](../reference/private-key.md).

`IMGAgent: missing settings: ... (see .env.example)`
:   One or more of `IMGAGENT_APP_ID`, `IMGAGENT_WEBHOOK_SECRET`, `IMGAGENT_ALLOWED_OWNERS` and `ANTHROPIC_API_KEY` are empty. `IMGAGENT_PRIVATE_KEY_FILE (or IMGAGENT_PRIVATE_KEY)` is listed when no key was found, or when the key does not contain `PRIVATE KEY`. This can happen when `imgagent.pem` is missing and `IMGAGENT_PRIVATE_KEY` is not set, or when the one-line key in `.env` is incomplete. Fill these in `.env`. See [Environment variables](../reference/index.md).

The container has a health check that requests `/healthz` every 30 seconds. If `docker ps` shows the container as unhealthy, the server is not listening on `PORT`.

## Startup warnings from the App check

After a successful start, the server asks GitHub about the App and logs the answer:

```
signed in as the GitHub App imgagent; answering @IMGAgent
app events: issue_comment, issues; permissions: contents=write, issues=write, metadata=read, pull_requests=write
installed on: industrial-mathematics-group
listening on :8080 (allowed owners: industrial-mathematics-group)
```

The server keeps running even if this check fails or warns. Each of the following warnings means some or all commands will go unanswered.

| Log message | Cause and fix |
|---|---|
| `could not reach GitHub as the app (check IMGAGENT_APP_ID and the private key): ...` | The App ID or the private key is wrong, or GitHub was unreachable at startup. Check both values and restart. |
| `the App is not subscribed to 'issues' events` (or `'issue_comment'`) | Tick **Issues** and **Issue comment** under the App's settings → *Permissions & events* → *Subscribe to events*. |
| `the App lacks contents: write (has ...)` (also `issues`, `pull_requests`) | Set that repository permission to *Read and write*. See [Register and install the GitHub App](../getting-started/github-app.md). |
| `IMGAGENT_ALLOWED_OWNERS names <owner>, but the App isn't installed there` | Install the App on that account, or correct the name in `.env`. |
| `the installation on <owner> doesn't receive issues, issue_comment yet` | After you change the App's events or permissions, an owner of the account must accept them under *Settings → GitHub Apps → IMGAgent → Review request*. |

## Reading Recent Deliveries

Every webhook delivery gets a short plain-text response that is shown in *Recent Deliveries*. The same text is written to the log.

| Status and text | Meaning |
|---|---|
| `200 pong` | The App's `ping` arrived. The webhook works. |
| `401 bad signature` | The webhook secret in the App settings and `IMGAGENT_WEBHOOK_SECRET` differ. The log shows `rejected a delivery with a bad signature from <address>`. |
| `400 bad length` / `400 bad json` | The body was empty, larger than 25 MB, or not JSON. |
| `404 not found` | The request went to a path other than `/webhook`. Check the Webhook URL and your reverse proxy. |
| `200 already handled` | The server has already received a delivery with this id since it started. It remembers the last 1000. To run a command again, write a new comment. |
| `202 ignored: owner <owner> is not in IMGAGENT_ALLOWED_OWNERS` | The installation belongs to an account that is not listed. Add it to `IMGAGENT_ALLOWED_OWNERS`. |
| `202 ignored: <event> has no repository or installation` | The event is not about a repository of an installation. |
| `202 queued <kind>` | A job was started. If nothing happens in the issue, see the sections below. |

If no deliveries arrive at all, GitHub cannot reach the server. See [Expose it to GitHub](../getting-started/expose.md).

### Why an event started nothing

When an event does not contain a command, the response is `202 ignored:` followed by one of these reasons.

`sent by the bot <login>`
:   IMGAgent never answers bots, including itself.

`IMGAgent doesn't use <event> events`
:   Only `issues` and `issue_comment` are used. The App can be subscribed to fewer events.

`no @IMGAgent in '...'`
:   The text does not mention the handle. If you changed `IMGAGENT_HANDLE`, people must write that name.

`commands in an issue are only read when it is opened, edited or reopened`
:   For example, closing or labelling an issue does not start anything.

`neither title nor body changed, or there is no command in them`
:   An issue edit that does not touch the title or body, such as a label change, is not read.

`the edit didn't turn a comment without a command into one`
:   Editing a comment runs its command only if the old text had no command that ran. This means fixing a typo in a working command does not run it a second time.

`@IMGAgent found but no command: write @IMGAgent <ask|update|make|help> ...`
:   The handle is there, but no command follows it. A common cause is a command inside a code block or a quoted line (`> ...`), because these are skipped. Another is `@IMGAgent signoff` in a closed issue, a pull request, or an issue made with the signoff form, because the assistant only answers in open issues. See [Commands](../usage/index.md).

## The job was queued but nobody answered

These are the cases where a delivery says `queued ...` but no comment appears.

- **`help` from someone without write access.** `help` gets no reply in this case, so a mention by anyone cannot make the bot talk. The log shows `<login> has read permission on <repo>: not answering`. Other commands get a reply instead: ``` `@IMGAgent ask docs` is only for people with write access to this repository. ```
- **An edited or reopened issue that IMGAgent already answered.** A command in an issue runs on edit or reopen only while IMGAgent has not commented on the issue yet. Only the first 100 comments are checked. The log shows `not run, IMGAgent already commented on this issue (write a new comment instead)`. Write the command in a new comment.
- **A job is waiting.** Jobs run on `IMGAGENT_WORKERS` threads, which is 2 by default. `make` and `update` in the same repository run one after the other, as do jobs in the same issue. A long `make docs` can therefore delay the next one.

Most jobs add an eyes reaction to the comment when they start. If the reaction appears but no answer follows, the job is still running or has failed.

## "IMGAgent couldn't finish this"

When a job raises an error, IMGAgent comments:

> @you IMGAgent couldn't finish this (`make`). A maintainer can find the details in the IMGAgent server log.

In the log, look for `<kind> failed for <repo>#<number>` followed by a traceback. Scroll up to the `  | ...` lines for the script's own output. Common causes:

| In the log | Cause |
|---|---|
| `ask.py failed`, `write_docs.py failed`, `update.py failed`, `assistant.py failed`, `request.py failed` | The script exited with an error. Its output, logged just before this line, says why. |
| `Claude declined this request.` | The model refused. Rephrase the question, task or hint. |
| `The answer hit max_tokens (...) and was cut off.` | One answer was too long. For `make docs`, ask for smaller pages in the hint. |
| `TimeoutExpired` | The script ran longer than its limit: 5 minutes for `ask`, 45 minutes for `make` and `update`, and 10 minutes for the signoff scripts. |
| `GitHub API 4xx: ...` | A GitHub call was refused, for example because a permission is missing. |

If the failure comment itself cannot be posted, the log shows `could not report the failure`.

## Replies about the command

These replies come from IMGAgent when the command cannot be carried out as written. Each one includes the right syntax.

| Reply | What to do |
|---|---|
| `` `ask` needs a folder: ...`` | Name at least one folder, such as `@IMGAgent ask docs`. |
| `` `<x>` is not a path in this repository I can use`` | The name was refused before cloning. `..`, absolute paths, `.git` and glob characters are not allowed. |
| ``there is no `<x>` in this repository`` | The path does not exist on the default branch, or it is a symlink that points outside the repository. Paths are case-sensitive. |
| `` `make` only knows `docs` for now`` | Use `make docs`. To change existing files elsewhere, use `update`. |
| `commands are now action then target` | Write `@IMGAgent ask docs`, not `@IMGAgent docs ask`. |
| ``I don't know `...` `` | The text starts with `@IMGAgent` followed by an unknown word. The reply lists the commands. |
| `write your question after ...` / `write what to do after ...` | `ask` and `update` need text after the folders. |

### Folders that are too large

`ask` and `update` read at most about 150,000 tokens of text. That is about 600,000 characters, and files over 200 kB are skipped. If the folders are larger, the reply is:

> `src` is too large to read at once: about 210,000 tokens in 840 files, the limit is about 150,000. Name smaller folders.

For `ask` this text is the answer. For `update` it appears as the first line of a "nothing needed to change" style reply. Name subfolders instead, for example `src/package` rather than `src`. See [ask](../usage/ask.md) and [update](../usage/update.md).

### Nothing changed

`make docs` and `update` reply without a pull request when no file in scope changed. `make docs` replies with ``@you `make docs`: ...``, and `update` replies with ``@you `update ...`: ...``. The rest of the reply is the first line of the summary. For `update`, only modifications of existing tracked files under the target folders or at the top level count. Files under `.github/workflows/` never count. Anything else the script changed is left out, and the log shows `leaving out changes outside its scope: ...`.

## Problems inside the pull request

Some problems do not stop the job. Instead, they are reported in the pull request description.

- **The nav could not be updated.** If `make docs` cannot write a `zensical.toml` that reads back with the planned nav, it keeps the pages. The description then says **The nav in `zensical.toml` could not be updated** and gives the `nav = [...]` block to paste by hand. See [make docs](../usage/make-docs.md).
- **Edits that could not be applied.** `update` makes find-and-replace edits. An edit whose text is not found exactly once is skipped, and the file's line in the description says `N edit(s) could not be applied (text not found exactly once), please check this file by hand.`
- **Skipped files.** If the plan wanted to change a file that `update` may not touch, the description lists it as **skipped** together with what was wanted.
- **The requester is not assigned.** If assigning fails, the pull request is still opened, and the log shows `could not assign <login>: ...`.

## Signoff

The signoff assistant and the signoff form report their own problems in the issue. The assistant asks for missing details, or lists the checks the answers failed. The form replies with **The request couldn't be turned into a pull request.** and a list of problems; editing the issue runs it again. If the repository has no `SIGNOFF.toml`, both say so: a maintainer creates it once with `aisignoff init`. If the assistant cannot reach Claude, it says so and suggests the form. See [signoff](../usage/signoff.md).
