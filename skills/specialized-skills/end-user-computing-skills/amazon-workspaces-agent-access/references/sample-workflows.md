# Running the GnuCash sample on the desktop

Use this when the user is trying the WorkSpaces Applications sample: the agent
installs GnuCash and LibreOffice on a sample desktop, then runs three sample
accounting workflows in GnuCash.

Before each step the user would care about, write one short line saying what you
are about to do. Do not write one for reading files, loading skills or tools,
getting credentials, looking up the screenshot link, or a single click, key press,
typed line or screenshot. While a workflow runs, write at most one line per
numbered step of its prompt. Where this file gives the exact text to send, that
text is the line. Anything meant for the user goes in your reply, because text
written only in your reasoning is never shown to them.

## Requires

The sample runs on a desktop that is already set up for it, by the
`setting-up-workspaces-applications` skill's sample path. This file never creates or
deletes AWS resources. The only change it makes to them is stopping the sample's fleet
in Step 5, when the user chooses that.

- **The sample's fleet and stack, and the agent UserId**: the ones the sample was
  set up with, from the conversation or the environment. If you don't know them,
  count them as missing. Do not list the account's fleets or stacks to find them,
  and never pick or suggest one, even one with agent access on, because it may
  belong to other work.
- **The fleet is running**: `RUNNING` with `ComputeCapacityStatus.Available` of 1 or
  more, or 0 when this agent is already attached (see Step 1).
- **The stack**: agent access on, with `COMPUTER_VISION` and `COMPUTER_INPUT`
  enabled.
- **The desktop**: Windows Server 2025.
- **Internet access on the desktop.**
- **Home folder**: enabled, with the sample files in it: the setup and staging
  scripts, and the data in the three workflow folders from the table in Step 3.

Check each value the user gives before it goes into a command: a stack or fleet name
matches `^[a-zA-Z0-9][a-zA-Z0-9_.-]{0,100}$`, and a user ID is 2 to 32 characters of letters,
digits and `_+=,.@-`. Quote each value in the commands. Check with:

```
aws appstream describe-fleets --names "<fleet>" --region <region>
aws appstream describe-stacks --names "<stack>" --region <region>
aws s3 ls s3://<home folder bucket>/user/custom/<sha256 of the UserId>/ --recursive
```

If anything on this list is missing, stop. In one message, in plain words, tell
the user everything the sample needs, every item on this list, and mark which ones
you found and which are missing, so they can set it all up in one pass. If the
fleet, stack or UserId is missing because you don't know them, say that they can
give you the names. Also say that the `setting-up-workspaces-applications` skill sets
up the sample, files included. If they ask for that, load it and follow its sample
path, which comes back here once the desktop is running. Nothing in this file creates
the sample.

## Step 1: connect the agent

If `get_session_info` already returns the sample stack and UserId, the agent is
connected: go to Step 2 and do not create a streaming URL. Otherwise connect as
the sample UserId (connection-setup.md). The desktop tools appear once the
session is attached. If you are the agent and the desktop tools aren't in your tool
list, your MCP client started the Agent Access server before the fleet was ready:
reconnect it, or ask the user to and wait (connection-setup.md, From a coding agent's
MCP config). Don't look for another way in. Before the first desktop action, get the parameters of every
desktop tool you will use, scroll included, because a call made without them
fails. Never write a streaming URL to a file, a log or the chat:
it grants access to the session.

## Step 2: run the setup script

1. Press Win+R, **click the input box** (the dialog can open without focus, and
   typed text is then lost), then press Ctrl+A, not a triple-click (the box keeps
   the last command, and the click unselects it, so new text would be appended).
   Do the same whenever you use the Run box.
2. Type the following as one line and press Enter. It opens PowerShell in the
   home folder and starts the setup script:

   ```
   powershell -NoExit -Command "cd '~\My Files\Home Folder'; .\setup-sample.ps1"
   ```

   If PowerShell says `.\setup-sample.ps1` is not recognized, the home folder has
   not synced yet. Close that window, wait a minute and run the same command from
   the Run box again, for up to 5 minutes.

Typed text arrives at about 20 characters a second after the tool call returns,
so a screenshot taken right after typing can show the line empty or cut short. Take
another screenshot instead of typing again, and retype only after Escape has
cleared the line. Never put a newline in typed text, and type one command at a time. Before
pressing Enter as its own key action, take a screenshot and check that the whole
line is there.
Do not pause with `sleep` or any other timer: the screenshot is the wait, and it
also shows whether the line is complete. The only timed waits are while the
setup script or the staging script runs: 30 seconds between screenshots, every
time. More frequent screenshots only fill the context, and a longer wait only
delays noticing that the script finished. Do not type `$HOME` or
`$PATH`: requests containing them are rejected with HTTP 403. Use `~` for the
profile folder.

The script takes about 5 minutes and ends with a `READY` line per
application and `Setup complete`. While it runs, write a line only when an
application becomes `READY`, not "still unpacking" between screenshots. If it printed `FAILED`, read
`%TEMP%\sample-setup.log` and type `.\setup-sample.ps1` in the same window to
run it again, which picks up where it stopped.

## Step 3: offer the workflows

Some clients return a question with no answer after a few minutes. When that
happens to any question in this file, never choose for the user. End your turn with
one line saying you'll wait for their choice, and continue when they reply.

Ask which workflow to run as one question, with its options numbered one per line and
no default. Don't use the client's option-picker tool. Everything the user reads
before choosing goes in that one message, in this order:

1. The desktop is ready.
2. The command to watch it, with the real values, to run in a new terminal window
   that has AWS credentials for account `<account>`. Give the one for the user's
   operating system, on a line of its own with no backticks, so it copies cleanly.
   It opens the agent's session in the browser and never prints the streaming URL,
   which grants access to the session:

   ```
   open "$(aws appstream create-streaming-url --stack-name "<stack>" --fleet-name "<fleet>" --user-id "<user-id>" --region <region> --validity 60 --query StreamingURL --output text)"
   ```

   On Linux, use `xdg-open` in place of `open`. In PowerShell on Windows:

   ```
   Start-Process (aws appstream create-streaming-url --stack-name "<stack>" --fleet-name "<fleet>" --user-id "<user-id>" --region <region> --validity 60 --query StreamingURL --output text)
   ```

3. This sentence, as written: "It opens the agent's desktop in your browser, where you can watch the agent and stop it at any time. To open the view again later, run the same command again."
4. This sentence, filled in, followed by the screenshot link (see "Screenshot link"): "Every screenshot the agent takes is saved here, including the ones from installing the apps. Open it while signed in to the AWS console for account `<account>`:"
5. "Which workflow should the agent run?"

Do not run the command yourself. Use these labels and descriptions word for word
and add nothing to them, not "(Recommended)" or "(default)" either:

1. "Invoice from a PO": create an invoice from a customer purchase order.
2. "Customer import": register a new customer from a CRM export.
3. "Refund review": review a refund request and apply a credit.

Each workflow's folder in the home folder, the data files in it, and its prompt in
this skill. Every folder also holds a copy of `Wendlecote.gnucash`, the sample's
GnuCash book:

| Label | Folder | Data files | Prompt |
|-------|--------|------------|--------|
| Invoice from a PO | `wf1t-invoice-from-po` | `sample-po-orrindell-dental-tabular.html` | `assets/wf1t-invoice-from-po.md` |
| Customer import | `wf2t-customer-import` | `customers-import.csv`, `sample-customer-export.csv` | `assets/wf2t-customer-import.md` |
| Refund review | `wf3t-refund-request` | `sample-refund-requests.csv` | `assets/wf3t-refund-request.md` |

## Step 4: run the chosen workflow

After each pick, the line that announces the first step starts with this, filled
in with the workflow's description from Step 3, and its time, about 10 minutes
for each:

```
Thanks for confirming. The agent will now <description>, which takes about <minutes> minutes.
```

1. Stage that workflow's files and open the book with one command in the Run box,
   as in Step 2, with `<workflow folder>` being its folder in the home folder:

   ```
   powershell -NoExit -Command "cd '~\My Files\Home Folder'; .\stage-sample-data.ps1 -Source '.\<workflow folder>'"
   ```

   It prints `STAGED` lines, an `OPENED` line for each input file it opens on
   screen (the purchase order in Edge, a CSV in Notepad), and `Book open`, then closes its
   PowerShell window by itself, so GnuCash is in front and the taskbar icons stay
   where gnucash-business.md expects them. If the window stays open, the script
   failed: read the error on screen. To read an input file, switch to the window
   already open with it. Do not launch Edge or PowerShell yourself to read one.
2. Send the workflow's prompt as the task, with
   [gnucash-business.md](references/gnucash-business.md) read first. GnuCash is already open
   with the book. Read everything on the desktop. Apart from the workflow's prompt,
   never open, copy or query the sample's data files outside the desktop, including
   the book: the sample shows the agent doing the work on the desktop. Before creating,
   importing or posting anything, write one line in your reply with what the agent
   found and what it will do, such as the customer it matched and the total. For
   the refund review, that line gives the amount claimed, the amount the agent will
   credit, and why.
3. Offer the next step the same way as the pick. First work out which workflows
   have already run in this session, not only the last one. The options are the
   workflows not run yet, with their labels word for word, then "I'm done": after
   the first workflow the other two, after the second only the one left. After all
   three, skip this question and go to Step 5. The question text starts with the
   result in three to five bullets: what was created or decided, with the amounts,
   and no notes about retries or credentials. Then the screenshot link, saying it
   shows every step the agent took. Do not go to Step 5 until the user picks "I'm
   done" or all three have run.

## Screenshot link

If the stack's `AgentAccessConfig` has `ScreenshotsUploadEnabled` true, every
screenshot the agent takes is saved in the bucket named by its `S3BucketArn`, under
`agentaccess/screenshots/year=<YYYY>/month=<MM>/day=<DD>/<session id>/`, with the
UTC date and the session ID. Read the bucket from `describe-stacks` each time, not
from earlier in the conversation, and the session ID with:

```
aws appstream describe-sessions --stack-name <stack> --fleet-name <fleet> --user-id <user-id> --region <region> --query "Sessions[0].Id" --output text
```

Give that folder as an S3 console link, with each `=` in the path written as `%3D`.
Put the bare URL on a line of its own, with no code fence, backticks or Markdown
link syntax, so it copies cleanly from plain question text:

```
https://<region>.console.aws.amazon.com/s3/buckets/<bucket>?region=<region>&prefix=agentaccess/screenshots/year%3D<YYYY>/month%3D<MM>/day%3D<DD>/<session id>/
```

The user opens it signed in to their own account. Never give a presigned URL,
because it opens the screenshots to anyone who has it. Screenshots taken after
midnight UTC are in the next day's folder. If screenshot storage is off, leave the
link out.

## Step 5: when the user is done

Ask what to do with the fleet as one numbered question, the same way as the workflow
pick. Right after the third workflow, its question text starts with that workflow's
result and the screenshot link, as in Step 4. Then it says the fleet is still running
and billing. Use these labels in this order, word for word and with nothing added,
not "(Recommended)" or "(default)" either:

1. "Stop the fleet": billing for the desktop stops and nothing is deleted. It can be
   started again later. The screenshots and uploaded files stay in S3.
2. "Delete everything": the fleet, the stack, the screenshot bucket if only the sample
   uses it, and the files the sample uploaded.
3. "Keep it running": billing continues until the fleet is stopped.

For "Delete everything", load the `setting-up-workspaces-applications` skill and follow
its sample-workflows.md, "Removing the sample". It checks which buckets belong to the
sample, asks its own confirmation that names each resource, and does the deletes.
Deleting is part of setting up, so nothing in this file deletes resources.

For "Stop the fleet", stop it with `aws appstream stop-fleet --name <fleet> --region <region>`
and wait with one `aws appstream wait fleet-stopped --names <fleet> --region <region>`
command, which checks every 30 seconds and returns once the fleet is `STOPPED`, instead of
repeated `describe-fleets` calls. It gives up after 20 minutes. Write a line when it
returns, and nothing while it waits. If it exits with an error, describe the fleet to see
why.

After the pick, the line that announces the first step starts with the matching text,
filled in. For "Keep it running" it is the whole reply:

```
Thanks for confirming. I'm now stopping the fleet <fleet>. Nothing is deleted, and this takes about 5 minutes.
```

```
Thanks for confirming. The fleet <fleet> keeps running, and billing, until you stop it. To stop it later, ask me to stop the fleet <fleet>, or stop it in the WorkSpaces Applications console in <region>.
```

When the fleet is stopped, end with this, filled in:

```
The fleet <fleet> is stopped, so billing for the desktop has stopped. The stack, the screenshots and the uploaded files are kept. To use the desktop again, ask me to start the fleet. To remove everything, ask me to delete the sample.
```

## Notes

- To resume after the agent's connection dropped, for example when its runtime
  timed out, reconnect with a new streaming URL. The sample fleet has one desktop, and
  the agent's session holds it, so reconnecting with the stack and user ID headers fails
  with `No available capacity on the fleet` (troubleshooting.md). The desktop keeps its apps and
  files for up to 4 hours after the last connection ends, within the session's
  4-hour limit from when it started. If GnuCash is already
  installed, skip to Step 3.
- If desktop tool calls start to hang or time out, check the AWS credentials
  first (`aws sts get-caller-identity`). After renewing them, reconnect to Agent
  Access, because the open connection keeps the old credentials.
- Only one agent can drive a desktop at a time. A connection dropped without a
  clean close blocks a new one with `Another agentic client is already connected`
  until it times out (session-lifecycle.md).
- After a session is expired, wait about 5 minutes before starting a new one for
  the same UserId. A session started sooner came up without its Home Folder in
  testing.
