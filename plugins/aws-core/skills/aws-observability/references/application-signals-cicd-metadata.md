# Application Signals: Git & Deployment Metadata Propagation

Propagate git and deployment metadata to an Application Signals service so ServiceEvents can correlate deployments with telemetry. This is **Tier 2** of onboarding (see [application-signals-onboarding.md](application-signals-onboarding.md)) — it applies only to **EC2/ECS/EKS** services in **Python, Node.js, or Java**. It does NOT apply to Lambda or .NET.

Never modify application source code. Only edit the CI/CD workflow, Dockerfiles, and deployment manifests. Make minimum changes and present them for review.

## The 5 environment variables

### Category 1 — Git metadata (BUILD time, bake into the Docker image)

| Variable | Description | Git fallback |
|----------|-------------|--------------|
| `OTEL_AWS_SERVICE_EVENTS_GIT_REPO_URL` | HTTPS URL of the **app** repo | `git remote get-url origin` |
| `OTEL_AWS_SERVICE_EVENTS_GIT_COMMIT_SHA` | Full SHA of the **app** commit | `git rev-parse HEAD` |

**Note:** use a plain repo URL for `GIT_REPO_URL` — not one with embedded credentials (e.g. `https://<token>@github.com/...`). This value is propagated into telemetry, so an embedded token would leak. `git remote get-url origin` returns a credential-free URL in the normal case; strip any userinfo if your remote includes it.

CI/CD provider mappings (use only when the app IS the workflow repo):

| Provider | Repo URL | Commit SHA |
|----------|----------|------------|
| GitHub Actions | `${{ github.server_url }}/${{ github.repository }}` | `${{ github.sha }}` |
| Jenkins | `$GIT_URL` | `$GIT_COMMIT` |

### Category 2 — Deployment metadata (DEPLOY time, runtime env vars only)

| Variable | Description |
|----------|-------------|
| `OTEL_AWS_SERVICE_EVENTS_DEPLOYMENT_URL` | URL of the CI/CD run that deployed the app |
| `OTEL_AWS_SERVICE_EVENTS_DEPLOYMENT_ID` | Unique identifier of the CI/CD run (run ID / build number) |
| `OTEL_AWS_SERVICE_EVENTS_DEPLOYMENT_TIMESTAMP` | ISO 8601 UTC timestamp: `date -u +%Y-%m-%dT%H:%M:%SZ` |

Deployment URL by provider — GitHub Actions: `${{ github.server_url }}/${{ github.repository }}/actions/runs/${{ github.run_id }}`; Jenkins: `$BUILD_URL`. Deployment ID — GitHub Actions: `${{ github.run_id }}`; Jenkins: `$BUILD_NUMBER`.

**NEVER bake Category 2 (deployment metadata) into Docker images** — it must be set at deploy time. **NEVER set Category 1 using the deploy repo's git metadata if the app comes from a different repo.**

## Procedure

### 1. Read the workflow and app

Read the deploy workflow YAML, the `Dockerfile*` and `docker-compose*.yml` in the app path, any deploy scripts (`deploy*.sh`, scripts using `envsubst`), and any deployment manifests referenced by the workflow (k8s YAML, `*.tf`, ECS task defs, `*.json.tpl`).

### 2. Identify the app source for Category 1

- **App IS the workflow repo** (no `repository:` on `actions/checkout`, app path within the repo): use `github.*` context vars for Category 1.
- **App is a DIFFERENT repo** (`actions/checkout` with `repository:`, or `git clone`): extract Category 1 from the app checkout dir using git commands.

### 3. Trace the propagation chain

Trace how env vars flow from CI/CD to the running container. Every intermediate layer must explicitly forward each var or it is silently dropped:

- Category 1: workflow step env → shell → docker build args → Dockerfile `ARG`/`ENV`.
- Category 2: workflow step env → shell → template engine / Terraform vars → deployment manifest → container env.

### 4. Apply changes

**Category 1 (build-time):** add a "Set git metadata" workflow step after the app checkout; pass `--build-arg` (or docker-compose `args:`) for the 2 git vars; add matching `ARG` + `ENV` to the Dockerfile(s).

**Category 2 (deploy-time):** add a "Set deployment metadata" workflow step; forward the 3 deployment vars through the existing chain (envsubst exports, Terraform vars, etc.) into the deployment manifest; add the env vars to the manifest (k8s YAML, ECS task def, Terraform env block).

### 5. Review

Summarize changes, stating which vars are build-time vs deploy-time. Present for review.

## Pattern examples

### GitHub Actions — app IS the workflow repo

```yaml
- name: Set git metadata
  id: git-meta
  run: |
    echo "git_repo_url=${{ github.server_url }}/${{ github.repository }}" >> $GITHUB_OUTPUT
    echo "git_commit_sha=${{ github.sha }}" >> $GITHUB_OUTPUT
```

### GitHub Actions — app is a DIFFERENT repo (multi-checkout)

```yaml
- name: Set git metadata from app repo
  id: git-meta
  working-directory: <app-checkout-dir>
  run: |
    echo "git_repo_url=$(git remote get-url origin)" >> $GITHUB_OUTPUT
    echo "git_commit_sha=$(git rev-parse HEAD)" >> $GITHUB_OUTPUT
```

### Dockerfile ARG/ENV (build-side — 2 git vars only)

```dockerfile
ARG OTEL_AWS_SERVICE_EVENTS_GIT_REPO_URL
ARG OTEL_AWS_SERVICE_EVENTS_GIT_COMMIT_SHA
ENV OTEL_AWS_SERVICE_EVENTS_GIT_REPO_URL=${OTEL_AWS_SERVICE_EVENTS_GIT_REPO_URL}
ENV OTEL_AWS_SERVICE_EVENTS_GIT_COMMIT_SHA=${OTEL_AWS_SERVICE_EVENTS_GIT_COMMIT_SHA}
```

### Kubernetes deployment YAML with envsubst (deploy-side — 3 deployment vars only)

```yaml
        - name: OTEL_AWS_SERVICE_EVENTS_DEPLOYMENT_URL
          value: "${OTEL_AWS_SERVICE_EVENTS_DEPLOYMENT_URL}"
        - name: OTEL_AWS_SERVICE_EVENTS_DEPLOYMENT_ID
          value: "${OTEL_AWS_SERVICE_EVENTS_DEPLOYMENT_ID}"
        - name: OTEL_AWS_SERVICE_EVENTS_DEPLOYMENT_TIMESTAMP
          value: "${OTEL_AWS_SERVICE_EVENTS_DEPLOYMENT_TIMESTAMP}"
```

Quotes around `value` are required — `DEPLOYMENT_ID` is numeric and YAML rejects it without quotes.

### Terraform ECS (deploy-side — 3 deployment vars only)

```hcl
variable "deployment_url" { type = string; default = "" }
variable "deployment_id" { type = string; default = "" }
variable "deployment_timestamp" { type = string; default = "" }

# In the container definition environment:
{ name = "OTEL_AWS_SERVICE_EVENTS_DEPLOYMENT_URL", value = var.deployment_url },
{ name = "OTEL_AWS_SERVICE_EVENTS_DEPLOYMENT_ID", value = var.deployment_id },
{ name = "OTEL_AWS_SERVICE_EVENTS_DEPLOYMENT_TIMESTAMP", value = var.deployment_timestamp },
```

## Jenkins syntax note

In Groovy-interpolated blocks (`sh """..."""`) use `${env.BUILD_URL}`; in shell-interpreted blocks (`sh '''...'''`) or Freestyle jobs use `$BUILD_URL`. Check the quoting style before choosing.

## Constraints

- Minimum changes; preserve existing content; don't duplicate env vars that already exist.
- Use the exact `OTEL_AWS_SERVICE_EVENTS_*` names above.
- Never bake deployment metadata into Docker images.
- Trace the full propagation chain end-to-end.
