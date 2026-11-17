# Reserve the @IMGAgent name

IMGAgent is addressed by writing `@IMGAgent` in an issue or comment. Before you register the GitHub App, reserve that name as a GitHub account so that nobody else owns it.

## Why the name is an account

In a comment, `@IMGAgent` is a mention. GitHub turns it into a link to whichever account is called `IMGAgent`. IMGAgent itself does not need the account to read the command: it reads the text of the comment. But if the name belongs to a stranger, every command you write would link to and notify their account.

So you own the name yourself:

1. Create a free GitHub organisation called **IMGAgent**.
2. Leave it empty.

Mentioning an organisation notifies nobody, so the commands stay quiet for everyone except the bot that answers them.

## Why an organisation owns the App

GitHub only lets a GitHub App take the name of an existing account when that account owns the App. For this reason, the App is registered under the `IMGAgent` organisation, not under a personal account. The next step, [Register the GitHub App](github-app.md), starts from this organisation's settings page.

The bot's replies come from the App's bot account, `imgagent[bot]`. The organisation and the App are separate things that share the name.

## The handle setting

The name people write after `@` is set by `IMGAGENT_HANDLE`. It defaults to `IMGAgent`, so you only set it if your organisation has a different name:

```bash
# in .env
IMGAGENT_HANDLE=IMGAgent
```

The handle is matched without regard to upper or lower case, so `@imgagent help` works as well as `@IMGAgent help`. The same value is used in the `help` reply and in the text of commands the bot posts.

!!! note
    `IMGAGENT_HANDLE` only changes which name the server listens for. It does not rename the GitHub App or the organisation. If you change it, make it match the account you reserved.

See the [configuration reference](../reference/index.md) for all settings, and continue with [Register the GitHub App](github-app.md).
