# Register and install the GitHub App

IMGAgent receives events and acts on GitHub as a GitHub App. This page covers registering the App under the `IMGAgent` organisation and installing it on the repositories where the bot should work.

Before you start, create the empty `IMGAgent` organisation described in [Reserve the name](reserve-name.md). GitHub only lets an App use an existing account's name when that account owns the App, so the App is registered under this organisation.

## Register the App

Open *github.com/organizations/IMGAgent/settings/apps → New GitHub App* and fill in:

| Setting | Value |
|---|---|
| GitHub App name | `IMGAgent` |
| Homepage URL | `https://github.com/industrial-mathematics-group` (or the IMGAgent repository) |
| Callback URL, Setup URL, Device flow | leave empty / off |
| **Webhook → Active** | **on** |
| Webhook URL | `https://<your-domain>/webhook` (see [Expose it to GitHub](expose.md)) |
| Webhook secret | a long random string, for example from `openssl rand -hex 32` |
| SSL verification | enabled |

The webhook secret must also go into `.env` as `IMGAGENT_WEBHOOK_SECRET`. The server checks the `X-Hub-Signature-256` header of every delivery against this secret and answers `401` to anything unsigned or wrongly signed. You can generate the value now:

```bash
openssl rand -hex 32
```

### Repository permissions

Set these permissions. Leave everything else at *No access*.

| Permission | Access | Used for |
|---|---|---|
| Contents | Read and write | cloning, pushing the pull request branches |
| Issues | Read and write | comments, reactions |
| Pull requests | Read and write | opening pull requests, assigning the requester |
| Metadata | Read-only (always on) | the write-access check |

Do not grant organisation or account permissions.

!!! note "Leave Workflows off"
    IMGAgent never changes files under `.github/workflows/`. Without the Workflows permission GitHub would refuse such a push anyway, and `update` leaves those files out of its pull requests. For the same reason, `make docs` cannot add a GitHub Pages workflow. Add that workflow by hand.

### Event subscriptions

Under *Subscribe to events*, tick:

- **Issues**
- **Issue comment**

Comments on pull requests arrive as issue comments, so no pull request events are needed. The server ignores all other event types.

### Where the App can be installed

Choose **Any account**. The App is owned by `IMGAgent` but installed on `industrial-mathematics-group`, which is a different account, so *Only on this account* would not work.

Anyone could install the App, but the server only answers installations on the accounts listed in `IMGAGENT_ALLOWED_OWNERS`. Events from other accounts are ignored, and the response notes that the owner is not in `IMGAGENT_ALLOWED_OWNERS`. Only you hold the private key.

### App ID and private key

After *Create GitHub App*:

1. Note the **App ID** shown at the top of the App's settings page. It goes into `.env` as `IMGAGENT_APP_ID`.
2. Under *Private keys*, click *Generate a private key* and keep the downloaded `.pem` file. You will save it next to `compose.yaml` as `imgagent.pem` (see [Run the container](deploy.md) and [Private key](../reference/private-key.md)).
3. Optionally, upload a logo. The organisation's `logos/` folder has avatars.

## Install the App

On the App's page, click *Install App*, select `industrial-mathematics-group`, and then choose *Only select repositories* (or all repositories). The bot works in exactly the repositories you choose. You can add more later under the organisation's *Settings → GitHub Apps*.

## What the server checks at startup

When the container starts, it signs in as the App and logs what GitHub reports about it:

```
signed in as the GitHub App <slug>; answering @IMGAgent
app events: ...; permissions: ...
installed on: ...
```

It also logs a warning for each setting that would cause commands to go unanswered:

| Warning | Fix |
|---|---|
| `the App is not subscribed to 'issues' events` (or `'issue_comment'`) | tick the event under the App's settings → *Permissions & events* → *Subscribe to events* |
| `the App lacks contents: write` (likewise `issues`, `pull_requests`) | set the permission to *Read and write* |
| `IMGAGENT_ALLOWED_OWNERS names <owner>, but the App isn't installed there` | install the App on that account, or correct the variable |
| `the installation on <account> doesn't receive issues, issue_comment yet` | an owner of that account must accept the App's updated permissions under *Settings → GitHub Apps → IMGAgent → Review request* |

If the server cannot reach GitHub as the App at all, it logs `could not reach GitHub as the app (check IMGAGENT_APP_ID and the private key)` and keeps running. For more on these messages, see [Troubleshooting](../operations/troubleshooting.md).

Next: [Run the container](deploy.md).
