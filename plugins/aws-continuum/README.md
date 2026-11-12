# AWS Continuum plugin

## What it does

The AWS Continuum plugin helps a coding agent set up Continuum for a repository, explain the application’s security state, and prepare fixes for confirmed issues. It turns the public Continuum results into a readable view of affected application paths and groups related fixes for review. The developer stays in control of every AWS change and every pull request.

## Quick start

You need AWS CLI 2.38.5 or newer, Git, and Node.js 20 or newer. Before setup, configure an AWS CLI profile with valid credentials and permission to use AWS Continuum and create the AWS resources you approve. You will choose that profile and its Region during setup.

The plugin uses skills, native `aws continuum` commands, and the repository's own checks. It runs no MCP server. A bundled renderer validates Markdown and safely escapes untrusted text into standalone HTML. A small offline source checker repeats multi-location code-presence checks; it performs no acquisition or application execution. A setup script generates the integration role's random external ID and trust policy offline. Node is needed for these local steps; a fresh install needs no `npm install`. Docker is not required by the plugin.

### Prepare the packed marketplace

From the checkout root containing the root README and `package.json` (not this `plugins/aws-continuum` directory), run the following in a Bash shell. Packaging requires Node.js 24 or newer and npm; the installed renderer needs only Node.js 20 or newer. No dependency installation or build is needed to pack the checked-in release payload.

```bash
pack_dir="$(mktemp -d /tmp/aws-continuum-pack.XXXXXX)"
export CONTINUUM_MARKETPLACE="$(mktemp -d /tmp/aws-continuum-marketplace.XXXXXX)"
archive="$(npm pack --ignore-scripts --pack-destination "$pack_dir" --silent)"
tar -xzf "$pack_dir/$archive" -C "$CONTINUUM_MARKETPLACE" --strip-components=1
printf 'Packed marketplace: %s\n' "$CONTINUUM_MARKETPLACE"
```

Keep the extracted marketplace directory: the host may use it for later refreshes. This packed payload is the reviewed release boundary: one bundled renderer, one offline source checker and one offline external-ID generator, with no development inputs. Register the extracted directory, not the archive or the full checkout.

### Codex

In the same shell, install the packed marketplace:

```bash
codex plugin marketplace add "$CONTINUUM_MARKETPLACE"
codex plugin add aws-continuum@continuum-developer-plugin
```

For the in-app route, run `/plugins` in Codex, add a local marketplace using the absolute **Packed marketplace** path printed above, select `continuum-developer-plugin`, and install `aws-continuum`.

### Claude Code

In the same shell, install the packed marketplace:

```bash
claude plugin marketplace add "$CONTINUUM_MARKETPLACE"
claude plugin install aws-continuum@continuum-developer-plugin
```

Then run `/reload-plugins` inside an existing Claude Code session. Alternatively, use `/plugin marketplace add` with the absolute **Packed marketplace** path printed above, followed by `/plugin install aws-continuum@continuum-developer-plugin`. Paste the actual printed path into slash commands; they do not expand shell variables.

### Development-only installs

Registering the full checkout as a marketplace is a development convenience only. It can copy source modules, tests and build inputs that the packed release excludes. Do not use a checkout install to validate or describe the release payload.

Both hosts load the skills without starting a server. A skill resolves the plugin root from its own loaded path; Claude Code can also use `CLAUDE_PLUGIN_ROOT`. Codex's old `PLUGIN_ROOT` substitution was specific to MCP configuration and is not assumed to be a shell variable.

### Use it

You can ask in ordinary language or use the matching command:

- Say **“Set up Continuum for this repo”** or run `/aws-continuum:setup`.
- Say **“Where do we stand?”** or run `/aws-continuum:status`.
- Say **“Fix the issues”** or run `/aws-continuum:fix`.

## What it will and won’t do

- It shows every AWS change and waits for your approval before making it.
- It never merges code.
- It creates pull requests only when you ask, and it creates drafts only.
- It uses only public AWS APIs under the shared safety prelude: STS and scope disclosure for reads, intended-tenant signer matching and exact consent for writes.
- It starts no scan beyond the automatic first scan created with a new environment.
- It can wait for work in the background without blocking you; it does not create a watcher or notification service.

Read the detailed [safety rules](SAFETY.md) before using the plugin with an AWS account.

## Known limits

- The former MCP App widget and its inline decision buttons are removed. Standalone HTML keeps its diagrams, expandable detail, navigation, and first-fix shortcuts; decisions are recorded from chat in a private local JSON plan.
- Native reads, quota checks, and plan secret/concurrency safeguards are now skill instructions, not enforced by a local tool. Confirm the actual commands and recorded evidence.
- Combined testing uses repository-owned checks, not the former locked-down Docker runner. Do not describe its network, credential, or immutable-image isolation as enforced without a repository harness that proves it.

- In Codex, a finished background scan does not wake the conversation. Ask **“did the scan finish?”** to receive its result.
- An environment supports at most [10 repositories across all integrations](https://docs.aws.amazon.com/continuum/latest/userguide/quotas.html), unless AWS has granted your account a higher quota.
- Public documentation does not specify a repository ZIP-size limit. The plugin measures ZIP sizes and reports the uncertainty before upload.
- The plugin has no cost meter. Review the proposed resources and scanning cadence before approving setup.
