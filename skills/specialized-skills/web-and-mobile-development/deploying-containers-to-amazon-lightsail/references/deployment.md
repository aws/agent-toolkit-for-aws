# Create the deployment and confirm it serves

The shared final step for every path, once the image is available — referenced publicly, or pushed into the
service registry.

## Deployment shape

A deployment is an immutable version: one or more container entries plus one public endpoint — omit the endpoint only
when the service should be reachable privately rather than from the internet: from your other Lightsail resources in
the same region over its private domain `<service>.service.local`, or from your own VPC where VPC peering is active —
see SKILL.md Security considerations. Create it with the **`create-container-service-deployment`** operation:

```bash
aws lightsail create-container-service-deployment \
  --service-name NAME \
  --containers '{"web":{"image":"public.ecr.aws/nginx/nginx:latest","ports":{"80":"HTTP"}}}' \
  --public-endpoint '{"containerName":"web","containerPort":80,"healthCheck":{"path":"/"}}' \
  --region REGION
```

The parameters:

- **`containers`** — a map of container name → entry. Each entry:
  - `image` — a public image name, or a versioned reference from a push (not the local image name). These are immutable
    snapshots and increment on every push, so a deployment still naming an earlier version serves the old image while
    reporting `ACTIVE`. Reference `:<service>.<label>.latest` for the newest, or the exact number the push printed —
    see [local-image.md](references/local-image.md).
  - `ports` — ports to open, e.g. `{"80": "HTTP"}`. The public-endpoint container must have an HTTP or HTTPS port
    open here for the load balancer to route to.
  - `command` / `environment` — optional launch command and environment variables. Values here are
    readable via `get-container-service-deployments` — see SKILL.md Security considerations.
- **`publicEndpoint`** — names exactly one container and the port to route to. It is also what makes Lightsail
  health-check the container; leave it out and the URL will not serve — see below.
  - `containerName` + `containerPort` — **where** to route and probe. The port must match what the app listens on and
    be in that container's `ports`.
  - `healthCheck.path` — the load balancer probes **this path** and it must return 2xx before the deployment goes live;
    default `/`. Its other settings (`intervalSeconds`, `timeoutSeconds`, `healthyThreshold`, `unhealthyThreshold`,
    `successCodes`) all have defaults: raise the interval or the unhealthy threshold for an app that boots slowly, and
    set `successCodes` when the path deliberately answers a non-2xx code.

**A deployment REPLACES the whole spec — it is not a patch.** Every deployment must restate everything you want to keep:

- Omit `publicEndpoint` and the service loses its public route: the deployment still reports `ACTIVE` while the default
  domain answers `404 No Such Service`, so a URL that was working stops serving.
- Omit a container and it is removed from the service, so anything that depended on it breaks.

Read the current spec with `get-container-service-deployments` first, then change only what must change.

## Several containers in one deployment

Each entry in `containers` is independent, with its own image and ports. Only the one named by `publicEndpoint` is on
the public URL. To open communication between containers in the same deployment, add an environment variable that
references `localhost` (like `CACHE_ADDR` below); one that opens no ports, like `worker`, can still call out but
nothing on the public URL can reach it. From a different Lightsail resource in the same region, reach a service at
`<service>.service.local:<port>`.

```json
{
  "containers": {
    "web":    {"image": "<web-image>", "ports": {"80": "HTTP"},
               "environment": {"CACHE_ADDR": "localhost:6379"}},
    "cache":  {"image": "<cache-image>", "ports": {"6379": "TCP"}},
    "worker": {"image": "<worker-image>"}
  },
  "publicEndpoint": {
    "containerName": "web",
    "containerPort": 80,
    "healthCheck": {"path": "/"}
  }
}
```

`CACHE_ADDR` is a non-secret address; anything sensitive placed here is readable via
`get-container-service-deployments` — see SKILL.md Security considerations.

## Wait until it serves

Poll `get-container-service-deployments` for the deployment `state` (follow SKILL.md Polling — repeated
short checks, never a wait loop inside one call). Don't return the URL before the deployment is `ACTIVE`.

```bash
aws lightsail get-container-service-deployments --service-name NAME --region REGION
```

| Deployment state | Service state | Meaning | What to do |
| --- | --- | --- | --- |
| `ACTIVATING` | `DEPLOYING` | containers are launching | keep polling |
| `ACTIVE` | `RUNNING` | serving on the public endpoint | read the URL and verify it responds |
| `FAILED` | `RUNNING` (prior kept) or `READY` | a container failed to launch | read logs, fix, redeploy — see the troubleshooting reference |
| `INACTIVE` | — | superseded by a newer version | historical only |

Read the generated URL from the service's `url` field (via `get-container-services`) — it contains a random id, so
read it, don't construct it — then confirm it responds (e.g. a `curl` to the URL should return a success code).

## When a redeploy "does nothing"

A deployment that fails does **not** take the service down: if a previous deployment is running, Lightsail keeps that
one active, so the service still reports `RUNNING` and the URL still returns 200 — serving the **old** version. "It
looks healthy" is therefore not evidence the update shipped. Check `get-container-service-deployments`: if the newest
version is `FAILED`, that update never took, and the log for that version says why.

The other way an update silently doesn't land is referencing a stale image version — see `image` above.

## Change capacity

Change `power` (size of each node) or `scale` (number of nodes) on a running service with
**`update-container-service`**, at any time and **without downtime**. Lightsail applies it by re-deploying the current
deployment for you — you don't create a deployment yourself, and you never need to delete and recreate the service.
The re-deploy keeps the same deployment version, and no other deployment can be created until the update finishes.
The monthly cost becomes the new power × scale. Read `get-container-service-powers` for the available sizes and
prices rather than quoting remembered ones.

## Roll back

Every deployment is saved as a version (Lightsail keeps a limited number of the most recent ones — see the Lightsail
quotas for the current limit — past that, the oldest are dropped and can no longer
be redeployed from). Roll back by creating a new deployment from a prior version; that produces a *new* version whose
spec matches the old one, since there is no "reactivate this version" operation. If you redeploy from a `FAILED`
version, fix the cause first or it will fail the same way.

## Tear down

Deleting the service stops all charges.

```bash
aws lightsail delete-container-service --service-name NAME --region REGION
```
