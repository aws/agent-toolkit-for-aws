# Troubleshooting container deployments

## Reading the container log (start here)

When a deployment goes `FAILED`, or the URL returns 502/503 or won't serve, **read the container log first** with
`get-container-log`, then match what you see to the cause — don't redeploy blindly:

```bash
aws lightsail get-container-log \
  --service-name NAME --container-name CONTAINER --region REGION
```

| What the log shows | Likely cause | Fix |
| --- | --- | --- |
| App started and is listening on a port, but the deployment still `FAILED` | `publicEndpoint.containerPort` (or `healthCheck.path`) doesn't match where the app serves, so the health check can't reach it | redeploy pointing at the port the log shows |
| `exec format error`, or the container exits immediately at startup | CPU-architecture mismatch — built for arm64, but Lightsail runs **amd64** | rebuild for `linux/amd64` and redeploy |
| A crash / stack trace, `command not found`, or a missing-variable error on boot | the app itself failed to start | fix the image, `command`, or `environment`, then redeploy |
| Little or no output | the container isn't starting at all (bad image reference or entrypoint) | recheck the image and launch command |

Logs are kept 4 days. If the failure is older than that its log is gone — redeploy that version unchanged to reproduce
the failure, then read the fresh log.

A failed deployment does not take down a previously running one — the service keeps the last good deployment active,
or stays `READY` with no active deployment if there was none.

## Common issues

- **502 / 503 on the URL** — the endpoint is up but the app isn't serving on the declared port, or the
  `healthCheck.path` is wrong. Confirm the container listens on `containerPort` and that the path returns 2xx.
- **`exec format error`** — CPU-architecture mismatch; rebuild for `linux/amd64` (`docker build --platform linux/amd64`).
- **The URL returns `404 No Such Service`** — the current deployment has no `publicEndpoint`. A deployment replaces the
  whole spec, so one sent without it takes the service off its public URL while still reporting `ACTIVE`. Redeploy with
  the `publicEndpoint` restated — see [deployment.md](references/deployment.md).
- **A redeploy changed nothing on the site** — two causes, both of which still report `ACTIVE`: the newest deployment
  version is `FAILED` (so the previous one is still serving), or the deployment references a stale image version. Check
  `get-container-service-deployments` for the newest version's state and the `image` it names.
- **Utilization graphs went empty after a deploy** — expected. Each new deployment resets the service's metrics; only
  the current deployment's metrics are shown. Nothing is wrong with the service.
- **HTTPS / custom domain** — HTTPS is automatic on the generated default domain
  (`https://<service>.<random-id>.<region>.cs.amazonlightsail.com`, HTTPS-only). Read the exact URL from
  `get-container-services` (`.url`); don't construct it. A custom domain is a separate step; the default domain
  needs nothing.

## `lightsailctl not found`

`push-container-image` reports this when the plugin isn't installed or isn't on `PATH`. The normal install commands are
in SKILL.md Prerequisites. When those don't work:

- **macOS and the Homebrew build is blocked** (restricted network) — download the prebuilt binary instead:
  `curl "https://s3.us-west-2.amazonaws.com/lightsailctl/latest/darwin-amd64/lightsailctl" -o /usr/local/bin/lightsailctl && chmod +x /usr/local/bin/lightsailctl && xattr -c /usr/local/bin/lightsailctl`
  The `xattr -c` clears macOS quarantine — without it the binary is blocked from running.
- **Installed but still `not found`** — it isn't on the `PATH` the CLI sees. Confirm with `which lightsailctl`.
- **Nothing can be installed at all** — use the plugin-free push (Option B in
  [local-image.md](references/local-image.md)); it needs only Docker and ordinary AWS API calls.
- Reference: https://docs.aws.amazon.com/lightsail/latest/userguide/amazon-lightsail-install-software.html
