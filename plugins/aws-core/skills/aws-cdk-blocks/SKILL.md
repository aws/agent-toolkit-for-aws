---
name: aws-cdk-blocks
description: Guides building or extending apps with AWS CDK Blocks (formerly AWS Blocks), an Infrastructure-from-Code framework on CDK. Each Block packages an application capability with its infrastructure, the app code that connects to it, and a local implementation, deployed into the developer's own AWS account. Triggers when the user mentions CDK Blocks, AWS Blocks, or the aws-cdk-blocks, @aws-cdk-blocks or @aws-blocks packages, or adding capabilities such as agents, sign-in, a database, background jobs or file uploads to an app using CDK. Does not apply to requests that name neither Blocks nor CDK. Covers starter templates, composing Blocks into app code (KVStore, Agents, Email, Database, Auth, Realtime, AsyncJob, FileBucket, etc.), running locally, deploying to AWS, Swift, Kotlin and Dart clients, and custom Blocks.
metadata:
  version: "1"
---

# AWS CDK Blocks

## Overview

AWS CDK Blocks (formerly AWS Blocks) is an open-source TypeScript framework that extends the AWS CDK. A Block is an npm package for one application capability, such as a data store, sign-in, file storage, realtime channels, background and scheduled jobs, email or an AI agent. It holds the CDK construct for the infrastructure, the code the app calls, and a local implementation. An app's backend is one `cdk-blocks/` folder. It runs on the developer's machine without an AWS account, and the same code deploys to the developer's own AWS account as CloudFormation stacks.

CDK Blocks fits a TypeScript web app, API or mobile backend whose infrastructure should be CDK code in the developer's account. This skill covers the start of a project. Inside an app that already uses CDK Blocks, the app's own `AGENTS.md` and docs task describe the installed version and take precedence over this skill.

Local development needs no AWS credentials. Deploying does: the AWS MCP server is recommended for AWS API calls (sandboxed execution and audit logging) but is not required; every step here runs with npm and the AWS CLI.

## Guardrail — where this skill's own files live (MCP vs local install)

This skill ships only documents (`references/*.md`), no scripts. It can be loaded two ways, and they resolve those files from different places:

- **Loaded through the AWS MCP `retrieve_skill` tool:** The skill is not installed on the local filesystem. You MUST fetch each reference via `retrieve_skill` with the `file` parameter (for example `file="references/existing-project.md"`). Do NOT `file_read` these paths locally: they do not exist on disk.
- **Installed locally** (for example `.kiro/skills/aws-cdk-blocks/` or `~/.claude/skills/aws-cdk-blocks/`): Read the references from the local skill directory using relative paths.

This distinction applies only to the skill's own packaged files. User data and session artifacts are always read from and written to the user's working directory. Never fetch or write customer data through `retrieve_skill`.

## Where to start

Take the first row that matches the request or the project.

| The request or the project | Go to |
|---|---|
| A deploy to AWS | [references/deploying.md](references/deploying.md) |
| A production launch or a security review | [references/security.md](references/security.md) |
| An iOS, Android, desktop or Flutter client for the backend | [references/native-clients.md](references/native-clients.md) |
| An AWS service that no Block covers, or a Block a team wants to own | [references/custom-block.md](references/custom-block.md) |
| The project has a `cdk-blocks/` folder | [Work in an existing app](#work-in-an-existing-app). Never scaffold again. |
| The project is an AWS CDK app with its own stacks (`cdk.json`, `cdk deploy`) | [references/existing-cdk-app.md](references/existing-cdk-app.md) |
| The project has a `package.json` and no CDK Blocks: Vite, Next.js, an Express API, Amplify Gen 2 | [references/existing-project.md](references/existing-project.md) |
| An empty directory, or a request for a new app | [Create an app](#create-an-app) |

Apps created before the rename have an `aws-blocks/` folder and `@aws-blocks/*` packages: treat them as existing apps and keep their names, or move them with [references/migrating-from-aws-blocks.md](references/migrating-from-aws-blocks.md) when the user asks.

## Create an app

1. Choose a template. A template sets the starting frontend and sample code only: every Block can be added to every template later, for example the `Database` Block in a `nextjs` app that needs PostgreSQL.

   | The user wants | `--template` |
   |---|---|
   | Their own features on a web frontend. The smallest app: Vite and one `greet()` API method | `bare` |
   | A React frontend: a todo app with sign-in, a data store and realtime | `react` |
   | A Next.js App Router app whose Server and Client Components call the backend | `nextjs` |
   | A backend with no frontend and one API method | `backend` |
   | A backend for mobile, CLI or third-party clients: a public health check and sign-in-gated CRUD | `api-only` |
   | A PostgreSQL backend with migrations, foreign keys and transactions | `sql` |
   | A tour of sign-in: email sign-up with a code, groups, a profile | `auth` |
   | OpenID Connect sign-in, with a stub identity provider for local runs | `auth-oidc` |
   | An AI agent with a tool, and a canned model for local runs | `agent` |
   | Scheduled jobs, no frontend | `cron` |
   | Logs, metrics, traces and a dashboard, no frontend | `observability` |
   | A larger sample: sign-in and a priority-sorted todo list | `demo` |
   | No preference: Vite with sign-in, a data store and realtime | `default` |

   The scaffolder prints the templates of the installed version:

   ```bash
   npx --yes @aws-cdk-blocks/create-blocks-app --help
   ```

2. Scaffold. The command never prompts for a new app:

   ```bash
   npx --yes @aws-cdk-blocks/create-blocks-app <directory> --template <template>
   ```

   - Always pass a directory. `.` works when the current directory holds nothing but `.git` and editor settings.
   - The command installs dependencies. After `Installing dependencies...` it can run for minutes with little output. Wait for it to exit with status 0; it ends with `✓ AWS CDK Blocks app created!`. Start no app task before that.
   - On `Error: Target directory is not empty and no package.json found.` choose another directory. Do not delete the files it lists.
   - `npm create @aws-cdk-blocks/blocks-app@latest <directory>` runs the same scaffolder, but `npm create` passes flags to it only after `--`: `-- --template <template>`.

3. Read `AGENTS.md` at the app root from start to end before writing code. It is long: read the whole file, not a preview. Then read `package.json`, `cdk-blocks/index.ts` (the backend) and `test/e2e.test.ts`.

4. Check the app from its root with `npm run test:e2e` and `npm run build`. The test starts a local server when none runs and stops the one it started.

## Work in an existing app

- Follow the app's `AGENTS.md`. An app that got CDK Blocks through the existing-project path has none: read `npm run -s docs guide -- --output text` instead.
- Look up a Block before writing code that uses it. Positional arguments follow the task; flags follow `--`:

  ```bash
  npm run -s docs -- --output text                           # every Block, one line each
  npm run -s docs KVStore Auth -- --output text              # the docs of one or more Blocks
  npm run -s docs KVStore -- --section local --output text   # one topic of a Block's docs
  npm run -s docs:api KVStore -- --output text               # exact signatures
  npm run -s docs:search "partition key" -- --output text    # search
  ```

  Without `--output text` these print JSON when the output is not a terminal. The docs and task output also call a Block a "Building Block".
- `npm run help` lists every task and `npm run help <task>` its flags. When a script name was already taken, the task is named `blocks:<name>`: check `scripts` in `package.json`.
- Store data and reach AWS through Blocks, never through local files or memory.

## Deploy

Deploying creates billable resources in the user's AWS account. Ask the user before a deploy, a destroy, `cdk bootstrap` or an AWS sign-in, then follow [references/deploying.md](references/deploying.md).

## Security considerations

- An API method is public until it requires a session. The local server does not flag a method left public.
- Keep API keys and credentials in the `Secret` Block, never in source, committed `.env` files or plain environment variables.
- Add no `*` IAM policies and do not open buckets to the public: each Block grants least-privilege access to its own resources.
- Never print or log credentials, tokens or secrets. `Logger` does not redact.
- Deploy with short-lived credentials scoped to the app, not an administrator user or long-lived access keys.
- Before the first production deploy, work through [references/security.md](references/security.md).

## Troubleshooting

| Message or symptom | Do |
|---|---|
| `Error: Unknown template` | Use a name from `--help` |
| The scaffolder prints `Proceed? (y/N)` or exits having changed nothing | In an existing project, pass `--yes` after the template |
| `not inside an AWS CDK Blocks app` | Run the task from the folder that holds `package.json` and `cdk-blocks/` |
| `AWS credentials could not be verified` or `CDK is not bootstrapped` | [references/deploying.md](references/deploying.md) |
