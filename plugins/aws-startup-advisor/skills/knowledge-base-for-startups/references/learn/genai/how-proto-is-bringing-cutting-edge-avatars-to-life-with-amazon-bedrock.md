---
source_url: https://aws.amazon.com/startups/learn/how-proto-is-bringing-cutting-edge-avatars-to-life-with-amazon-bedrock
title: "How Proto is bringing cutting-edge avatars to life with Amazon Bedrock"
---

## How Proto is bringing cutting-edge avatars to life with Amazon Bedrock

A patient in Australia requires urgent specialist care from a doctor in the UK. A robotics firm needs to demo its latest invention to potential investors without the hassle of transporting machinery. A new hotel wants to wow guests with a premium experience. [Proto](https://protohologram.com/) is enabling all of these things and more – with holograms powered by [generative AI](https://aws.amazon.com/generative-ai/).

Proto harnesses generative artificial intelligence (AI) to create realistic avatars which are beamed into an impressive 7ft hologram machine, where they can engage in authentic conversation, provide information, assist with tasks and entertain. They're already live in industries like advertising and retail, entertainment, transportation, hospitality, education, training, and healthcare, serving Fortune 500 companies and some of the world's best-known sports teams and celebrities.

So, that patient needing urgent care can be assessed remotely by a specialist thousands of miles away. The robotics firm can show off its latest product without having to navigate the cost and complexity of exporting expensive kit. And the hotel can welcome guests with life-size chatbots and provide a personalized digital concierge service to set its business apart from the competition.

Each of these use cases have characteristics (e.g., costs, latency, accuracy) that require [choosing one foundational model](https://aws.amazon.com/startups/learn/selecting-the-right-foundation-model-for-your-startup) (FM) over another. As such, Proto needed a solution that facilitated the experimentation, testing, and adaption of AI-enhanced avatars based on their particular use case. Migrating to [Amazon Bedrock](https://aws.amazon.com/bedrock/) provided this solution, giving Proto access to a wide choice of FMs which can be evaluated, experimented with, deployed and customized with ease.

## Improving and streamlining with Amazon Bedrock

Despite being a leader in its field, market demand for lower latency, greater realism, and more accuracy in engagements meant Proto was looking for a way to improve its AI avatars. Proto's avatars can be broadcast to thousands of viewers or personalized to a single person, relay real-time information, or deliver high-level training. Whatever their purpose or industry, they must provide a sophisticated level of realism, accuracy and security while delivering an avatar persona adapted to the use case. For example, a virtual hotel concierge would require specific fine-tuning to enhance the experience of guests while a virtual art teacher needs flexibility to process language into pictures.

Crucially, Proto also wanted to streamline the process of building and managing applications. This had been complicated by Proto's use of different services and tools in the past: it was using a suite of AWS services but building using another provider.

Generative AI is a rapidly evolving space, demanding players continue to innovate their products and best serve their customers. This requires human time and resources, supported by flexible tools that can help with the heavy lifting. Fragmented across multiple solutions, Proto's legacy environment made it difficult to manage existing AWS services and deploy new ones. With an Amazon Bedrock-based approach, Proto is able to continuously iterate on its avatars and adapt them based on real-time user interactions. This helps ensure that the content is always appropriate for any given context. For example, Proto can decide in the moment if a certain topic is appropriate or not and set up guidelines – known as guardrails – mid-interaction to keep these engagements safe.

These factors, as well as the need for the latest in generative AI tools, prompted Proto's decision to migrate to [Anthropic's Claude on Amazon Bedrock](https://aws.amazon.com/startups/learn/anthropic-claude-3-next-gen-models-on-amazon-bedrock). This enabled the company to improve its AI avatars and the processes used to create them.

## Why Amazon Bedrock

Amazon Bedrock is a fully managed service that offers a choice of high-performing foundation models through a single API, alongside a broad set of capabilities to help startups build generative AI applications with security, privacy, and responsible AI.

Amazon Bedrock allows users to easily experiment with and evaluate top FMs for a variety of use cases, privately customize them with their own data using techniques such as fine-tuning and [Retrieval Augmented Generation (RAG)](https://aws.amazon.com/startups/learn/serverless-retrieval-augmented-generation-on-aws), and build agents that execute tasks using their own enterprise systems and data sources.

Amazon Bedrock is also serverless, meaning startups don't have to manage any infrastructure, and can securely integrate and deploy generative AI capabilities into applications using the AWS services they are already familiar with.

## The mechanics of the migration

Proto migrated to Amazon Bedrock and chose Anthropic's Claude Instant, an FM available on Amazon Bedrock, to demonstrate a conversational avatar at a major conference. It fine-tuned this model to optimize its AI avatar, putting guardrails in place to ensure interactions were appropriate for the setting, audience, and context.

Amazon Bedrock allowed Proto to test the performance of various FMs before progressing to the next stage of development, meaning it could pick the most cost-effective solution for each use case. This was a straightforward process, so didn't impact on workflow or deployment pipelines – both critical for startups wanting to stay at the forefront of AI development. As Raffi Kryszek, Chief Product and AI Officer at Proto explains, "_Amazon Bedrock allowed us to test the performance of our avatar when sourced from different foundational models by only changing one line of code._"

Proto also deployed [Amazon Polly](https://aws.amazon.com/polly/), a cloud service that converts text to lifelike speech, and [Amazon Transcribe](https://aws.amazon.com/transcribe/), a speech recognition service that automatically converts speech into text. This provides them with the agility to adapt their solution to support conversation in different languages such as Japanese, Korean, and Spanish.

In addition to the range of services offered, the specific capabilities of Amazon Bedrock both ensured a smooth process during the migration and allowed Proto to rapidly adapt and take advantage of the latest generative AI tools as it grows.

The crux of the migration was focused on API reconfiguration. This required a deep dive into the internal workings of both systems to ensure seamless communication between Proto's user interface and Amazon Bedrock services. Proto's technical team was able to quickly refactor their code using Amazon Bedrock APIs, and used Claude's specific prompt formatting technique to increase the quality of the avatar responses.

The migration signalled a pivotal shift in Proto's approach to inference parameter customization, whereby parameters are adjusted to control the responses of the model. The process involved comprehensive use of Amazon Bedrock's API capabilities, with the team leveraging its extensive configuration options for fine-tuning response generation. This included temperature and top K settings.

Better handling of temperature allows for more nuanced control of creativity versus fidelity. For an informational AI avatar, such as one used by a healthcare company to provide medical information, Proto can opt for a lower temperature setting, prioritizing accuracy and relevancy. Being able to adjust temperature in this way means Proto can take a more nuanced approach to meeting the needs of different customers deploying different kinds of AI avatars. Importantly, its team can do this far faster and more easily than in the past, as Amazon Bedrock reduces the technical demands placed on its users.

Proto can also be more precise in the calibration process when it comes to controlling top K settings. Like temperature, the top k setting is another category of inference parameter which can be adjusted to limit or influence the model response.

Top K is the number of most-likely options that a model considers for the next token in a sequence. This could be the next word in a sentence, which makes the top-k setting critical in controlling text generation and ensuring that text is coherent and accurate. Lowering the value reduces the size of the pool of options the model can choose from to the most likely options. This might be used for more predictable and focused outputs, like technical documentation. A higher value increases the size of this pool and allows the model to consider less likely options. This could be used for creative storytelling, where a wider variety of word choices is desirable to enhance the narrative's richness and unpredictability.

Leveraging this feature allowed Proto to optimize performance and quality by carefully customizing outputs for different AI avatars, depending on their use case.

Finally, Proto benefitted from Claude's prompt engineering capabilities. The team developed a set of best practices for parameter tuning, enhancing the AI's responsiveness and relevance. This bespoke approach underscores the importance of understanding the underlying AI model's capabilities and constraints, ensuring that developers can fully harness the technology to meet specific requirements of the AI avatar they're deploying, its audience and their needs.

## High-level architecture implementation

Using Amazon Bedrock allowed Proto to improve how AI avatars respond to user queries. The architecture starts with a user posing a question that is then directed to Amazon Bedrock. The RAG process merges real-time user inputs with deep insights from Proto's proprietary data as well as external data repositories. This helps generate prompts that are both precise and relevant, resulting in conversation which is personalized to the user posing the query.

Proto was able to choose the chunk sizes of embeddings, which allows for more or less information to be used in the responses provided by its AI avatars. Smaller embeddings are best used for applications like a personal assistant, allowing it to add many memories into the prompt. On the other hand, larger embeddings are more useful when the documents are separated in a way that the information is not scattered throughout.

Once the prompt is augmented, it is processed by a selection of advanced AI models, including Claude. Within each Proto application, a unique avatar ID directs these queries, enabling precise and contextually aware responses by consulting the appropriate database.

Responses are then sent to Amazon Polly to ensure that each word spoken by its avatars is not only visually represented with precise lip syncing but also delivered at high speed, resulting in responses that are both visually and interactively seamless. The AI avatar looks more like a human when it talks to its user, and conversation is as close to real-time as possible.

## Conclusion

As a result of the migration, Proto is now using the most cutting-edge generative AI tools to provide the most innovative generative AI applications to its customers. As a fully managed service, switching to Amazon Bedrock meant Proto's team didn't have to spend time re-architecting their solutions to support multiple foundational models. The team is now freed up to focus on what matters: building, scaling and optimizing products to adapt to their end users' needs – and growing their startup as a result.

The optimization of those products is already clear: by focusing on API reconfiguration as part of the managed migration, Proto has enhanced its avatars' capabilities, ensuring they remain at the forefront of conversational AI technology. Tailoring these to different sectors – and the speed at which it can do so – allows the company to better serve a wide customer base and extend its reach into multiple industries at a competitive speed.

Migrating workloads and applications to AWS is just the beginning. Proto has taken this one step further, adapting and taking advantage of AWS' generative AI capabilities. It's now using these throughout its workflow: from tinkering with tools from leaders in the field, to deploying the tech that creates meaningful engagements for its customers.

In migrating to AWS it's lightened the (technical) load for its team while expanding their creative abilities, and is more easily building, scaling and deploying its own gen AI applications with security, privacy and responsible AI. Whether you're a startup looking to begin your journey with generative AI, or you want to optimize and enhance your current workflow and products, the [AWS Migration Acceleration Program](https://aws.amazon.com/migration-acceleration-program/) can help you explore your options, and discover more about how Amazon Bedrock can work for you.

> _With contributing writing from Shaun Wang and Tony Gabriel Silva_

---

## Authors

### Aymen Saidi

Aymen is a Principal Solutions Architect in the AWS EC2 team, where he specializes in cloud transformation, service automation, network analytics, and 5G architecture. He's passionate about developing new capabilities for customers to help them be at the forefront of emerging technologies. In particular, Aymen enjoys exploring applications of AI/ML to drive greater automation, efficiency, and insights. By leveraging AWS's AI/ML services, he works with customers on innovative solutions that utilize these advanced techniques to transform their network and business operations.

### Hrushikesh Gangur

Hrushikesh Gangur is a Principal Solutions Architect for AI/ML startups with expertise in both AWS machine learning and networking services. He helps startups building generative AI, autonomous vehicles, and ML platforms to run their business efficiently and effectively on AWS.

### Nolan Cassidy

Nolan Cassidy is the Lead R & D Engineer at Proto Hologram, specializing in holographic spatial technology. His pioneering work integrates AI and advanced communication systems to develop low-latency, highly interactive experiences, enabling users to feel present in one location while physically being in another.
