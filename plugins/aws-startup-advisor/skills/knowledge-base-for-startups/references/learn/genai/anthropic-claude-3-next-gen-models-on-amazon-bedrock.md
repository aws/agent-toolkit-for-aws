---
source_url: https://aws.amazon.com/startups/learn/anthropic-claude-3-next-gen-models-on-amazon-bedrock
title: "Anthropic Claude 3: Next-gen models on Amazon Bedrock"
---

## Anthropic Claude 3: Next-gen models on Amazon Bedrock

> _Author: Swami Sivasubramanian, AWS VP Database Analytics and Machine Learning_

You already know Amazon Bedrock is the easiest way to build generative AI solutions with foundation models, including as Anthropic's state-of-the-art model, Claude. And now, the next generation of Claude is here. I've made 3 separate videos covering the first launch so far, but I wanted to write a little companion piece with the key facts and quick links I think developers will be most interested in!

![The next generation of Claude coming to Amazon Bedrock Opus-Sonnet-Haiku](https://d22k7geae6sy8h.cloudfront.net/files/65fbaaeab7309a0008609fb0/8lu0oitni-image1.webp)

## 1 - Things are moving FAST

The [official AWS launch post](https://aws.amazon.com/blogs/machine-learning/unlocking-innovation-aws-and-anthropic-push-the-boundaries-of-generative-ai-together/) called "Unlocking Innovation: AWS and Anthropic push the boundaries of generative AI together" really shows the speed that the industry is moving. Anthropic first started building on AWS in 2021, and Amazon Bedrock became generally accessible in September 2023. Since then, more than 10,000 customers have been building with Amazon Bedrock, and lots are choosing to build with Claude.

## 2 - Which should you use? It depends!

The answer to a lot of questions in Machine Learning and Artificial Intelligence is often "it depends" which can be frustrating for newbies, but "it depends" is the answer for a reason - design, deployment and use cases are all super varied, so there's never going to be a single answer for what you should use. In practice, AI/ML is all about tradeoffs and looking at what you **should** use, not just what you **could** use. If you are interested in learning how to decide which model to choose on Amazon Bedrock, step 1 should always be understanding what you **could** choose, as this will make the decision process for what you **should** choose much easier.

So, it makes a lot of sense that Claude 3 is a family of 3 new models from Anthropic, not just a single release. The 3 models give you the opportunity to find the right balance of intelligence, speed and cost for your use case.

![Opus - advanced FM with top-level performance on highly complex tasks, Sonnet is an ideal balance between intelligence and speed and Haiku is fast and cost effective](https://d22k7geae6sy8h.cloudfront.net/files/65fbaaf6b7309a0008609fb1/8lu0oj3ig-image2.webp)

So, which one is "good enough" for your use case? Well - this depends on what "good enough" looks like for you! Sometimes, you might want a super advanced model for really complex tasks involving deep reasoning, so you might choose Opus. But, other times you just want to be super fast and economical, so you might choose Haiku.

Think of Sonnet like the "Goldilocks" option - a nice balance between intelligence and speed that is "just right" for a lot of things.

## 3 - Diverse Data Inputs

All 3 new models in the Anthropic Claude 3 family are trained understand both structured and unstructured data. This might not sound too interesting on the surface, but what it really means is that the models can understand more than just language - builders can now use images, charts, diagrams and more as inputs. This opens up a lot of doors for tricky problems that need to synthesize different kinds of data to solve a problem like parsing text from images in research papers or generating captions for multimedia content.

## 4 - Benchmarks

I know benchmarks are important and I tried SO HARD to get them to fit on the screen in the video I made for the AWS Machine Learning page, but it's tricky to properly communicate this information in such a short video!

So - here are the benchmarks (which also appear on the [AWS launch post](https://aws.amazon.com/blogs/machine-learning/unlocking-innovation-aws-and-anthropic-push-the-boundaries-of-generative-ai-together/) and the [Anthropic launch post](https://www.anthropic.com/news/claude-3-family)).

![Claude benchmarks for Opus Sonnet Haiku vs GPT-4, GPT-3.5, Gemini 1.0 Ultra and Gemini 1.0 Pro](https://d22k7geae6sy8h.cloudfront.net/files/65fbab67b7309a0008609fb3/8lu0olify-Graphic_anthropicblog3-jpg.webp)

## 5 - JSON as an output

This feels like a "secret menu item" because it's kind of buried in Anthropic's official launch post, but I've seen so many people on social media trying to wrestle with Foundation Models (FMs) to get JSON as outputs, so I wanted to specifically flag this here!

Great news for developers - the Claude 3 models are better at producing structured outputs like JSON, which will make them SUPER USEFUL for lots of you!

## 6 - How you can get building

Claude 3 Sonnet is available on [Amazon Bedrock](https://aws.amazon.com/bedrock/) today, so you can get building with the family of Claude 3 models from [Anthropic](https://www.anthropic.com/news/claude-3-family) right away on AWS! For full instructions on how you can get started with Anthropic's Claude 3 Sonnet in Amazon Bedrock, visit [the News Blog post](https://aws.amazon.com/blogs/aws/anthropics-claude-3-sonnet-foundation-model-is-now-available-in-amazon-bedrock/). Opus and Haiku will be available soon, so keep an eye out for them!

There's so much happening, and I can't wait to see what you all build! If there's a specific aspect you'd like me to cover in upcoming videos, articles or tutorials, send me a message on [LinkedIn](https://www.linkedin.com/in/brookejamieson/), [Twitter](https://twitter.com/brooke_jamieson), [Instagram](https://instagram.com/brooke.bytes) or [TikTok](https://www.tiktok.com/@brookebytes).
