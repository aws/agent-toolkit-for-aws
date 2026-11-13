# AWS Continuum plugin

The AWS Continuum plugin helps a coding agent set up Continuum for a repository, explain the application's security state, and prepare fixes for confirmed issues. It shows how issues connect to the parts of the application and groups related fixes for review. The developer stays in control of every AWS change and every pull request.

## Install

You need AWS CLI 2.38.5 or newer, Git, and Node.js 20 or newer. Configure an AWS CLI profile with valid credentials and permission to use AWS Continuum before setup.

Version 1.0.0 is tested on Claude Code and Codex. See [Known limits](#known-limits) for other clients.

### Claude Code

```text
/plugin marketplace add aws/agent-toolkit-for-aws
/plugin install aws-continuum@agent-toolkit-for-aws
/reload-plugins
```

### Codex

In your terminal:

```text
codex plugin marketplace add aws/agent-toolkit-for-aws
```

Then launch Codex, run `/plugins`, and install **aws-continuum** from the `agent-toolkit-for-aws` marketplace.

### Cursor

Open **Settings → Plugins → Team Marketplaces → Add Marketplace → Import from Repo**, enter `aws/agent-toolkit-for-aws`, then install **aws-continuum** from the Plugins panel.

### Devin

```text
devin plugins install aws/agent-toolkit-for-aws#plugins/aws-continuum
```

This adds the plugin to your personal plugins. Add `--local` to install it only on this machine.

## Use it

Ask in ordinary language or use the matching command:

- Say **“Set up Continuum for this repo”** or run `/aws-continuum:setup`.
- Say **“Where do we stand?”** or run `/aws-continuum:status`.
- Say **“Fix the issues”** or run `/aws-continuum:fix`.

The plugin uses skills, native `aws continuum` commands, and the repository's own checks. It runs no MCP server. Status writes `.continuum/reports/security-report.md` as self-contained GitHub-flavoured Markdown. A small offline source checker repeats multi-location code-presence checks, and a setup script generates the integration role's random external ID and trust policy. These scripts do not acquire AWS data or execute application code. A fresh install needs no `npm install`, and Docker is not required by the plugin.

## What it will and won't do

- It shows every AWS change and waits for your approval before making it.
- It never merges code.
- It creates pull requests only when you ask, and it creates drafts only.
- It uses only public AWS APIs under the shared safety prelude: STS and scope disclosure for reads, intended-tenant signer matching and exact consent for writes.
- It starts no scan beyond the automatic first scan created with a new environment.
- It can use a host-supported background agent to wait for work; it does not create a watcher or notification service.

Read the detailed [safety rules](SAFETY.md) before using the plugin with an AWS account.

## Known limits

- Version 1.0.0 is tested on Claude Code and Codex. The Cursor and Devin manifests are included but not yet tested. Kiro, fx and `aws configure agent-toolkit` install skills from this repository's top-level `skills/` folder rather than plugins, so this plugin is not available there yet.
- Native reads, quota checks, report checks and plan safeguards are skill instructions, not enforcement by a local service. Confirm the actual commands and recorded evidence.
- Combined testing uses repository-owned checks. The plugin provides no execution isolation; rely only on isolation the target repository's reviewed harness proves.
- In Codex, a finished background scan does not wake the conversation. Ask **“did the scan finish?”** to receive its result.
- An environment supports at most [10 repositories across all integrations](https://docs.aws.amazon.com/continuum/latest/userguide/quotas.html), unless AWS has granted your account a higher quota.
- Public documentation does not specify a repository ZIP-size limit. The plugin measures ZIP sizes and reports the uncertainty before upload.
- The plugin has no cost meter. Review the proposed resources and scanning cadence before approving setup.
