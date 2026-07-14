# Service Skill Handoff

**Do NOT answer the user's service-specific question until the service skill is loaded.** The service skill has deeper, more current guidance than the knowledge cards. Even if you believe you can answer from the knowledge card alone, you MUST load the service skill first — the knowledge card is a summary, not a substitute. Follow the procedure below to load it first.

## Before loading (skip once the service is known)

1. **Resolve the service** — if the service isn't already clear from context, map common names:
   - "Postgres" → Aurora PostgreSQL
   - "Aurora" / "my cluster" → Aurora PostgreSQL or Aurora MySQL (ask if unclear)
   - "MySQL" → Aurora MySQL or RDS for MySQL (ask if unclear)
   - "DynamoDB" / "my table" → DynamoDB
   - "DSQL" → Aurora DSQL
   - "Redis" / "Valkey" / "my cache" → ElastiCache
   - "Mongo" / "DocumentDB" → DocumentDB
   - Other service names → map directly to the service reference table
   - If you still can't determine the service, ask: "Which AWS database service are you using?"

2. **Confirm intent** — if the user's question is actually about choosing or comparing services ("should I be using this?" / "is there something better?"), re-route to `select` instead.

## How to load a service skill

Look up the skill name from the service reference table in SKILL.md (the `Service skill` column).

If the table shows `—` (no service skill listed), skip directly to "If the service skill is not available" below — answer using the knowledge card and documentation tools.

Otherwise, try these methods in order:

### 1. Local skills directory

If the skill is already installed locally, it will activate automatically — the agent runtime detects installed skills and loads them. Check whether the skill is already available before attempting to install.

### 2. AWS MCP server (if available)

If the skill is not installed locally and the AWS MCP server is connected, call `aws___retrieve_skill` with the skill name from the service reference table in SKILL.md. You already have the authoritative skill name, so you do not need to call `aws___search_documentation` first to discover it — pass the listed name directly.

### 3. npx (Agent Toolkit CLI)

If neither of the above worked, install the skill now using the AWS Agent Toolkit CLI:

```bash
npx skills add https://github.com/aws/agent-toolkit-for-aws --skill <skill-name> --full-depth
```

For example:

```bash
npx skills add https://github.com/aws/agent-toolkit-for-aws --skill amazon-aurora-postgresql --full-depth
```

Once installed, the skill will be available. Some agents pick it up mid-session automatically; others require a session restart. If the user needs to run it themselves, show them the command and ask them to run it, then continue once they confirm.

### 4. GitHub (manual)

If none of the above work, point the user to the skill on GitHub:

```
https://github.com/aws/agent-toolkit-for-aws/tree/main/skills/specialized-skills/database-skills/<skill-name>
```

They can copy the skill into their agent's skills directory manually.

## If the service skill is not available

If no service skill exists for this service (table shows `—`) or the skill cannot be loaded by any method above, **proceed immediately** using:

- The service's knowledge card (loaded from this skill)
- The service's `llms.txt` documentation index (URL in the knowledge card)
- AWS documentation tools (`aws___search_documentation`, `aws___read_documentation`) if available

Do NOT narrate failed attempts or explain which methods you tried. **Lead with the recommendation** — answer the user's question directly from the knowledge card first. Mention the service skill at the end, not the beginning:

> "For detailed guidance, install the [service] skill: `npx skills add https://github.com/aws/agent-toolkit-for-aws --skill <skill-name> --full-depth`"

**Before taking any provisioning action**, confirm the service choice with the user and load the appropriate service skill for safe execution. The service skill provides the domain-specific configuration, safety guardrails, and resource tagging patterns needed to provision correctly.
