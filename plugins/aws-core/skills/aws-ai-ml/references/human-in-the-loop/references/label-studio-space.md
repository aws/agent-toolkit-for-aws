# Label Studio in a SageMaker Studio shared space

The skill does not host Label Studio. The **Label Studio app** runs in a **shared** space on the Label Studio image. The user launches it from its icon in SageMaker Studio, or the skill creates the space or starts its app when the user chooses that at Step 3a.3 of `overview.md` (Creating or starting the space, below). The skill connects to that space from wherever the agent runs, using `scripts/ls_space_client.py`.

## What runs in the space

| Item | Value |
|---|---|
| Space | Shared JupyterLab space on the first-party `label-studio-jupyterlab` image (Which space, below) |
| Label Studio | Community Edition, bound to `127.0.0.1:8080` inside the space (never exposed) |
| Browser URL | `https://<space-host>/jupyterlab/default/label-studio/<ls-path>` (e.g. `projects/<project-id>/data`) |
| Sign-in | Automatic, from the Studio proxy's `StudioAuthToken` cookie. First visit creates the Label Studio user `<annotator-profile>@studio.local`. Users have no password, so the only way in is through Studio. |
| Data | `~/label-studio-data` on the space's storage volume — survives app restarts |

### Which space

- A Label Studio space is a **shared** JupyterLab space whose image, read from its image ARN or image-version ARN, is named exactly `label-studio-jupyterlab` and belongs to the image owner's account, never the user's own: an image of that name in the user's own account is their custom image and never counts. On prod the image ships only in the regions `scripts/label-studio-images.json` lists, so the space must be in one of them and the image account must be that region's account. On a non-prod stage (`AWS_ENDPOINT_URL_SAGEMAKER` set to a non-AWS host), any account other than the user's own counts, because those image accounts aren't listed. For a running app the skill reads the image Studio resolved at start, from the app itself. The space's name is never used to identify it, because any user can give a space on another image a similar name. A private space on the image belongs to one user and is an ordinary space.
- In each domain, the Label Studio space is the oldest such space that is not failed or being deleted. `create` names the spaces it makes `label-studio-<UTC YYYYMMDDHHMMSS>`.
- `discover` returns at most one space per domain. `--space-name` checks only that space, which must be a Label Studio space.

`<space-host>` comes from `describe-space --query Url` (e.g. `abc123example.studio.us-west-2.sagemaker.aws`). It is per-space, not the domain id.

Useful paths:

| Path | What it does |
|---|---|
| `/projects/` | Project list |
| `/projects/<project-id>/data` | Task list for one project — the link given to annotators |
| `/projects/<project-id>/labeling` | Labeling stream (skips the task list) |

## How the skill connects

1. **Discover** — `ListDomains` → in each domain, `ListSpaces` and `ListApps`, then `DescribeSpace` for each shared JupyterLab space whose image no running app shows and that is older than any space a running app already shows to be Label Studio → `ListApps` to confirm the found space's JupyterLab app is InService.
2. **Authenticate** — `CreatePresignedDomainUrl` for the admin profile (`--admin-profile`, confirmed at Step 3a.4) and the space, a 5-second URL redeemed at once into an in-memory cookie jar. If Studio rejects it as expired (a slow link), the skill mints one fresh URL and tries once more; a URL is never reused.
3. **Call the REST API through the proxy** — `https://<space-host>/jupyterlab/default/label-studio/api/...`. Label Studio's autologin treats each call as coming from the admin profile, so no Label Studio API token is involved. Write calls send Django's `csrftoken` back as `X-CSRFToken`, plus the Studio origin.

Rules:

- ⛔ **Never print, store, or hand out the presigned URL or the session cookies the skill uses.** A presigned URL is a bearer credential for the whole JupyterLab IDE, not just Label Studio. Store only coordinates (`region`, `domain_id`, `space_name`, `admin_profile`, project ids) in the manifest, and mint a new session for each command.
- ⛔ **Create a space or start its app only after the user chose to have the skill do it** at Step 3a.3 of `overview.md`, and only with `create` or `start`. Otherwise, the user launches it from the Studio UI.
- ⛔ **Never stop or delete a space, and never stop a running app.** The one deletion the skill makes is a Failed app's (Creating or starting the space).
- ⛔ **The agent never mints a presigned URL for a person to open, and never pastes one.** For annotators, give the plain project link, or the deep-link *command* below for the user or the annotator to run.

## Creating or starting the space

`create` sets up the domain's Label Studio space; `start` starts the app in a Label Studio space that exists. Commands: `references/setup-example.md`, 3a.3.

Before it creates anything, `create` checks the following, and changes nothing when a check fails:

- The domain has a default space execution role, which a shared space runs as (exit 6 otherwise).
- `--admin-profile` is an InService user profile in the domain. It becomes the space's owner.
- When a new space is needed: `scripts/label-studio-images.json` lists the Label Studio image for the region, and `--ebs-gb` is at least 5 and no more than the domain's `max_ebs_gb` (`null` when the domain sets no limit). An existing Label Studio space is reused and started in the same 4 regions (us-west-2, us-east-1, eu-west-1, ap-northeast-1), with its own volume; `--ebs-gb` doesn't resize it (Operating limits).

Then it looks for the domain's Label Studio space again, and creates one only when there is none:

| Setting | Value |
|---|---|
| Name, display name | `label-studio-<UTC YYYYMMDDHHMMSS>`, `Label Studio` |
| Sharing, owner | `Shared`, owned by the admin profile; neither can be changed later |
| Image | `arn:aws:sagemaker:<region>:<account>:image/label-studio-jupyterlab` with the image version alias, both from `scripts/label-studio-images.json` |
| Instance type | `ml.t3.medium` (a larger one does not raise the save limit: Operating limits) |
| Storage | `--ebs-gb`, default 5 GB (Operating limits) |

`scripts/label-studio-images.json` holds the image's account and version alias per region, because no API or public page lists them (they come from the Label Studio image's owner, for prod); they may change with a new image release. On prod, every command that looks for the space checks the space's region and image account against it: a space in a region it doesn't list is never found, and a new region or image account must be added here before its spaces are found or created.

Right after creating, it looks once more. When an older Label Studio space shows up there (someone launched Label Studio at the same moment), the older one is used, and the new space is reported as `unused_space`. The skill never deletes it: tell the user its name, that it has no app and is billed for its storage only, and that they can delete it in Studio.

Starting the app, in both commands: wait for the space to be `InService`. A `Failed` app is deleted and created again only by `start --replace-failed-app`, which the agent passes after the user approved it: `start` without it exits 4 and changes nothing, and `create` leaves the app as it is and reports `app_status: Failed`. An app being deleted is waited out. The app, named `default`, belongs to the space, not to a profile, so any user in the domain can start it. Each wait (for the space, for a failed app to go, and for the new app) lasts up to 5 minutes; `--no-wait` returns once the app's start is accepted, and a later `discover` shows when it is running.

What it costs: the app's instance (`ml.t3.medium` in a space `create` made; for `start`, the space's own `instance_type` in `discover`'s `not_running`, or, when that is null, the domain's default: `aws sagemaker describe-domain --region <region> --domain-id <domain-id> --query DefaultSpaceSettings.JupyterLabAppSettings.DefaultResourceSpec.InstanceType`) is billed for as long as the app runs, and the storage until the space is deleted ([SageMaker pricing](https://aws.amazon.com/sagemaker/pricing/)). Stopping the app ends the instance charges and keeps every project (Stopping and cleaning up, below); deleting the space deletes the storage and every project in it.

## Presigned deep-links (no manual Studio sign-in)

The plain project link only works for someone already signed in to Studio who has opened the space. A presigned domain URL removes that step: it signs the person in as their SageMaker user profile **and** lands them in their labeling project in one click. Whoever mints it runs this command on a machine with their own AWS credentials, once per annotator. The IAM section below decides who that is and what their policy needs:

```bash
aws sagemaker create-presigned-domain-url --region <region> --domain-id <domain-id> \
  --space-name <space-name> --user-profile-name <annotator-profile> \
  --landing-uri "app:JupyterLab:label-studio/projects/<project-id>/data" \
  --expires-in-seconds 300 --session-expiration-duration-in-seconds 43200 --query AuthorizedUrl --output text
```

For a non-prod stage, add `--endpoint-url <endpoint-url>` (see Endpoint stage below). Placeholders: `references/setup-example.md` → Placeholders.

- ⭐ **`--user-profile-name` sets who the link signs in as.** Label Studio's autologin reads that profile from the `StudioAuthToken` cookie, so hand each profile's link to the matching person. For a shared space, any profile in the domain works.
- ⭐ **`--landing-uri "app:JupyterLab:<relative-path>"`** is everything after `/jupyterlab/default/`, here `label-studio/projects/<project-id>/data`. Without it the link lands in JupyterLab, not the project.
- ⛔ **`--expires-in-seconds` is capped at 300 (5 minutes), and the link is single-use.** Opening it twice (or a link preview) burns it: "Invalid or Expired Auth Token". Mint it the moment the annotator is ready, and send it over a private channel. Never pre-generate or store it.
- ⚠️ **`--session-expiration-duration-in-seconds`** sets how long the session lasts after opening (1800–43200 seconds). It cannot extend the 5-minute window to open the link.
- ⚠️ Opening it in a browser that already holds another Studio session can also fail with "Invalid or Expired". Use a fresh or private window.

## Endpoint stage

`ls_space_client.py` makes its SageMaker calls through the SageMaker Python SDK and boto3, both on boto3 sessions, so they route to whatever `AWS_ENDPOINT_URL_SAGEMAKER` names (unset = prod). Leave it unset unless the user was given a non-prod stage endpoint URL; never compose one by hand.

- Studio domains, spaces and profiles live on one stage. `create` and `start` run on the stage `discover` found the domain on, and `create` always names the prod image from `scripts/label-studio-images.json`: on a non-prod stage, Studio resolves it to that stage's first-party image when the app starts. A space created from the Studio console is on prod: if `discover` finds nothing on a non-prod stage, run it again with `AWS_ENDPOINT_URL_SAGEMAKER` unset.
- Use the stage where the space was found for every later `ls_space_client.py` command, and save it as `label_studio.endpoint_url` in the manifest (omit it for prod).
- The presigned deep-link command gets `--endpoint-url <endpoint-url>` only for a non-prod stage. For prod, omit the flag entirely — the CLI rejects an empty value.

## Manifest

Label Studio mode stores coordinates, paths and the export destination only in `manifests/human-in-the-loop.json` → `human_in_the_loop.label_studio` — never a presigned URL or cookie: `region`, `endpoint_url` (non-prod stage only), `domain_id`, `domain_name`, `space_name`, `space_url`, `admin_profile`, `annotators`, `export_destination` (Step 3a.4), `run_id`, and `assignments` (`{<annotator-profile>: {project_id, title, url, task_count}}`). Step 5 adds `annotation_export_path` and, with an S3 copy, `annotation_export_s3_uri`.

## IAM

Three principals, three different policies. **Do not advise `AmazonSageMakerFullAccess`** — it grants `CreatePresignedDomainUrl` on every profile in the domain, which defeats the annotator control below.

These are the **person's** permissions, not a list of calls the skill may make. The project creator is one human who does two things — launches the Label Studio app, and runs the skill — so their policy covers both. The **Studio UI** calls `CreateSpace`/`CreateApp` on their behalf when they click the Label Studio icon, and the skill calls them only with `create` or `start`, after the user chose that (How the skill connects → Rules). Keep `CreateSpace`/`CreateApp` in it: the person needs them to launch the app.

No principal needs `iam:PassRole`.

### Project creator (the person who launches the app and runs the skill)

The project creator's own user profile is the admin profile (`overview.md`, Step 3a.4).

| Action | Resource | Why |
|---|---|---|
| `sagemaker:ListDomains`, `ListUserProfiles`, `ListSpaces`, `ListApps` | `*` — these support no resource-level permission ([Service Authorization Reference](https://docs.aws.amazon.com/service-authorization/latest/reference/list_sagemaker.html)); scoping any of them **denies** the call | Find the domain, list annotator candidates, check whether the app is running. `ListUserProfiles` discloses other profiles' names, so grant these to the project creator and not to annotators |
| `sagemaker:DescribeDomain` | `domain/<domain-id>` | Read the domain's settings |
| `sagemaker:DescribeSpace` | `space/<domain-id>/*` | Find the Label Studio space: discovery may need to read the image of any shared JupyterLab space in the domain, whose names it can't know in advance (Which space, above; How the skill connects, step 1). Scoped to particular space names, it is denied on the other spaces, and a domain where such a read is needed is reported as not fully checked |
| `sagemaker:CreateSpace`, `CreateApp`, `DescribeApp` | `space/<domain-id>/label-studio-*`, plus `app/<domain-id>/label-studio-*/*` | Create the space and start its app, from the Studio UI or with the skill's `create` and `start` (both name new spaces `label-studio-<UTC timestamp>`); `DescribeApp` follows the app while it starts. A Label Studio space named otherwise needs its own ARNs here, or `start` is denied on it. Whoever creates the space must set `SharingType=Shared` in the same `CreateSpace` call, because it can't be changed later |
| `sagemaker:UpdateSpace` | `space/<domain-id>/label-studio-*` | Enlarge the annotation volume (see Operating limits). Needed only if you resize; omit it to make the volume fixed |
| `sagemaker:DeleteApp` | `app/<domain-id>/label-studio-*/*` | **Stopping** the app, which a resize requires — SageMaker has no `StopApp`, so the stop action *is* `DeleteApp` ([Studio docs](https://docs.aws.amazon.com/sagemaker/latest/dg/studio-updated-running-stop.html)). ⚠️ Stopping the app keeps the space and its data; it is **deleting the space** that destroys annotations, and nothing here grants `DeleteSpace`. Needed to stop the app to end its charges (Stopping and cleaning up, below) and for a resize, and by `start` to replace a Failed app |
| `sagemaker:CreatePresignedDomainUrl` | `user-profile/<domain-id>/<admin-profile>` — the admin profile, always. **Add one ARN per annotator only if the project creator mints that annotator's deep-link**; see below | **Two presign calls need this action.** (1) The skill's own session: `ls_space_client.py` presigns the **admin profile** only (for `setup`, `status` and `export`, and once for `profiles --admin-profile`'s check at Step 3a.4, which discards that URL unopened). (2) Each presigned deep-link: one call per annotator, with `--user-profile-name <annotator-profile>` (Presigned deep-links, above). ⭐ **Which profiles to name depends on who mints the deep-links; the table below decides it.** ⛔ **Whatever you name, enumerate the profiles rather than using `user-profile/<domain-id>/*`**, which grants presign rights over every profile in the domain, including profiles with no part in this job. This is the one grant that can open a session as a profile other than the caller's own, so grant it only to people you intend to have it |

Plus the S3 actions below for the export copy.

⚠️ **Which actions can be ARN-scoped is SageMaker's to change, so re-check it rather than trusting this table forever.** Both halves above come from the [Service Authorization Reference for SageMaker](https://docs.aws.amazon.com/service-authorization/latest/reference/list_sagemaker.html): an action with no resource types listed must be granted on `*`, and the rest are scoped to the ARNs shown. If SageMaker adds resource-level support to one of the `List*` actions, that row can be tightened; if a scoped call starts returning `AccessDenied`, check there before widening the policy.

⭐ **Two people can mint an annotator's deep-link, and which one you choose decides this row.** Offer the user both and let them pick:

| Who mints it | Project creator's presign resources | When to prefer it |
|---|---|---|
| **The annotator, for themselves** (recommended) | the admin profile **only** | Each annotator already signs in to AWS. Their `OpenOwnProfileOnly` statement below is all the permission needed, so the project creator gets no reach over anyone else's profile |
| The project creator, on their behalf | the admin profile **plus** that annotator's profile ARN | The annotator has no AWS console access of their own. A presigned URL is a bearer credential, so this is the only way to get them in |

⭐ **Recommend the first row**, and add an annotator's ARN only for the annotators the project creator actually mints for. Resolve the names before writing the policy: the admin profile is the project creator's own, confirmed at Step 3a.4 of `overview.md`, and the `profiles` output lists the annotator candidates. Only fall back to `user-profile/<domain-id>/*` when the set genuinely cannot be known in advance, and say plainly that doing so grants presign rights over every profile in the domain.

`sts:GetCallerIdentity` (the bucket-owner check, `caller_arn`, and telling the first-party image from the user's own: Which space) is not in this table: it needs no permission and can't be denied ([STS API reference](https://docs.aws.amazon.com/STS/latest/APIReference/API_GetCallerIdentity.html)).

### Annotator

An annotator needs **one** statement. It is what stops an annotator opening a session as somebody else, so it is a control, not a convenience:

```json
{ "Sid": "OpenOwnProfileOnly",
  "Effect": "Allow",
  "Action": "sagemaker:CreatePresignedDomainUrl",
  "Resource": "arn:aws:sagemaker:<region>:<account>:user-profile/<domain-id>/<their-profile>" }
```

Where each placeholder comes from, so the ARN is filled in rather than guessed — all four are already in hand by the time this policy is written:

| Placeholder | Source | Format |
|---|---|---|
| `<region>` | `region` in the manifest (`human_in_the_loop.label_studio`) — the Region the space was found in, not necessarily the caller's default | Region code, e.g. `us-west-2` |
| `<account>` | the caller's own account, from `sts:GetCallerIdentity` (needs no IAM grant — see the note under the project-creator policy) | 12 digits |
| `<domain-id>` | `domain_id` in the manifest, as returned by `ls_space_client.py discover` | `d-` followed by lowercase alphanumerics |
| `<their-profile>` | that one annotator's own profile name — a key of `assignments`, or an entry of `annotators`, in the manifest; originally from `ls_space_client.py profiles` | user-profile name, exactly as the domain spells it |

Write the resource out per annotator, naming that one profile. Do not widen it to `user-profile/<domain-id>/*` — that hands every annotator the project creator's reach. Because the restriction is in IAM, an annotator running this skill with their own credentials can mint a link for themselves and no one else, whatever the agent is asked to do.

### Shared Label Studio space execution role

**Label Studio gets no AWS credentials at all, so this role needs nothing granted on its behalf.** The image starts Label Studio with the container credential variables stripped from its environment, so the Label Studio process — and every Python dependency it loads — cannot reach the space's execution role. It makes no AWS calls; `DescribeSpace` is not called either, and the host is derived per request instead.

Two consequences to pass on to the user, because they change what can be set up:

- **This image has no validated path to Label Studio's own S3 storage** — neither target storage for results nor import storage for input. Label Studio supports both as a product; the first-party image strips the container credential variables they would need, so there is nothing here to authenticate them with. Deliver to S3 with the skill instead, using the caller's credentials (`export --s3-uri`).
- **An `s3://` media reference has no validated path on this image either.** Label Studio resolves one only through an import storage connected to the project, and this image sets none up (see above). For image or audio tasks, import the media as data the browser can fetch rather than as an `s3://` reference.

The skill itself always runs as the project creator — from their laptop or their own private space — never as the shared space's role.

## Operating limits

The figures here were measured against the shipped first-party image, by driving the real paths through the Studio proxy on the instance type the space deploys with. They are not service limits and no API reports them, so treat them as guidance for sizing a run, and re-check them if the image or the Label Studio version changes.

**About 8 annotators can save at the same time.** The image runs Label Studio against SQLite, which takes one writer at a time, so simultaneous saves queue. Past roughly 8, each save takes seconds instead of under a second and the space completes less work overall, not more. Any number can be signed in and reading; the limit is on saving at the same moment.

⛔ **A larger instance does not raise this limit, so do not offer one as the fix.** The constraint is SQLite's single writer, not compute; more concurrent annotators would need a different database, which the image does not provide.

**The first request after the app starts can take up to a minute** while Label Studio warms up. Tell the user, so it does not look like a hang.

**Records per project: tested to 20,000.** Import is fast — 20,000 records import in seconds, and each annotator's project adds more time than its records do, so the annotator count is usually the number worth discussing. ⚠️ **20,000 is the largest size tested, not a proven ceiling.** Above it, say so rather than implying support, and offer to split the work across runs — not across more annotators, since each adds a project and the ceiling above still applies.

**Storage is rarely the binding limit for text.** Annotation data lives in SQLite under `/home/sagemaker-user/label-studio-data` on the space's EBS volume, shared with `MEDIA_ROOT` and the home directory. Read the current size with the space's own name — take `<space-name>` from the manifest's `space_name` (the `discover` output), because it is not always the same in every domain. ⚠️ **The two `aws` commands below are raw CLI, so they need the stage the space was found on** — pass `--region <region>` from the manifest, and for a non-prod stage add `--endpoint-url <endpoint-url>` as the presigned deep-link command does (Endpoint stage); for prod omit the flag entirely, because the CLI rejects an empty value. Without the Region both default to prod and fail with `SpaceNotFoundError` against a space discovered on another stage:

```bash
aws sagemaker describe-space --region <region> \
  --domain-id <domain-id> --space-name <space-name> \
  --query 'SpaceSettings.SpaceStorageSettings.EbsStorageSettings.EbsVolumeSizeInGb'
```

**Estimate from the user's own data, not a fixed per-record figure** — record size varies by orders of magnitude. For a JSONL input of size `S` with `N` records each annotated once, expect the database to grow by about **`2S + N/2 KB`** (roughly twice the record JSON, plus ~½ KB per annotation). Label Studio's own bookkeeping is negligible: a project costs about a kilobyte. **A figure well above or below that is a reason to re-measure, not to patch the constants.** `estimate-storage` does this arithmetic for a JSONL file (`estimated_gb`). Do the arithmetic before creating projects — the input file is in hand and `describe-space` gives the volume — and tell the user if it will not fit, leaving headroom because the volume is shared.

The volume **can** be enlarged after the space is created, but only while no app is running: stop the app, raise the size, then start the app again. `<new-size>` is the new size in **whole GB** and must be larger than the `EbsVolumeSizeInGb` the `describe-space` query above returned — it is the new total, not an increment, and the volume cannot be shrunk:

```bash
aws sagemaker update-space --region <region> \
  --domain-id <domain-id> --space-name <space-name> \
  --space-settings 'SpaceStorageSettings={EbsStorageSettings={EbsVolumeSizeInGb=<new-size>}}'
```

 Attempting it with the app `InService` fails and tells you to stop the app first. ⚠️ This path needs `sagemaker:UpdateSpace` **and** `sagemaker:DeleteApp` (the stop) — both are rows in the IAM table above, and `UpdateSpace` is marked as needed only for resizing. On a policy scoped without them the resize fails with AccessDenied, so check the grants before telling a user the volume can be grown.

⚠️ **What happens when the volume fills has NOT been measured — do not tell the user it degrades gracefully.** Annotations are written synchronously to SQLite on that volume, so a full volume should surface as failed saves, with an annotator's in-progress work the most likely loss. Treat it as unsafe to reach: size with the estimate above before importing, and enlarge before it is close rather than after. If a user reports saves failing, check free space before looking at the concurrency limit above — the two look similar to an annotator and are unrelated.

## Assignment model

Label Studio Community Edition has no per-project access control: every signed-in user can see every project in the space (Enterprise adds roles and workspaces — [Label Studio docs](https://docs.humansignal.com/guide/manage_users.html); this may change). The skill assigns work by convention:

- One project per annotator, titled `<project-name>-<annotator-profile>-<run-id>`, holding that annotator's share of the records (even split, file order). Label Studio limits titles to 50 characters; `ls_space_client.py` shortens longer ones itself (drops the year from the run id, then shortens the project name and adds a 4-character hash; the profile is cut only at extreme lengths), so always use the titles it returns.
- Each annotator gets a direct link to their project.
- Attribution comes from each annotation's `completed_by` user, mapped back to the profile through `<annotator-profile>@studio.local`.

### Attribution

Each export row has `attribution`, a list of flags; it is empty when the task's annotations are the assigned annotator's own work:

- `other_annotator`: an annotation (or a skip) was made by another profile.
- `unknown_annotator`: the user of an annotation (or a skip) is not a `<profile>@studio.local` user.
- `edited_by_other`: the last editor (`updated_by_profile`, which Label Studio sets itself) differs from the submitter, or isn't a `<profile>@studio.local` user.
- `multiple_annotations`: the task has more than one annotation that wasn't skipped.

`export` also prints `attribution_summary`: `flagged_tasks`, the count per flag (`by_flag`), and the first 50 flagged rows (`task_id`, `project_id`, `unique_id`, `assigned_profile`, `completed_by_profiles`, `updated_by_profiles`, `flags`; an unknown user is `null`). Attribution is best-effort: an unflagged row means no flag fired, not that the work is proven to be the assigned annotator's. Another member editing a draft before its owner submits it is not flagged, and someone using another person's Studio session appears as that person.

For overlapping review (several annotators per task), create a shared project and set `maximum_annotations`. Label Studio documents its built-in agreement statistics as an Enterprise feature ([Label Studio docs](https://docs.humansignal.com/guide/stats.html); this may change), so compute agreement after export. auto-labeling's seed fold (`fold_review.py hil` / `check`) keeps an overlapping task only when its annotations agree and reports disagreeing ones as `conflicting_ids` to adjudicate.

### Discarded rows

A relabel round is `setup --relabel-of <approval-id> --project-dir <project-dir> --out <file>` with the export as `--records`: it sets up only the rows that approval entry discarded (`discarded_unique_ids`, matched on each task's `data.unique_id`), its setup output records `relabel_of`, and it adds an `artifact` entry to the HIL log (`artifact: relabel-round`, `relabel_of`, `setup`), the record of the cycle's relabel rounds.

`export --approval-id <approval-id> --project-dir <project-dir>` writes the export without the discarded rows, and each `--relabel-setup <file>` (a relabel round's setup output) adds that round's rows. For each record the newest round's row is kept, so a relabel replaces the discarded row; a row is also left out when any approval made after its round (that entry, or a round's `relabel_of`) discarded it. The export output adds `discarded` (`count`, `unique_ids`: records left with no row, such as a relabel not annotated yet) and `relabeled` (records whose row comes from a relabel round, each marked `relabel_of`). `--discarded-out <file>` also writes the rows of the records left with no row, one per record as exported, for Step 8.

## Status report

The `status` report (the fields below mirror the return contract of `get_progress()` in `scripts/ls_space_client.py` — that function is the source of truth):

- `annotators` has one row per annotator: `completed` / `total`, `skipped`, `remaining`, `pct`. Each task is counted once: `completed` has a submitted annotation, `skipped` was only skipped, `remaining` has neither. `totals` sums them, and `all_done` is true when nothing remains. Surface those values for each annotator and the totals (the `markdown` field is one ready rendering).
- If `annotators` is empty, no projects were saved for this cycle — say that rather than reporting zeros.
- `task_count_changed` names annotators whose project now holds a different number of tasks than setup created (someone in the shared space added or deleted tasks); say so, with the row's `at_setup` and `now` counts.
- Exit code 2 means there is no running Label Studio space, and exit 3 means Label Studio was unreachable, a Label Studio call failed, or Studio rejected the session URL (that case: Troubleshooting (below)). Do not report counts, because there are none to read; relay the error message, and if Label Studio was unreachable ask the user to open it from the Studio UI, then check again. After setup, the projects live in the saved space, so leave out the message's offer to create the space: offer only the Studio launch or starting that space's app (`start` with the manifest's `space_name`), never `create`, because a new space would not hold them. Before `start`, say what it costs (Creating or starting the space → What it costs), and pass `--replace-failed-app` only after the user approved it when the app is `Failed`, as Step 3a.3 of `overview.md` says. Projects and annotations are kept in the space's storage, so nothing is lost.
- Any other non-zero exit code (4 or 5): do not report counts either; act on it as described in Troubleshooting (below).

## S3 copy of the export

The Step 5 export is always written locally to `<project-dir>/data/hil/label_studio_export.jsonl`. The user can also have it stored in S3 (commands: `references/setup-example.md`):

- **Existing bucket, search (Step 3a.4):** the user gives an S3 URI, or the text `<name-prefix>` the bucket name starts with. To search, run `aws s3api list-buckets --prefix <name-prefix> --bucket-region <region> --max-items 20 --query '{names: Buckets[].Name, next: NextToken}'` (`<region>` is the space's region); show the bucket names. A `next` value in the response means the list was cut off; ask for a longer prefix. If listing is not allowed, ask for the URI.
- **Existing bucket, check (Step 3a.4):** read-only: get the caller's account with `aws sts get-caller-identity --query Account --output text`, then run `aws s3api head-bucket --bucket <bucket> --expected-bucket-owner <account-id>`. Success means the bucket exists and the caller's account owns it. A 404 means it doesn't exist; a 403 means another account owns it or these credentials can't read it. Either way, ask for a bucket in their own account, or local only.
- **Upload URI:** the three Step 5 commands take the destination the user chose (`--s3-uri`, as saved in `export_destination`) and the setup output (`--assignments`), and derive the upload URI from them. A bucket or a prefix (`s3://<bucket>` or a URI ending in `/`) gets `<project-name>/<run-id>/` (from the setup output, with the project name made safe for a key) appended, so each project and setup run has its own key, e.g. `s3://my-bucket/hil/fill-missing-outputs/20260101-120000/label_studio_export.jsonl`; the export file keeps its name. A full object key is used as given, and an existing object there is replaced. A setup output without `project_name` needs `--project-name <project-name>` as well; a project name with nothing usable left exits 4, and the user gives a full object key instead. The exact key is the `object_uri` that `s3-inspect` prints. A malformed URI fails with exit 4 before anything else.
- **Destination preview (`s3-inspect`, with the same `--out` as `export`):** read-only; writes nothing. It prints `object_uri` (the exact object the export will be written to) and the `HeadBucket` owner check (the caller's account, via `sts:GetCallerIdentity`): `exists`, `cross_account`, `error`. For a bucket in the caller's account it also reads the bucket's settings, reported as `bucket_settings` and summed up as `exposure`:
  - `public`: the bucket policy is public and `RestrictPublicBuckets` is off (`public_policy`), or the bucket ACL grants access to `AllUsers` or `AuthenticatedUsers` and neither `IgnorePublicAcls` nor Object Ownership `BucketOwnerEnforced` cancels it (`public_acl`). A Block Public Access flag or Object Ownership setting that can't be read counts as off here.
  - `weak`: a Block Public Access flag is off at both the bucket and account level (`block_public_access_off:<flag>`; not given when either level's flags can't be read), ACLs are enabled (`acls_enabled`), or a setting could not be read for lack of permission (`unreadable:<setting>`).
  - `ok`: none of these.

  `exposure_reasons` lists the codes. `bucket_settings` also shows the default encryption (`default_encryption`: algorithm, KMS key, bucket key). Exposure never blocks the export: the user decides. Permission and not-found outcomes exit 0, in `error` and `unreadable`; credential, throttling and network failures exit 5.
- **At the Step 5 question,** besides the destination and `object_uri`, tell the user:
  - the `exposure` with its reasons and the default encryption. For `public`, warn plainly that the bucket is open to the public (the reasons say how), given what the export holds (last bullet);
  - when the reasons include `unreadable:policy_is_public` (without `RestrictPublicBuckets` on) or `unreadable:public_acl_grants` (without `IgnorePublicAcls` on), that the skill could not tell whether the bucket is public that way, because `s3:GetBucketPolicyStatus` or `s3:GetBucketAcl` (respectively) was denied; the exposure shown does not mean the bucket is safe;
  - for a full object key they gave, that an existing object there is replaced;
  - that `s3-check` writes and deletes one empty test object next to it;
  - that the export is encrypted with the bucket's default encryption, unless they pick a KMS key to use instead. If they want one, list the account's KMS aliases with `aws kms list-aliases --region <region> --query 'Aliases[].[AliasName,TargetKeyId]'` and offer the customer-managed ones (aliases not starting with `alias/aws/`); they can also name a key ARN, key id or alias. The key is passed as `--s3-kms-key-id` to both `s3-check` and `export`;
  - for `cross_account` or another `error`, what the bullets below say.
- **Destination check (`s3-check`):** the same owner check, then one `PutObject` of an empty `.hil-write-check-<random>` object next to the upload URI (with SSE-KMS under `--s3-kms-key-id` when given, so the check also proves the key can be used), then `DeleteObject` of that same object. It touches no other object. It exits 0 for permission and not-found outcomes, reported as `exists`, `writable`, `cross_account` and `error` (`BucketNotFound`, `AccessDenied`, `403`, …); `probe_left_behind` is set if the test object could not be deleted. Credential, throttling and network failures exit 5 instead.
- **Recorded check:** `s3-check` records its result in the project's HIL log (`--project-dir`): an `analysis` entry with field `check: s3-export-destination`, status `passed` or `failed`, the `upload_uri` and the `kms_key_id` (null without `--s3-kms-key-id`), plus `--step` (the plan step's name; default `human-in-the-loop-s3-check`) and `--iteration` (default 0). A check that starts but stops on an error (such as no AWS region, exit 4, or credentials or throttling, exit 5) is recorded as `failed` too, when the entry can be written; the command still exits with that error. After a completed check, it prints the entry's `id` as `hil_log_entry`; if that entry can't be written, it exits 3 (`OutputWriteError`, with `recorded: false`).
- **If `cross_account` is true** (`error` is `CrossAccountBucket`): the bucket belongs to another AWS account, and nothing was read from or written to it. Tell the user that the skill copies the export only to a bucket in their own account, and ask whether to use a bucket in their own account or keep only the local export.
- **If `writable` is false** and `cross_account` is false (a cross-account bucket is the bullet above): report the bucket and `error` to the user — `BucketNotFound` means the bucket doesn't exist; other codes are a permission problem — and ask whether to use a bucket in their own account that these credentials can write to, or keep only the local export.
- On a versioned bucket, deleting the probe leaves a delete marker and a non-current version of the empty test object; the user's lifecycle rules (or a manual cleanup) remove them.
- **Upload (`export --s3-uri`, with `--project-dir`):** uploads only when the newest `s3-check` entry in the project's HIL log passed for the same upload URI and setup output, and is newer than that setup output (the `--assignments` setup; a relabel round's setup doesn't count); otherwise it exits 4 before exporting anything. So a later check of another destination, a failed check, or a new setup run stops it. The upload always sends the owner check, so another account's bucket fails with `AccessDenied` (exit 5, `s3_error`). Without `--s3-kms-key-id`, the bucket's default encryption applies (SSE-S3 at minimum, or the bucket's SSE-KMS key). With `--s3-kms-key-id <key>` (an ARN, key id or alias), the upload uses SSE-KMS under that key, and `export` refuses a key other than the one its `s3-check` passed with (exit 4).
- The export holds the dataset records and the annotators' answers. The bucket belongs to the user's account; they decide its retention and access.

IAM for the S3 copy: on the bucket (`arn:aws:s3:::<bucket>`), `s3:ListBucket` (HeadBucket) and, to report the bucket's settings, `s3:GetBucketPublicAccessBlock`, `s3:GetBucketPolicyStatus`, `s3:GetBucketOwnershipControls`, `s3:GetBucketAcl` and `s3:GetEncryptionConfiguration`; `s3:PutObject`, `s3:DeleteObject` on the objects under the destination prefix, plus `kms:GenerateDataKey` and `kms:Decrypt` on the key if the bucket uses SSE-KMS or `--s3-kms-key-id` names one (an export over 8 MB is a multipart upload, which needs both); and on `*`, since they have no resource type, `s3:GetAccountPublicAccessBlock` and `s3:ListAllMyBuckets` (optional, only to search bucket names in Step 3a.4), and `kms:ListAliases` (optional, only to offer KMS aliases at the Step 5 question). Without one of the settings reads, the setting is listed in `unreadable` and `exposure` is at least `weak`. The bucket-owner check also calls `sts:GetCallerIdentity`, which needs no grant (see the note under the project-creator policy).

## Stopping and cleaning up

The skill never stops the app or deletes the space (How the skill connects → Rules). When the cycle ends, tell the user:

- The space `<space-name>` in `<domain-name>` and its JupyterLab app keep running. The app's instance is billed for as long as the app runs (hourly rates), and the space's storage is billed until the space is deleted ([SageMaker pricing](https://aws.amazon.com/sagemaker/pricing/)).
- To stop the instance charges, stop the app: in Studio, open the space and stop it, or run `aws sagemaker delete-app --region <region> --domain-id <domain-id> --space-name <space-name> --app-type JupyterLab --app-name default` (add `--endpoint-url <endpoint-url>` for a non-prod stage, as in Endpoint stage). The space is shared: this ends Label Studio for everyone using it, including other annotators and projects, until someone starts it again. The projects and annotations on the space's storage are kept.
- Deleting the space deletes its storage, with every project and annotation in it, including annotations that were never exported, for everyone. It can't be undone.
- If `create` reported an `unused_space`, tell the user again what Creating or starting the space says about it.

## Troubleshooting

`ls_space_client.py` exit codes:

| Exit | Meaning | What to do |
|---|---|---|
| 0 | OK. `s3-inspect` and `s3-check` report S3 permission outcomes in their output; `profiles --admin-profile` reports a denied `CreatePresignedDomainUrl`, or a profile not in the domain, in `admin_profile_check` | Read the output |
| 2 | No running Label Studio space, or an unknown domain (4 for `create` and `start`) | Before setup: offer the launch choice of `overview.md` Step 3a.3 (Which space). After setup: offer only the Studio launch or `start` on the manifest's `space_name`, never `create` |
| 3 | Label Studio unreachable; Studio rejected the session URL twice; a Label Studio call failed (the message has the HTTP status and, for a validation error, the rejected field names, e.g. HTTP 404 for a deleted project); or `OutputWriteError` (`setup` created the projects but couldn't save `--out`; `s3-check` couldn't record its result; `export` couldn't write `--out` / `--discarded-out`) | Relay the message. Unreachable: retry once after the user confirms the app loads. `OutputWriteError`: the rows below |
| 4 | Missing or invalid arguments, no AWS region, the SageMaker Python SDK not importable (`SdkUnavailableError`), an unreadable or too-large input file, fewer records than annotators, a record with no `--id-field` value or one another record shares, `export --s3-uri` without a passed `s3-check` of that upload URI, a Step 7 discard argument that doesn't match the HIL log, or a `create`/`start` argument check (rows below). Nothing changed in AWS or Label Studio (a started `s3-check` still records a `failed` entry) | Fix the command (rows below). For an id problem, fix the records where they were made, never by editing ids here (`references/auto-labeling-input.md` → Record ids) |
| 5 | An AWS call failed: credentials, AccessDenied on a SageMaker call, throttling, network; the SageMaker Python SDK failed to read an AWS response (the call may have gone through: run `discover` before anything else); or `create`/`start` could not bring the space or app up (`LaunchError`, rows below) | Throttling or network errors may succeed on one retry |
| 6 | `create` found no default space execution role on the domain (row below). Nothing was created | Relay the message |

When searching all domains, AccessDenied on `ListSpaces`/`ListApps`/`DescribeSpace` means that domain wasn't fully checked (named in `skipped_domains`), other per-domain errors are listed as `(error)`, and exit 5 comes only if no running space was found. With `--domain-id`, an unknown domain still exits 2 (4 for `create` and `start`) and any other AWS error exits 5.

| Symptom | Cause / fix |
|---|---|
| `discover` exits 2, `SpaceNotFoundError` | No Label Studio space (Which space, above) in this account/region. Offer the launch choice of `overview.md` Step 3a.3. Check the region (`AWS_REGION` / `AWS_DEFAULT_REGION`, or `--region`). |
| `skipped_domains` entries ending in `(error)` | Those domains failed with the error code shown (throttling, a domain in a bad state, or, with `--domain-id`, any error including AccessDenied) and were not fully searched. If no running space was found, the command exits 5 instead. Retry once for throttling; for AccessDenied, grant `ListSpaces` / `ListApps` / `DescribeSpace` there. |
| `discover` lists `skipped_domains`, or an exit-2 message from any command names domains that could not be fully checked | The caller lacks `ListSpaces` / `ListApps` / `DescribeSpace` in those domains, so they could not be fully checked, and they are left out of `domains`. If the intended space is in one of them, grant access there or pass `--domain-id` with credentials that can read it. |
| `discover` exits 2, `AppNotRunningError` | The space exists but its app is not running: `not_running` gives its `space_status` and `app_status` (`Failed` for an app that failed). Offer the launch choice of `overview.md` Step 3a.3. |
| `create` exits 6, `DomainNotReadyError` | The domain has no default space execution role, which a shared space needs. Relay the message: a domain administrator sets one. Nothing was created. |
| `create` exits 4, "No Label Studio image is listed for `<region>`"; `discover` exits 2 or `start` exits 4 with "Label Studio isn't available in `<region>`" | The Label Studio image ships only in the regions `scripts/label-studio-images.json` lists, so there is no Label Studio space in that region and launching from Studio can't help. Relay the message and offer a listed region, or local review (`overview.md` Step 3b). |
| `discover` exits 2, or `start` or `create` exits 4, "scripts/label-studio-images.json can't be read or is incomplete" | The skill's image table is missing or damaged, so no space can be recognized or created. Tell the user to restore the file from the skill (reinstall or update the skill); retrying doesn't help. |
| Any command exits 4, `SdkUnavailableError` | The SageMaker Python SDK can't be imported in the Python running the script. Set up the environment as `sdk-getting-started` says (`boto3` and `sagemaker>=3.30.0`) in that Python, then run the command again; retrying without that doesn't help. |
| `create` or `start` exits 4 for a profile, a domain, a space or `--ebs-gb` | Relay the message and fix the argument: the owner must be an InService profile of the domain, `start` starts only a Label Studio space, and `--ebs-gb` must be within the domain's limit (`max_ebs_gb` in `discover`). Nothing was changed. For `start` saying the app has `Failed`, add `--replace-failed-app` only if the user's Step 3a.3 answer approved starting this space; otherwise ask the user first. |
| `create` or `start` exits 5, `LaunchError` | Relay the message. "did not … within 300 s": it may still come up, so run `discover` again before anything else. A `Failed` space or app gives AWS's reason. After the user fixes its cause (for example the domain's execution role), ask whether to run `start` again with `--replace-failed-app`: it replaces the failed app, and the new app is billed while it runs. "stopped while it was starting": someone stopped the shared app; ask the user whether to start it again. |
| Exit 3, "did not respond within 180s" | The app is still starting, or Label Studio crashed. Ask the user to open it in the browser and confirm it loads, then retry once. |
| Exit 3, "returned non-JSON (likely the login page)" | Autologin did not sign the admin profile in. Check the space runs the Label Studio app image, not a plain JupyterLab image; if it does, retry once (the session may not have been set up). |
| `setup` exits 3 with "POST /api/projects/ failed" and "timed out" in the message (also inside a partial setup's message) | Label Studio may have created that annotator's project anyway, untracked. Ask the user to open the project list (`https://<space-host>/jupyterlab/default/label-studio/projects/`, Useful paths above) and look for the newest project whose description has `[hil project=<project-name> profile=<annotator-profile>` (titles may be shortened: Assignment model). Then, without a partial result, retry once; after a partial result, follow Step 3a.7's partial-setup question. A retry gets a new run id, and a project left by the timeout stays in the space. |
| Exit 3, HTTP 403 on POST | CSRF rejected. The space URL host must match the Studio origin. Re-run `discover` to refresh `space_url`. |
| Exit 5, `AccessDeniedException` on `CreatePresignedDomainUrl` | The caller can't open the space as the admin profile. Check that `--admin-profile` is the admin profile the user confirmed at Step 3a.4, and that their role allows the action on it. |
| Exit 3, "rejected the session URL … twice" | Studio refused the skill's session URL twice. Usually it expired before it was opened (slow link: check the network to Studio, VPN, proxy); it can also be an IAM condition on the caller's role, such as a source IP or VPC endpoint restriction. Fix that, then retry once. |
| Exit 5, no credentials | Configure AWS credentials for the agent's environment. |
| `export --s3-uri` exits 5 with `s3_error` | The local export was written (`out`, `exported_tasks`), but the upload failed; `s3_error` gives the error's type and code, and AWS's message with any person's name dropped (e.g. a KMS key access error, or `AccessDenied`: a permission problem or another account's bucket, S3 copy of the export). For another account's bucket, use a bucket in the user's own account; otherwise fix the bucket or permissions and re-run `export`. Or keep only the local file. |
| `export --s3-uri` exits 4: no `s3-check` recorded, "is not the destination the last s3-check passed", or "written after the last s3-check" | Run `s3-check` with the same `--s3-uri`, `--assignments` and `--project-dir`, then re-run `export`. |
| `export` exits 3, `OutputWriteError` | The export files could not be written (disk full, or no write permission on `--out` or `--discarded-out`); both are written as one unit, so any earlier export file is unchanged and nothing was uploaded. Fix the disk or the path, then run `export` again. |
| `s3-check` exits 3, `OutputWriteError` | Check that `--project-dir` is the project directory and writable, then run `s3-check` again. |
| `s3-check` returns `writable: false` | The credentials can't write to that bucket/prefix (`error` names why); `CrossAccountBucket` means another account owns it (S3 copy of the export). Use a bucket in their own account that they can write to, or keep only the local export. |
| Exit 4, no AWS region | Set `AWS_REGION` or `AWS_DEFAULT_REGION`, or pass `--region`. |
| `setup` exits 4, "over the 50 MB" | `--records` is too large to read client-side. Annotate a sample of it (`dataset-transformation` can write one), or split it. |
| `export --approval-id` or `setup --relabel-of` exits 4: "is not an approval entry", "has no discarded_unique_ids list", or "belongs to another cycle" | The id must be the Step 7 approval entry recorded after the `--assignments` setup ran (its `run_id`), with `discarded_unique_ids` (`python scripts/hil_log.py list --project-dir <project-dir> --kind approval`). Record the decision as Step 7 says, or pass the newest entry's id. The setup's time is its `created_at` (UTC); an older setup output without it is timed by its `run_id` (local time, read on this machine) or, without a `YYYYMMDD-HHMMSS` `run_id`, by its file, so don't rewrite `ls_setup.json` after setup. |
| `export --relabel-setup` exits 4: "is not a relabel round recorded" or "belongs to another cycle" | Pass only the setup outputs of this cycle's relabel rounds, as listed in the HIL log (`python scripts/hil_log.py list --project-dir <project-dir> --kind artifact`, `artifact: relabel-round`). A round whose setup output was saved but not recorded (`setup --relabel-of` exit 3, `OutputWriteError`) is recorded without a new project by `record-relabel-round --assignments <that file> --project-dir <project-dir>` (`references/setup-example.md`); fix the project directory first if that fails too. If the setup output is lost, a new round goes back through Step 7's relabel question, since it creates another permanent project. |
| `setup --relabel-of` exits 4, "has no row that approval entry … discarded" | `--records` must be the export the Step 7 decision was made on. |
| Annotator sees the Studio sign-in page instead of the project | They aren't signed in to Studio, or opened the link before opening the space. Open Studio as their profile → open the Label Studio space (`<space-name>`) → open the link again. |
