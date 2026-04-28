---
name: find-aws-skills
description: >
  Discovers and retrieves additional AWS skills for specialized tasks
  not covered by the default bundled skills. Searches the AWS MCP server
  when a user's request involves an AWS service or workflow without a
  matching default skill. Use when the user asks about an AWS service
  or workflow and no bundled skill covers it.
---

# Find AWS Skills

## Workflow

### Step 1: Search for skills

Use `aws___search_documentation` with the translated search phrase as `search_phrase`, `topics=["agent_skills"]`, and `limit=3`.

Translate the user's intent into a somewhat verbose search phrase that preserves context — this improves vector search relevance over minimal keywords.

| User says | Search phrase |
|---|---|
| "Create a production VPC with multiple AZs" | `create production VPC multi-AZ networking` |
| "My Lambda is timing out" | `Lambda function timeout debugging troubleshooting` |
| "Lock down my S3 buckets" | `secure S3 bucket access policy hardening` |
| "Deploy my app to AWS" | `deploy application AWS infrastructure` |
| "I'm getting access denied on S3" | `S3 access denied error troubleshooting` |

New skills are added regularly. Do not assume a skill does not exist without searching first.

### Step 2: Pick and load a skill

Read the returned results' descriptions and scores. Results are ordered by relevance — the first result is the strongest match. Pick the most relevant one based on this ordering and the user's context.

Use `aws___retrieve_skill` with the exact `skill_name` from the selected result. Skill names are opaque identifiers — do not guess or fabricate them.

Follow the loaded skill's instructions. If the skill references additional files (e.g., `references/architecture.md`), retrieve them by calling `aws___retrieve_skill` again with the same `skill_name` and the `file` parameter set to the referenced path.

If none of the returned results are relevant to the user's request, treat it the same as no results and proceed to Step 3.

### Step 3: Handle failures

If the search returns no results, no result is relevant, or skill retrieval fails for any reason, give the user a friendly message explaining what happened and offer options:

1. Retry with a different search phrase
2. Proceed with direct AWS CLI commands (`aws___call_aws`, `aws___suggest_aws_commands`)
3. Let the user guide you on how they'd like to proceed

Do not silently fall back to CLI tools — always wait for the user's confirmation first.
