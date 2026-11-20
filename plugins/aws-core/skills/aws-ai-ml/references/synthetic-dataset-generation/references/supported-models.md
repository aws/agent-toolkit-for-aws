# Supported Models

`SampleGenerationModelConfig.ModelId` and each
`SampleVerificationModelConfigs[].ModelId` take the ID from the table below,
and every model in it works for both. The service rejects any other ID. No API
lists this allowlist, and it changes as models are added or retired, so if the
service rejects an ID the user asked for, report the validation error instead
of guessing a different ID.

| Model | ID | Code generation |
|---|---|---|
| Claude Sonnet 4 | `us.anthropic.claude-sonnet-4-20250514-v1:0` | Yes |
| Claude Sonnet 4.5 | `us.anthropic.claude-sonnet-4-5-20250929-v1:0` | Yes |
| Claude Sonnet 4.6 | `us.anthropic.claude-sonnet-4-6` | Yes |
| Claude Sonnet 5 | `us.anthropic.claude-sonnet-5` | Yes |
| Claude Sonnet 5.5 | `global.anthropic.claude-sonnet-5-5` | Yes |
| Claude Haiku 5.5 | `us.anthropic.claude-haiku-5-5` | Yes |
| Claude Opus 4.6 | `us.anthropic.claude-opus-4-6-v1` | Yes |
| Claude Opus 4.7 | `us.anthropic.claude-opus-4-7` | Yes |
| Claude Opus 4.8 | `us.anthropic.claude-opus-4-8` | Yes |
| Claude Opus 5 | `us.anthropic.claude-opus-5` | Yes |
| Claude Opus 5.5 | `us.anthropic.claude-opus-5-5` | Yes |
| GPT-5.6 Terra | `us.openai.gpt-5.6-terra` | Yes |
| GPT-5.6 Luna | `us.openai.gpt-5.6-luna` | Yes |
| GPT-5.6 Sol | `us.openai.gpt-5.6-sol` | Yes |
| GPT-6 Astra | `us.openai.gpt-6-astra` | Yes |
| GPT-6 Luna | `us.openai.gpt-6-luna` | Yes |
| GPT-6 Sol | `us.openai.gpt-6-sol` | Yes |
| GPT-6.1 Sol | `us.openai.gpt-6.1-sol` | Yes |
| GLM 5.3 | `us.zai.glm-5.3` | No |
| Grok 4.7 | `us.xai.grok-4.7` | No |
| Kimi K3 | `us.moonshotai.kimi-k3` | No |
| DeepSeek R1 | `us.deepseek.r1-v1:0` | No |
| Kimi K2.5 | `moonshotai.kimi-k2.5` | No |
| DeepSeek V3.2 | `deepseek.v3.2` | No |
| Qwen3 32B | `qwen.qwen3-32b-v1:0` | No |
| Qwen3 235B | `qwen.qwen3-235b-a22b-2507-v1:0` | No |
| Qwen3 Coder 480B | `qwen.qwen3-coder-480b-a35b-v1:0` | No |
| Qwen3 Next 80B | `qwen.qwen3-next-80b-a3b` | No |
| Mistral 7B Instruct | `mistral.mistral-7b-instruct-v0:2` | No |
| Mistral Large 2402 | `mistral.mistral-large-2402-v1:0` | No |
| Mistral Large 2407 | `mistral.mistral-large-2407-v1:0` | No |
| Mistral Large 3 | `mistral.mistral-large-3-675b-instruct` | No |
| Mistral Small | `mistral.mistral-small-2402-v1:0` | No |
| Mixtral 8x7B | `mistral.mixtral-8x7b-instruct-v0:1` | No |
| Nemotron Super 3 120B | `nvidia.nemotron-super-3-120b` | No |
| GPT OSS 20B | `openai.gpt-oss-20b-1:0` | No |
| GPT OSS 120B | `openai.gpt-oss-120b-1:0` | No |
| Nova 2 Lite | `us.amazon.nova-2-lite-v1:0` | No |

`CodeGenerationModelConfig.ModelId` accepts only the models marked Yes. The
notebook sets it on the spec-based sample run, the only submission that
generates code, and leaves it out of the `CodeArtifacts` submissions, which run
code the user supplies.
