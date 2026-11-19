# Bedrock migration artifacts

This folder holds artifacts only. No code was changed and nothing ran against AWS. To rewrite the SDK calls on a branch, use llm-to-bedrock.

## Route `gpt-5.5__mantle-openai-responses__responses__web-search`

- Workloads: `openai_api.gpt-5.5.openai.responses.create.plain`
- Call sites: `app/research.py:12`
- Source model `gpt-5.5` -> Bedrock model `openai.gpt-5.5` (client_config)
- Endpoint: bedrock-mantle (web_search, detected)

Use `routes/gpt-5.5__mantle-openai-responses__responses__web-search.py`: `call_bedrock(prompt)` is the after call.

Before:

```python
client = OpenAI()
reply = client.responses.create(model="gpt-5.5", input=prompt)
```

After:

```python
client = OpenAI(base_url="https://bedrock-mantle.us-east-1.api.aws/openai/v1", api_key=provide_token(region="us-east-1"),
                default_headers={"OpenAI-Organization": Omit(), "OpenAI-Project": Omit()})
reply = client.responses.create(model="openai.gpt-5.5", input=prompt)
```

## Route `gpt-5.5__runtime-openai-cris__chat-completions`

- Workloads: `openai_api.gpt-5.5.openai.chat.completions.create.plain`
- Call sites: `app/support.py:30`
- Source model `gpt-5.5` -> Bedrock model `us.openai.gpt-5.5` (client_config)
- Endpoint: bedrock-runtime
- No Mantle-only requirement was recorded for openai_api.gpt-5.5.openai.chat.completions.create.plain; bedrock-runtime selected. If this workload needs background inference, server-side tools, Projects/Workspaces, or single-Region processing, re-run Clarify.

Use `routes/gpt-5.5__runtime-openai-cris__chat-completions.py`: `call_bedrock(prompt)` is the after call.

Before:

```python
client = OpenAI()
reply = client.chat.completions.create(model="gpt-5.5", messages=messages)
```

After:

```python
client = OpenAI(base_url="https://bedrock-runtime.us-east-1.amazonaws.com/openai/v1", api_key=provide_token(region="us-east-1"),
                default_headers={"OpenAI-Organization": Omit(), "OpenAI-Project": Omit()})
reply = client.chat.completions.create(model="us.openai.gpt-5.5", messages=messages)
```

## Route `text-embedding-3-small__direct__invoke`

- Workloads: `openai_api.text-embedding-3-small.openai.embeddings.create.plain`
- Call sites: `app/index.py:8`
- Source model `text-embedding-3-small` -> Bedrock model `amazon.titan-embed-text-v2:0` (provider_adapter)
- Endpoint: bedrock-runtime
- No Mantle-only requirement was recorded for openai_api.text-embedding-3-small.openai.embeddings.create.plain; bedrock-runtime selected. If this workload needs background inference, server-side tools, Projects/Workspaces, or single-Region processing, re-run Clarify.

Use `routes/text-embedding-3-small__direct__invoke.py`: `call_bedrock(prompt)` is the after call.

Before:

```python
client = OpenAI()
vector = client.embeddings.create(model="text-embedding-3-small", input=text).data[0].embedding
```

After:

```python
bedrock = boto3.client("bedrock-runtime", region_name="us-east-1")
body = bedrock.invoke_model(modelId="amazon.titan-embed-text-v2:0", body=json.dumps({"inputText": text}))["body"].read()
vector = json.loads(body)["embedding"]
```

## Dependencies

- Add aws-bedrock-token-generator>=1,<2 and boto3; keep openai>=2.45.0,<3.

Credentials come from Bedrock tokens (`aws-bedrock-token-generator`) or the default AWS credential chain.

## Switching traffic

Wire `generate(prompt, source_call=<your existing call>)` from the route file. Set `AI_PROVIDER=shadow` first, then `AI_PROVIDER=bedrock`. Set `AI_PROVIDER=source` to roll back.

## Order

1. `./setup_bedrock.sh` (dry run), then `./setup_bedrock.sh --execute`.
2. `python3 test_comparison.py --target-only --quick`.
3. `python3 test_comparison.py` with your current provider's credentials in the environment its SDK already reads.

## Notes

- gpt-5.5__mantle-openai-responses__responses__web-search: call_bedrock sends the web_search tool with "external_web_access": false; keep it false unless you grant bedrock-websearch:ExternalWebAccess.
- openai.gpt-5.5, us.openai.gpt-5.5: not confirmed to bill under Amazon Bedrock. After the first day of traffic, check Cost Explorer grouped by Service; if the spend is elsewhere, export BUDGET_SERVICES with those names and run setup_bedrock.sh again.
- Estimate has no projected Bedrock figure, so setup_bedrock.sh creates no budget until you export BUDGET_USD.
- Generate does not scan code: if the app keeps client.responses.retrieve/cancel/delete on a runtime Responses route, add bedrock:GetInvoke/CancelInvoke/DeleteInvoke on project/default (iam_policy.py --stored-response-ops).
- AWS Activate credits can offset Bedrock usage for eligible startups: https://aws.amazon.com/startups/credits/
