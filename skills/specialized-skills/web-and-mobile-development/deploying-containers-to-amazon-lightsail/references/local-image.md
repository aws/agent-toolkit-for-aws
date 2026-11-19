# Deploy a locally built image

The image is built on the local machine, so it must be pushed into the container service's **own private
registry** before it can be deployed. That registry is separate from Amazon ECR.

## 1. Build for the right architecture

Lightsail container services run on **amd64 (x86_64)**. Build for that explicitly — a default build on an ARM
machine (for example Apple Silicon) produces an arm64 image that fails at runtime with `exec format error`:

```bash
docker build --platform linux/amd64 -t my-app .
```

## 2. Push the image into the service registry

Both options upload the image and register it, yielding a versioned reference `:<service>.<label>.<n>` for the
deployment. **Default to Option A**; use Option B when the `lightsailctl` plugin isn't available. Either way the
image upload **includes a local Docker operation** — it runs on your machine, not through the MCP tools.

**Pushing does not deploy, and every push registers a new version.** Each push stores a new, immutable image version
under a number Lightsail assigns — it always increases, but don't assume it starts at `.1` or counts per label — and
the running service is untouched until you create a deployment referencing the new version. Two consequences when
shipping a change:

- Rebuilding under the same local tag (`my-app:latest`) changes nothing on the service by itself. The local tag is
  irrelevant to what Lightsail serves.
- Read the versioned reference the push printed (or list them with `get-container-images`) and deploy **that** when
  you reference a specific version. Redeploying the previous reference ships the old image and still reports `ACTIVE`.

### Option A (default) — the `push-container-image` CLI command (needs lightsailctl)

Run this **`aws` CLI** command locally (service name, label, local image tag, region):

```bash
aws lightsail push-container-image --service-name NAME --label app --image my-app:latest --region REGION
```

It's a CLI command implemented by the **lightsailctl** plugin (a wrapper over Option B) — not an AWS API, so it
can't run through the MCP tools; it needs the plugin on `PATH` plus a running local Docker. If it reports
`lightsailctl not found`, install the plugin (the commands are in SKILL.md Prerequisites; if an install is blocked,
see [troubleshooting.md](references/troubleshooting.md)) or use Option B.

### Option B (plugin-free) — three steps, no lightsailctl

The same three steps lightsailctl performs, run directly:

1. **Get registry credentials** — `create-container-service-registry-login` returns a temporary username, password,
   and registry URL. This is an AWS API call — run it through your MCP tool or the CLI. These credentials are
   short-lived: use them in place and never write them to disk, a config file, or source control.

   ```bash
   aws lightsail create-container-service-registry-login --region REGION
   ```

2. **Push the image with Docker** (local — Docker only):

   ```bash
   echo "$PASSWORD" | docker login -u USERNAME --password-stdin REGISTRY
   docker tag my-app:latest REGISTRY/sr:my-app
   docker push REGISTRY/sr:my-app            # note the sha256 digest it prints
   ```

3. **Register the pushed image** — `register-container-image`, using the digest step 2 printed.

   ```bash
   aws lightsail register-container-image \
     --service-name NAME --label LABEL --digest sha256:DIGEST --region REGION
   ```

## 3. Deploy

Use the **returned versioned reference** (`:<service>.<label>.<n>`), not the local image name, in the deployment.
See [deployment.md](references/deployment.md) for the deployment shape and how to poll to `ACTIVE`.
