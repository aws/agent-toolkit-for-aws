# Bedrock migration artifacts

This folder holds artifacts only. No code was changed and nothing ran against AWS. To rewrite the SDK calls on a branch, use llm-to-bedrock.

## Route `gpt-4o__runtime-openai-cris__chat-completions`

- Workloads: `openai_api.gpt-4o`
- Call sites: not recorded (schema 1.0 profile)
- Source model `gpt-4o` -> Bedrock model `us.openai.gpt-5.6-terra` (client_config)
- Endpoint: bedrock-runtime
- No Mantle-only requirement was recorded for openai_api.gpt-4o; bedrock-runtime selected. If this workload needs background inference, server-side tools, Projects/Workspaces, or single-Region processing, re-run Clarify.

Use `routes/gpt-4o__runtime-openai-cris__chat-completions.py`: `call_bedrock(prompt)` is the after call.

Before:

```python
client = OpenAI()
reply = client.chat.completions.create(model="gpt-4o", messages=messages)
```

After:

```python
client = OpenAI(base_url="https://bedrock-runtime.us-east-1.amazonaws.com/openai/v1", api_key=provide_token(region="us-east-1"),
                default_headers={"OpenAI-Organization": Omit(), "OpenAI-Project": Omit()})
reply = client.chat.completions.create(model="us.openai.gpt-5.6-terra", messages=messages)
```

## Dependencies

- Add aws-bedrock-token-generator>=1,<2; keep openai>=2.45.0,<3.

Credentials come from Bedrock tokens (`aws-bedrock-token-generator`) or the default AWS credential chain.

## Switching traffic

Wire `generate(prompt, source_call=<your existing call>)` from the route file. Set `AI_PROVIDER=shadow` first, then `AI_PROVIDER=bedrock`. Set `AI_PROVIDER=source` to roll back.

## Order

1. `./setup_bedrock.sh` (dry run), then `./setup_bedrock.sh --execute`.
2. `python3 test_comparison.py --target-only --quick`.
3. `python3 test_comparison.py` with your current provider's credentials in the environment its SDK already reads.

## Notes

- gpt-4o__runtime-openai-cris__chat-completions: no generated source caller, so the full test_comparison.py run reports these routes INCOMPLETE. --target-only checks Bedrock alone; AI_PROVIDER=shadow logs Bedrock latency to set beside your source metrics.
- us.openai.gpt-5.6-terra: not confirmed to bill under Amazon Bedrock. After the first day of traffic, check Cost Explorer grouped by Service; if the spend is elsewhere, export BUDGET_SERVICES with those names and run setup_bedrock.sh again.
- Generate does not scan code: if the app keeps client.responses.retrieve/cancel/delete on a runtime Responses route, add bedrock:GetInvoke/CancelInvoke/DeleteInvoke on project/default (iam_policy.py --stored-response-ops).
- AWS Activate credits can offset Bedrock usage for eligible startups: https://aws.amazon.com/startups/credits/
