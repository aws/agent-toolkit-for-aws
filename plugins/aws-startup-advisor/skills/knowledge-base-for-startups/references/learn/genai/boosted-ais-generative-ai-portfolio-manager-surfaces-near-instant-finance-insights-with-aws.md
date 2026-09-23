---
source_url: https://aws.amazon.com/startups/learn/boosted-ais-generative-ai-portfolio-manager-surfaces-near-instant-finance-insights-with-aws
title: "Boosted.ai's generative AI portfolio manager surfaces near-instant finance insights with AWS"
---

## Boosted.ai's generative AI portfolio manager surfaces near-instant finance insights with AWS

_By switching from a generic LLM that was too expansive and cumbersome for their needs to a model tailored to their domain (capital markets), Boosted.ai reduced costs by 90 percent, vastly improved efficiency, and unlocked the GPU capacity needed to scale their generative AI investment management application._

## Summary

In 2020, [Boosted.ai](https://boosted.ai/) expanded their artificial intelligence (AI)-powered financial analysis platform—[Boosted Insights](https://boosted.ai/boosted-ai-for-institutional-investors/)—by building an AI portfolio assistant for asset managers on a large language model (LLM) that processed data from 150,000 sources. The output was macro insights and market trend analysis on over 60,000 stocks across every global equity market (North America, EU & UK, APAC, Middle East, Latin America, and India). But using an LLM came with some significant drawbacks—a high annual cost to operate and GPU capacity limitations that limited their ability to scale.

Boosted.ai began domain-optimizing a model running on AWS and:

- reduced costs by 90 percent without sacrificing quality
- moved from overnight to near real-time updates, unlocking more value for their investment manager clients acting on hundreds of thousands of data sources
- improved security and personalization with the ability to run a model in a customer's private cloud, rather than running workloads through an LLM cloud

## Introduction

2023 was the year generative AI went mainstream. Enhancing efficiency to do more with less will continue to be on corporate agendas throughout 2024 and beyond. It is critical for teams to have a strategy for how they will incorporate generative AI to create productivity gains. However, even when there's a clear use case, it's not always apparent how to implement generative AI in a way that makes sense for a business's bottom line.

Here's how Boosted.ai incorporated generative AI to automate research tasks for their investment management clients in a way that improved outcomes for both Boosted.ai and their customers.

Founded in 2017, Boosted.ai offers an AI and machine learning (ML) platform—Boosted Insights—to help asset managers sort through data to enhance their efficiency, improve their portfolio metrics, and make better, data-driven decisions. When the founders saw the impact of powerful LLMs, they decided to use a closed-source LLM to build an AI-powered portfolio management assistant. Overnight, it would process millions of documents from 150,000 sources, including nontraditional datasets like SEC filings such as 10Ks and 10Qs, earnings calls, trade publications, international news, local news, even fashion. After all, if you're talking about a company like Shein going public, a _Vogue_ article could become relevant investing information. Boosted Insights summarized and collated all this information into an interactive user interface that their asset manager clients could sort through themselves.

With their new generative AI model, Boosted.ai was now pushing critical investment information to all their clients, over 180 of the world's biggest asset managers. For these teams, time is money. When something impacts a company's stock price, how fast someone gets and acts on that information can be the difference of thousands, even millions of dollars. Boosted.ai gave these managers an edge. For instance, it flagged that Apple was moving some of its manufacturing capabilities into India before news broke in mainstream media outlets, because Boosted Insights was reading articles in Indian media.

Adding a generative AI component to Boosted Insights automated a lot of the research to turn an investing hypothesis into an actual trade. For instance, if an investor was concerned about a trade war with China, they could ask Boosted Insights: "What are the kinds of stocks I should buy or sell?" Before generative AI, answering that question was a 40-hour research process, sifting through hundreds of pages of analyst reports, news articles, and earnings summaries. With an AI-powered portfolio management assistant, 80 percent of that work was now automated.

## Solving for scale with domain-specific language models

Boosted.ai's generative AI rollout was extremely well received by clients, but the company wanted to scale it to run up to 5x or 10x more analysis and get from overnight reports to a true real-time system. But there was a problem: running the AI cost nearly $1 million a year in fees, and even if they wanted to buy more GPU capacity, they simply couldn't. There just wasn't enough GPU capacity for their AI financial analysis tool to scale into a real-time application.

## Right-sizing the model for lower costs and greater scale

Boosted.ai's challenges are increasingly common ones for organizations adopting LLMs and generative AI. Since LLMs are trained for general purpose use, the companies that train these models spend a lot of time, testing, and money to get them to work. The larger the model, the more accelerated compute it has to use on every request. As a result, for most organizations, including Boosted.ai, it is just not viable to use an LLM for a specific task.

Boosted.ai decided to explore a more targeted and cost-effective approach: fine-tuning a smaller language model to perform a specific task. In the AI/ML world, these models are often referred to as "open source," but that doesn't mean they are hacked together by random people sharing a wiki, as you might imagine from the early days of open-source coding. Instead, open-source language models, like [Meta's Llama 2](https://aws.amazon.com/bedrock/llama/), are trained on trillions of data points and maintained in secure environments like [Amazon Bedrock](https://aws.amazon.com/bedrock/). The difference is an open-source model gives users total access to its parameters and the option to fine-tune them for specific tasks. Closed-source LLMs, by contrast, are a black box that don't allow for the kind of customization Boosted.ai needed to create.

The ability to fine-tune their model would prove to make a difference for Boosted.ai. Through the [AWS Partner Network](https://aws.amazon.com/partners/), Boosted.ai connected with [Invisible](https://aws.amazon.com/marketplace/seller-profile?id=edc87aec-2a1e-46f5-a6ce-b9375e6b235e), whose global network of AI training specialists allowed Boosted.ai to stay focused on their core developmental work while Invisible provided high-quality data annotation faster and more cost effectively than staffing an in-house team to the project. Together, AWS, Invisible, and Boosted.ai found and implemented the smallest possible model that could handle their use case, benchmarking against the industry-standard Massive Multitask Language Understanding (MMLU) dataset to evaluate performance.

> "Our goal was to have the smallest possible model with the highest possible IQ for our tasks. We went into the MMLU and looked at subtasks we thought were highly relevant to what Boosted.ai is doing: microeconomics and macroeconomics, math, and a few others. We grabbed the smallest model we thought would work and tuned it to be the best it could be for our tasks. If that didn't work, we moved to the next size model and the next level of intelligence."
>
> – Joshua Pantony, Boosted.ai co-founder and CEO

With a more compact and efficient model that performed just as well at financial analysis, Boosted.ai slashed costs by 90 percent. The big benefit they saw from this efficiency was being able to massively upsize the amount of data they pulled—going from overnight updates to near real-time. More importantly, they got the GPUs they needed to scale. Where Boosted.ai once needed A100 and H100 to run their models, this more efficient domain-specific generative AI allowed them to run a layer on smaller and more readily available hardware.

## Better security and customization with a smaller model

Having fine-tuned a smaller model with the same efficacy, Boosted.ai had the computational capacity to run even more analysis. Now instead of processing data overnight, they could process data every minute and promise customers a delay of only 5-10 minutes between something happening and Boosted Insights picking it up.

The model also gave Boosted.ai more optionality for where and how they deploy. With an LLM, Boosted.ai was shipping the workload out to a closed-source cloud, getting the results back, and then storing it. Now, they can deploy inside another customer's virtual private cloud (VPC) on AWS for added security.

> "Having a generative AI strategy will be a fundamental expectation for investment management firms in 2024, and we are seeing huge demand of companies wanting to run their internal data through our generative AI to create smart agents. Understandably, leveraging proprietary data raises privacy concerns. A lot of our users feel safer on our model than on a big closed-source LLM. 90 percent of our clients have an AWS account, and the benefit we're seeing is that keeping their data secure within their private AWS cloud is extremely simple when we run on the same cloud."
>
> "Giving access to private deployments running their data is a lot easier than trying to build the entire thing from scratch."
>
> – Joshua Pantony

With the extra peace of mind that a private endpoint offers, more customers are willing to share their proprietary data to create more customized insights. For instance, a hedge fund might have access to interviews with hundreds of CFOs and management analysts. That dataset is too valuable and confidential to send to a public API endpoint. With Boosted.ai's domain-specific approach, it doesn't have to. The entire workload runs within the customer's cloud, and they get more customized insights.

## The future: domain-specific language models and a new way to tap expertise

As Boosted.ai's fine-tuned smaller language model grows, the insights it offers will get crisper and more quantified. For instance, today it can say which companies are affected by an event, like the war in Ukraine. In the future, it will be able to quantify that effect and say, "exactly 7 percent of this company's revenue will be impacted, and here's the probability of how it will be impacted."

Additionally, obtaining those insights will require less user interaction. It will be possible to upload your expertise and knowledge to your personalized AI, have it scan a vast database of information, and push unique ideas to you.

AI is the most rapidly adopted technology in human history, and for smaller organizations, today's cutting-edge use cases are likely to be table stakes in a few short years.

> "We're in this really unique time in history where there's a lot of big companies that don't know the potential of this technology and are adopting it in suboptimal ways. You're seeing a ton of chatbots go up left, right, and center. If you're a startup today, meet customers, learn their problems, and be aware of what generative AI is capable of. If you do, there's a very high probability you're going to find a unique value add."
>
> "Once you're confident that you've got some product-market fit, I would think about fine-tuning smaller models versus LLMs across speed, accuracy, and data sensitivity. If you think any of those are critical for your use case, it's probably worth it to use a domain-specific model."
>
> – Joshua Pantony

Additional thanks to [Invisible](https://www.invisible.co/) for their contributions to this project and article. Invisible is an operations innovation company that seamlessly merges AI and automation with a skilled human workforce to unlock strategic execution bottlenecks.

---

## About the Authors

### Ryan Masciovecchio

Ryan is a Solutions Architect at AWS living in Toronto, Canada. He provides technical advice to startups, allowing them to build innovative products using emerging technologies. Ryan has over 15 years of experience, from racking servers and configuring networking appliances to building infrastructure for web applications using cloud services. Ryan enjoys learning how technology can be used in creative ways to simplify people's lives.

### Deepam Mishra

Deepam Mishra is a Sr Advisor to Startups at AWS and advises startups on ML, Generative AI, and AI Safety and Responsibility. Before joining AWS, Deepam co-founded and led an AI business at Microsoft Corporation. Deepam has been a serial entrepreneur and investor, having founded 4 AI/ML startups in areas such as security, enterprise software and healthcare. He was the VP of New Ventures at Wipro Technologies and co-founded Venture Studio, a startup incubator, and seed-fund. He has created multiple successful startups, including SightLogix, EyeIC, Green-Power-Systems, Shippr, and more. Deepam has a BSEE from IIT Kanpur, an MSEE from Texas A&M, and an MBA from The Wharton School. He has 5 US patents and numerous publications. He is based in the Silicon Valley.

### Joshua Pantony

Josh is a co-founder and CEO of Boosted.ai, an AI company that brings advanced ML tools to institutional investors and wealth managers. Since starting Boosted.ai in 2017, the company has helped hundreds of investment managers implement machine learning in their portfolios. Prior to founding Boosted.ai, Josh was a Principal ML engineer at Bloomberg for 4 years. At Bloomberg, he helped start and build numerous critical ML initiatives including Ranking, Recommendation, Question and Answering, Crowd Sourcing, and Knowledge Graphs. He also acted as a consultant on numerous initiatives across the company and helped build several ML teams. As a student at the University of Waterloo, Josh co-founded his first company, Maluuba, a deep learning natural language processing company. At Maluuba, he built the earliest prototype, recruited the entire ML team, and oversaw general technology development from 4 people up to a 30 person company. He has 8 patents to his name all of which are core Maluuba IP. Maluuba was later bought by Microsoft.
