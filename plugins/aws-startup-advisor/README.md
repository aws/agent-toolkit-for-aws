# aws-startup-advisor

## Overview

This plugin brings [AWS Startups](https://aws.amazon.com/startups/) expertise directly into your coding assistant. Its skills encode the patterns AWS Startup Solutions Architects use with founders every day — stage-aware architecture advice, credit-conscious cost planning, and phased migrations onto AWS — so your agent gives startup-appropriate answers instead of enterprise-sized ones. Currently, skills are provided to assist with the following capability areas:

- **Startup Architecture Advice** — Recommend and review AWS architectures against a company's stage (pre-revenue through Series B+), team size, runway, and available credits, including preparing an architecture for a fundraise or technical diligence.
- **Guided Building** — Run an interactive discovery flow (intent, scope, constraints, preferences), scan what the codebase already implies, then write an AWS architectural scaffold and implementation into the project.
- **AI Agent Runtimes** — Choose a runtime for an agentic workload (Amazon Bedrock AgentCore, Amazon ECS, Amazon EKS, AWS Lambda), plan a migration for agents already running elsewhere, and build an executable proof of concept.
- **Cloud Migration** — Migrate from Microsoft Azure, Google Cloud Platform, or Heroku to AWS through a phased flow: discover, clarify, design, estimate, generate artifacts, and collect feedback.
- **AI Stack Migration** — Rewrite OpenAI, Gemini, or Anthropic API call sites to Amazon Bedrock, evaluate output quality against a golden prompt set, and deliver a ready-to-review git branch.
- **Terraform Quality Gate** — Apply AWS Terraform authoring posture and a security baseline while generating a `terraform/` directory, then run a read-only policy verdict over what was written.
- **Startup Reference Content** — Answer factual questions about AWS Activate, credits, programs, and partner offers, and serve AWS-curated learn articles, sample architectures, and copy-paste prompts for AI coding agents.

## Agent Skills

| # | Skill | Description | Documentation |
| -- | -------------------------- | ------------------------------------------------------------------------------------------------------------------------ | ---------------------------------------------------- |
| 1 | `architect-for-startups` | Stage-aware AWS architecture guidance and reviews tuned to team size, runway, and credits — advice rather than code changes | [SKILL.md](skills/architect-for-startups/SKILL.md) |
| 2 | `start-building-for-startups` | Interactive discovery flow that gathers requirements, scans the codebase, then writes an AWS scaffold and implementation into the project | [SKILL.md](skills/start-building-for-startups/SKILL.md) |
| 3 | `agent-advisor` | Runtime selection, migration planning, and an executable proof of concept for AI-agent workloads on AWS | [SKILL.md](skills/agent-advisor/SKILL.md) |
| 4 | `azure-to-aws` | Seven-phase Microsoft Azure to AWS migration over canonical `Microsoft.*` ARM resource types, with an opt-in generate gate and a what-if repricing workshop | [SKILL.md](skills/azure-to-aws/SKILL.md) |
| 5 | `gcp-to-aws` | Six-phase Google Cloud to AWS migration: discover, clarify, design, estimate, generate artifacts, feedback | [SKILL.md](skills/gcp-to-aws/SKILL.md) |
| 6 | `heroku-to-aws` | Six-phase Heroku to AWS migration with deterministic add-on mapping and an optional what-if repricing workshop | [SKILL.md](skills/heroku-to-aws/SKILL.md) |
| 7 | `llm-to-bedrock` | Rewrite OpenAI, Gemini, or Anthropic API call sites to Amazon Bedrock, evaluate quality, and deliver a git branch | [SKILL.md](skills/llm-to-bedrock/SKILL.md) |
| 8 | `tf-best-practices` | AWS Terraform authoring posture, security-baseline spec, and a read-only policy gate over generated Terraform | [SKILL.md](skills/tf-best-practices/SKILL.md) |
| 9 | `knowledge-base-for-startups` | AWS Activate FAQ, credits guide, programs, partner offers, sample architectures, and AWS-curated learn articles | [SKILL.md](skills/knowledge-base-for-startups/SKILL.md) |
| 10 | `prompt-library-for-startups` | AWS-curated copy-paste prompts for AI coding agents, plus downloadable installable agents | [SKILL.md](skills/prompt-library-for-startups/SKILL.md) |
| 11 | `contextual-offers-for-startups` | Appends at most one relevant AWS Activate partner offer as optional context after another skill's output is final | [SKILL.md](skills/contextual-offers-for-startups/SKILL.md) |

`contextual-offers-for-startups` is consulted by the other skills rather than invoked directly: it runs only after a recommendation, plan, or build is already final, and it never influences the technical advice.

### Bundled Resources

Alongside the skills, the plugin ships supporting material the skills load on demand:

- [`skills/shared/`](skills/shared/) — Canonical reference material shared across skills rather than an invocable skill of its own: the phase-workflow interpreter contract, estimation schemas and complexity tiers, a snapshot of AWS infrastructure rates, phase-status schema, what-if workshop invariants, shared Clarify question fragments, and the AI-migration guardrails and Bedrock model references. Each consuming skill carries a byte-identical copy under its own `references/vendored/` so the skill folder stays self-contained.
- [`agents/`](agents/) — Seven Claude Code subagent definitions: two generic, phase-agnostic migration phase workers (read/write and read/write/shell tiers) plus five specialists for the Bedrock rewrite flow (code analyzer, code rewriter, log ingestor, prompt evaluator, report generator).
- [`scripts/`](scripts/) — Three Python helpers that validate generated artifacts and emit run summaries: a migration report validator, a startup-program artifact check, and a plan summary emitter. The Heroku flow's report validator ships inside `skills/heroku-to-aws/scripts/`.
- [`fixtures/`](fixtures/) — Reference and regression fixtures for the migration report and estimation artifacts, used to keep generated output within the documented contract. `fixtures/azure-iac-terraform/` additionally carries deterministic asserters that pin the Azure Discover, Clarify, Design, and Estimate contracts against a committed synthetic estate.

## MCP Servers

| # | Server | Description |
| - | --------- | ----------------------------------------------------------- |
| 1 | `aws-mcp` | AWS API access, documentation search, regional availability, and skill retrieval via [AWS MCP Server](https://docs.aws.amazon.com/aws-mcp/latest/userguide/what-is-mcp-server.html) |

`aws-mcp` is a single stdio server launched through `uvx mcp-proxy-for-aws-cli@latest`. The skills use it for `aws___search_documentation` and `aws___read_documentation` (current AWS documentation), `aws___get_regional_availability` and `aws___list_regions` (service availability per region), `aws___call_aws` (authenticated AWS API calls), `aws___run_script` (sandboxed Python), and `aws___retrieve_skill` and `aws___recommend` (on-demand guidance). No other MCP server is required.

## Installation

In Claude Code, install from this repository's marketplace:

```
/plugin marketplace add aws/agent-toolkit-for-aws
/plugin install aws-startup-advisor@agent-toolkit-for-aws
/reload-plugins
```

For Codex and Cursor, see [Quick start](../../README.md#quick-start).

For standalone skill installs — Kiro, fx, and other hosts that consume skills directly — point the skills CLI at this plugin. The repository's top-level `skills/` tree does not contain these skills, so the command in Quick start will not install them:

```sh
npx skills add aws/agent-toolkit-for-aws/plugins/aws-startup-advisor/skills --skill '*'
```

Install all 11 skills together rather than a subset: `agent-advisor` delegates to `gcp-to-aws`, and the migration skills share vendored fragments. A standalone install covers the skills only — it does not configure the `aws-mcp` server declared in `.mcp.json`, which the host needs separately.

## Startup Architecture Advice

The `architect-for-startups` skill answers "what should we build on AWS?" the way a Startup Solutions Architect would: it establishes the company's stage, team size, runway, and credit position first, then recommends the smallest architecture that clears the bar, and names what to revisit at the next stage.

### How It Works

- **Stage-aware defaults** — Recommendations differ for a pre-revenue prototype and a Series B workload with paying customers; the skill asks before it assumes.
- **Cost and credit awareness** — Options are framed in terms of run-rate and credit burn, so the architecture stretches AWS Activate credits rather than consuming them in a month.
- **Reviews and diligence** — Existing architectures can be reviewed for a fundraise or technical diligence conversation, with gaps ranked by what an investor or acquirer will ask about.
- **Advice, not edits** — This skill recommends and reviews. When you want the architecture written into the repository, it hands off to `start-building-for-startups`.

### Examples

- "We're pre-seed with two engineers — what should our AWS architecture look like?"
- "Review our architecture before our Series A technical diligence"
- "How do we make our Activate credits last another six months?"
- "Is Aurora Serverless the right call at our stage?"

## Guided Building

The `start-building-for-startups` skill runs a structured discovery flow and then writes code. It gathers intent, scope, constraints, and preferences through picker-based questions, infers what it can from the existing codebase, and produces an AWS architectural scaffold and implementation in the project.

### Examples

- "Help me build the backend for our new app on AWS"
- "Scaffold an AWS project for a multi-tenant SaaS MVP"
- "Expand our existing service to add async processing"
- "Refactor this app onto managed AWS services"

## AI Agent Runtimes

The `agent-advisor` skill is the entry point for agentic work on AWS. It covers runtime selection, migration planning for agents already running elsewhere, and building an executable proof of concept, as one phased flow.

### How It Works

- **Runtime selection** — Compares Amazon Bedrock AgentCore, Amazon ECS, Amazon EKS, and AWS Lambda against the workload's latency, session, tool-calling, and operational requirements.
- **Migration planning** — Plans a move for existing agent workloads, including adding AgentCore capabilities (memory, gateway, identity, policy, observability) to an agent that already runs on AWS.
- **Durable execution** — Covers running Temporal workers on AWS and the Temporal Cloud versus self-hosted decision. Temporal workflow code is not rewritten into another orchestrator.
- **Proof of concept** — Produces a runnable POC rather than a slide-level recommendation.

The skill requires at least one agentic component. Non-agent compute or data migrations route to `azure-to-aws`, `gcp-to-aws`, or `heroku-to-aws`, and a pure LLM SDK rewrite routes to `llm-to-bedrock`.

### Examples

- "Which runtime should I use for my agent — AgentCore, ECS, EKS, or Lambda?"
- "Move our LangGraph agents to AWS"
- "Add memory and a gateway to the agent we already run on ECS"
- "We orchestrate with Temporal — how does that run on AWS?"

## Cloud Migration

The `azure-to-aws`, `gcp-to-aws`, and `heroku-to-aws` skills run the same migration flow: **discover**, **clarify**, **design**, **estimate**, **generate**, and **feedback**. Clarify must finish before design, estimate, or generate, so the plan is never built on unstated assumptions. `azure-to-aws` adds a seventh phase — an optional what-if **workshop** between estimate and generate — and makes generate opt-in behind a post-estimate decision gate.

### How It Works

- **Discover** — `azure-to-aws` and `gcp-to-aws` read Terraform files, application code, and billing exports. `heroku-to-aws` can additionally discover live through the authenticated Heroku CLI (read-only and consent-gated) or from `Procfile` and `app.json`.
- **Clarify** — Resolves the requirements that change the target architecture: availability, compliance, data residency, cutover tolerance, and team capacity.
- **Design** — Maps source resources to AWS services using deterministic mapping tables — for example Heroku dynos to AWS Elastic Beanstalk, Heroku Postgres to Amazon RDS or Aurora, Heroku Redis to Amazon ElastiCache, Heroku Kafka to Amazon MSK, Cloud SQL to Amazon RDS, GKE to Amazon EKS, Cloud Run to AWS Fargate, Azure App Service to AWS Elastic Beanstalk, AKS to Amazon EKS, Azure SQL to Amazon RDS, and Cosmos DB to Amazon DynamoDB or DocumentDB.
- **Estimate** — Costs the target architecture from the plugin's bundled rate reference data and a documented cost algorithm, with an estimation schema and complexity tiers so two runs of the same workload agree. Estimates are planning figures; confirm them against the [AWS Pricing Calculator](https://calculator.aws/) before committing budget.
- **Generate** — Emits migration artifacts, including Terraform, gated by the `tf-best-practices` policy check and a validated migration report.
- **Workshop mode** — After estimate, `azure-to-aws`, `gcp-to-aws`, and `heroku-to-aws` can reprice region, high-availability, compute, and AWS Graviton scenarios without repeating discovery.

### Examples

- "Migrate us off Heroku to AWS"
- "Move our Azure estate to AWS — map AKS onto EKS"
- "We want to move from GCP — what would this cost on AWS?"
- "Map our Cloud Run services onto Fargate"
- "Reprice the migration with Graviton in us-west-2"

## AI Stack Migration

The `llm-to-bedrock` skill is a focused model and SDK rewrite. It assesses the codebase, rewrites OpenAI, Gemini, or Anthropic API call sites to Amazon Bedrock, evaluates the rewritten behavior against a golden prompt set, and delivers a ready-to-review git branch with a migration report.

Model mapping is compatibility-guided rather than one-to-one parity. Validate prompts, tool-calling behavior, and evaluation metrics before cutover. The assess phase is delegated to `gcp-to-aws`, so install that skill alongside this one.

### Examples

- "Migrate our OpenAI calls to Bedrock"
- "Move off the Gemini API to Amazon Bedrock"
- "Which Bedrock model is closest to what we use today?"
- "Score our prompts against Bedrock before we switch"

## Startup Reference Content

Two skills serve AWS-curated content rather than performing work on your account:

- **`knowledge-base-for-startups`** — AWS Activate FAQ, credits guide, programs, partner offers, sample architectures, and learn articles spanning generative AI, cloud architecture, cost optimization, security, fundraising, and go-to-market. Answers come from the bundled `references/` tree.
- **`prompt-library-for-startups`** — Copy-paste prompts for AI coding agents (MVP scaffolding, RAG chatbot on Amazon Bedrock, security baseline evaluation, cost anomaly detection, GPU quota requests, Amazon EKS deployment, Well-Architected review) plus downloadable installable agents.

Neither skill can look up account-specific state such as your credits balance, Activate membership, or application status. Those questions belong at [AWS Startups](https://aws.amazon.com/startups/).

### Examples

- "Am I eligible for AWS Activate credits?"
- "Show me a sample architecture for a RAG application"
- "Give me a prompt to set up a security baseline"
- "Which Activate provider credits apply to us?"

## Supported Environments

### Using the plugin in your local compute

In your local environment, configure AWS credentials and set your target region to get started.

#### Prerequisites

- An AWS account
- Local AWS credentials and config
- [uv](https://docs.astral.sh/uv/getting-started/installation/) (for MCP server)
- Python 3 (for the bundled validation scripts)
- Git (the `llm-to-bedrock` flow delivers its rewrite on a branch)
- The Heroku CLI, authenticated, only if you want live discovery in `heroku-to-aws`
- Terraform, only if you want to run `fmt`, `init`, or `validate` over generated Terraform

#### Authentication and Authorization

Configure AWS credentials using one of the following methods:

- **AWS CLI** — Run [`aws configure`](https://docs.aws.amazon.com/cli/latest/userguide/cli-configure-quickstart.html) (IAM credentials) or [`aws sso login`](https://docs.aws.amazon.com/cli/latest/userguide/cli-configure-sso.html) (IAM Identity Center)
- **Environment variables** — Set `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, and `AWS_SESSION_TOKEN`. See [Configuring environment variables](https://docs.aws.amazon.com/cli/v1/userguide/cli-configure-envvars.html) for details.

Documentation search, regional availability lookups, and the reference-content skills need no AWS credentials. Credentials are needed when a skill inspects or provisions resources in your account. The relevant IAM action namespaces are:

- `sts` - Caller identity and account context checks
- `bedrock`, `bedrock-runtime` - Model availability and prompt evaluation for the Bedrock migration flow
- `ec2`, `rds`, `s3` - Read-only discovery of existing compute, database, and storage resources
- `iam` - Reviewing roles and policies referenced by a design or security baseline
- `cloudformation` - Inspecting and deploying generated infrastructure

Start with read-only credentials for discovery, advice, and estimation, and scope write permissions to the resources your workload actually uses.

#### Configuration

- Set `AWS_DEFAULT_REGION` to your preferred AWS region (e.g., `us-east-1`). See [Configuring environment variables](https://docs.aws.amazon.com/cli/v1/userguide/cli-configure-envvars.html) for details.

## Customizing Skills for Your Organization

The skills in this plugin follow AWS best practices, but they are fully customizable. You can fork the repository and modify any `SKILL.md` to reflect your organization's standards, naming conventions, approved services, or internal tooling. Workspace-level skills take precedence over global skills, so teams can maintain their own versions without affecting other users.

## Related Resources

- [AWS for Startups](https://aws.amazon.com/startups/)
- [AWS Activate](https://aws.amazon.com/activate/)
- [Amazon Bedrock User Guide](https://docs.aws.amazon.com/bedrock/latest/userguide/what-is-bedrock.html)
- [Amazon Bedrock AgentCore](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/what-is-bedrock-agentcore.html)
- [AWS Well-Architected Framework](https://docs.aws.amazon.com/wellarchitected/latest/framework/welcome.html)
- [AWS Pricing Calculator](https://calculator.aws/)
- [Agent Skills open standard — Anthropic](https://www.anthropic.com/engineering/equipping-agents-for-the-real-world-with-agent-skills)
- [Agent Toolkit for AWS](https://github.com/aws/agent-toolkit-for-aws)

## License

This project is licensed under the Apache 2.0 License.
