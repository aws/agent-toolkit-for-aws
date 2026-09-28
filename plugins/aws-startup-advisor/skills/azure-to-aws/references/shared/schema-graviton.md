# Graviton Schema Reference

> Canonical schemas for Graviton/ARM64 fields. Loaded by `discover-app-code.md` and `discover-iac.md` (to write `graviton_profile`), `design-refs/compute.md` (to write the per-service `graviton` block), and `estimate-infra.md` (to write `architecture_comparison`). See `shared/graviton.md` for behavior.

---

## `graviton_profile` (emitted by Discover, one entry per compute service)

```json
{
  "service_name": "api-service",
  "tier": "ready",
  "target_architecture": "arm64",
  "signals": ["python-3.11", "no-native-extensions", "docker-multi-arch-base"],
  "caveats": [],
  "source": "app_code"
}
```

| Field                 | Type     | Values / notes                                                        |
| --------------------- | -------- | --------------------------------------------------------------------- |
| `service_name`        | string   | Logical service or resource name                                      |
| `tier`                | enum     | `ready` \| `conditional` \| `incompatible` \| `unknown`               |
| `target_architecture` | enum     | `arm64` (tier ready/conditional) \| `x86_64` (tier incompatible)      |
| `signals`             | string[] | Evidence used to assign the tier (see detection tables below)         |
| `caveats`             | string[] | Human-readable risk notes; non-empty for `conditional`/`incompatible` |
| `source`              | enum     | `app_code` \| `iac` \| `billing`                                      |

Write `graviton_profile` entries into an array under the discovery output. `graviton_profile` is an empty array when no compute services are detected.

---

## Detection signals

### App code (`discover-app-code.md`) — highest fidelity

| Signal                       | Where                                                                               | Implies                                                         |
| ---------------------------- | ----------------------------------------------------------------------------------- | --------------------------------------------------------------- |
| Language runtime             | `requirements.txt`, `package.json`, `go.mod`, `pom.xml`, `Gemfile`, `composer.json` | Compatibility tier (Python/Node/Go/PHP/Ruby/pure-JVM → `ready`) |
| Dockerfile `FROM` base image | `Dockerfile`                                                                        | Whether a multi-arch base is available                          |
| `platform: linux/amd64`      | `docker-compose.yml`, build config                                                  | Hardcoded x86 — needs change, downgrade to `conditional`        |
| Native C extensions          | `requirements.txt` (niche pkgs), `package.json` (`node-gyp`)                        | Potential arm64 gap → `conditional`                             |
| x86 SIMD / intrinsics        | source grep `__asm__`, `_mm_`, `_mm256_`, `__SSE__`, `__AVX__`                      | NEON port needed → `conditional`/`incompatible`                 |
| JNI libraries                | Java grep `System.loadLibrary`, `JNI_OnLoad`                                        | Verify arm64 native build → `conditional`                       |
| CUDA / GPU                   | grep `import cuda`, `torch.cuda`, `nvidia`                                          | `incompatible` → route to G5/G6                                 |

### IaC only (`discover-iac.md`) — best effort, default `conditional`/`unknown`

| Signal                 | Where                               | Implies                                                |
| ---------------------- | ----------------------------------- | ------------------------------------------------------ |
| GCP `machine_type`     | `google_compute_instance`           | Map to Graviton equivalent (see `graviton.md` mapping) |
| Cloud Run CPU setting  | `google_cloud_run_service` / `_v2_` | Map to Fargate ARM64                                   |
| `node_selector` arch   | Kubernetes manifests                | Current architecture constraint                        |
| Windows AMI            | AMI data source                     | `incompatible`                                         |
| `.csproj` net48 target | `.NET` project files                | .NET Framework → `incompatible`                        |

### Billing only (`discover-billing.md`) — coarse

> **Status: planned, not yet emitted.** `discover-billing.md` does not yet write `graviton_profile`. Until it does, billing-only runs with compute reach Clarify with no profile, and the Q11b decision table (row 1: "no profile but compute present → ask") covers them. The tiers below are the target behavior for the follow-up that wires `discover-billing.md`.

| Service in billing             | Default tier                                            |
| ------------------------------ | ------------------------------------------------------- |
| Cloud SQL / managed DB         | `ready` (all major managed DB engines support Graviton) |
| Memorystore / cache            | `ready` (ElastiCache supports Graviton)                 |
| Compute Engine / GKE (generic) | `unknown` (no architecture signal from billing)         |
| Cloud Run                      | `conditional`                                           |

---

## `design_constraints.cpu_architecture` (added to `preferences.json` by Clarify)

```json
"design_constraints": {
  "cpu_architecture": {
    "value": "graviton",
    "chosen_by": "default"
  }
}
```

| Field       | Values                                                                                         |
| ----------- | ---------------------------------------------------------------------------------------------- |
| `value`     | `graviton` \| `x86` \| `mixed`                                                                 |
| `chosen_by` | `user` (explicit Clarify answer) \| `default` (auto-applied because all services were `ready`) |

When all compute services are `tier: ready` and the user is not asked, write `value: "graviton"`, `chosen_by: "default"`. When any service is `incompatible`, use `mixed` (Graviton where eligible, x86 elsewhere).

---

## `graviton` block (added to each compute service in `aws-design.json`)

```json
"graviton": {
  "compatibility": "ready",
  "target_architecture": "arm64",
  "caveats": []
}
```

`compatibility` mirrors the `tier` from `graviton_profile`. `target_architecture` is `arm64` for ready/conditional, `x86_64` for incompatible.

---

## `architecture_comparison` (added to `estimation-infra.json` when Graviton is selected)

```json
"architecture_comparison": {
  "graviton_monthly": 245.00,
  "x86_equivalent_monthly": 298.00,
  "savings_amount": 53.00,
  "savings_percent": 17.8,
  "note": "Hourly price savings only; performance uplift may allow further downsizing after load testing"
}
```

| Field                    | Notes                                                        |
| ------------------------ | ------------------------------------------------------------ |
| `graviton_monthly`       | Balanced-tier monthly cost using Graviton instance pricing   |
| `x86_equivalent_monthly` | Same architecture mapping priced on the x86 equivalents      |
| `savings_amount`         | `x86_equivalent_monthly − graviton_monthly`                  |
| `savings_percent`        | `savings_amount / x86_equivalent_monthly × 100`, one decimal |
| `note`                   | Required; states that only hourly price discount is modeled  |

**Report consistency:** when the migration report renders Graviton savings, the figures MUST equal these fields (no recomputation in the report layer). This is a **manual self-check** today; the post-write report validator is structural/readability only and does not audit dollar figures. An automated numeric assertion is a tracked follow-up (see `shared/graviton.md` → "Report rendering").
