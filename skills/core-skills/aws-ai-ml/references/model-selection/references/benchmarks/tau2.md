# τ²-bench

Multi-turn customer service simulation with dual-control (agent + user modify shared state). Telecom domain.

**Use this for:** Multi-turn tool use with policy following, accurate state management through API calls.

**Source:** Artificial Analysis (artificialanalysis.ai).
"—" = no data — infer from similar models in the same family, but tell the user you're inferring.

|   # | Model                                  | Family      | Score |
|-----|----------------------------------------|-------------|-------|
|   1 | Qwen3.6 27B (mode: reasoning)          | Qwen        | 94.2% |
|   2 | Qwen3.5 27B (mode: reasoning)          | Qwen        | 93.9% |
|   3 | Qwen3.5 4B (mode: reasoning)           | Qwen        | 92.1% |
|   4 | Qwen3.5 9B (mode: reasoning)           | Qwen        | 86.8% |
|   5 | Nova 2.0 Lite (mode: high)             | Amazon Nova | 72.8% |
|   6 | Gemma 4 31B (mode: reasoning)          | Google      | 59.9% |
|   7 | GPT-OSS 120B (mode: medium (averaged)) | OpenAI      | 55.4% |
|   8 | GPT-OSS 20B (mode: medium (averaged))  | OpenAI      | 55.3% |
|   9 | Qwen3 14B (mode: reasoning)            | Qwen        | 34.5% |
|  10 | Qwen2.5 72B Instruct                   | Qwen        | 34.5% |
|  11 | Qwen3 32B (mode: reasoning)            | Qwen        | 29.8% |
|  12 | Qwen3 8B (mode: reasoning)             | Qwen        | 27.8% |
|  13 | Llama 3.3 70B Instruct                 | Meta Llama  | 26.6% |
|  14 | Qwen3 1.7B (mode: reasoning)           | Qwen        | 26.0% |
|  15 | Nemotron 3 Nano 30B                    | NVIDIA      | 25.4% |
|  16 | DeepSeek R1 Distill Llama 70B          | DeepSeek    | 21.9% |
|  17 | Llama 3.2 3B Instruct                  | Meta Llama  | 21.1% |
|  18 | Qwen3 0.6B (mode: reasoning)           | Qwen        | 21.1% |
|  19 | Qwen3 4B (mode: reasoning)             | Qwen        | 19.0% |
|  20 | Nova Lite                              | Amazon Nova | 17.5% |
|  21 | Llama 3.1 8B Instruct                  | Meta Llama  | 16.4% |
|  22 | Llama 4 Scout 17B                      | Meta Llama  | 15.5% |
|  23 | Nova Pro                               | Amazon Nova | 14.0% |
|  24 | Nova Micro                             | Amazon Nova | 14.0% |
|  25 | Llama 3.2 1B Instruct                  | Meta Llama  |  0.0% |
|   — | Qwen2.5 32B Instruct                   | Qwen        |     — |
|   — | DeepSeek R1 Distill Llama 8B           | DeepSeek    |     — |
|   — | DeepSeek R1 Distill Qwen 32B           | DeepSeek    |     — |
|   — | DeepSeek R1 Distill Qwen 14B           | DeepSeek    |     — |
|   — | DeepSeek R1 Distill Qwen 1.5B          | DeepSeek    |     — |
|   — | Qwen2.5 14B Instruct                   | Qwen        |     — |
|   — | Qwen2.5 7B Instruct                    | Qwen        |     — |
|   — | DeepSeek R1 Distill Qwen 7B            | DeepSeek    |     — |
