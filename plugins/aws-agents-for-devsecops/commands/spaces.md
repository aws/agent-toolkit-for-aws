---
description: List configured AgentSpaces and summarize each one's accounts and capabilities
---

1. Call `aws_devops_agent__list_agent_spaces()` — get all spaces accessible with current auth.
   - **Bearer token auth:** Returns only the single space the token is scoped to.
   - **SigV4 auth:** Returns all spaces in the account.
2. For each space, call `aws_devops_agent__list_associations(agent_space_id="SPACE_ID")` to see attached AWS accounts.
3. For each space, probe its knowledge: `aws_devops_agent__chat(message="Summarize the AWS services and runbooks you have access to. One-paragraph answer.", agent_space_id="SPACE_ID")`.
4. Print a table: name, agentSpaceId, attached account IDs, one-line capability summary.
5. If more than one space exists and no routing guide in the workspace  (e.g. `.claude/aws-agents-for-devsecops.md`, `AGENTS.md`, or per-project notes), offer to write one.
