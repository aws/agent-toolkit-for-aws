---
source_url: https://aws.amazon.com/startups/learn/securing-justice-in-the-cloud-predictice-and-aws-transform-legal-work
title: "Securing justice in the cloud: Predictice and AWS transform legal work"
---

## Securing justice in the cloud: Predictice and AWS transform legal work

> _AWS Startups Customer Story_

![Predictice](https://d22k7geae6sy8h.cloudfront.net/files/68c7f07b5a0de3000cd61038/Predictice+2.jpg)

The arrival of generative AI has made gathering knowledge and making sense of this information faster and simpler for professionals in a multitude of sectors. For some, all this requires is a basic AI platform. However, when information is dense and complex and the sector is governed by strict security and ethical frameworks, deploying AI—and using it effectively—is a challenge. Nowhere is this more evident than in the legal sector.

[Predictice](https://predictice.com/) was founded in 2016 with a clear mission: "to automate low value tasks such as document reviews, legal research, and drafting, so professionals can focus on their expertise," says Vivien Douard, Content Marketing Officer, Predictice. Working with AWS, the company has created a secure and highly specialized solution for its customers, enabling those working in the sector to harness the benefits of AI and "make legal work faster and more efficient."

The partnership with AWS began in 2024, driven by the need for ultra-secure solutions, rapid database integration, and scalability. It was important to Predictice that its AI model and data be hosted in Europe, to meet the expectations of its customer base in France and Luxembourg and comply with data protection and security regulations.

Predictice migrated to [Anthropic Claude](https://aws.amazon.com/bedrock/anthropic/) on [Amazon Bedrock](https://aws.amazon.com/bedrock/) and utilized [Amazon OpenSearch Service](https://aws.amazon.com/opensearch-service/) for its search engine. It also adopted [Cohere Embed v4](https://cohere.com/blog/embed-4) on [Amazon SageMaker JumpStart](https://aws.amazon.com/sagemaker-ai/jumpstart/) to generate document processing embeddings that are indexed and stored as vectors in Amazon OpenSearch Service.

Predictice was already on a solid start before the migration, as a pioneer in the use of Retrieval Augmented Generation (RAG) in the legal sector. In 2023, it became the first company in France to launch a RAG AI platform specifically for legal professionals. Through the collaboration with AWS, Predictice has now built a comprehensive legal toolbox that enables the kind of transformative impacts of AI already experienced by those working in other fields. Crucially, it also offers the advanced security and specialized feature set that legal professionals require to adopt and use the technology with confidence.

## Motion denied: The challenges of AI integration

Those working in the legal sector play a critical role in societies by upholding the rule of law, protecting rights, providing access to justice, and facilitating effective governance. However, unlike other professionals, this group—which includes solicitors, judges, paralegals and more—conducts business not only in their native tongue but in a secondary language. 'Legalese' is rooted in centuries of legal history and incorporates Latin words, archaic structures, and phrasing long since out of use in everyday speech. This way of communicating ensures precision and formality, but also means that documentation can be technical and complex. "The legal field is data rich but underleveraged by traditional tools," says Douard.

The sector has historically been slow to adopt AI, due in part to its dependence on documentation and need for highly-accurate information. Such decisions are based on precedents outlined in specific texts, and new rules, amendments, and interpretations are continuously evolving. Security of infrastructure is also critical. "The main challenge at the beginning," says Douard, "was to convince them that they could trust AI."

This environment presented a dual challenge. Legal professionals must monitor and have access to a huge volume of documentation, while any technology they use must be capable of interpreting sector-specific data and providing verifiable answers to queries. For Predictice's customers, AI tools have to be highly secure and tailored to the Francophone—and legalese!—market.

## Translating legal complexity into actionable intelligence

Predictice partnered with AWS to create a solution which is solving this challenge. The platform provides access to a database of over 60 million documents as well as connecting to users' own internal databases. "This allows us to deliver highly relevant and reliable result data to legal professionals," says Douard. With an AI-powered search engine, the platform eases critical processes like information discovery, analysis, summarization, and reporting, all accessible within a single solution. The technology is also straightforward to deploy: "Predictice integrates directly into the tools that lawyers already use," says Douard, and as such "we offer our customers an optimal user experience thanks to the seamless integration of the AI directly in their work environment."

Predictice offers a bespoke approach to meet the needs of French-speaking customers operating in the region. "Unlike generic AI our assistant is trained on millions of French legal decisions, regulations, and collective agreements," says Douard. Crucially, the platform also features a translation tool allowing legal teams to accurately interpret information from global sources. "They can download documents, contracts for instance, and then translate them into 30 languages in around 10 seconds," says Douard.

## A 'complete solution' for security

![Predictice](https://d22k7geae6sy8h.cloudfront.net/files/68c7f38092af47000bc9826d/Predictice+1+%282%29.jpg)

Security was a priority when Predictice set out to build its platform. "It's very important, we cannot have data leaks from our customers," says Thibaud. Deploying a solution in the EU required the company to adhere to strict data protection laws and protocols, such as the General Data Protection Regulation (GDPR). Transferring data out of the region meanwhile requires specific legal safeguards. Predictice's legacy infrastructure was limiting in this regard, so when Anthropic's Claude Sonnet 4 launched on Amazon Bedrock earlier this year, the company seized it as the perfect opportunity to migrate to AWS. "Claude is winning in Europe!" says Thibaud.

Claude Sonnet 4 is a hybrid reasoning model designed for the next generation of autonomous AI agents. Using Amazon Bedrock made it "very easy to switch between models," says Thibaud, enabling it to enhance the platform whilst keeping security front of mind. When legal professionals upload documents, that data is stored on the platform, and "this is why we moved and transferred all data to AWS, for security, and because we can encrypt data at rest," explains Thibaud. Building on Amazon Bedrock provides this functionality as well as encrypting data in transit and offering security tools that have helped Predictice improve customer trust, giving the company a "marketing and commercial advantage."

A key element of this was gaining ISO 27001 certification (for customer data, hosted on AWS), from the International Organization for Standardization (ISO), demonstrating that infrastructure adheres to a strict—and globally recognized—safety and security framework. "The certification is really complex and requires a lot of documentation," says Thibaud. Predictice navigated this complexity with support from AWS, which offered a "complete solution" and "security hub," enabling it to "deliver proof that all data is really secure. That impressed me," he continued, "without it, we cannot have the certification."

## Meeting evolving expectations at speed

As Predictice grew, so too did its data requirements. As such, the company adopted Amazon OpenSearch Service, enabling it to store, search, and analyze large volumes of data in near real-time. "The migration was really smooth," says Thibaud. It was also cost-effective, as Predictice used promotional credits available through the [AWS Migration Acceleration Program](https://aws.amazon.com/migration-acceleration-program/), to offset costs of AWS solutions. AWS "helped us with the migration and offered technical advice," he adds. "The relationship was very good."

Predictice is tasked with managing a huge database which includes seven million case law documents with 16,000 tokens each. To vectorize this database Predictice is also using [Cohere Embed v4](https://cohere.com/blog/embed-4) via Amazon SageMaker JumpStart, a machine learning (ML) hub designed to accelerate the deployment of ML solutions.

Migrating to the Amazon OpenSearch service has dramatically improved the speed of operations and reduced complexity for Predictice. "Before, managing our cluster was not simple," explains Thibaud, requiring the team to "verify and upgrade the cluster every two or three weeks. With OpenSearch we just have to click a button." Using OpenSearch also unlocks easier scalability. A "typical example," says Thibaud, "was this morning; we wanted to integrate a new database, but we did not have free space available." He continues, "before, if we had to do that, we had to command a new machine and new server, wait, install it. It took about two days." Now, adding space on OpenSearch is "very fast" reducing the timeline to "a few minutes."

Amazon Bedrock is regularly updated with the latest AI models, which has helped Predictice further enhance its solution; it's currently in the process of migrating to Claude Sonnet 4 to improve its legal RAG search service.

## The verdict is in: AI success

Today, "over 5,000 legal professionals use Predictice on a daily basis," says Douard, who benefit from "the generative AI search engine that can answer any legal question." Choosing AWS solutions and integrating a database of millions of documents has meant the company "can make a real difference to the quality of the answers" teams are seeking.

Around 60 to 70 percent of Predictice's customers are law firms, ranging from sole practitioners to large organizations. However, the startup is seeing growing demand for its solution in the corporate sector, particularly in the insurance industry. Gaining market visibility plays a role here, and Predictice benefitted from an opportunity granted by AWS to present at VivaTech, Europe's largest startup and technology event.

Predictice's continuing relationship with AWS supports the company's ambitions to evolve its platform to meet the future needs of its customers. "The expectations around legal AI will keep rising," says Douard. Using AWS solutions allows the company to "prepare advanced features for auditing with transparency, performance, and security, as top priorities." With the right solutions, support, and potential for scalability, Predictice has proven beyond reasonable doubt that "contrary to some generic tools in the market, we can make a difference to secure the work of professionals in the legal sector," concludes Douard.

---

_Source: [AWS Startups](/startups/learn)_
