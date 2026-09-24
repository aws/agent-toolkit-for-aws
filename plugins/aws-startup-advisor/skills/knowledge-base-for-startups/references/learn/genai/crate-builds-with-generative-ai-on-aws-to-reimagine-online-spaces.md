---
source_url: https://aws.amazon.com/startups/learn/crate-builds-with-generative-ai-on-aws-to-reimagine-online-spaces
title: "Crate builds with generative AI on AWS to reimagine online spaces"
---

## Crate builds with generative AI on AWS to reimagine online spaces

> Anna Bofa's ambition for Crate is to create an internet where the user does not go out looking for content—the best of the internet comes to them.

Previous generations filled their attics with boxes of pictures, clothing, and souvenirs as memories of their lives. Today, more and more memorabilia lives online as texts, images, videos, snippets of poetry, chat comments, and more. This media from personal corners of the internet requires an entirely new kind of storage: Spaces created not with physical tools, but through lines of code by companies like [Crate](https://www.crate.co/).

Crate, founded in 2021 by chief executive officer (CEO) Anna Bofa and built on Amazon Web Services (AWS), offers an online storage system inclusive of all forms of digital artifacts. With the Crate app, TikToks can live alongside photos, music tracks, news articles, and more. These "crates" are shareable collections of content you collect from different platforms, all organized and powered by personalized artificial intelligence (AI). The company was born of Anna's belief that, at its core, the internet is a collection of content and people.

> "In my early thinking about Crate, I wanted to provide easy opportunities for people to connect over content in joyful ways," says Anna. "I envisioned a shared happy place away from some of the more negative aspects of social media."

"We like to say that we see crates everywhere. For example, you can make a crate of articles that really resonate with you or a crate of all the places you want to visit. You can add recommendations from friends, and store it all in one place," Anna explains.

For any given crate, the app generates a cover, title, and tag, while also using AI-generated language models to build a personalized understanding of a user's preferences and interests. Anna's ambition for Crate is to create an internet in which the user does not go out looking for content. Rather, the best of the internet's digital assets come to them.

## Proving what's possible with generative AI

Through her experience working at Google, Facebook, and multiple startups, Anna is well aware of the power of AI to transform the internet. "What we do with AI in the early days really matters because it will be the foundation for everything else," she explains. Using generative AI to raise the bar on Crate's product has been a key component of the startup's success.

The Crate team is proving it's possible to generate content across multiple mediums–such as the text and images for crates—via one easy-to-use interface, while also personalizing media suggestions based on your saved content. For example, let's say you're interested in urban gardening. You save relevant digital content of any sort to your gardening crate. Based on that collection, Crate will then automatically go out and find additional gardening content for you. With Crate, the idea is that you don't have to be a prompt engineer to gather content that matters.

Anna sees Crate as offering a solution to what she believes is the internet's biggest problem: information overload.

"It used to be that you went online to read the morning news, check Facebook or Tumblr. Now, with everything online, the magic of the internet is also its biggest pain point because the amount of information is overwhelming and fragmented."

Crate is working to change that by making the abundance of online content more manageable and enjoyable, simplifying the user's experience. Or, in Anna's words, the app is "bringing the magic back."

## Accelerating success with AWS

From the beginning, Anna and the Crate team have relied on AWS for support—whether that's technical solutions, business expertise, or networking opportunities. "As a startup, we literally could not have built our product without AWS," explains Anna.

### Building with AWS solutions

From a technical perspective, Crate's entire infrastructure is built on AWS. Crate's ability to save content from anywhere across the web and organize it using AI-powered automation occurs via two distinct stages: content ingestion (pre-processing and indexing, which happens in the background after a user saves a piece of content) and downstream tasks (organizational features that are facilitated by the processes that take place during content ingestion). While Crate leverages AWS solutions for both stages, content ingestion is the most computationally intensive part of their product and an area where they've greatly benefitted from building with AWS services.

Content ingestion is an event-driven process facilitated by [Amazon Kinesis](https://aws.amazon.com/kinesis/) and step functions, which entails a number of steps, including: content retrieval; image captioning, performed using a model hosted in [Amazon SageMaker](https://aws.amazon.com/sagemaker/); video transcription using [Amazon Transcribe](https://aws.amazon.com/transcribe/); content summarization; the generation of semantic embedding vectors, stored OpenSearch to support semantic search and clustering, and more.

Each step happens asynchronously, triggered by events that are sent and via Kinesis and made even more robust with the use of [Amazon Simple Queue Service (Amazon SQS)](https://aws.amazon.com/sqs/), in the case of a failure in one of the steps. Additionally, most of the steps run in [AWS Lambda](https://aws.amazon.com/lambda/) functions, which are cost-effective and enable efficient deployment and iteration.

Kinesis is particularly critical to Crate's tech stack because it enables the asynchronous processing of data in a robust and decoupled manner, allowing them to add or remove steps easily. Additionally, the Crate team shares that SageMaker is also useful for deploying smaller models in a hassle-free, robust way that saves their small team much time.

> What Anna finds beautiful about building on AWS is that "everything is already built and we don't have to spend time on the heavy lifting." She adds: "AWS understands how systems come together—no matter what our need, AWS has something to meet it."

### Leveraging AWS programs

As a member of [AWS Activate](https://aws.amazon.com/startups), a program for startups offering technical support, architecture guidance, and cloud credits, Crate has had access to the technologies and technical expertise it has needed. With AWS Activate's technical support and credits, Crate has been able to grow to where the company can now effectively begin to monetize or raise funds. "As a founder, I'm always thinking about costs," says Anna. "We've been fortunate to benefit from credits through multiple AWS programs. It's been transformative for leveling the playing field and allowing us to build a competitive product."

Along with AWS Activate, Crate also participated in the [AWS Generative AI Accelerator](https://aws.amazon.com/blogs/startups/aws-launches-global-generative-ai-accelerator-for-startups/), a 10-week program designed to take the most promising AI startups globally to the next level. It provides access to AI models and tools, customized business strategies, machine learning stack optimization, and more. On the business side, the accelerator connects entrepreneurs to investors, customers, experts, and networking opportunities.

> "One of the most important benefits of the AWS Generative AI Accelerator was being able to talk directly with Amazon's internal talent," says Anna. "We had a biweekly call with AWS engineers. They helped us build things we hadn't been able to build before."

Anna's goal in the accelerator program was to launch the Crate beta app and come out of stealth mode. She met that goal, launching Crate in app stores the day after the program finished. "The accelerator also introduced us to investors, which has really helped," explains Anna.

## Envisioning the future of Crate

As the Crate team continues to seek more efficient ways to scale their product and delight their users, Anna plans to move more of the app's stack to AWS. The Crate team has tested [Amazon Bedrock](https://aws.amazon.com/bedrock/), for instance–a fully managed service that offers a choice of high-performing foundation models (FMs) from leading AI companies through a single API, simplifying development while maintaining privacy and security. Crate is now in beta and available for early users to try.

Anna believes that the potential for AI to revolutionize how we live and work is unparalleled, and startups will lead the way. To other founders, she advises, "Dive in. Explore the potential. Participate in AI communities and discussions. Envision a positive future for AI and build toward it."

---

> _Author: Megan Crowley_

Megan Crowley is a Senior Technical Writer on the Startup Content Team at AWS. With an earlier career as a high school English teacher, she is driven by a relentless enthusiasm for contributing to content that is equal parts educational and inspirational. Sharing startups' stories with the world is the most rewarding part of her role at AWS. In her spare time, Megan can be found woodworking, in the garden, and at antique markets.
