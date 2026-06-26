# Application Signals Onboarding (Enable Auto-Instrumentation via ADOT)

Enable AWS Application Signals for a service that is **not yet instrumented**, by using ADOT (AWS Distro for OpenTelemetry) auto-instrumentation SDKs and making minimal, reviewable changes to the customer's infrastructure-as-code, Dockerfiles, CI/CD workflows, and deployment manifests. This is the *enablement* side of observability (turning an un-instrumented service into one that reports to Application Signals via ADOT). For querying, alarms, dashboards, or trace analysis on an already-instrumented service, use the other references.

**Never modify application source code** (`.py`, `.js`, `.ts`, `.java`, `.cs`). Only edit IaC, Dockerfiles, CI/CD workflows, dependency files, and deployment manifests. Make the minimum changes needed and preserve existing configuration. Present changes for the user to review; do not run `terraform apply`, `cdk deploy`, or `kubectl apply` automatically.

## Scope: two tiers

Onboarding has two tiers. Apply the second only when it is supported for the platform + language.

| Tier | What it adds | Supported on |
|------|--------------|--------------|
| **1. Application Signals enablement** (always) | ADOT auto-instrumentation: CloudWatch Observability add-on (EKS), CloudWatch Agent, IAM, the inject annotation / init container / SDK install | **All** platforms (EC2, ECS, EKS, Lambda) and **all** languages (Python, Node.js, Java, .NET) |
| **2. ServiceEvents extras** (when supported) | Git & deployment metadata env vars (CI/CD propagation) + OTLP endpoints + Dynamic Instrumentation | **EC2, ECS, EKS** with **Python, Node.js, Java** only |

**Minimum component versions for ServiceEvents (Tier 2).** The base Application Signals (Tier 1) works on any recent version. ServiceEvents requires:

| Component | Minimum for ServiceEvents | Notes | Latest version links |
|---|---|---|---|
| CloudWatch Agent | `1.300070.0` (recommended — includes on-prem credential bugfix) or `1.300069.0` | Use latest by default; flag to the user if they are on an older version | — |
| CloudWatch Observability EKS add-on | `v6.3.0` | Use latest by default; flag if the customer's IaC pins an older version | — |
| ADOT Python SDK / ECS init container | `0.18.0` | pip: `aws-opentelemetry-distro==0.18.0`; ECR: `adot-autoinstrumentation-python:v0.18.0` | [releases](https://github.com/aws-observability/aws-otel-python-instrumentation/releases/latest) · [ECR](https://gallery.ecr.aws/aws-observability/adot-autoinstrumentation-python) |
| ADOT Node.js SDK / ECS init container | `0.12.0` | npm: `@aws/aws-distro-opentelemetry-node-autoinstrumentation@0.12.0`; ECR: `adot-autoinstrumentation-node:v0.12.0` | [releases](https://github.com/aws-observability/aws-otel-js-instrumentation/releases/latest) · [ECR](https://gallery.ecr.aws/aws-observability/adot-autoinstrumentation-node) |
| ADOT Java agent / ECS init container | `2.28.2` | jar: `aws-opentelemetry-agent-2.28.2.jar`; ECR: `adot-autoinstrumentation-java:v2.28.2` | [releases](https://github.com/aws-observability/aws-otel-java-instrumentation/releases/latest) · [ECR](https://gallery.ecr.aws/aws-observability/adot-autoinstrumentation-java) |
| ADOT .NET / ECS init container | ServiceEvents not supported on .NET | | [releases](https://github.com/aws-observability/aws-otel-dotnet-instrumentation/releases/latest) · [ECR](https://gallery.ecr.aws/aws-observability/adot-autoinstrumentation-dotnet) |

**Tier 2 is NOT supported on Lambda or .NET.** For a Lambda service, or a .NET service on any platform, do Tier 1 only — the service still gets Application Signals, just without the ServiceEvents metadata/OTLP/DI env vars. Do not add `OTEL_AWS_SERVICE_EVENTS_*`, `OTEL_AWS_OTLP_*`, or `OTEL_AWS_DYNAMIC_INSTRUMENTATION_*` env vars for Lambda or .NET.

## Step 1: Determine platform and language

Detect from the IaC and app code, and confirm with the user if ambiguous:

- **EKS**: k8s Deployment manifests (`kind: Deployment`), Helm charts, `kubectl` in scripts, Terraform `aws_eks_*`, the `amazon-cloudwatch-observability` add-on.
- **ECS**: ECS task definitions, `containerDefinitions`, Terraform `aws_ecs_*`.
- **Lambda**: Lambda function definitions, SAM templates, Terraform `aws_lambda_function`.
- **EC2**: EC2 instances, userdata scripts, launch templates, Terraform `aws_instance`.
- **Language**: `requirements.txt`/`pyproject.toml`/`*.py` → Python; `package.json`/`*.ts`/`*.js` → Node.js (`nodejs`); `pom.xml`/`build.gradle`/`*.java` → Java; `*.csproj`/`*.sln`/`*.cs` → .NET (`dotnet`).

## Step 2 (EKS only): Install or import the CloudWatch Observability add-on

The `amazon-cloudwatch-observability` add-on injects ADOT auto-instrumentation via init containers and runs the CloudWatch Agent.

**Prefer the EKS add-on (`aws_eks_addon` / `CfnAddon`)** — do NOT introduce `helm_release` to replace an existing add-on (the add-on provides functionality the Helm chart alone does not, e.g. automatic `OTEL_AWS_APPLICATION_SIGNALS_EXPORTER_ENDPOINT` injection). If the user's IaC already uses `helm_release` for this chart, work with their existing setup.

Check whether the add-on is already enabled. Present the user with these options and proceed based on their response:

1. **You run it** — offer to run the AWS CLI command yourself (requires CLI/credentials access and the cluster name + region from the IaC):

   ```bash
   aws eks describe-addon --cluster-name <cluster-name> --addon-name amazon-cloudwatch-observability --region <region>
   ```

   A successful response means it exists; `ResourceNotFoundException` means it does not.

2. **User runs it** — ask the user to run the command above themselves or check the [EKS console → Add-ons tab](https://docs.aws.amazon.com/AmazonCloudWatch/latest/monitoring/CloudWatch-Application-Signals-Enable-EKS.html), and share the result.

3. **User says it's not enabled** — proceed to add the add-on (see below).

4. **User says it's already enabled** — proceed to the import step (see "Add-on already exists" below).

- **Add-on does NOT exist**: add the `aws_eks_addon` / `CfnAddon` resource:

  ```hcl
  resource "aws_eks_addon" "cloudwatch_observability" {
    cluster_name = ...
    addon_name   = "amazon-cloudwatch-observability"
    # addon_version omitted = uses the latest default version (recommended).
    # ServiceEvents requires v6.3.0+. If the customer's IaC pins an older version, flag it.
  }
  ```

- **Add-on already exists (Terraform)**: still add the resource above, and add a `terraform import` step to the CI/CD workflow **before** `terraform apply` so apply uses UpdateAddon instead of CreateAddon. Use `|| true` so reruns don't fail:

  ```bash
  # Import existing CW Observability add-on into Terraform state (first run only; can be removed after).
  # Add only this import line, BEFORE the workflow's existing `terraform apply` step, and mention that it can be removed after the first run as a comment.
  terraform import -var="region=..." -var="cluster_name=..." \
    aws_eks_addon.cloudwatch_observability <cluster-name>:amazon-cloudwatch-observability || true
  ```

- **Add-on already exists (CDK)**: do NOT add it to CDK; no change needed.

Do NOT introduce `helm_release`, `kubernetes`, or `helm` provider resources for this purpose.

## Step 3: IAM permissions for the CloudWatch Agent

The CloudWatch Agent needs `CloudWatchAgentServerPolicy` and `AWSXRayDaemonWriteAccess` to send metrics, logs, and traces. When ServiceEvents Dynamic Instrumentation applies (Tier 2), also add a custom policy with `application-signals:ListInstrumentationConfigurations` and `application-signals:ReportInstrumentationConfigurationStatus` on `Resource: "*"`.

Attach to the role the CloudWatch Agent uses, per platform:

- **EKS**: the node group's IAM role (used by the CloudWatch Agent pods).
- **ECS**: the role used by the CloudWatch Agent container (task role or execution role, depending on deployment).
- **EC2**: the instance profile / role used by the CloudWatch Agent process.

**EKS — `terraform-aws-modules/eks/aws` module** (most common): add to `iam_role_additional_policies`:

```hcl
resource "aws_iam_policy" "application_signals_di" {
  name = "${var.cluster_name}-${var.region}-application-signals-di"
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = [
        "application-signals:ListInstrumentationConfigurations",
        "application-signals:ReportInstrumentationConfigurationStatus"
      ]
      # Resource = "*" is the recommended scope for Dynamic Instrumentation: these
      # application-signals actions do not support resource-level permissions.
      Resource = "*"
    }]
  })
}

eks_managed_node_groups = {
  main = {
    iam_role_additional_policies = {
      CloudWatchAgentServerPolicy = "arn:aws:iam::aws:policy/CloudWatchAgentServerPolicy"
      AWSXRayDaemonWriteAccess    = "arn:aws:iam::aws:policy/AWSXRayDaemonWriteAccess"
      ApplicationSignalsDI        = aws_iam_policy.application_signals_di.arn
    }
  }
}
```

For raw `aws_iam_role` / ECS / EC2, attach the same three policies via `aws_iam_role_policy_attachment`. Use the exact managed-policy name `AWSXRayDaemonWriteAccess` (not `AWSXRayWriteOnlyAccess`). Omit the `application_signals_di` policy entirely for Lambda/.NET (Tier 1 only).

**Note**: the per-language guide (Step 4) may mention `CloudWatchAgentServerPolicy` but omit `AWSXRayDaemonWriteAccess`, or use a raw attachment pattern that doesn't match the module's `iam_role_additional_policies` syntax. Match the actual IaC pattern; prefer this step's guidance if they conflict.

## Step 4: Apply the per-platform, per-language enablement guide

Read the guide for the detected combination and apply its instrumentation changes (the inject annotation on EKS, the ADOT init container on ECS, the SDK/agent install on EC2, the Lambda layer on Lambda):

```
references/appsignals-guides/<platform>-<language>.md
```

Valid platforms: `ec2`, `ecs`, `eks`, `lambda`. Valid languages: `python`, `nodejs`, `java`, `dotnet`. Example: Python on EKS → `references/appsignals-guides/eks-python.md`.

If the running agent has the AWS MCP server / Application Signals tooling available, `get_enablement_guide` can be used as a fallback for the same parameters.

## Step 5 (Tier 2 only — skip for Lambda and .NET): ServiceEvents env vars

For EC2/ECS/EKS with Python/Node.js/Java, add the ServiceEvents environment variables.

**5a and 5b are the core of Tier 2 — apply them by default, do NOT ask the user whether to include them.** They are part of what "enable ServiceEvents / onboard to Application Signals" means. They differ in how strict they are:

- **5b (OTLP endpoints for transport) is required where it applies** — without it ServiceEvents telemetry has nowhere to go. Wire it per the platform (see 5b for the ECS/EC2-vs-EKS specifics).
- **5a (git/deployment metadata) is best-effort** — it's correlation data that degrades gracefully. Wire in whatever the IaC supports; if a value can't be sourced (e.g. no CI/CD provider for a git URL / commit SHA, or no deploy-time hook for the deployment vars), set what you can and skip the rest, noting it in the Step 6 review rather than blocking onboarding or interrogating the user.

**Only 5c and 5d are optional opt-in questions.**

### 5a. Git & deployment metadata (CI/CD propagation) — should be applied by default, best-effort

Add these 5 env vars, using the exact names below. See [application-signals-cicd-metadata.md](application-signals-cicd-metadata.md) for the full propagation-chain procedure and per-provider patterns.

| Variable (exact name) | When set |
|----------|----------|
| `OTEL_AWS_SERVICE_EVENTS_GIT_REPO_URL` | build-time (bake into image) |
| `OTEL_AWS_SERVICE_EVENTS_GIT_COMMIT_SHA` | build-time (bake into image) |
| `OTEL_AWS_SERVICE_EVENTS_DEPLOYMENT_URL` | deploy-time (runtime env var) |
| `OTEL_AWS_SERVICE_EVENTS_DEPLOYMENT_ID` | deploy-time (runtime env var) |
| `OTEL_AWS_SERVICE_EVENTS_DEPLOYMENT_TIMESTAMP` | deploy-time (runtime env var) |

### 5b. OTLP endpoints — required in specific environments

ServiceEvents adds two OTLP endpoint env vars — `OTEL_AWS_OTLP_LOGS_ENDPOINT` and `OTEL_AWS_OTLP_METRICS_ENDPOINT`. These are **in addition to** (not replacements for) the base Application Signals exporter env vars the per-platform guide already sets (`OTEL_AWS_APPLICATION_SIGNALS_EXPORTER_ENDPOINT`, `OTEL_EXPORTER_OTLP_TRACES_ENDPOINT`). On ECS/EC2 a fully onboarded service ends up with all of them. All point at the CloudWatch Agent's OTLP receiver on **port 4316** (NOT the OpenTelemetry SDK default 4318). Where the two ServiceEvents vars are set depends on the platform:

| Variable | EKS | ECS / EC2 |
|----------|-----|-----------|
| `OTEL_AWS_OTLP_LOGS_ENDPOINT` | **Auto-injected by the CloudWatch Observability add-on — do NOT set as a pod env var** | Set manually: `http://localhost:4316/v1/logs` (ECS sidecar / EC2), or the CloudWatch Agent host/IP on port 4316 (ECS daemon) |
| `OTEL_AWS_OTLP_METRICS_ENDPOINT` | **Auto-injected — do NOT set** | Set manually: `http://localhost:4316/v1/metrics` (ECS sidecar / EC2), or the CloudWatch Agent host/IP on port 4316 (ECS daemon) |

**EKS: do NOT manually set the OTLP endpoint env vars on the pod** — the `amazon-cloudwatch-observability` add-on injects them into instrumented pods with the correct values. On EKS, Step 5b typically adds nothing to the Deployment manifest; the Step 5a metadata env vars are still set as usual.

Steps 5c and 5d are the **only** parts of onboarding to ask the user about — two separate, **optional** ServiceEvents features, both **off by default** and both Tier 2 (EC2/ECS/EKS × Python/Node.js/Java). (5a and 5b above are not opt-in questions — they are applied by default; see the Step 5 intro.) Ask the user about 5c and 5d each **as its own distinct question** before moving to Review — they are independent (the user may want neither, either, or both). Fold whatever the user opts into the same place as the other Step 5 env vars (k8s Deployment env, ECS container env, or EC2 process/userdata env), so Step 6 reviews the complete set.

### 5c (optional): Per-function instrumentation

Ask the user whether they want per-function (`FunctionCall`) telemetry for their own application code. It emits nothing by default — but not because a toggle is off: `OTEL_AWS_SERVICE_EVENTS_FUNCTION_INSTRUMENT_ENABLED` is **already `true` by default**. What suppresses output is the empty `OTEL_AWS_SERVICE_EVENTS_PACKAGES_INCLUDE` allowlist. The two work as a pair — with the flag on but no allowlist, the SDK installs the hooks and instruments nothing. So opting in means setting **one** env var (do NOT set the enable flag — it is already on):

| Variable | Value |
|----------|-------|
| `OTEL_AWS_SERVICE_EVENTS_PACKAGES_INCLUDE` | The only way to opt code in. Empty = nothing instrumented (there is **no** implicit default scope). On Node.js, a list entry of exactly `*` or `**` is dropped (with a warning) as too broad — but partial wildcards (`**/src/**`, `*.js`) are fine. |

The match syntax differs per SDK — set it to the customer's own application code, not third-party libraries:

| SDK | Form | Example |
|-----|------|---------|
| **Java** | Java package prefix (dot-separated; no wildcard needed) | `com.example.simplesample`, `com.amazon.indico` |
| **Python** | dotted module path + `.*` | `indico.*`, `myapp.*` |
| **Node.js** | **path glob** (minimatch) matched against the file's **absolute resolved path** (NOT a module name) | `**/indico/src/**` — i.e. `**/<app-dir>/src/**` for code under `<app-dir>/src/` |

**Determining the value — inspect the customer's source layout.** `PACKAGES_INCLUDE` is the one onboarding value that depends on how the customer's code is organized, so **read** the repo to derive it (reading source to determine config is allowed; the never-modify rule is about *editing* source, not looking at it). Per SDK:

- **Java** — find the application's root package from the source tree (`src/main/java/<group>/<artifact>/…`) or the `package`/`namespace` declarations and `groupId` in `pom.xml`/`build.gradle`. Use the top-level package that covers the customer's own classes, e.g. `com.amazon.indico`.
- **Python** — find the top-level package directory (the one with `__init__.py`, or the `name`/`packages` in `pyproject.toml`/`setup.py`) and append `.*`, e.g. `myapp.*`.
- **Node.js** — find the directory holding the customer's own source (commonly `src/`, or `main`/`exports` in `package.json`) and build a path glob `**/<app-dir>/src/**`. Remember it matches the absolute *runtime* path, so anchor on a suffix that survives the build/deploy (the `**/` prefix), not the repo-relative path.

If the layout is ambiguous or spans multiple top-level packages, confirm the intended scope with the user rather than guessing — too broad an allowlist adds overhead and noise; too narrow misses functions. Prefer the customer's own application packages over dependencies unless the user explicitly wants a dependency instrumented.

**Node.js — the leading `**/` is required, not optional.** The SDK matches the pattern against the fully-resolved absolute path (e.g. `/app/indico/src/handlers/order.js`), which begins with deploy-specific prefixes the customer doesn't control (`/app`, the WORKDIR, etc.). minimatch's `matchBase` only helps for slash-free patterns; any pattern containing a `/` (like `…/src/**`) is anchored to the whole absolute path, so `indico/src/**` matches **nothing**. Lead with `**/` to absorb the prefix (`**/indico/src/**`), or — less portably — hardcode the absolute path (`/app/indico/src/**`). Usually you want the customer's own application code.

### 5d (optional): Dynamic Instrumentation

Ask the user — as a separate question from 5c — whether they want Dynamic Instrumentation. It shares `OTEL_AWS_OTLP_LOGS_ENDPOINT` with ServiceEvents. To enable, set `OTEL_AWS_DYNAMIC_INSTRUMENTATION_ENABLED=true` — on EKS either as a pod env var on the Deployment OR via the add-on's `autoInstrumentationConfiguration` (`configuration_values`); on ECS/EC2 as a container/process env var. Leave it off (omit, or set `false`) unless the user wants it.

| Variable | EKS | ECS / EC2 |
|----------|-----|-----------|
| `OTEL_AWS_DYNAMIC_INSTRUMENTATION_ENABLED` | Opt in by EITHER setting it `true` as a pod env var OR via the add-on's `autoInstrumentationConfiguration` | Set `true` to opt in |
| `OTEL_AWS_DYNAMIC_INSTRUMENTATION_API_URL` | **Auto-injected — do NOT set** | Only needed on ECS daemon (CloudWatch Agent host/IP on port 2000); default `localhost:2000` works on ECS sidecar / EC2 |

## Step 6: Review

Summarize all changes grouped by file, state the platform + language, list the env vars that will reach the app at runtime (including any optional 5c / 5d features the user opted into), and note build-time vs deploy-time. **Explicitly call out anything that was NOT set** — in particular any 5a git/deployment metadata vars skipped because their value couldn't be sourced (which ones, and why, e.g. "no CI/CD provider detected to supply `GIT_COMMIT_SHA`"), so the user knows the metadata is partial and can wire it manually if they want full deployment correlation. Present for the user to review and commit. Do not deploy automatically.

## Constraints

- Minimum changes; preserve existing content and formatting; never duplicate an env var, policy, or resource that already exists.
- Only IaC, Dockerfiles, CI/CD workflows, dependency files, and deployment manifests — never application source code.
- OTLP endpoints must target the CloudWatch Agent's OTLP receiver on port 4316.
- Use exact env var names and the exact managed-policy name `AWSXRayDaemonWriteAccess`.
- Lambda and .NET get Tier 1 (Application Signals enablement) only — no ServiceEvents env vars.
