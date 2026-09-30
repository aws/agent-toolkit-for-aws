# Managed Agent Alternatives (awareness, not actively recommended)

Surface these as awareness with tradeoffs when the user is committed to a single provider.

## Claude Managed Agents (Claude-committed)

- Tradeoffs: not in AWS compliance boundary (Anthropic is data processor); no governance
  stack (no Policy/Registry/Identity); organizational lock-in (cannot export).
- If the customer needs HIPAA/SOC/FedRAMP, governance, multi-agent A2A, code export, or
  multi-model → AgentCore wins regardless.

## Bedrock Managed Agents (OpenAI-committed)

- Now officially announced in preview (Sep 2026) in `us-east-1`, `us-west-2`, and `us-east-2` ([AWS announcement](https://aws.amazon.com/about-aws/whats-new/2026/09/bedrock-managed-agents-preview/)).
- Built on customized OpenAI Agents API, AWS-native, with IAM roles per agent, durable sessions, MCP tool support, human approval, and CloudTrail logging; no additional charge during preview beyond underlying AWS resources ([user guide](https://docs.aws.amazon.com/bedrock/latest/userguide/bedrock-managed-agents-openai.html)).
- If the customer needs model flexibility, governance, or code export → AgentCore wins.

## Rule

Multi-provider or undecided → AgentCore (only option supporting all models natively, no lock-in).
