---
_fragment: terraform
_of_phase: discover
_contributes:
  - heroku-resource-inventory.json (resource entries, apps, metadata, terraform_metadata sections)
---

# Discover Phase: Terraform Discovery (Primary Path)

> Self-contained Terraform discovery sub-file. Scans `.tf` files for `heroku_*` resource types, extracts resource configuration attributes, maps them to inventory format, and integrates Procfile/app.json parsing when repo artifacts are available.
> If no `.tf` files with `heroku_*` resources are found, exits cleanly with no output.

**Execute ALL steps in order. Do not skip or optimize.**

---

## Step 0: Scan for `.tf` Files with `heroku_*` Resources

Recursively scan the workspace directory for Terraform files containing Heroku resources.

### 0a. File Discovery

Glob pattern: `**/*.tf`

Exclude directories:

- `.terraform/` (provider binaries and cached modules)
- `node_modules/`
- `.git/`

### 0b. Content Filtering

For each discovered `.tf` file, scan file contents for resource blocks matching:

```
resource "heroku_*" "..." {
```

Specifically, match lines containing `resource "heroku_` (with double-quote before the provider prefix).

**Target resource types:**

- `heroku_app`
- `heroku_addon`
- `heroku_formation`
- `heroku_domain`
- `heroku_config_association`
- `heroku_pipeline`
- `heroku_space`

---

## Step 1: Extract Resources from Terraform

For each `.tf` file containing `heroku_*` resources, parse the Terraform HCL to extract resource blocks. Process files in alphabetical order for deterministic output.

### 1a. HCL Block Extraction

For each `resource` block with a `heroku_*` type, extract:

| Field              | Source                                    | Description                       |
| ------------------ | ----------------------------------------- | --------------------------------- |
| `tf_resource_type` | Block type label (e.g., `heroku_app`)     | The Terraform resource type       |
| `tf_resource_name` | Block name label (e.g., `"my-app"`)       | The Terraform resource local name |
| `tf_file`          | File path relative to workspace root      | Source file for traceability      |
| `attributes`       | All key-value pairs within the block body | Configuration attributes          |

### 1b. Attribute Extraction Rules

Extract top-level attributes from each resource block. Handle these patterns:

**Simple attributes:**

```hcl
resource "heroku_app" "my_app" {
  name   = "my-web-app"
  region = "us"
  stack  = "heroku-22"
}
```

→ `{ "name": "my-web-app", "region": "us", "stack": "heroku-22" }`

**Nested blocks (flatten with dot notation for key fields):**

```hcl
resource "heroku_app" "my_app" {
  name   = "my-web-app"
  region = "us"

  organization {
    name = "my-org"
  }
}
```

→ `{ "name": "my-web-app", "region": "us", "organization.name": "my-org" }`

**Dynamic references and interpolations:**

```hcl
resource "heroku_addon" "postgres" {
  app_id = heroku_app.my_app.id
  plan   = "heroku-postgresql:standard-0"
}
```

- Terraform references (e.g., `heroku_app.my_app.id`) → record as `"ref:heroku_app.my_app.id"`
- Interpolations (`"${var.name}"`) → record as `"var:name"` (unresolvable, metadata only)
- Literal values → record as-is

**Lists and maps:**

```hcl
resource "heroku_config_association" "config" {
  app_id = heroku_app.my_app.id
  vars = {
    DATABASE_URL = "postgres://..."
    REDIS_URL    = "redis://..."
  }
}
```

- Record map keys only (values may contain secrets) → `"vars_keys": ["DATABASE_URL", "REDIS_URL"]`
- List attributes → record as JSON arrays

### 1c. Resource Type Extraction Details

#### `heroku_app`

| Attribute           | Inventory Field                     | Required |
| ------------------- | ----------------------------------- | -------- |
| `name`              | `app_name`                          | Yes      |
| `region`            | `region`                            | Yes      |
| `stack`             | `stack` (feeds Cedar/Fir detection) | No       |
| `space`             | `space` (Private Space name)        | No       |
| `organization.name` | `organization`                      | No       |
| `buildpacks`        | `buildpacks` (array)                | No       |
| `acm`               | `acm_enabled` (boolean)             | No       |

#### `heroku_addon`

| Attribute | Inventory Field                       | Required |
| --------- | ------------------------------------- | -------- |
| `app_id`  | resolve to `heroku_app` via reference | Yes      |
| `plan`    | `plan` (format: `service:plan-tier`)  | Yes      |

Parse the `plan` attribute to split into `addon_service` and `plan_tier`:

- `"heroku-postgresql:standard-0"` → `addon_service: "heroku-postgresql"`, `plan: "standard-0"`
- `"papertrail:choklad"` → `addon_service: "papertrail"`, `plan: "choklad"`

#### `heroku_formation`

| Attribute  | Inventory Field                       | Required |
| ---------- | ------------------------------------- | -------- |
| `app_id`   | resolve to `heroku_app` via reference | Yes      |
| `type`     | `process_type`                        | Yes      |
| `quantity` | `quantity` (integer)                  | Yes      |
| `size`     | `dyno_type`                           | Yes      |

#### `heroku_domain`

| Attribute         | Inventory Field                       | Required |
| ----------------- | ------------------------------------- | -------- |
| `app_id`          | resolve to `heroku_app` via reference | Yes      |
| `hostname`        | `hostname`                            | Yes      |
| `sni_endpoint_id` | `sni_endpoint`                        | No       |

#### `heroku_config_association`

| Attribute | Inventory Field                                | Required |
| --------- | ---------------------------------------------- | -------- |
| `app_id`  | resolve to `heroku_app` via reference          | Yes      |
| `vars`    | `config_var_keys` (keys only, values redacted) | Yes      |

**Security: Record variable KEYS ONLY from `vars` map. Redact all values.**

#### `heroku_pipeline`

| Attribute | Inventory Field | Required |
| --------- | --------------- | -------- |
| `name`    | `pipeline_name` | Yes      |

Note: Pipeline stage assignments come from `heroku_pipeline_coupling` resources. If couplings are present, associate apps to stages. If not found, record pipeline with empty stages.

#### `heroku_space`

| Attribute      | Inventory Field    | Required            |
| -------------- | ------------------ | ------------------- |
| `name`         | `space_name`       | Yes                 |
| `region`       | `region`           | Yes                 |
| `shield`       | `shield` (boolean) | No (default: false) |
| `organization` | `organization`     | No                  |

### 1d. Reference Resolution

Terraform resources often reference each other (e.g., `heroku_addon.postgres.app_id = heroku_app.my_app.id`).

**Resolution strategy:**

1. Build a lookup table of all `heroku_app` resources: `tf_resource_name` → `app_name`.
2. For each resource with an `app_id` reference:
   - If reference is to a `heroku_app` resource in the same set → resolve to that app's `name` attribute.
   - If reference is to a variable or external data source → record as `"unresolved:{reference}"` and set `heroku_app` to `"unassociated"`.
3. If `app_id` is a literal string (UUID or app name) → use directly.

### 1e. Parse Error Handling

If a `.tf` file contains syntax that prevents extraction (malformed HCL, incomplete blocks):

- Log warning: "Failed to parse Terraform resource in `{filename}` at line {N}: {error}. Skipping this resource block."
- Skip the malformed block and continue to next resource block.
- **Do not halt** — continue processing remaining files and blocks.
- Record warning in output `parse_warnings` array.

---

## Step 2: Map Terraform Resources to Inventory Format

Transform each extracted Terraform resource into the standard inventory resource entry format.

### 2a. Resource ID Generation

| Terraform Type              | Inventory `resource_id` Format            | Inventory `resource_type` |
| --------------------------- | ----------------------------------------- | ------------------------- |
| `heroku_app`                | `app:{app_name}`                          | `app`                     |
| `heroku_addon`              | `addon:{app_name}:{addon_service}:{plan}` | `addon`                   |
| `heroku_formation`          | `formation:{app_name}:{process_type}`     | `formation`               |
| `heroku_domain`             | `domain:{app_name}:{hostname}`            | `domain`                  |
| `heroku_config_association` | `config:{app_name}`                       | `config`                  |
| `heroku_pipeline`           | `pipeline:{pipeline_name}`                | `pipeline`                |
| `heroku_space`              | `space:{space_name}`                      | `space`                   |

### 2b. Resource Entry Construction

Each resource becomes a standard inventory entry:

```json
{
  "resource_id": "<generated per 2a>",
  "resource_type": "<mapped type>",
  "heroku_app": "<resolved app name or 'unassociated'>",
  "config": { "<extracted attributes>" },
  "source": "terraform",
  "tf_file": "<relative file path>",
  "tf_resource_name": "<terraform local name>"
}
```

### 2c. Formation Entry Example

```hcl
resource "heroku_formation" "web" {
  app_id   = heroku_app.my_app.id
  type     = "web"
  quantity = 2
  size     = "standard-2x"
}
```

→

```json
{
  "resource_id": "formation:my-web-app:web",
  "resource_type": "formation",
  "heroku_app": "my-web-app",
  "config": {
    "process_type": "web",
    "command": null,
    "dyno_type": "standard-2x",
    "quantity": 2
  },
  "source": "terraform",
  "tf_file": "heroku.tf",
  "tf_resource_name": "web"
}
```

Note: Terraform `heroku_formation` does not include the `command` field — this comes from Procfile. Set to `null` when unavailable.

### 2d. Add-On Entry Example

```hcl
resource "heroku_addon" "postgres" {
  app_id = heroku_app.my_app.id
  plan   = "heroku-postgresql:standard-0"
}
```

→

```json
{
  "resource_id": "addon:my-web-app:heroku-postgresql:standard-0",
  "resource_type": "addon",
  "heroku_app": "my-web-app",
  "config": {
    "addon_service": "heroku-postgresql",
    "plan": "standard-0",
    "provider": "heroku"
  },
  "source": "terraform",
  "tf_file": "heroku.tf",
  "tf_resource_name": "postgres"
}
```

### 2e. Space Entry Example

```hcl
resource "heroku_space" "private" {
  name         = "my-private-space"
  organization = "my-org"
  region       = "virginia"
  shield       = false
}
```

→

```json
{
  "resource_id": "space:my-private-space",
  "resource_type": "space",
  "heroku_app": "unassociated",
  "config": {
    "space_name": "my-private-space",
    "region": "virginia",
    "shield": false,
    "organization": "my-org",
    "peering": {
      "detected": false,
      "vpc_id": null,
      "peer_cidr": null
    }
  },
  "source": "terraform",
  "tf_file": "spaces.tf",
  "tf_resource_name": "private"
}
```

Note: VPC peering cannot be detected from Terraform alone unless `heroku_space_peering_connection_accepter` or similar resources are present. Default `peering.detected` to `false` unless peering resources found.

### 2f. Pipeline Entry Example

```hcl
resource "heroku_pipeline" "main" {
  name = "my-pipeline"
}
```

→

```json
{
  "resource_id": "pipeline:my-pipeline",
  "resource_type": "pipeline",
  "heroku_app": "unassociated",
  "config": {
    "pipeline_name": "my-pipeline",
    "stages": [],
    "review_apps_enabled": false,
    "detection_status": "detect-only"
  },
  "source": "terraform",
  "tf_file": "pipelines.tf",
  "tf_resource_name": "main"
}
```

If `heroku_pipeline_coupling` resources are found, populate the `stages` array:

```hcl
resource "heroku_pipeline_coupling" "production" {
  app_id   = heroku_app.my_app.id
  pipeline = heroku_pipeline.main.id
  stage    = "production"
}
```

→ Add to pipeline stages: `{ "stage": "production", "app": "my-web-app" }`

### 2g. Domain Entry Example

```hcl
resource "heroku_domain" "www" {
  app_id   = heroku_app.my_app.id
  hostname = "www.example.com"
}
```

→

```json
{
  "resource_id": "domain:my-web-app:www.example.com",
  "resource_type": "domain",
  "heroku_app": "my-web-app",
  "config": {
    "hostname": "www.example.com",
    "sni_endpoint": null
  },
  "source": "terraform",
  "tf_file": "dns.tf",
  "tf_resource_name": "www"
}
```

### 2h. Config Association Entry Example

```hcl
resource "heroku_config_association" "config" {
  app_id = heroku_app.my_app.id
  vars = {
    DATABASE_URL = "postgres://..."
    REDIS_URL    = "redis://..."
    SECRET_KEY   = "abc123"
  }
}
```

→

```json
{
  "resource_id": "config:my-web-app",
  "resource_type": "config",
  "heroku_app": "my-web-app",
  "config": {
    "config_var_keys": ["DATABASE_URL", "REDIS_URL", "SECRET_KEY"]
  },
  "source": "terraform",
  "tf_file": "config.tf",
  "tf_resource_name": "config"
}
```

**Security:** Only key names are recorded. All values are redacted.

---

## Step 3: Integrate Procfile and app.json (Repo Artifacts)

After Terraform extraction, scan the workspace for Procfile and app.json to supplement resource data.

### 3a. Procfile Integration

Search for `Procfile` at workspace root or in subdirectories matching Terraform-discovered app names.

**If found**, parse using the Procfile format:

- One process declaration per line: `<process_type>: <command>`
- Lines starting with `#` are comments
- Empty lines are ignored
- Process type names: `[a-zA-Z0-9_-]+`

For each parsed process type:

- If a matching `formation` resource exists from Terraform (same app + process type) → add the `command` field from Procfile
- If a process type appears in Procfile but NOT in Terraform formations → add a formation resource with `command` from Procfile and `quantity: 0`, `dyno_type: "unknown"` (declared but not in Terraform)

**If NOT found**: Log "No Procfile found — `command` fields will be null for formation resources." Continue processing.

**On parse error**: Record `procfile_parse_warning` on the app entry, continue processing.

### 3b. app.json Integration

Search for `app.json` at workspace root or in subdirectories.

**If found**, parse as JSON and extract:

- `addons` → Cross-reference with Terraform-discovered add-ons. Record any add-ons declared in app.json but not in Terraform (useful for detecting intent).
- `formation` → Formation defaults (quantity, size). Terraform values take precedence; app.json provides supplementary context.
- `buildpacks` → Record for Cedar/Fir assessment and container build strategy.
- `env` → Record variable names (keys only, no values) for downstream reference.
- `stack` → Supplements Cedar/Fir generation detection.

**If NOT found**: Log "No app.json found." Continue processing.

**On parse error**: Record `app_json_parse_warning`, continue processing.

### 3c. Cedar/Fir Detection from Stack

For each `heroku_app` resource:

- If `stack` attribute is present in Terraform OR app.json:
  - Stack containing `heroku-20`, `heroku-22`, `heroku-24` → `heroku_generation: "cedar"`
  - Stack containing `fir` or `cnb` → `heroku_generation: "fir"`
  - Other/absent → `heroku_generation: "unknown"`
- Set `generation_action: "detect_only"` for all apps (v1)

---

## Step 4: Output Contribution for Parent Orchestrator

The phase assembler (`discover-assemble.md`) owns the inventory's STRUCTURE (which
sections exist and their field lists). This fragment contributes the following
terraform-specific content and rules:

- **Resources:** all Terraform-sourced entries go into `resources[]` as the
  primary inventory data; Procfile/app.json supplements them (adds `command`,
  buildpacks, declared add-ons). When Procfile was available, formation entries
  have `command` populated; otherwise `command` is `null`.
- **Confidence:** set `metadata.confidence` to `"full"` when all Terraform files
  parsed successfully, or `"reduced"` if any parse errors occurred or expected
  resources were missing.
- **Discovery sources:** contribute `"terraform"` to `metadata.discovery_sources`,
  and `"procfile"` as well if Procfile/app.json were found and parsed.
- **`terraform_metadata`:** contribute the shape shown below.

```json
{
  "terraform_metadata": {
    "found": true,
    "tf_files_scanned": 5,
    "resource_types_extracted": ["heroku_app", "heroku_addon", "heroku_formation"],
    "parse_warnings": []
  }
}
```

---

## Error Handling

| Error Category                        | Behavior                                     | Effect on Discovery                      |
| ------------------------------------- | -------------------------------------------- | ---------------------------------------- |
| HCL parse error in one file           | Log warning, skip malformed blocks, continue | Other files still processed              |
| HCL parse error in all files          | Log warning, exit cleanly                    | Billing discovery may still run          |
| Unresolvable Terraform reference      | Set `heroku_app: "unassociated"`, continue   | Resource included with limited context   |
| `heroku_app` resource has no `name`   | Skip resource, log warning                   | Other resources still processed          |
| `heroku_addon` has unparseable `plan` | Record with `plan: "unknown"`, continue      | Resource included with limited plan info |
| File read permission denied           | Log warning, skip file, continue             | Other files still processed              |
| Circular Terraform references         | Resolve to best-effort, log warning          | Resources included with available data   |

**Key principle:** Terraform discovery is the **primary** discovery path in v1. Any parse failure results in a warning and graceful skip for that specific block — it should NOT halt the entire discovery. Partial results are always better than no results.

---

## Scope Boundary

**This sub-file covers Terraform resource extraction ONLY.**

FORBIDDEN — Do NOT include ANY of:

- AWS service names, recommendations, or equivalents
- Migration strategies, phases, or timelines
- Terraform generation for AWS
- Cost estimates or comparisons
- Effort estimates
- Terraform state file (`terraform.tfstate`) parsing — only `.tf` source files
- Terraform module resolution across remote registries
- `terraform plan` or `terraform apply` execution

**Your ONLY job: Extract Heroku resource declarations from `.tf` files, integrate Procfile/app.json data, and produce inventory entries. Nothing else.**

After generating the resource entries and conflict records, the parent `discover.md` handles merging into the final inventory and updating phase status — do NOT update `.phase-status.json` from this sub-file.
