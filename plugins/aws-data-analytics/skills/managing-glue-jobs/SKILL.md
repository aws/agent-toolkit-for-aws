---
name: managing-glue-jobs
description: "Guides AWS Glue customers through automatic version upgrades (auto upgrade, GlueVersion = auto) for Spark ETL jobs, step by step as the AWS Glue user guide describes: assess jobs, confirm they are safe to retry, turn on auto upgrade, set up email notifications, review the eligibility summary, approve or decline one job, monitor upgraded runs, and read the auto upgrade evaluation summary. Use when the user asks to assess Glue jobs for auto upgrade, turn auto upgrade on or off, proceed with eligible jobs, get auto upgrade emails, see which jobs wait for upgrade approval, approve or decline an upgrade, or find out why an upgrade failed. Not for debugging job runs or editing job scripts."
metadata:
  version: "1"
  service: [glue]
  task: [assess, audit, plan, configure, review, approve]
  persona: [developer, data-engineer, platform-engineer]
  workload: [data-analytics]
---

# AWS Glue auto upgrade

This skill follows [Automatic version upgrades for AWS Glue jobs](https://docs.aws.amazon.com/glue/latest/dg/auto-version-upgrades.html) in the AWS Glue User Guide.

## Journey

Each step names the file to read. **Stop** marks a point where you wait for the user's decision.

| Step | What happens | Read | Stop |
|---|---|---|---|
| 1. Assess | You check which jobs can use auto upgrade. Read-only. | [assess-and-turn-on.md](references/assess-and-turn-on.md) | — |
| 2. Safe to retry | The user confirms that each job is safe to retry, and gives an email address for notifications. | same | **Stop** |
| 3. Notifications | If the user gave an address, you set up the emails first, so no approval email is missed. | [notifications.md](references/notifications.md) | — |
| 4. Turn on | You set `GlueVersion` to `auto` with a full job update. | [assess-and-turn-on.md](references/assess-and-turn-on.md) | — |
| 5. Review | Days later, you show the eligibility summary and what to check. | [approval.md](references/approval.md) | **Stop** |
| 6. Approve or decline | You record the decision for the one job that the user names. | same | — |
| 7. Monitor and results | You report status and the auto upgrade evaluation summary. | same | — |

Steps 1 to 4 can run in one conversation. A job that runs often can reach the approval request within an hour, so set up emails before turning on jobs. Step 5 starts after AWS Glue requests approval. Never approve in the same turn that turns on auto upgrade.

## Tools

The skill uses only the AWS CLI (version 2, with the auto upgrade commands). It ships no scripts. Run each command exactly as the reference file shows it, with `--region <region> --no-cli-pager`. Add `--profile <profile>` when the user names a profile.

The AWS MCP server is recommended for working with AWS, but this skill doesn't require it. Run the commands in this skill with the AWS CLI, because the auto upgrade operations need a current AWS CLI.

Check the CLI once per session. This call makes no AWS request:

```bash
aws glue get-job-upgrade-analysis --generate-cli-skeleton > /dev/null
```

If it fails, reply: "Your AWS CLI version doesn't support auto upgrade. To continue, update the AWS CLI to the latest version."

The assessment uses the `generate_assessment` tool of the `spark-upgrade` MCP server ([assess-and-turn-on.md](references/assess-and-turn-on.md) explains the setup). Permissions for each step are in [permissions.md](references/permissions.md).

## Rules

1. **Change only what the user confirmed.** Before any call that changes something (`update-job`, `create-job`, `start-job-upgrade-analysis`, `create-topic`, `set-topic-attributes`, `put-rule`, `put-targets`, `subscribe`), say what will change. Run it only for jobs and resources that the user confirmed in this conversation.
2. **One named decision per job.** Approve or decline only after you show that job's review, and only when the user names the job and the decision. Never approve in bulk, on a condition, or on a schedule.
3. **No secrets in the chat.** Never repeat job argument values in a reply. Never print, store, or quote a summary link: the links are presigned, work for 1 hour, and are read only inside the one command in [approval.md](references/approval.md).
4. **No IAM changes or installs.** Tell the user what to grant or install.
5. **No scripts.** Write any temporary file inside the one command that uses it, and delete it in the same command.

## How to reply

- **Answer first.** The first sentence states the result.
- **Name the actor.** Each sentence names who acts: AWS Glue or you. Don't use "we" or chatty words.
- **Use the user guide's terms.** Auto upgrade, eligibility summary, auto upgrade evaluation summary, approve, decline, previous version, safe to retry, subsequent job runs. Format `GlueVersion`, `MaxRetries`, and `auto` as code.
- **Keep it short.** Use present tense and active voice, with sentences of about 15 words and never more than 25. Put one sentence before each table or list.
- **No internal details.** Don't show raw status values, analysis IDs, run counts, or service-internal names.
- **Show write modes at approval.** One table row per job with its recorded write mode (`append`, another mode, `Not recorded`, or `overwrite`) and paths. The write mode describes what AWS Glue recorded; it never says a job is safe.
- **One question, at the end.** End with the exact text that the user can enter, in code format.
