---
source_url: https://aws.amazon.com/startups/learn/build-ai-agents-that-scale-serverless-architecture-on-aws
title: "Build AI agents that scale: Serverless architecture on AWS"
---

## Build AI agents that scale: Serverless architecture on AWS

> Source: [AWS Startups](https://startups.aws/startups/learn/build-ai-agents-that-scale-serverless-architecture-on-aws)

Building software in the generative AI era presents a paradox. On one hand, frontier knowledge models have become so powerful that creating an initial version of an AI-powered application may involve little more than calling a simple chat API (and having a coding agent write most of the code!). On the other hand, the level of accuracy, performance, and cost-optimization required by a production-grade AI application often involves a complex technical architecture.

This complexity arises in part because generative AI algorithms are probabilistic rather than deterministic. To reduce the variance in a model's output and improve reliability, developers use techniques such as providing examples of what a 'good' response looks like or including additional information ('context'), that the model can consider when generating output. As a result, the code of an AI-powered application quickly becomes a lot more complex than simple calls to the model's chat API. At a minimum, developers will need to add at least one data serving layer which includes calls to specialized databases to construct the context that will be shown to the model.

But the complexity doesn't stop there. As developers add more capabilities to their AI-powered applications, they'll often find that this requires different contexts and different sets of prompts. So developers—being drawn to abstractions—will organize the code powering these different capabilities into self-contained modules. In AI, this type of design pattern is known as an 'agent.'

## Agents assemble: overcoming complexity in generative AI

An agent is a module of code that uses generative AI models to perform a specific task autonomously. Agents can act alone or in conjunction with other agents. They can also call 'tools' which are typically APIs or functions that are included in the context available to the agent. The net result of this agentic approach to software design is that context engineering—the process of fetching the relevant data that an agent needs to complete its task—becomes more complex. Further, the agents themselves often need to run asynchronously outside the main application (this is especially true for agents that require access to sensitive data). This can require managing entirely separate runtime environments as well as credentials.

A typical agentic AI application can be broken down into the following components:

1. The generative AI model, which typically includes a large language model (LLM) and the APIs that provide access to it.
2. Software frameworks, which provide convenient abstractions to the lower-level model APIs, and software development kits for building agents and performing many of the data access operations required for context engineering.
3. Data serving components, which provide the information included in the context supplied to the agents. These can consist of a variety of different data stores (relational database management systems, NoSQL databases etc.), but will almost always include some form of a semantic search service. For agentic applications, this is typically offloaded to a vector store, which stores numeric representations of text data called embeddings.
4. A runtime environment for the agents. For simple agentic applications, the agents may run in-process with the application code. But in most cases the agents will need to run in their own process space, sandboxed from the main application.

As with all software architectures that require multiple components working together, there is a substantial amount of undifferentiated heavy lifting required to ensure these components are resilient, redundant, and performant. Fortunately, agentic AI applications benefit from the same cloud native architectures that traditional applications do. Serverless architectures are particularly attractive for agentic AI applications, and AWS offers a variety of serverless offerings that allow developers to quickly, easily, and cost-effectively build agentic AI applications.

## Inference in action

Let's start with the component that is the most well-known: the generative AI models themselves. The term for model serving is 'inference' and for serverless inference, [Amazon Bedrock](https://aws.amazon.com/bedrock/) provides a managed service for running and accessing [generative AI foundation models](https://aws.amazon.com/bedrock/model-choice/). These range from frontier-knowledge LLMs such as Anthropic's Claude, to speech-based models such as [Amazon Nova Sonic](https://aws.amazon.com/nova/models/), to open-weight models from OpenAI and Mistral, all of which can be accessed through a unified API.

Next, inference. This is typically complex and requires specialized hardware like GPUs and a deep understanding of the low-level networking frameworks that allow clusters of GPUs to communicate with one another. Traditionally this has created operational challenges and a barrier to accessibility, especially for startups. Amazon Bedrock helps break down these barriers, as users only need to learn how to use the solution's APIs.

## Embedding intelligent: Knowledge Bases and vector stores

In addition to inference and model serving, Amazon Bedrock also has full support for the most common data serving components in the agentic AI stack. [Amazon Bedrock Knowledge Bases](https://aws.amazon.com/bedrock/knowledge-bases/), for instance, can be used for semantic search, which involves searching a collection of documents that are semantically similar to the text in the query. This is critical in instances where an AI agent needs additional information in its context.

For example, a customer service agent may need to consult FAQ documents that match the information the customer is asking for, e.g. 'How do I change the address associated with my account?' Using Amazon Bedrock Knowledge Bases, FAQ documents can be indexed for semantic search by storing them in an [Amazon S3](https://aws.amazon.com/s3/) bucket and configuring that bucket as a data source for a Bedrock Knowledge Base. The service handles the 'chunking' of the documents (breaking a document into smaller parts), 'vectorizing' each chunk (creating the numeric embeddings of the text), and storing and relating the chunks and the embeddings to one another so relevant chunks can be returned in a semantic query.

Once these embeddings are created, they need to be stored in a specialized database for embeddings, or vector store. Amazon Bedrock Knowledge Bases support several vector store options, including [Amazon S3 Vectors](https://aws.amazon.com/s3/features/vectors/), a serverless vector database built into Amazon S3. This type of data serving layer is known as Retrieval Augmented Generation (RAG), and is straightforward to implement using Amazon Bedrock Knowledge Bases, S3, and S3 Vectors. This allows developers to focus on the functionality of their AI agents rather than managing complex data serving infrastructure.

## Building, running, scaling

Once embeddings are stored and accessible through vector stores, the next step is to run AI agents that use this data. [Amazon Bedrock AgentCore](https://aws.amazon.com/bedrock/agentcore/) provides a serverless runtime environment for developers. Agents can be built using frameworks like LangChain, Strands, or even something homegrown. Developers can then package the agent in a zip archive and load it to S3. Alternatively, they can build a container image and push it into [Amazon's Elastic Container Registry](https://aws.amazon.com/ecr/) (ECR). Once their code is in S3 or ECR, they can configure AgentCore to run their agent in the cloud, without needing to manage servers. AgentCore also handles operational processes such as authentication, supporting either in-built AWS Identity and Access Management roles, or JSON Web Token for signing in through a corporate identity provider.

Amazon Bedrock and AgentCore offer many more serverless capabilities, but the three detailed in this article provide the ideal starting point for developing agentic AI applications with full support for RAG. First, Amazon Bedrock for inference with a wide selection of models; second, Amazon Bedrock Knowledge Bases and S3 Vectors for document indexing and semantic search; and finally, Amazon AgentCore for running agents in a secure and cost-effective manner.

Developing agentic AI applications has traditionally been complex and challenging, especially for startups which are often operating with limited resources. Serverless architectures reduce this complexity by removing the need for engineers to build and manage underlying infrastructure. Whether you're an experienced agentic AI developer or just starting out, Amazon Bedrock provides a comprehensive set of tools and services to help you build and scale with confidence.

Ready to start building agentic AI on AWS? [AWS Activate](https://aws.amazon.com/activate/activate-landing/) offers access to [AWS Credits](/startups/credits) which can be used to offset the cost of solutions covered in this article, as well as a broad range of other services. Since its inception in 2013, AWS Activate has provided more than $8 billion in credits to startups around the world. Founders also benefit from programs and resources, technical support, business mentorship, and a closer connection with the global startup community. Join millions of others and discover how to take your ideas from concept to cloud-ready.
