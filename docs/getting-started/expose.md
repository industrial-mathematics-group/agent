# Expose it to GitHub

GitHub sends every event to `https://<your-domain>/webhook`, so the container must be reachable there over HTTPS. This page shows how to put a reverse proxy in front of it and how to test the connection.

## What the container listens on

The server inside the container listens on port `8080` (the `PORT` variable set in the `Dockerfile`). `compose.yaml` publishes that port on the loopback interface of the host only:

```yaml
ports:
  - "127.0.0.1:${IMGAGENT_PORT:-8080}:8080"
```

The container is not reachable from outside the host by itself. A reverse proxy on the same host terminates HTTPS and forwards the requests to `127.0.0.1:8080`. To use a different host port, set `IMGAGENT_PORT` in `.env`.

The server answers these paths:

| Method and path | Answer |
|---|---|
| `POST /webhook` | the GitHub App webhook |
| `GET /healthz`, `GET /` | `ok`, used by the container health check |

Any other path gets `404 not found`. The Webhook URL in the App's settings must therefore end in `/webhook` (see [Register and install the GitHub App](github-app.md)).

## Reverse proxy examples

=== "Caddy"
    Caddy gets a certificate for the domain automatically:

    ```
    imgagent.example.org {
        reverse_proxy 127.0.0.1:8080
    }
    ```

=== "Nginx Proxy Manager / Traefik"
    Create a proxy host for your domain that forwards to `127.0.0.1:8080` (or to the container `imgagent:8080` on a shared Docker network), with a Let's Encrypt certificate.

=== "Cloudflare Tunnel"
    No open ports on the host: point a Cloudflare Tunnel at `http://127.0.0.1:8080`.

### When the proxy runs in another container

From inside another container, `127.0.0.1` refers to that container and not to the host, so the published port cannot be reached. Do one of the following:

- Change the port line in `compose.yaml` to `"8080:8080"`, so the port is published on all interfaces of the host.
- Put the proxy and the `imgagent` container on one Docker network, and forward to `imgagent:8080`.

!!! warning
    With `"8080:8080"` the plain-HTTP port is open to the network. Keep the reverse proxy in front of it, because GitHub must reach the webhook over HTTPS.

## Signatures

The server checks the `X-Hub-Signature-256` header of every delivery against `IMGAGENT_WEBHOOK_SECRET`. A delivery that is unsigned or signed with another secret gets `401 bad signature`, and the server logs a warning with the client address. The proxy only forwards requests and does not need to know the secret.

## Test the connection

1. On the App's page, open *Advanced → Recent Deliveries*. It lists the `ping` that GitHub sent when the App was created.
2. *Redeliver* the ping. The response should be `200` with the body `pong`.
3. Write `@IMGAgent help` in an issue of a repository where the App is installed. IMGAgent should reply with the list of commands.

If the redelivery fails, these responses tell you what went wrong:

| Response | Meaning |
|---|---|
| no response, or a proxy error | GitHub can't reach the server: check the domain, the certificate and the proxy target |
| `404 not found` | the Webhook URL doesn't end in `/webhook` |
| `401 bad signature` | the webhook secret in the App's settings and `IMGAGENT_WEBHOOK_SECRET` in `.env` differ |
| `200 already handled` | the server has already seen this delivery id since it was started; deliveries are processed once |

!!! note
    The help reply only goes to people with write, maintain or admin permission on the repository, and only for installations on accounts listed in `IMGAGENT_ALLOWED_OWNERS`. If the ping works but `@IMGAgent help` gets no answer, the response text of that delivery in *Recent Deliveries* says why. See [Troubleshooting](../operations/troubleshooting.md).

Next: [Per-repository setup](per-repository.md).
