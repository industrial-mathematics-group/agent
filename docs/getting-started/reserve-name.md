# Reserve the name

Before you register the GitHub App, create an empty GitHub organisation called **IMGAgent**. This makes sure `@IMGAgent` in a comment points to an account you own, and lets the App use that name.

## Why

People call the bot by writing `@IMGAgent` in an issue or comment. GitHub turns that mention into a link to whatever account is called `IMGAgent`. If someone else owned that name, every command would link to their account.

An organisation is a safe owner for the name: mentioning an organisation notifies nobody, so writing `@IMGAgent signoff` or `@IMGAgent help` doesn't send notifications to anyone.

The App also needs this organisation. GitHub only lets an App take an existing account's name when that account owns the App. You therefore register the App under the **IMGAgent** organisation, as described in [Register and install the GitHub App](github-app.md).

## Steps

1. On GitHub, create a new free organisation named **IMGAgent**.
2. Leave it empty. It needs no repositories and no members besides you.

!!! note "A different name"
    The name people write after `@` is set by `IMGAGENT_HANDLE` (default `IMGAgent`). If you choose another handle, reserve that name instead. See [Environment variables](../reference/index.md).

Next: [Register and install the GitHub App](github-app.md).
