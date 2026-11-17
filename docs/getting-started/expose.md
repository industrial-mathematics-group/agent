# Expose the webhook to GitHub

GitHub delivers events to IMGAgent over HTTPS, so the container's port must be reachable from the internet through a reverse proxy or a tunnel. This page covers how the port is published, how to put a proxy in front of it, and how to test the connection.

## How the port is published

The server inside the container listens on port 8080 (`PORT`, default `8080`). `compose.yaml` publishes it on the host like this:

```yaml
ports:
  - "127.0.0.1:${IMGAGENT_PORT:-8080}:8080"
```

The port is bound to `127.0.0.1` only. Nothing outside the host can reach it directly, which is intended: a reverse proxy on the same host terminates TLS and forwards requests to it. To use a different host port, set `IMGAGENT_PORT` in `.env`.

The server answers these paths:

| Method and path | Answer |
|---|---|
| `POST /webhook` | The GitHub App webhook. Also accepted at `/`. |
| `GET /healthz` | `200 ok`. Also answered at `/`. |

Use `https://<your-domain>/webhook` as the **Webhook URL** in the [GitHub App's settings](github-app.md).

## Choose a way to reach it

=== "Caddy"

    With Caddy on the same host:

    ```text
    imgagent.example.org {
        reverse_proxy 127.0.0.1:8080
    }
    ```

    Caddy obtains the certificate automatically.

=== "Nginx Proxy Manager / Traefik"

    Create a proxy host for your domain that forwards to `127.0.0.1:8080`, with a Let's Encrypt certificate. If the proxy runs in a container on a shared Docker network, it can forward to the container as `imgagent:8080` instead.

=== "Cloudflare Tunnel"

    Point a Cloudflare Tunnel at `http://127.0.0.1:8080`. This needs no open ports on the server.

### When the proxy runs in another container

A container cannot reach `127.0.0.1` of the host. Do one of the following:

- Change the port line in `compose.yaml` to `"8080:8080"`, so the port is published on all interfaces. Make sure your firewall only allows what you intend.
- Put the proxy and the `imgagent` container on one Docker network, and forward to `imgagent:8080`.

## Unsigned requests are rejected

Every delivery to `/webhook` is checked against the `X-Hub-Signature-256` header, using the webhook secret from `IMGAGENT_WEBHOOK_SECRET`. A request with a missing or wrong signature gets `401 bad signature`, and the server logs a warning with the sender's address. If every delivery from GitHub gets a 401, the secret in the App's settings and in `.env` differ.

!!! note
    Behind a proxy, the logged address is the proxy's address, not the sender's.

## Test the connection

1. Check that the server is up. On the host:

    ```bash
    curl http://127.0.0.1:8080/healthz
    ```

    The answer is `ok`. Through the proxy, `curl https://<your-domain>/healthz` should give the same answer.

2. Open the App's page on GitHub, then *Advanced → Recent Deliveries*. GitHub sent a `ping` when you created the App. Click **Redeliver** and expect the response `200 pong`.

3. In an issue of a repository where the App is installed, write a comment that starts with:

    ```text
    @IMGAgent help
    ```

    IMGAgent answers with the list of commands. Only people with write access to the repository get an answer.

If something fails, the response text in *Recent Deliveries* tells why an event started nothing, for example that the owner is not in `IMGAGENT_ALLOWED_OWNERS` or that no command was found.
