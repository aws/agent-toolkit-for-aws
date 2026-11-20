# Bedrock migration artifacts

This folder holds artifacts only. No code was changed and nothing ran against AWS. To rewrite the SDK calls on a branch, use llm-to-bedrock.

## Route `claude-sonnet-5__runtime-messages__messages`

- Workloads: `anthropic_api.claude-sonnet-5.anthropic.messages.create.plain`
- Call sites: `svc/agent.py:22`
- Source model `claude-sonnet-5` -> Bedrock model `us.anthropic.claude-sonnet-5` (client_config)
- Endpoint: bedrock-runtime
- No Mantle-only requirement was recorded for anthropic_api.claude-sonnet-5.anthropic.messages.create.plain; bedrock-runtime selected. If this workload needs background inference, server-side tools, Projects/Workspaces, or single-Region processing, re-run Clarify.

Use `routes/claude-sonnet-5__runtime-messages__messages.py`: `call_bedrock(prompt)` is the after call.

Before:

```python
client = Anthropic()
reply = client.messages.create(model="claude-sonnet-5", max_tokens=1024, messages=messages)
```

After:

```python
client = Anthropic(base_url="https://bedrock-runtime.us-east-1.amazonaws.com/anthropic", api_key=provide_token(region="us-east-1"))
reply = client.messages.create(model="us.anthropic.claude-sonnet-5", max_tokens=1024, messages=messages)
```

## Route `gemini-2.5-flash__converse__converse`

- Workloads: `gemini_api.gemini-2.5-flash.genai.models.generate_content.plain`
- Call sites: `svc/summarize.py:9`
- Source model `gemini-2.5-flash` -> Bedrock model `us.anthropic.claude-haiku-5-5` (provider_adapter)
- Endpoint: bedrock-runtime
- No Mantle-only requirement was recorded for gemini_api.gemini-2.5-flash.genai.models.generate_content.plain; bedrock-runtime selected. If this workload needs background inference, server-side tools, Projects/Workspaces, or single-Region processing, re-run Clarify.

Use `routes/gemini-2.5-flash__converse__converse.py`: `call_bedrock(prompt)` is the after call.

Before:

```python
client = genai.Client()
reply = client.models.generate_content(model="gemini-2.5-flash", contents=prompt)
```

After:

```python
bedrock = boto3.client("bedrock-runtime", region_name="us-east-1")
reply = bedrock.converse(modelId="us.anthropic.claude-haiku-5-5", messages=[{"role": "user", "content": [{"text": prompt}]}])
text = reply["output"]["message"]["content"][0]["text"]
```

## Dependencies

- Add aws-bedrock-token-generator>=1,<2 and boto3; keep anthropic; remove google-genai after cutover.

Credentials come from Bedrock tokens (`aws-bedrock-token-generator`) or the default AWS credential chain.

## Switching traffic

Wire `generate(prompt, source_call=<your existing call>)` from the route file. Set `AI_PROVIDER=shadow` first, then `AI_PROVIDER=bedrock`. Set `AI_PROVIDER=source` to roll back.

## Order

1. `./setup_bedrock.sh` (dry run), then `./setup_bedrock.sh --execute`.
2. `python3 test_comparison.py --target-only --quick`.
3. `python3 test_comparison.py` with your current provider's credentials in the environment its SDK already reads.

## Notes

- us.anthropic.claude-haiku-5-5, us.anthropic.claude-sonnet-5: billed through AWS Marketplace and shown in Cost Explorer under the model provider, not under Amazon Bedrock, so a budget on the Amazon Bedrock service would not see this spend. setup_bedrock.sh creates no budget until you export BUDGET_SERVICES with the service names Cost Explorer shows.
- Generate does not scan code: if the app keeps client.responses.retrieve/cancel/delete on a runtime Responses route, add bedrock:GetInvoke/CancelInvoke/DeleteInvoke on project/default (iam_policy.py --stored-response-ops).
- AWS Activate credits can offset Bedrock usage for eligible startups: https://aws.amazon.com/startups/credits/
