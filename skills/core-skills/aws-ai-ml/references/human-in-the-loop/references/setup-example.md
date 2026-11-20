# Label Studio Setup Example

This file is the one home for the `scripts/ls_space_client.py` command lines used in Steps 3a.3–3a.7, the job status check, Step 5, and Step 7's relabel round. The annotator deep-link is not one of them: it is an AWS CLI command the user or the annotator runs (`references/label-studio-space.md` → Presigned deep-links). Every command prints JSON to stdout; errors print `{error, message}` JSON to stderr (exit codes: `references/label-studio-space.md` → Troubleshooting). Run from the skill directory (or use the full path to the script). Add `--region <region>` to every command when the agent's AWS config has no default region, and run every command with the endpoint stage the space was found on (`references/label-studio-space.md` → Endpoint stage).

**3a.3 — find the running Label Studio space** (exit 2 = not found or not running; stdout then has `not_running` and `domains`):

```bash
python scripts/ls_space_client.py discover   # add --domain-id <domain-id> --space-name <space-name> once they're known
```

**3a.3 — when the user chose to have the skill create or start it.** List the domain's profiles (no space needed) and estimate the storage from the records to annotate:

```bash
python scripts/ls_space_client.py profiles --domain-id <domain-id>
python scripts/ls_space_client.py estimate-storage --records <local-path-to-data>
```

Then create the space and start its app, or start the app in the space `discover` reported as not running (waits, `--no-wait` and Failed apps: `references/label-studio-space.md` → Creating or starting the space). They print `{"progress"}` lines on stderr while they wait. Both print `space` (the `discover` coordinates), `app_status` and `replaced_failed_app`; `create` also prints `created_space` and `unused_space` (`references/label-studio-space.md` → Creating or starting the space):

```bash
python scripts/ls_space_client.py create --domain-id <domain-id> --admin-profile <admin-profile> [--ebs-gb <ebs-gb>]
python scripts/ls_space_client.py start --domain-id <domain-id> --space-name <space-name> [--replace-failed-app]
```

**3a.4 — list the domain's profiles** (prints `profiles`, `owner_profile` and `caller_arn`; AWS only, does not contact Label Studio). `caller_arn` is the account, the identity type and, for an assumed role, the role name; a person's name (an assumed role's session, a federated user or an IAM user) is left out. If the `sts:GetCallerIdentity` call fails, every command that looks for the space (and `create` and `start`) exits 5: it needs the caller's account to tell the first-party image from the user's own (`references/label-studio-space.md` → Which space).

```bash
python scripts/ls_space_client.py profiles --domain-id <domain-id> --space-name <space-name>
# after the user names their profile, or for the profile already named at 3a.3 (admin_profile_check: overview.md Step 3a.4)
python scripts/ls_space_client.py profiles --domain-id <domain-id> --space-name <space-name> --admin-profile <admin-profile>
```

**3a.7 — split records and create one project per annotator:**

```bash
python scripts/ls_space_client.py setup --domain-id <domain-id> --space-name <space-name> \
  --admin-profile <admin-profile> --annotators <annotator-profile>,<annotator-profile> \
  --project-name <project-name> --label-config <project-dir>/specs/label_config.xml \
  --records <local-path-to-data> --out <project-dir>/data/hil/ls_setup.json \
  [--data-fields <input-field>] [--hide-fields <hidden-field>] [--id-field <id-field>]
```

**Job status check** (any time; read-only):

```bash
python scripts/ls_space_client.py status --domain-id <domain-id> --space-name <space-name> \
  --admin-profile <admin-profile> --assignments <project-dir>/data/hil/ls_setup.json
```

**Step 5 — export completed annotations:**

```bash
python scripts/ls_space_client.py export --domain-id <domain-id> --space-name <space-name> \
  --admin-profile <admin-profile> --assignments <project-dir>/data/hil/ls_setup.json \
  --out <project-dir>/data/hil/label_studio_export.jsonl
```

**Step 5 — optional S3 copy** (fields and outcomes: `references/label-studio-space.md` → S3 copy of the export). Preview the destination (read-only), then check it:

```bash
python scripts/ls_space_client.py s3-inspect --s3-uri <s3-uri> \
  --assignments <project-dir>/data/hil/ls_setup.json --out <project-dir>/data/hil/label_studio_export.jsonl
python scripts/ls_space_client.py s3-check --s3-uri <s3-uri> \
  --assignments <project-dir>/data/hil/ls_setup.json --project-dir <project-dir> \
  [--step <plan-step> --iteration <iteration>] [--s3-kms-key-id <kms-key>]
```

`--step` and `--iteration` are the plan step's name and loop iteration, under a plan. Pass `--s3-kms-key-id` only when the user names a KMS key (ARN, key id or alias).

Then add `--s3-uri <s3-uri> --project-dir <project-dir>` to the Step 5 export command, with the same `<s3-uri>` (and the same `--s3-kms-key-id`, when the check used one).

**Step 7 — relabel round** (auto-labeling's input; `references/label-studio-space.md` → Discarded rows). Set up the round from the export:

```bash
python scripts/ls_space_client.py setup --domain-id <domain-id> --space-name <space-name> \
  --admin-profile <admin-profile> --annotators <relabel-profile> --project-name <project-name>-relabel \
  --label-config <project-dir>/specs/label_config.xml --records <project-dir>/data/hil/label_studio_export.jsonl \
  --relabel-of <approval-id> --project-dir <project-dir> --out <project-dir>/data/hil/ls_setup_relabel_<n>.json
```

If `setup` saved the round's output but couldn't record it in the HIL log (exit 3, `OutputWriteError`), record it without a new project:

```bash
python scripts/ls_space_client.py record-relabel-round \
  --assignments <project-dir>/data/hil/ls_setup_relabel_<n>.json --project-dir <project-dir>
```

Once it is annotated, export with every relabel round's setup output so far (one `--relabel-setup` each). For an input other than auto-labeling's there is no relabel round: run the same export without `--relabel-setup`, adding `--discarded-out <project-dir>/data/hil/discarded_rows.jsonl`.

```bash
python scripts/ls_space_client.py export --domain-id <domain-id> --space-name <space-name> \
  --admin-profile <admin-profile> --assignments <project-dir>/data/hil/ls_setup.json \
  --approval-id <approval-id> --project-dir <project-dir> --out <project-dir>/data/hil/label_studio_export.jsonl \
  --relabel-setup <project-dir>/data/hil/ls_setup_relabel_1.json [--relabel-setup <project-dir>/data/hil/ls_setup_relabel_<n>.json ...]
```

The same operations are available as Python functions (`find_label_studio_space`, `create_label_studio_space`, `start_label_studio_app`, `estimate_storage`, `list_annotator_profiles`, `check_admin_profile`, `setup_projects`, `get_progress`, `export_annotations`) if a step needs them in code.

## Placeholders

| Placeholder | Format | Example |
|---|---|---|
| `<account-id>` | The caller's own AWS account (`aws sts get-caller-identity --query Account --output text`) | `111122223333` |
| `<domain-name>` | Domain name, from `discover` output | `my-domain` |
| `<region>` | AWS region of the domain | `us-west-2` |
| `<domain-id>` | From `discover` output | `d-xxxxxxxxxxxx` |
| `<space-name>` | Shared space hosting the Label Studio app, from `discover` (or `create`) output | `label-studio-20260101120000` |
| `<ebs-gb>` | The new space's storage volume in whole GB; default 5, up to the domain's `max_ebs_gb` from `discover` | `10` |
| `<space-host>` | Host of the space's `space_url` from `discover` | `<space-id>.studio.<region>.sagemaker.aws` |
| `<admin-profile>` | The admin profile, which the skill acts as in Label Studio; confirmed at Step 3a.4 (required) | `data-scientist-1` |
| `<annotator-profile>` | SageMaker user profile name from `profiles` output | `annotator-1` |
| `<project-name>` | Short slug, no spaces | `fill-missing-outputs` |
| `<project-id>` | Label Studio project id from `ls_setup.json` → `assignments` | `12` |
| `<project-dir>` | The human-in-the-loop project directory in the user's workspace | `./my-hil-project` |
| `<bucket>` | Existing S3 bucket in the user's account | `my-bucket` |
| `<s3-uri>` | The S3 destination the user chose, from `export_destination`: a bucket, a prefix, or a full key. The script derives the upload URI (`references/label-studio-space.md` → S3 copy of the export → Upload URI) | `s3://my-bucket/hil/` |
| `<plan-step>` | The plan step's name in kebab-case; omit outside a plan | `export-annotations` |
| `<approval-id>` | The `id` of the Step 7 approval entry in the HIL log (`hil_log.py write` prints it) | `approval-human-in-the-loop-edit-plan-iter0-approved` |
| `<relabel-profile>` | The profile the user chose to relabel the discarded rows, from `profiles` output | `annotator-2` |
| `<n>` | The relabel round's number: 1 for a cycle's first relabel round, then 2, 3, ... | `1` |
| `<iteration>` | The plan's loop iteration; omit outside a loop | `2` |
| `<run-id>` | Setup run id (`YYYYMMDD-HHMMSS`) from `ls_setup.json` → `run_id` | `20260101-120000` |
| `<ls-path>` | Label Studio page path after `/jupyterlab/default/label-studio/` | `projects/12/data` |
| `<relative-path>` | Path after `/jupyterlab/default/`, used as `--landing-uri "app:JupyterLab:<relative-path>"` in the presigned deep-link | `label-studio/projects/12/data` |
| `<local-path-to-data>` | Local JSONL file (after ARN/S3 resolution) | `<project-dir>/data/hil/low_confidence.jsonl` |
| `<input-field>` | A record field annotators see, comma-separated for several; without `--data-fields` every field except the `_`-prefixed and `--hide-fields` ones is uploaded | `text`, the labeling run's `--text-fields` |
| `<hidden-field>` | A record field no task carries, comma-separated for several, even without `--data-fields`; a `--data-fields` name among them is refused | `split,_review_reason`, auto-labeling's hidden fields |
| `<id-field>` | The record id field; every record needs a value no other record shares, or `setup` exits 4 and creates nothing | `id` |
| `<endpoint-url>` | Non-prod SageMaker endpoint the space was found on; omit for prod (`references/label-studio-space.md` → Endpoint stage) | (none for prod) |

## Setup output (`ls_setup.json`)

Fields: `space` (the `discover` coordinates, including `space_url`), `admin_profile`, `project_name`, `run_id` (local time), `created_at` (when setup ran, UTC), `relabel_of` (a relabel round only: `references/label-studio-space.md` → Discarded rows), `admin_url` (the project list), `assignments` (`{<annotator-profile>: {project_id, title, url, task_count}}`), and `markdown` (a ready rendering of the links). Partial setup output instead carries `"partial": true` and `failed_profile`, with the projects created so far, and no `markdown`. `setup --out` writes this file only when setup succeeds or is partial, so a failed re-run keeps the previous one. `status` and `export` accept it directly as `--assignments`; the S3 commands need this file, not a plain assignments file.
