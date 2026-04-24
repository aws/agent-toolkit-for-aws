# AWS Agent Rules

Platform-agnostic agent configuration snippets for working with AWS. Copy the relevant sections into your `AGENTS.md`, `CLAUDE.md`, or `.kiro/steering/` files.

## Recommended Rules

### Use MCP servers for AWS documentation

```markdown
When answering questions about AWS services, always use the AWS Knowledge MCP server
for documentation lookups and recommendations before relying on training data.
```

### Search for skills before building from scratch

```markdown
Before attempting an AWS task from scratch, search for existing skills in the
agent-toolkit-for-aws plugin that may already solve the problem. Use the skill's
references and scripts when available.
```

### Confirm before deploying

```markdown
Always confirm with the user before deploying AWS resources. Show estimated costs
and the resources that will be created before proceeding.
```

### Use least-privilege IAM

```markdown
When creating IAM roles or policies, always follow the principle of least privilege.
Never create policies with wildcard (*) actions or resources unless explicitly
requested by the user.
```
