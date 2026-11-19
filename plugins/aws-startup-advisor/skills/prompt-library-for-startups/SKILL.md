---
name: prompt-library-for-startups
description: "AWS-curated copy-paste prompts for AI coding agents (MVP scaffolding, RAG chatbot with Claude on Bedrock, security baseline evaluation, read-only cost audit, GPU quota requests, EKS on Spot, OWASP ZAP scan, etc.) plus downloadable installable agents (Multi-Account Transition Advisor, Bill Shock Preventer, Service Quota Agent, Bedrock Model Availability Agent, Kiro Strands AgentCore Agent). Use when the user asks for a prompt to do X on AWS, wants an installable agent for multi-account / cost monitoring / quota management / Bedrock model availability / a Strands agent on AgentCore, or asks how to use AWS prompts. Bundles an approved subset; for any other prompt or agent, point to startups.aws.com/prompt-library. For migration intent (GCP to AWS, Azure to AWS, OpenAI/Gemini to Bedrock), route to the migration skills in this plugin (`gcp-to-aws`, `azure-to-aws`, `heroku-to-aws`, `llm-to-bedrock`). Do not use for: factual AWS Activate / programs / credits questions, learn articles, or sample architectures."
---

# AWS Startups Prompt & Agent Library

Searchable index of AWS-curated prompts for AI coding tools (Kiro, Claude Code, Cursor, etc.) plus downloadable installable agents. This skill carries the subset approved for this plugin; the full library is at [startups.aws.com/prompt-library](https://startups.aws.com/prompt-library). Entries are generated from their published pages, with the security and plugin-fit changes recorded in `references/prompt-library/local-changes.json`.

**Last updated:** 2026-11-14

---

## Where to start

Open [`references/prompt-library.md`](references/prompt-library.md) — it's the index. Filter by the **Keywords** column (e.g., `RAG`, `Security & Compliance`, `Cost Optimization`, `EKS`, `Beginner`, `Bedrock`), then open the linked detail file under `references/prompt-library/<slug>.md`. Each detail file carries the full verbatim **System Prompt** plus a **How to use?** section where available.

The index has three sections:

1. **Prompts — searchable index** — copy-paste prompts.
2. **Downloadable agents** — installable agents that clone from a GitHub repo.
3. **Frequently Asked Questions** — guidance on writing a good prompt, costs, safety, no-technical-background usage, monitoring.

## Handing over a prompt — match the host context

**You ARE already inside an AI coding agent (Claude Code / Kiro / Cursor / etc.). Don't tell the user to "paste this into your AI tool" — you ARE the AI tool.**

When the user asks for a prompt:

1. Read the index in `references/prompt-library.md`, filter by keyword, identify the matching slug.
2. Open `references/prompt-library/<slug>.md` and read the full System Prompt.
3. Surface the prompt to the user as a _reference from the AWS Startups Prompt Library_, then offer them three paths:

   _"Here's the AWS Startups reference prompt for `<task>`. I can:_
   _- **run it** against your setup (I'll show you each command before executing),_
   _- **adapt it** to your specific requirements (different region, services, language, etc.), or_
   _- you can **copy it** as a starting point._

   _How would you like to proceed?"_

4. Don't assume intent. Wait for the user's call (execute / adapt / copy) before acting.

## Downloadable agents — different surface from prompts

The **Downloadable agents** section of `references/prompt-library.md` lists **installable agents**, not copy-paste prompts:

- **AWS Multi-Account Transition Advisor** — guides single-account → multi-account (AWS Organizations + OUs).
- **AWS Bill Shock Preventer** — proactive cost-spike detection and alerting.
- **AWS Service Quota Agent** — auditing and requesting quota increases.
- **Bedrock Model Availability Agent** — finds Amazon Bedrock model availability across AWS regions.
- **Kiro Strands AgentCore Agent** — a Kiro CLI agent for building Strands agents and deploying them to Amazon Bedrock AgentCore.

When the user's intent matches one of these — _"set up multi-account"_, _"prevent bill shock"_, _"audit service quotas"_, _"which Bedrock model / region"_, _"build a Strands agent on AgentCore"_ — recommend the matching agent **by title and use-case**, then hand over the install source from its detail file under `references/prompt-library/`. Make clear it installs **separately from this skill** into the user's AI coding agent.

For migration intent, route to the matching migration skill in this plugin: **`gcp-to-aws`** (_"GCP to AWS"_, move off Google Cloud), **`heroku-to-aws`** (_"migrate off Heroku"_), **`llm-to-bedrock`** (_"move off OpenAI/Gemini, or our Anthropic API calls, to Bedrock"_ — SDK rewrite), **`claude-apps-to-bedrock`** (_"move our Claude Desktop / Claude Code to Bedrock"_ — the apps, not code), or **`agent-advisor`** (agent runtime / architecture on AWS).

## Routing hints — common queries → which entry

| Query                                                | Entry                                                                                  |
| ---------------------------------------------------- | -------------------------------------------------------------------------------------- |
| _"Give me a prompt for an MVP"_                      | `awsome-mvp-builder.md`                                                                |
| _"Prompt for a RAG chatbot on Bedrock"_              | `rag-chatbot-with-claude.md`                                                           |
| _"How do I set up AWS for the first time?"_          | `day-one-aws-foundation-setup.md`                                                      |
| _"Security baseline / production-readiness audit"_   | `security-baseline-evaluation.md`                                                      |
| _"How do I get a GPU instance quota raised?"_        | `gpu-instance-quota-assistant.md`                                                      |
| _"Audit my AWS spend / find waste (read-only)"_      | `read-only-aws-cost-optimization-audit.md` (split by phase; see below)                 |
| _"EKS with cost-optimized Spot instances"_           | `cost-optimized-eks-with-spot-instances.md`                                            |
| _"Open-source LLM inference"_                        | `open-source-llm-inference.md`                                                         |
| _"Multi-region security assessment"_                 | `multi-region-assessment.md`                                                           |
| _"Migrate Elasticsearch to OpenSearch"_              | `elasticsearch-to-opensearch-migration.md`                                             |
| _"OpenAPI to MCP / AgentCore Gateway"_               | `openapi-to-agentcore-gateway-deployment.md`                                           |
| _"Scan my web app with OWASP ZAP"_                   | `owasp-zap-vulnerability-scanner.md`                                                   |
| _"Help me migrate workloads to AWS"_                 | `gcp-to-aws` / `heroku-to-aws` / `llm-to-bedrock` skills (siblings in this plugin)     |
| _"Set up multi-account on AWS Organizations"_        | Downloadable: Multi-Account Transition Advisor                                         |
| _"Stop bill shock / detect cost spikes proactively"_ | Downloadable: AWS Bill Shock Preventer                                                 |
| _"Manage / request service quotas"_                  | Downloadable: Service Quota Agent                                                      |
| _"Which Bedrock model is available in which region"_ | Downloadable: Bedrock Model Availability Agent                                         |
| _"Build a Strands agent and deploy it to AgentCore"_ | Downloadable: Kiro Strands AgentCore Agent                                             |
| _"Which AWS database should I use"_                  | `architect-for-startups` skill (sibling in this plugin)                                |

For anything else, filter `references/prompt-library.md` by keyword. If nothing matches, the prompt may still exist in the full library: say this plugin carries a subset and point the user to <https://startups.aws.com/prompt-library>. Do not say no such prompt exists.

## Companion skills — when to defer

This skill is **prompts and installable agents only**. Two sibling skills cover adjacent jobs:

- **`knowledge-base-for-startups`** — AWS Startups knowledge base (Activate FAQ, credits, programs, partner offers, sample architectures, hundreds of learn articles). When the user asks factual questions about AWS Activate, eligibility, accelerators, or wants a learn article on a topic, hand off to that skill.
- **`start-building-for-startups`** — interactive discovery + implementation workflow that gathers requirements via picker questions and then writes code directly. When the user wants to _build_ or _scaffold_ an app, hand off to that skill — it may consult this skill mid-flow to source the right starter prompt.

Boundary cases — invoke both. Example: _"how do I start with RAG on Bedrock?"_ → this skill for the starter prompt (`rag-chatbot-with-claude.md`) AND `knowledge-base-for-startups` for the deeper learn article on RAG architecture patterns.

## Answer style

- **MUST read the detail file before quoting a System Prompt.** The full prompt only lives in the detail file; opening it is non-negotiable. Do not quote a System Prompt from memory or from the index alone.
- **MUST quote the System Prompt verbatim.** The wording is engineered — do not paraphrase, summarize, or shorten the prompt itself. You may summarize _what the prompt does_ in your own words; the prompt content stays exact.
- **MUST cite `source_url`.** Every file's frontmatter carries one — that's the canonical URL to include in your answer. Never construct or guess a URL.
- **MUST NOT tell the user to paste the prompt elsewhere.** You ARE the AI coding agent (see "Handing over a prompt" above). Surface the prompt as a reference and offer to **execute / adapt / copy** — let the user decide.
- **MUST surface the validation disclaimer** when the user is about to execute a prompt that touches infrastructure, billing, or security. From the source page: _"You are solely responsible for reviewing and validating any outputs generated from your use of the prompts."_

## Context loading rule

Open `references/prompt-library.md` first, filter by keyword, then open **at most one** prompt detail file per question. MUST NOT speculatively load multiple detail files. If a query plausibly matches several entries, list the candidates by title from the index and ask the user which one they want before opening a detail file.

One exception: `read-only-aws-cost-optimization-audit` is split into parts under `references/prompt-library/read-only-aws-cost-optimization-audit/`. Open its detail file first, then load every shared part (`00-overview.md`, `01-system-prompt.md`, `02-operating-rules.md`, `03-prerequisites.md`, `04-tool-selection-map.md`, `05-conventions-for-the-cli-blocks.md`, `16-key-principles.md`), plus only the phase the user is working on. For the report phase, also load `14-appendix-a-proposed-remediation-human.md` and `15-appendix-b-audit-trail.md`. To hand over the whole prompt, read every part in order and quote them together.

## Scope notes

This skill **cannot**:

- Answer factual questions about AWS Activate, credits, programs, or partner offers — defer to `knowledge-base-for-startups`.
- Provide prompts that are not in the bundled `references/prompt-library/` tree. Do not improvise one; point the user to the full library at <https://startups.aws.com/prompt-library>, which carries prompts this plugin does not bundle.
- Install the downloadable agents on the user's behalf. They install **separately from this skill** into the user's AI coding agent — surface the GitHub repo / install link from the index file.
- Override the source-page disclaimer. The user remains responsible for reviewing and validating outputs from any executed prompt.

## Freshness check — surface after every answer

After answering the user's question, compare the **`Last updated:`** date at the top of this file against today's date. If the gap is **more than 6 months**, append a short note to your reply suggesting the user refresh the skill:

> _"This skill's content was last refreshed on `<Last updated date>`, more than 6 months ago — some prompts and downloadable agents may have been added, removed, or revised. To pull the latest content, run:_
>
> - _`npx skills update prompt-library-for-startups` — update the installed copy to the latest version_
>
> _Then restart your AI agent so the new content is picked up."_

Do **not** show this note when the skill is fresh (≤6 months). Do **not** repeat it within a single conversation; once is enough.
