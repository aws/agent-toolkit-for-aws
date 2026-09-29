# Service Skill Handoff

**Do NOT answer the user's service-specific question until you have checked for the service skill using the approved methods below.** The service skill has deeper, more current guidance than the knowledge cards. If it is unavailable, follow the documented knowledge-card fallback.

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

Otherwise, use an already available local skill or the AWS MCP server. Loading a skill through either of these approved methods does not require user consent. It is not software installation and does not authorize any AWS resource change.

### 1. Local skills directory

If the skill is already installed locally, it will activate automatically — the agent runtime detects installed skills and loads them. Check whether the skill is already available before attempting to install.

### 2. AWS MCP server (if available)

If the skill is not installed locally and the AWS MCP server is connected, call `aws___retrieve_skill` with the skill name from the service reference table in SKILL.md. You already have the authoritative skill name, so you do not need to call `aws___search_documentation` first to discover it — pass the listed name directly.

## If the service skill is not available

If no service skill exists for this service (table shows `—`) or the skill cannot be loaded by any method above, **proceed immediately** using:

- The service's knowledge card (loaded from this skill)
- The service's `llms.txt` documentation index (URL in the knowledge card)
- AWS documentation tools (`aws___search_documentation`, `aws___read_documentation`) if available

Do NOT narrate failed attempts or explain which methods you tried. **Lead with the recommendation** — answer the user's question directly from the knowledge card first. Mention the service skill at the end, not the beginning.

If the service reference table lists a service skill but it is not available locally or through the AWS MCP server, advise the user that installing the service-specific skill is the remaining option. Tell them they can find it by searching skills.sh for the exact skill name and verifying the source is `aws/agent-toolkit-for-aws`, or by searching the official `aws/agent-toolkit-for-aws` GitHub repository. Ask for consent before providing or running installation steps. Do not run a package manager, clone or copy a repository, or install the skill before the user explicitly agrees.

**Before taking any provisioning action**, confirm the service choice with the user. If the service skill is available locally or through the AWS MCP server, load it immediately and follow its confirmation requirements before changing AWS resources. Skill loading does not itself require confirmation. If the service skill would first need to be installed, obtain installation consent as described above. If no service skill is listed, do not provision from this parent skill; provide guidance from the knowledge card and official AWS documentation instead. Consent to load or install a skill does not authorize resource creation or modification.
