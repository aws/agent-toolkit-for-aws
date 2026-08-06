# IF-Bench

Precise instruction-following generalization — 58 novel verifiable output constraints.

**Use this for:** Tasks requiring tight control over model output.

**Source:** Artificial Analysis (artificialanalysis.ai).
"—" = no data — infer from similar models in the same family, but tell the user you're inferring.

|   # | Model                                  | Family      | Score |
|-----|----------------------------------------|-------------|-------|
|   1 | Qwen3.5 27B (mode: reasoning)          | Qwen        | 75.6% |
|   2 | Gemma 4 31B (mode: reasoning)          | Google      | 75.6% |
|   3 | Nova 2.0 Lite (mode: high)             | Amazon Nova | 70.7% |
|   4 | Qwen3.6 27B (mode: reasoning)          | Qwen        | 67.6% |
|   5 | Qwen3.5 9B (mode: reasoning)           | Qwen        | 66.7% |
|   6 | GPT-OSS 120B (mode: medium (averaged)) | OpenAI      | 63.6% |
|   7 | GPT-OSS 20B (mode: medium (averaged))  | OpenAI      | 61.5% |
|   8 | Qwen3.5 4B (mode: reasoning)           | Qwen        | 52.0% |
|   9 | Llama 3.3 70B Instruct                 | Meta Llama  | 47.1% |
|  10 | Qwen3 14B (mode: reasoning)            | Qwen        | 40.5% |
|  11 | Llama 4 Scout 17B                      | Meta Llama  | 39.5% |
|  12 | Nova Pro                               | Amazon Nova | 38.1% |
|  13 | Nemotron 3 Nano 30B                    | NVIDIA      | 37.5% |
|  14 | Qwen2.5 72B Instruct                   | Qwen        | 36.9% |
|  15 | Qwen3 32B (mode: reasoning)            | Qwen        | 36.3% |
|  16 | Nova Lite                              | Amazon Nova | 34.1% |
|  17 | Qwen3 8B (mode: reasoning)             | Qwen        | 33.5% |
|  18 | Qwen3 4B (mode: reasoning)             | Qwen        | 32.5% |
|  19 | Nova Micro                             | Amazon Nova | 29.4% |
|  20 | Llama 3.1 8B Instruct                  | Meta Llama  | 28.6% |
|  21 | DeepSeek R1 Distill Llama 70B          | DeepSeek    | 27.6% |
|  22 | Qwen3 1.7B (mode: reasoning)           | Qwen        | 26.9% |
|  23 | Llama 3.2 3B Instruct                  | Meta Llama  | 26.2% |
|  24 | Qwen3 0.6B (mode: reasoning)           | Qwen        | 23.3% |
|  25 | DeepSeek R1 Distill Qwen 32B           | DeepSeek    | 22.9% |
|  26 | Llama 3.2 1B Instruct                  | Meta Llama  | 22.8% |
|  27 | DeepSeek R1 Distill Qwen 14B           | DeepSeek    | 22.1% |
|  28 | DeepSeek R1 Distill Llama 8B           | DeepSeek    | 17.6% |
|  29 | DeepSeek R1 Distill Qwen 1.5B          | DeepSeek    | 13.2% |
|   — | Qwen2.5 32B Instruct                   | Qwen        |     — |
|   — | Qwen2.5 14B Instruct                   | Qwen        |     — |
|   — | Qwen2.5 7B Instruct                    | Qwen        |     — |
|   — | DeepSeek R1 Distill Qwen 7B            | DeepSeek    |     — |
