# Model Selection

Help the user choose a base model for finetuning. This reference applies to both Nova and OSS model paths — benchmark data helps compare models regardless of family.

Select the most relevant benchmark(s), then provide the user with a list of available models listed in performance order for that benchmark.

## Understanding the use case

Use what you already know from the conversation — the user may have described their task, domain, data, or goals. Make sure you're familiar with `use_case_spec.md` if it exists. Be sure to think about the success criteria from the user, if any has been documented. If you still don't have enough to map to relevant benchmarks, ask the user to describe their use case and success criteria in more detail.

## Making a recommendation

### Selecting relevant benchmark(s)

Read the benchmark descriptions below and identify which 2-3 benchmarks are most relevant to the user's task.

**Understand the usecase:** Model Selection is an essential step in model customization. You MUST make sure you understand the customer's use case well enough to select the proper benchmark. If you do not understand the usecase in enough detail, you MUST ask follow-up questions.

**Criteria for Benchmark Selection:** Picking the most relevant benchmarks is essential, because the user bases their model selection on this. You must think carefully about which benchmarks are really the most fitting. Frequently, intelligence index is the best, so make sure there is a good reason to rank anything else above that. Think about which benchmarks are testing model functionality that is the most relevant to what the user is trying to do.

**Data Source:** Artificial Analysis (artificialanalysis.ai). Independent evaluator, consistent methodology across all models.

#### [Intelligence Index](benchmarks/intelligence-index.md)

Artificial Analysis's composite overall quality score, combining multiple benchmarks into a single ranking. It's an index on AA's own scale where higher is better.

**Consider this:** As a default ranking, when no other benchmark seems to fit. This MUST always be in the top 2-3 recommended benchmarks, because it's relevant to all tasks.

#### [GPQA](benchmarks/gpqa.md)

The hardest 198 questions from the GPQA benchmark — graduate-level multiple-choice in biology, physics, and chemistry, written by PhD-level domain experts. Questions are "Google-proof" — skilled non-experts with unrestricted web access score only 34%, so the benchmark tests genuine scientific reasoning rather than information retrieval.

**Consider this:** For tasks related to scientific reasoning, particularly in the fields of biology, physics, and chemistry. Could be a good proxy for general scientific knowledge or the ability to think critically or logically.

#### [IF-Bench](benchmarks/ifbench.md)

Tests precise control over text output — the model must satisfy unusual, mechanically verifiable constraints like placing a specific word at an exact position in a sentence, using exactly N numbers, or ensuring no two consecutive words share the same first letter. 58 novel constraint types designed to be harder than standard instruction-following tests.

**Consider this:** For any task requiring tight control over model output, where the user has very specific requirements about features that must be present in the model output. Could be a good proxy for instruction following, although the benchmark is really about _precise_ instruction following in unusually difficult contexts

#### [MMMU-Pro](benchmarks/mmmu-pro.md)

College-level multimodal questions requiring both vision and reasoning across six disciplines: Art & Design, Business, Science, Health & Medicine, Humanities & Social Science, and Tech & Engineering. Image types include charts, diagrams, tables, maps, and chemical structures. The "Pro" version filters out questions answerable without the image, so it specifically tests integrated visual-textual understanding.

**Consider this:** For any task combining visual and textual inputs — chart/diagram interpretation, visual reasoning, document understanding. Also relevant for comparing overall model capability, since VLMs that score well here tend to perform well on text-only tasks too.

#### [τ²-bench](benchmarks/tau2.md)

Simulates multi-turn customer service conversations where both the agent and a simulated user actively modify a shared state (e.g., databases, account records). The agent must follow domain-specific policies, use API tools, and resolve customer requests. Scores are from the telecom domain.

**Consider this:** For situations where accurate tool use is important, for multi-turn conversation, and situations where instruction following or adherence to business logic is important. Be careful not to over-index on this for customer service conversations.

#### [HLE (Humanity's Last Exam)](benchmarks/hle.md)

2,500 expert-written questions across dozens of subjects including mathematics, humanities, and natural sciences, designed to be at the frontier of human knowledge. Questions can't be answered via internet retrieval. Scores are very low — most models cluster in the single digits.

**Consider this:** For tasks where reasoning, the ability to think logically, and the ability to draw connections between different concepts to form an analysis or conclusion is important. This benchmark may not show a large difference between most models.

#### [Coding Index](benchmarks/coding-index.md)

Artificial Analysis's composite coding score, combining Terminal-Bench Hard (agentic software engineering, system administration, and data processing in terminal environments) and SciCode (scientist-curated coding problems across 16 scientific disciplines).

**Consider this:** For software engineering tasks, scientific/research computing, system administration automation, any task where the model needs to write and/or execute code .

#### [Agentic Index](benchmarks/agentic-index.md)

Artificial Analysis's composite agentic score, combining GDPval-AA (real-world tasks across 44 occupations and 9 industries, with shell access and web browsing in an agentic loop) and τ²-bench Telecom.

**Consider this:** For autonomous agents, workflow automation, tool-using assistants, any use case where the model needs to independently use tools, browse the web, or carry out multi-step tasks.

### Presenting relevant benchmarks

After picking 2-3 relevant benchmarks from the above list (including Intelligence Index), present them in ranked order to the user, with a short explanation of what the benchmark is, and why you think it's relevant:

> "In order to select a model, it's helpful to look at performance on public benchmarks. After considering several benchmarks, I think these are the most relevant to your task: "
> "1. [benchmark]: [short description of benchmark]. [Why this is relevant]
> "2. [benchmark]: [short description of benchmark]. [Why this is relevant]

(Include a 3rd only if you think there are 3 relevant benchmarks)

> "Which of these do you think are relevant? After you pick, I'll show you the model rankings."

'' wait for user

### Presenting Models for Selection

After the user tells you which benchmarks they think are relevant, you need to present the models from the corresponding benchmark file in `/benchmarks`. Present the table exactly as it appears in the benchmark table, skipping any rows for models that are not in the user's list of available models. VLMs MUST be included in all benchmark tables where they have scores — do not filter them out based on the user's task being text-only. Double check your work to avoid hallucinations:

> "[Benchmark 1:]
> "[table from benchmark file]
>
> "========================="
>
> "[Benchmark 2:]
> "[table from benchmark file]

Give a 1-2 sentence analysis of what these benchmarks tell us. Keep in mind that most users balance performance and cost requirements.

Ask the user to select a model:

> "Given this information, which model would you like to select?"

''wait for user

If the user has any questions about model selection, answer them to the best of your ability, leaning on the benchmarks as much as possible and being transparent about your knowledge gaps and confidence.

Once the user has chosen a model, consider that the chosen base model. This workflow is complete.
