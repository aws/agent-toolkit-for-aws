---
source_url: https://aws.amazon.com/startups/learn/selecting-the-right-foundation-model-for-your-startup
title: "Selecting the right foundation model for your startup"
---

## Selecting the right foundation model for your startup

> _Learn how to build a generative AI application — get products to market as quickly as possible, while maintaining cost efficiency and high performance_

---

When startups build generative artificial intelligence (AI) into their products, selecting a foundation model (FM) is one of the first and most critical steps. An FM is a large [machine learning](https://en.wikipedia.org/wiki/Machine_learning) (ML) model that is pre-trained on a vast quantity of data at scale. This results in a model that can be adapted to a wide range of downstream tasks.

Model selection has strategic implications for how a startup gets built. Everything from user experience and go-to-market, to hiring and profitability, can be affected by the model you choose. Models vary across a number of factors, including:

- **Level of customization** – The ability to change a model's output with new data ranging from prompt-based approaches to full model re-training
- **Model size** – How much information the model has learned as defined by parameter count
- **Inference options** – From self-managed deployment to API calls
- **Licensing agreements** – Some agreements can restrict or prohibit commercial use
- **Context windows** – How much information can fit in a single prompt
- **Latency** – How long it takes for a model to generate an output

The following sections show you what to consider when selecting an FM to meet your startup's needs.

## Application-specific benchmarks

As you evaluate the performance of different FMs for your use case, a critical step in the process is establishing a benchmark strategy. This helps you quantify how well the content matches your expectations.

> "There are a large number of models out there, ranging from closed source players … to open-source models like Dolly, Alpaca, and Vicuna. Each of these models have their own tradeoffs — it's critical that you choose the best model for the job," explains Noa Flaherty, chief technology officer (CTO) and co-founder of Vellum. "We've helped businesses implement a wide variety of AI use cases and have seen first-hand that each use case has different requirements for cost, quality, latency, context window, and privacy."

Generalized benchmarks (such as Stanford's [Holistic Evaluation of Language Models](https://crfm.stanford.edu/helm/latest/)) are a great starting point for some startups, because they help prioritize which foundation models to start experimenting with. However, generalized benchmarks may be insufficient for startups that are focused on building for a specific customer base.

For example, if your model needs to summarize medical appointments or customer feedback, the model should be evaluated against how well it can perform these specific tasks. "To do custom benchmarking, you need a workflow for rapid experimentation — typically via trial and error across a wide variety of scenarios. It's common to over-fit your model/prompt for a specific test case and think you have the right model, only for it to fall flat once in production," Noa advises. Custom benchmarking may include techniques such as calculating [BLEU and ROUGE scores](https://medium.com/@sthanikamsanthosh1994/understanding-bleu-and-rouge-score-for-nlp-evaluation-1ab334ecadcb). These are two metrics that help startups quantify the number of corrections necessary to apply to AI-generated text before its approved for use in human-in-the-loop applications.

Quality metrics and model evaluation are critical, which is why Noa founded Vellum in the first place. This [Y Combinator](https://www.ycombinator.com/) backed startup focuses their product offerings on experimentation. Per Noa, "The more you can compare/contrast models across a variety of cases that resemble what you'll see in production, the better off you'll be once in production."

## Smaller, purpose-built models are on the rise

Once your quality benchmarks have been established, you can begin to experiment with using smaller models meant for specific tasks, like following instructions or summarization. These purpose-built models can significantly reduce a model's parameter count while maintaining its ability to perform domain-specific tasks. For example, startup [GoCharlie](https://gocharlie.ai/) [partnered with SRI](https://gocharlie.ai/2023/05/07/sri-international-invests-in-gocharlie-ai-to-make-multimodal-ai-a-reality/) to develop a marketing-specific multi-modal model with 1B parameters.

> "One-size-fits-all models will never truly solve an end user's needs, whereas models designed to serve those needs specifically will be the most effective," explains Kostas Hatalis, the chief executive officer (CEO) and co-founder of GoCharlie. "We believe purpose-built models tailored to specific verticals, such as marketing, are crucial to understanding the genuine requirements of end users."

The open-source research community is driving a lot of innovation around smaller, purpose-built models such as Stanford's [Alpaca](https://crfm.stanford.edu/2023/03/13/alpaca.html) or Technology Innovation Institute's [Falcon 40B](https://aws.amazon.com/blogs/machine-learning/technology-innovation-institute-trains-the-state-of-the-art-falcon-llm-40b-foundation-model-on-amazon-sagemaker/). Hugging Face's [Open LLM Leaderboard](https://huggingface.co/spaces/HuggingFaceH4/open_llm_leaderboard) helps rank these open-source models across a range of general benchmarks. These smaller models deliver comparable benchmark metrics on instruction-following tasks, with a fraction of the parameter count and training resources.

As startups customize their models for domain-specific tasks, open-source FMs empower them to further customize and fine-tune their systems with their own datasets. For example, [Parameter-Efficient Fine-tuning (PEFT)](https://huggingface.co/blog/peft) solutions from Hugging Face have shown how adjusting a small number of model parameters, while freezing most other parameters of the pre-trained LLMs, can greatly decrease the computational and storage costs. Such domain adaptation based fine-tuning techniques are generally not possible with API-based proprietary FM which can limit the depth to which a startup can build a differentiated product.

Focusing usage on specific tasks also makes the FM's pre-trained knowledge across domains like mathematics, history, or medicine, generally useless to the startup. Some startups choose to intentionally limit the scope of FM to a specific domain by implementing boundaries, such as Nvidia's open-source [NeMo Guardrails](https://blogs.nvidia.com/blog/2023/04/25/ai-chatbot-guardrails-nemo/), within their models. These boundaries help to prevent models from hallucination: irrelevant, incorrect, or unexpected output.

## Inference flexibility matters

Another key consideration in model selection is how the model can be served. Open-source models, as well as self-managed proprietary models, grant the flexibility to customize how and where the models are hosted. Directly controlling a model's infrastructure can help startups ensure reliability of their applications with best practices like autoscaling and redundancy. Managing the hosting infrastructure also helps to ensure that all data generated and consumed by a model is contained to dedicated cloud environments which can adhere to security requirements set by the startup.

The smaller, purpose-built models we mentioned earlier also require less compute intensive hardware, helping startups to optimize unit economics and price performance. In a [recent experiment](https://aws.amazon.com/blogs/machine-learning/reduce-amazon-sagemaker-inference-cost-with-aws-graviton/), AWS measured up to 50% savings in inference cost when using ARM-based [AWS Graviton3](https://aws.amazon.com/ec2/graviton/) instances for open-source models relative to similar [Amazon Elastic Compute Cloud (EC2)](https://aws.amazon.com/ec2/) instances.

These AWS Graviton3 processors also use up to 60% less energy for the same performance than comparable Amazon EC2 instances, which helps startups who are considering the environmental impacts of choosing power hungry inference hardware. A [study from World Economic Forum](https://www.weforum.org/agenda/2023/04/balancing-ais-carbon-footprint-and-its-potential-for-transformative-positive-climate-impact/) detailed the energy consumption of data centers. Once considered an externality, environmental implications have risen to top of minds of many and AWS enables startups to quantify their environmental impact through offerings such as [Carbon Footprint Reporting](https://aws.amazon.com/aws-cost-management/aws-customer-carbon-footprint-tool/), which helps companies compare the energy efficiency of different hardware selections.

## Conclusion

---

## About the Author

### Aaron Melgar

Aaron empowers the AI/ML Startups & Venture Capital ecosystem at AWS, focused on early stage company growth. He is a former Founder, Series-A Product Manager, Machine Learning Director, and Strategy Consultant. He is a first-generation American who loves tennis, golf, travel, and exchanging audiobook recommendations about economics, psychology, or business.
