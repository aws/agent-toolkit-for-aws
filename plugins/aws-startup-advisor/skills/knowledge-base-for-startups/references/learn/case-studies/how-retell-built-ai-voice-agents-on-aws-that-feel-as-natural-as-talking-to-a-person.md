---
source_url: https://aws.amazon.com/startups/learn/how-retell-built-ai-voice-agents-on-aws-that-feel-as-natural-as-talking-to-a-person
title: "From $4M to $70M in two years: How Retell built AI voice agents on AWS that feel as natural as talking to a person"
---

## From $4M to $70M in two years: How Retell built AI voice agents on AWS that feel as natural as talking to a person

[Watch the video on YouTube](https://www.youtube.com/watch?v=_gF8syYr4yM)

[Retell](https://www.retellai.com/) is a conversational AI platform that allows businesses to create humanlike conversations with their customers. Running its entire infrastructure on AWS, the startup relies on services like [Amazon DynamoDB](https://aws.amazon.com/dynamodb/), [Amazon ElastiCache](https://aws.amazon.com/elasticache/), and [Amazon Elastic Container Service (ECS)](https://aws.amazon.com/ecs/) to ensure low-latency, consistent, and reliable communications at scale.

---

When customers call a business for support, they expect an immediate, natural conversation. “They want something snappy. They want something that feels instant and conversational,” says Zexia Zhang, Co-founder and CTO at Retell. Managing these higher demands from greater numbers of customers traditionally required companies to scale human operations. As a result, “There's a lot of management pain. There's a lot of training overhead. And you probably have to open up a lot of different locations to cover more time zones,” says Zhang.

Retell is helping businesses deliver a more scalable approach. For its customer Anker, Retell’s AI resolves 80 percent of customer support cases, all while maintaining a net promoter score of 63 across live support calls in the US and UK.

### Humanlike, voice-first, real-time & 24/7

Built on AWS, Retell’s LLM-based, humanlike, voice-first conversational AI platform enables businesses to communicate in real time with their customers. AI agents respond naturally, ask follow-up questions, look up information, carry out tasks or transfer the call to a human when needed. “The AI agent is consistent in quality. It's not going to be impacted by emotions. It's there 24/7. And it's a lot cheaper as well,” says Zhang. Freed from the need to invest in expensive physical infrastructure, Retell’s customers “can now scale their businesses and operations a lot faster.”

People may want “something snappy” from businesses they engage with, but alongside speed they also want reliability and accuracy from these engagements. Unlike many legacy solutions which feature pre-recorded messages and are mostly used for routing purposes, Retell’s platform delivers “an end-to-end conversation,” says Zhang. “A lot of the time the end user cannot even tell it's AI. And it's able to plug into businesses' workflows and systems and conduct actions that actually get things done.” The platform can access a business’s internal system, retrieve relevant data, evaluate it, and based on its findings deliver meaningful results, all at a fraction of the time it would traditionally take a human to do this same process.

### How they architected for speed

Retell set itself high standards when selecting an infrastructure provider, seeking a partner that could help it deliver the best possible experience for its customers and their end-customers. “We don't compromise to solutions that just barely work and we don't compromise to infrastructure that maybe works,” says Zhang. “We value quality, we value the product, and that's something that we're really proud of. We're trying our best to push the best quality we can build in the fastest manner.” And AWS, he continues, “satisfies all our needs.”

Retell runs its entire infrastructure on AWS and is “deeply embedded in the AWS ecosystem,” says Zhang. It uses Amazon DynamoDB, a serverless, fully managed, distributed NoSQL database with single-digit millisecond performance at scale. For caching, it relies on Amazon ElastiCache, which together with Amazon DynamoDB “provides us with pretty fast retrievals for anything, so when a call comes in we go into those services to get the data and configurations needed.”

It builds, manages, and runs containerized applications with Amazon ECS[](https://aws.amazon.com/ecs/), enabling it to scale up and down at speed to support ‘golden hours,’ the key moments during the day when a business experiences a high call load. Latency was another factor that was critical to the platform’s success. Building the solution from the ground up meant every element had to be low latency: “you cannot have any single pipeline that’s taking very long,” says Zhang. Locating “a lot of things within AWS” has helped Retell achieve this low latency; with GPU and CPU clusters located in the same data center, “you don’t have to travel outside of the network.”

### Pushing forward

Retell's growth has been rapid. In 2024, the startup ended the year at around $4 million in annualized revenue. By the end of 2025, that hit $40 million. "And right now we are around $70 million," says Zhang. The team size has doubled from 20 to 40, and traffic has increased 10x.

That kind of growth puts pressure on infrastructure. "We're seeing everything starting to expand," says Zhang. "We need more IP addresses. We need more instances. We need more GPUs." AWS has kept pace since the early days, when participating in [AWS Activate](https://startups.aws.com/join) allowed Retell to focus on product rather than operational costs. "It enabled us to not worry about any operational costs and just keep focusing on building the business, building the product, talking to customers," says Zhang.

The relationship has deepened as Retell has scaled. "We're able to, for example, get engineers from AWS to jump on the call with us, to troubleshoot something in production," says Zhang. "That really helps us to push forward." Now, Retell is unlocking new use cases with additional GPU capacity from AWS and working toward a listing on [AWS Marketplace](https://aws.amazon.com/marketplace/) to widen its reach and accelerate sales cycles. "AWS is our biggest infrastructure provider and we are going to continue to keep investing in this," says Zhang. "There are a lot more things that we're going to achieve together."
