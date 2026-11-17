# Register the GitHub App

IMGAgent works as a GitHub App. GitHub sends issue and comment events to your server as signed webhooks, and the server answers as `imgagent[bot]` using short-lived installation tokens. This page lists the exact settings to use when you create the App, and how to install it.

Register the App under the organisation you created in [Reserve the @IMGAgent name](reserve-name.md). GitHub only lets an App take the name of an existing account when that account owns the App.

## Create the App

Open `github.com/organizations/IMGAgent/settings/apps` and choose **New GitHub App**.

| Setting | Value |
|---|---|
| GitHub App name | `IMGAgent` |
| Homepage URL | `https://github.com/industrial-mathematics-group`, or the URL of this repository |
| Callback URL, Setup URL, Device flow | leave empty / off |
| Webhook → Active | on |
| Webhook URL | `https://<your-domain>/webhook` |
| Webhook secret | a long random string, for example the output of `openssl rand -hex 32` |
| SSL verification | enabled |

The webhook URL is the address of your reverse proxy, which forwards to the container. See [Expose the webhook to GitHub](expose.md). You can create the App before the URL works and correct the URL later.

Keep the webhook secret. You enter the same value in `.env` as `IMGAGENT_WEBHOOK_SECRET`. The server rejects every delivery whose `X-Hub-Signature-256` does not match it.

### Repository permissions

Set these and leave everything else at *No access*.

| Permission | Access | Used for |
|---|---|---|
| Contents | Read and write | cloning, and pushing the pull request branches |
| Issues | Read and write | comments and reactions |
| Pull requests | Read and write | opening pull requests and assigning the requester |
| Metadata | Read-only (always on) | the write-access check |

Do not grant any organisation or account permissions.

!!! warning "Leave Workflows off"
    IMGAgent never changes `.github/workflows/`. Without the **Workflows** permission, the bot cannot add or edit workflow files, for example a GitHub Pages workflow. Add such files by hand.

### Subscribe to events

Tick **Issues** and **Issue comment**. Comments on pull requests arrive as issue comments.

### Where can this App be installed?

Choose **Any account**. The App is owned by `IMGAgent` and installed on your own organisation, for example `industrial-mathematics-group`, which is a different account. Anyone could install the App, but the server only answers accounts listed in `IMGAGENT_ALLOWED_OWNERS`, and only you hold the private key. See [Access control and allowed owners](../reference/allowed-owners.md).

## Note the App ID and create a private key

Choose **Create GitHub App**. Then:

1. Note the **App ID** shown at the top of the App's settings page. It becomes `IMGAGENT_APP_ID`.
2. Under **Private keys**, choose **Generate a private key**. Keep the downloaded `.pem` file. It is saved as `imgagent.pem` on the server, as described in [Run the container](deploy.md).
3. Optionally upload a logo. The organisation's `logos/` folder has avatars.

The private key is a secret. Do not commit it to git. See [The private key and secrets](../reference/private-key.md).

## Install the App

On the App's page, choose **Install App**, pick `industrial-mathematics-group`, and select **Only select repositories**, or all repositories. The bot works in exactly the repositories you choose. To add more later, use the organisation's *Settings → GitHub Apps*.

## What the server checks at startup

When the server starts it asks GitHub about the App and logs what it finds. It warns about settings that would leave commands unanswered:

- The App is not subscribed to `issues` or `issue_comment` events.
- The App lacks `write` access for `contents`, `issues` or `pull_requests`.
- `IMGAGENT_ALLOWED_OWNERS` names an account where the App is not installed.
- An installation does not receive `issues` or `issue_comment` yet. This happens after you add events or permissions to an existing App: an owner of the account must accept the updated permissions under *Settings → GitHub Apps → IMGAgent → Review request*.

If you see one of these in the log, fix it in the App's settings and see [Troubleshooting](../operations/troubleshooting.md).

## Next step

Continue with [Run the container](deploy.md).
