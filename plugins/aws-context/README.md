# AWS Context

Ground your coding agent in your organization's knowledge with
AWS Context. The plugin connects the agent to your
AWS Context graph through the AWS Context MCP server and adds a skill that tells
it when and how to use it.

## What it does

- **Retrieve**: answer questions that depend on your organization's data and
  documents, with search, traversal and agentic retrieval over your graph.
- **Curate**: correct or extend the graph with change sets, which your graph's
  curation policies apply or hold for review.
- **Record**: send a session trace to your graph when you ask, so it can learn
  from it.

## Contents

| Path | What it is |
|---|---|
| `skills/aws-context/` | The `aws-context` skill and its retrieval, curation, connecting and hooks references |
| `commands/setup.md` | `/setup`: connect the agent to your graph's Region, with OAuth or SigV4 |
| `commands/context-login.md` | `/context-login`: sign in, or check that you are signed in |
| `commands/context-hooks.md` | `/context-hooks`: show or change the hooks |
| `com.anthropic.claude-code/hooks/` | Claude Code hooks, off by default: prompt steering (`UserPromptSubmit`) and session traces (`SessionEnd`, PutTrace). Python 3.7+ standard library, with unit tests |
| `.mcp.json`, `mcp.json` | The AWS Context MCP server, us-east-1 by default |

## Getting started

1. Install the plugin from the Agent Toolkit for AWS marketplace for your agent.
2. Connect to the Region your graph is in. In Claude Code or Cursor, run `/setup`; in
   other agents, ask the agent to connect to AWS Context. If your graph is in us-east-1,
   sign in with OAuth instead.
3. Ask a question about your organization's data.

To create a graph, use the `setting-up-aws-context` skill in the `aws-core` plugin.

## Hooks (Claude Code)

Both hooks are off until you turn them on with `/context-hooks`, which shows what each one
sends and waits for your yes. They call AWS Context with an AWS profile on your machine.
Session traces send the session log as recorded, with nothing removed, so keep secrets and
personal data out of sessions while traces are on. Other agents get the skill and commands
without hooks.

## Privacy

See the [AWS Privacy Notice](https://aws.amazon.com/privacy/).
