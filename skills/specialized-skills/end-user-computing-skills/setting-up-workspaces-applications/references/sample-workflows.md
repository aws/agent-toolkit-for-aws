# Sample workflows (the pre-built demo path)

Use this when the user picks the sample option at question 1b of
[onboarding-flow.md](references/onboarding-flow.md). The sample path stands up a desktop that
already has an application, data, and a scripted workflow, so the user sees an
agent finish real work without describing a workflow of their own.

## Workflows

| # | Workflow | Input files | What the agent proves |
|---|----------|-------------|-----------------------|
| 1 | Create an invoice from a customer purchase order | 1 purchase order, the book | Reads the purchase order from the screen, finds the existing customer, enters each line with the right income account, posts the invoice |
| 2 | Register a new customer from a CRM export | 1 CRM export CSV, 1 ready import file, the book | Imports the customer, then sets the billing term and discount the import cannot carry |
| 3 | Review a refund request and apply a credit | 1 request CSV, the book | Checks the claim against the posted invoice instead of trusting it, applies the refund policy, records the decision |

This skill sets up the desktop and uploads the data files, which ship in its `assets/`. The
`amazon-workspaces-agent-access` skill runs the workflows: it holds their prompts and the GnuCash
steps. Do not ask the user to describe a workflow.

## Talking to the user

- Before each step the user would care about, such as checking their account,
  creating or deleting something, or starting a task on the desktop, write one
  short line saying what you are about to do. Do not announce reading files,
  loading skills or tools, getting credentials, looking up links, single clicks or
  screenshots.
- Where this file gives the exact text to send, that text is the line. Do not add
  another one of your own.
- Anything meant for the user goes in your reply. Text written only in your
  reasoning is never shown to them.
- While the fleet starts, wait for it with one
  `aws appstream wait fleet-started --names <fleet> --region <region>` command,
  which checks every 30 seconds and returns once the fleet is `RUNNING`, instead of
  repeated `describe-fleets` calls. It gives up after 20 minutes. Write a line when it
  returns, and nothing while it waits. If it exits with an error, describe the
  fleet to see why. `RUNNING` alone doesn't mean a session can start, so then check
  `describe-fleets` until `ComputeCapacityStatus.Available` is 1 or more, about 15
  seconds apart. This replaces the 15-second checks and per-check updates in
  rule 3 of SKILL.md and in [create-workspace.md](references/create-workspace.md).
- Number the creation lines to match the plan's five items ("Step 2 of 5: creating
  the fleet and the stack"). Associating the fleet belongs to step 2. Do not number
  the teardown lines.

## Environment shape

Before writing the plan, read
[fleet-stack-recommendations.md](references/fleet-stack-recommendations.md). Every value in
the plan that is not listed below comes from that file. These sample-specific
choices replace its defaults:

- **A public base image.** Nothing is baked into an image, so no image builder
  pass is needed.
- **Fixed names.** Fleet `workspaces-onboarding-sample-fleet`, stack
  `workspaces-onboarding-sample-stack`, screenshot bucket
  `workspaces-onboarding-sample-<account>-<region>`. If the environment already
  names them, use those names instead.
- **`stream.standard.small`, capacity 1 to 5.** Create the fleet with
  `DesiredInstances: 1`, then register the scaling target with `MinCapacity: 1` and
  `MaxCapacity: 5` and no scaling policy. One desktop runs, and the fleet can be
  raised to five later without a new setup.
- **Internet access on.** The setup script downloads the applications at the
  start of every session.
- **Home folders on.** Add `StorageConnectors=[{ConnectorType=HOMEFOLDERS}]` to
  `CreateStack`. This is how the setup script reaches the desktop.
- **Screenshot storage on.** Every screenshot the agent takes is saved to an S3
  bucket in the user's account, so the user can check the agent's work without
  watching the desktop. Create the bucket first, as in "Creating the screenshot
  bucket" below, and add `"S3BucketArn": "arn:aws:s3:::<bucket>",
  "ScreenshotsUploadEnabled": true` to the stack's `AgentAccessConfig`.
- **`DisconnectTimeoutInSeconds` 14400 and `IdleDisconnectTimeoutInSeconds` 3600.**
  Every session starts from a clean profile, so a session that ends means running
  setup again. These keep the desktop for up to 4 hours after the agent's
  connection drops, for example when its runtime times out, so it can reconnect
  and carry on. The session still ends at `MaxUserDurationInSeconds` (4 hours by
  default), counted from when it started. An Always-On fleet bills the same whether or not anyone is
  connected.

## The plan to show

Right after the user picks the sample, send this word for word, then look up the
network and the image:

```
Thanks for confirming. You chose a cloud desktop for an AI agent, with the GnuCash sample. I'm now checking your AWS account for the network and the base image with read-only calls, which takes about a minute.
```

If the request itself already chose the sample, so neither question was asked,
replace the first two sentences with one line saying what you took from the
request, for example "You asked for the GnuCash sample for your AI agent." Don't
say that questions were skipped.

When that is done, check for the sample's fleet and stack as in "Look for an earlier setup" in
[create-workspace.md](references/create-workspace.md). If either exists, follow "Coming back to
a partial setup" there instead of this plan. Otherwise, ask
"Ready to create the sample cloud desktop?" as one multiple-choice question as in
[onboarding-flow.md](references/onboarding-flow.md). Its question text is this plan, filled in,
followed by the question. A plan sent as its own message just before a question can
be shown collapsed, so it goes in the question itself:

```
I checked account <account>. I'll create the sample cloud desktop in <region>, using your default VPC <vpc> and its subnets in <zones>. Here is the plan:

1. Create an S3 bucket named <bucket>, where every screenshot the agent takes is saved, so you can check its work later.
2. Create the cloud desktop, fleet <fleet> and stack <stack>, from the public Windows Server image, with agent access on, so the agent can see and act on the desktop and you can watch it.
3. Upload the setup scripts and the files for the 3 sample workflows to the agent's home folder, which WorkSpaces Applications keeps in an S3 bucket in your account.
4. Start the desktop.
5. On the desktop, install GnuCash and LibreOffice from their publishers' official downloads (unmodified, not hosted by AWS), then open the sample book.

Billing starts when the desktop starts and runs until it is stopped, so stop it when you are done. Pricing: https://aws.amazon.com/workspaces/applications/pricing/

This demo is provided by Amazon Web Services ("AWS") for testing purposes only. AWS makes no warranties, express or implied, and any deliverables will be intended for non-production use only. Any outputs and deliverables will be illustrative and based solely on fictitious information. GnuCash and any associated marks are the property of their respective owners. AWS is not affiliated with, endorsed by, or sponsored by the GnuCash project.

This demo uses GnuCash, licensed under GPL-2.0, downloaded directly from the official GnuCash project at install time into your AWS account; AWS does not distribute, host, or modify GnuCash. License and source: https://www.gnucash.org

Defaults chosen for you:
- Desktop size: <instance type>, 1 desktop kept on all the time, with room for up to 5
- Internet access: on, so the setup script can download the apps
- Time limits: a session lasts up to <hours> hours. If the agent disconnects, the desktop waits <hours> hours for it to come back, and it disconnects the agent after <hours> hour of no activity.
- Agent user name: <user id>
```

Write the time limits in hours, never in seconds. Keep the two notices after the pricing line
word for word, as in "Legal notices" below.

The options are "Yes, create the sample cloud desktop", "Not yet, make changes to
the plan" and "Exit", none marked as recommended. Only the first starts creating anything. An empty reply
or Enter is not a yes.

After a yes, the line that announces the first step, creating the screenshot
bucket, starts with this, filled in, and the step's own words follow it. If the
user changed the plan under "Not yet", add a sentence that names each change:

```
Thanks for confirming. I'm now creating the sample cloud desktop <fleet> and the screenshot bucket <bucket> in account <account>, <region>. This takes about 15 minutes: about 10 for the desktop to start, and about 5 to install the apps.
```

## Legal notices

The sample shows two notices: the demo disclaimer and the GnuCash license notice. Both are in
the plan above. Send them word for word every time the plan is shown, including after a change
under "Not yet", and don't shorten, reword or translate them. When you finish a partial sample
setup instead ("Coming back to a partial setup" in
[create-workspace.md](references/create-workspace.md)), put both notices in that plan the same
way, after the pricing link. The setup script also prints the GnuCash notice on the desktop each
time it runs.

## Creating the screenshot bucket

Do this before `CreateStack`, because the stack names the bucket. Name it as in
"Fixed names" above, which stays within the 63-character bucket name limit in every
Region. Create it and set its policy as in "Creating a new bucket" in
[agent-access-config.md](references/agent-access-config.md). If `aws s3api head-bucket`
shows it already exists in this account from an earlier run, use it as it is.

The service writes each screenshot with the connecting agent's own credentials, so
the agent's role also needs `s3:PutObject` on
`arn:aws:s3:::<bucket>/agentaccess/screenshots/*`.

## Setting up the applications

There is no API that puts a file on a streaming desktop, and typing the script
through the agent loses characters. So the script goes into the user's home
folder in S3 first, and the desktop shows it at session start.

### Step 1: upload the scripts and data (on the user's machine, before the session)

Do this after the stack is created and before starting the fleet, so the files
are in place whenever a session starts.
Home folder contents are listed at session start. A file added to a running
session can take a few minutes to appear. The caller needs
`s3:ListAllMyBuckets`, `s3:ListBucket` and `s3:PutObject` on that bucket.

1. **Find the home folder bucket.** The service creates it when home folders are
   first enabled in the Region. Its name starts with
   `appstream2-36fb080bb8-<region>-<account-id>` and can carry an extra suffix, so
   match on the prefix:

   ```
   aws s3api list-buckets --query "Buckets[?starts_with(Name, 'appstream2-36fb080bb8-<region>-<account-id>')].Name" --output text
   ```

   Expect exactly one name. If none is listed yet, wait a minute and run it again.
   If more than one is listed, stop and ask the user which to use.

2. **Hash the agent's UserId.** The folder is the lowercase hex SHA-256 of the
   exact UserId passed to `CreateStreamingURL`, with no trailing newline:

   ```
   printf '%s' '<user-id>' | shasum -a 256          # macOS (Linux: sha256sum)
   ```

   ```
   [BitConverter]::ToString([Security.Cryptography.SHA256]::Create().ComputeHash([Text.Encoding]::UTF8.GetBytes('<user-id>'))).Replace('-','').ToLower()   # PowerShell
   ```

3. **Rebuild the book.** GnuCash keeps the sample book in a SQLite database, and this skill
   ships it as SQL text so it can be reviewed: `assets/Wendlecote.gnucash.sql`. Turn it into the
   book file in a new folder in the user's working directory, such as `workspaces-sample-data/`.
   This needs Python 3 (`python3`, or `py` on Windows) or the `sqlite3` command. Run the SQL
   only into a file that doesn't exist yet, because it fails over an existing book:

   ```
   python3 -c "import sqlite3; sqlite3.connect('Wendlecote.gnucash').executescript(open('<skill dir>/assets/Wendlecote.gnucash.sql', encoding='utf-8').read())"
   ```

   ```
   sqlite3 Wendlecote.gnucash < <skill dir>/assets/Wendlecote.gnucash.sql
   ```

   Check it holds the sample's 7 customers:

   ```
   python3 -c "import sqlite3; print(sqlite3.connect('Wendlecote.gnucash').execute('select count(*) from customers').fetchone()[0])"
   ```

4. **Upload** each file to the home folder: `aws s3 cp <source> s3://<bucket>/user/custom/<hash>/<home folder path>`,
   once per row. The book goes into every workflow folder, because staging a workflow copies
   its folder's book over the open one, so each workflow starts from the same book.

   | Home folder path | Source in this skill | SHA-256 of the source |
   |------------------|----------------------|-----------------------|
   | `setup-sample.ps1` | `scripts/setup-sample.ps1` | `5ecee8bdb723d2a6800eee374abf3291f853adb1c9aa08cab4082c7e139c4379` |
   | `stage-sample-data.ps1` | `scripts/stage-sample-data.ps1` | `48168148847ff1530483799b5cd8e82028540f189bf95726a74b3716725111ac` |
   | `wf1t-invoice-from-po/sample-po-orrindell-dental-tabular.html` | `assets/sample-po-orrindell-dental-tabular.html` | `698d13d4f21193f77b896be7def234b9fce14edda475b4e275695270e35eea6a` |
   | `wf2t-customer-import/customers-import.csv` | `assets/customers-import.csv` | `dd31bb09f1a174e3e12de2f0858d47670c1ef83d5ee720e1f8c460bd6613d680` |
   | `wf2t-customer-import/sample-customer-export.csv` | `assets/sample-customer-export.csv` | `03957a499c7049d33a69fde24e4fd4b18c8b7bca9b4542b506ef3203484de66b` |
   | `wf3t-refund-request/sample-refund-requests.csv` | `assets/sample-refund-requests.csv` | `5383e98699f7c3c46b68e090b7aef3f730e593724f45d694fdcca94efb2b4f55` |
   | `wf1t-invoice-from-po/Wendlecote.gnucash`, `wf2t-customer-import/Wendlecote.gnucash`, `wf3t-refund-request/Wendlecote.gnucash` | the book rebuilt in step 3 from `assets/Wendlecote.gnucash.sql` | `bc012b4bb9492ab4f7a3c4481e3b5066ac7e73c1a57b846437e9eb1b615eacc1` (of the SQL file) |

   If the skill was loaded through `retrieve_skill`, first write each source file to the
   user's working directory, check its SHA-256 against the table (`shasum -a 256 <file>`,
   `sha256sum` on Linux, `Get-FileHash` in PowerShell), and write it again from a fresh
   `retrieve_skill` call if it differs. Upload only files whose hash matches.

5. **Read it back before starting the session.** `aws s3 ls s3://<bucket>/user/custom/<hash>/ --recursive` must list
   all nine files, with the same byte sizes as the local files. Do not start the session
   until it does.

The home folder persists across sessions, so this is needed once per UserId.
Upload again only when a script or the data changes.

### Step 2: run the sample on the desktop

Once the fleet is `RUNNING` with a desktop available and the read-back matches, load the
`amazon-workspaces-agent-access` skill (through your client's skill tool, or `retrieve_skill`)
and follow its `references/sample-workflows.md` from its Step 1, in the same turn, with the
fleet, stack, UserId and Region from the plan. Read that file before connecting: it says how.
Do not stop to report or ask first: the sample is not set up until the apps are installed on
the desktop. If the Agent Access server is in your own MCP config, it connected before the
fleet was ready and has no desktop tools yet, so reconnect it or ask the user to.

## Removing the sample

When the user asks to delete the sample, or picks "Delete everything" at the end of a run in
the `amazon-workspaces-agent-access` skill, follow the Teardown section of
[create-workspace.md](references/create-workspace.md) with these rules for the sample's
buckets:

- **Describe first.** Read the screenshot bucket from the stack's `AgentAccessConfig`
  (`describe-stacks`) before deleting the stack, and confirm the fleet, the stack and the
  sample's home folder files exist.
- **The screenshot bucket is deleted only when it belongs to the sample alone.** Its name must
  be the sample's fixed name, `workspaces-onboarding-sample-<account>-<region>`, and no other
  stack or image builder in the Region may name it in its `AgentAccessConfig`
  (`describe-stacks`, `describe-image-builders`). If either check fails, keep it and say which.
- **The home folder bucket is never deleted, and neither is its policy.** The service created
  it, and it holds the home folders of every stack in the Region, including stacks deleted
  earlier. Delete only the sample's files:
  `aws s3 rm s3://<bucket>/user/custom/<hash>/ --recursive`.
- **One confirmation, by name.** Ask it as a numbered question with no default. The question
  lists the fleet and its scaling target, the stack, the screenshot bucket and its screenshots
  (or that it's kept, and why), and the sample's folder in the home folder bucket, and says
  that deletion is permanent and the screenshot links stop working. The options are
  "1) Yes, delete these" and "2) No, keep everything".

After the yes, the line that announces the first step starts with this, filled in:

```
Thanks for confirming. I'm now deleting the fleet <fleet>, the stack <stack>, the screenshot bucket and the files the sample uploaded. This takes about 10 minutes.
```

Then, one announced step at a time: `stop-fleet`, one
`aws appstream wait fleet-stopped --names <fleet> --region <region>` (it checks every 30
seconds and gives up after 20 minutes), `disassociate-fleet`,
`aws application-autoscaling deregister-scalable-target --service-namespace appstream --resource-id fleet/<fleet> --scalable-dimension appstream:fleet:DesiredCapacity`,
`delete-fleet`, `delete-stack`, `aws s3 rb s3://<screenshot bucket> --force` if it's on the
list, and the `aws s3 rm` of the sample's files. Describe each resource afterwards, then end
with this, filled in:

```
Done. Everything on the list is deleted, and I checked that none of it is left in account <account>, <region>. Your network and your other fleets and stacks were not changed.
```

## What the setup script does

The applications live under `%LOCALAPPDATA%\SampleApps`, not
`Program Files`, so a workflow must not hard-code the usual install paths. The script's first
line of output is the GnuCash license notice (see "Legal notices").

Why it works the way it does:

- **The streaming user is not an administrator,** and both vendor installers ask
  for elevation. The script unpacks GnuCash from its installer with innoextract
  and LibreOffice with an MSI administrative install (`msiexec /a`), which only
  copy files, into `%LOCALAPPDATA%\SampleApps`.
- **Versions and SHA-256 hashes are pinned.** The GnuCash and LibreOffice hashes
  match the publishers' checksums. innoextract publishes only a GPG signature, so its
  hash is of the file whose signature verified against the publisher's key
  (28555A66D7E1DEC9, listed on constexpr.org/innoextract). Do not switch to "latest": a new LibreOffice
  release can 404 on the download site until its mirrors catch up. When a newer LibreOffice
  ships, the pinned one moves to the publisher's archive with the same hash, and the script
  falls back to it.
- **Downloads are deleted after a successful run**, including innoextract, so
  only the unpacked applications stay on the desktop. A failed run keeps them in
  `%TEMP%\sample-setup` so a rerun picks up where it stopped. A rerun after
  success skips straight to the shortcuts because the applications are found.
- **First-run dialogs are turned off** before either application is opened:
  GnuCash's welcome assistant and tip of the day through its registry-backed
  GSettings, and LibreOffice's welcome page and tip of the day through its user
  profile (`WhatsNew` and `ShowTipOfTheDay` set to false). Its automatic update
  check is off too, so a newer release does not prompt over the pinned version.

Third-party software the script downloads, all from the publishers' official
locations:

| Software | Version | License | Source |
|----------|---------|---------|--------|
| GnuCash | 5.17 | GPL-2.0 | github.com/Gnucash/gnucash releases |
| LibreOffice | 26.8.1 | MPL 2.0 | download.documentfoundation.org, or its archive at downloadarchive.documentfoundation.org once a newer release ships |
| innoextract | 1.9 | zlib | github.com/dscharrer/innoextract releases |
