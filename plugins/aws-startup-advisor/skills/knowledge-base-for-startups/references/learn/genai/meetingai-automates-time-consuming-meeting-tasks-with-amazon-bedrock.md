---
source_url: https://aws.amazon.com/startups/learn/meetingai-automates-time-consuming-meeting-tasks-with-amazon-bedrock
title: "Meeting.ai automates time-consuming meeting tasks with Amazon Bedrock"
---

## Meeting.ai automates time-consuming meeting tasks with Amazon Bedrock

> Powered by generative AI, Meeting.ai enables users to spend more time engaged in meetings, and less time trying to recall key takeaways after the fact.

Conference calls, stand-ups, impromptu catch-ups around the water cooler—meetings are fundamental to most of our working lives. Whether we're receiving a new project brief, presenting financial reports, or workshopping new ideas, we're all used to seeing new invites land in our inboxes, and new bookings appear in our calendars.

But professional life moves quickly, and it's not always easy to find the time to properly process the content of the meetings we attend, to make and review notes on what was discussed, revisit recordings, or quickly pick out the insights that we need at a moment's notice. [Meeting.ai](https://meeting.ai/), an Indonesian startup based in Jakarta, is changing that by automating time-consuming activities like note-taking.

Powered by generative artificial intelligence (AI), Meeting.ai enables users to spend more time engaged in meetings, and less time trying to recall key takeaways after the fact. Having been unsatisfied with the performance of other large language models (LLMs), the Meeting.ai team decided to implement [Claude 3 Sonnet and Haiku on Amazon Bedrock](https://aws.amazon.com/bedrock/claude/). Now the startup is able to generate meeting summaries with industry-leading accuracy—all while cutting costs by 33 percent.

## From the classroom to the boardroom

Meeting.ai—originally named Bahasa.ai—was founded in 2017 by Hokiman Kurniawan, Fathur Rachman Widhiantoko, and Samsul Rahmadani. The trio became friends while studying mathematics at college together. During their studies, they created one of the first LLM in Bahasa Indonesia, the nation's official language. This had, up until that point, proven difficult due to the many nuances and intricacies of languages spoken across the country.

"Indonesia has a population of over 270 million across thirty-three regions, and there are many different accents, regional dialects, and local terminology," says Hokiman, the company's CEO. "Although we say Indonesia is one language, we actually have hundreds of local languages too"—over 700, to be precise— "the largest ones being Javanese and Sundanese, and people often use a mixture of languages when speaking to each other."

Developing a model capable of handling that level of complexity takes a lot of data. "We've collected over thirty thousand hours of voice data over the last seven years," says Hokiman. Once the team had created simple language models for Bahasa Indonesia, word spread quickly. The startup soon landed its first customer, an Indonesian pharmaceutical company—the largest of its kind in Southeast Asia—in need of natural language expertise for customer service use cases.

In those days, the company primarily offered consulting services for AI and natural language. "We didn't have products, we had solutions," says Hokiman. But that all changed with the launch of the Meeting.ai tool in 2023.

## Intelligent automation meets market-leading accuracy

Meeting.ai is a generative AI-powered meeting assistant that helps users reduce time spent on meeting-related tasks. It was developed using the company's proprietary LLMs for Bahasa Indonesia. As Hokiman explains: "our tool automatically records, transcribes, and summarizes meetings, helping you save time and work more productively."

Seamless integration with popular meeting services, such as Google Meet, Zoom, and Microsoft Teams, has helped Meeting.ai quickly attract a user base of over 70,000, primarily based in Indonesia. Unlike built-in alternatives, the tool can also be used for offline meetings. "Our offline capabilities already account for more than 50 percent of the total utilization of our product," says Hokiman.

Another key differentiator for Meeting.ai is that it delivers 97% transcription accuracy in Bahasa Indonesia, the highest of any tool on the market. "We often see our customers light up when they realize that they can speak informally, and the AI will understand them, even if they use slang. They don't expect that level of AI support for Bahasa Indonesia—it's a real 'aha' moment."

## Meetings have never been so technologically advanced

The Meeting.ai team have been working with AWS since their college days, which made it a natural choice when looking for a partner to help build their tool. "Two things make AWS a great partner. Firstly, the technology—if it works, it works, and people will use it. So far, every AWS product we've used has delivered," says Hokiman. "Secondly, it's the people. Products alone are great, but in our world, access to new models and expertise comes down to relationships with people, and AWS has been really supportive."

The architecture behind Meeting.ai combines multiple AWS services that help to control costs without sacrificing performance. For example, the team opted to use [Amazon EC2 G4 Instances](https://aws.amazon.com/ec2/instance-types/g4/) as the primary node pool for AI workers because of the industry-leading price-to-performance of NVIDIA T4 GPUs. Similarly, [Amazon Elastic Kubernetes Service](https://aws.amazon.com/eks/) (EKS) ensures cost-efficient compute resource provisioning and automatic Kubernetes application scaling. The team also recently implemented [Amazon Bedrock](https://aws.amazon.com/bedrock/), a fully managed service offering a choice of high-performance foundation models (FMs) to securely experiment with, and privately customize. This has enabled them to not only significantly reduce costs, but also improve the accuracy of the summaries generated by Meeting.ai.

## High-performance LLMs, all accessible from a single source

Generative AI is evolving at pace, and as new models and services become available, tools like Meeting.ai can gain a competitive advantage by keeping up with the latest releases. The summarization capabilities provided by Meeting.ai had previously relied on LLM services that did not meet the quality and accuracy the team were looking for. When news reached them that Anthropic's new Claude 3 models were going to be available on Amazon Bedrock, they jumped at the opportunity.

"I immediately contacted my mentor from college, who had previously worked as a regional manager for AWS in Indonesia," says Hokiman. "I asked him if he could introduce me to someone at AWS who could get us access to the models, which at the time were not publicly available—within a week we were given that access."

Implementing Amazon Bedrock was a simple process that was completed in approximately 3 weeks, involving just two developers. "It's an integrated experience, it's like a single marketplace where we can test and experiment with a variety of models. If a new model is released, we can easily access it on Amazon Bedrock," says Hokiman.

After getting their hands on Claude 3 on Amazon Bedrock, the team got to work testing the quality of Sonnet and Haiku models.

## Test. Compare. Choose.

The Meeting.ai team first collected a test dataset consisting of recordings of several internal company meetings and podcast videos available on YouTube. They then processed these data samples using both the original LLM and their selected Claude 3 models. The team were able to start testing with the same prompts they had been using with the original LLM, allowing them to invest more time in identifying the right model instead of engineering new prompts.

The team soon found that the quality of summaries produced by the Claude 3 Haiku model were of a higher quality than the previous model. "Claude 3 in general is far more efficient, and can handle things that other models can't. The Haiku model is also a far smaller model than the alternatives, which makes it much cheaper for us to use," says Hokiman. "We're always looking to balance performance and cost, and Haiku delivers both."

Haiku is now being used for the majority of Meeting.ai use cases and has enabled the team to save more than 33 percent on costs. For other, more specific use cases like summarizing work performance from one-to-one meetings between employees and leaders, Meeting.ai also utilizes the Claude 3 Sonnet model.

## A step up in performance and efficiency

Claude 3 models offer a high context window of 200k, allowing them to take account of more data and information when generating outputs. This enables Meeting.ai to provide far more accurate meeting summaries than what had been possible with the previous model. It also allows the tool to automatically distinguish between important discussion points and casual chatter, which the previous LLM model found difficult to do, especially in Bahasa Indonesia.

Another benefit of the longer context window is that customers receive results much faster—up to 1,200 percent to be precise. For a two-hour meeting transcript, Meeting.ai only needs a single LLM API request, compared to the previous model which required approximately twelve LLM API requests for summarization. "The more requests that need to be made, the more costs we incur. In some cases, it could be twice as expensive to complete the same task with our previous model compared to Claude 3," says Hokiman.

The Meeting.ai team also found Claude 3 to be more obedient and reliable in following instructions. For example, both Haiku and Sonnet models are consistently able to provide responses in JSON format when requested.

## Meetings reimagined—both on and offline

Going forward, the Meeting.ai team are expanding globally and extending their tool's capabilities. They will soon release real-time note-taking functionality, enabling users to transcribe and summarize offline meetings without needing to record them. Beyond that, the team envision a future where users will be able to have meetings with Meeting.ai.

"We are currently working on an integrated voice model so that users can ask the AI questions," says Hokiman. "We'd even like to see reoccurring things like standups outsourced to the AI, enabling teams to spend more time focusing on work and less time in meetings."

As the Meeting.ai team continues to evolve their product, AWS is helping to ensure they always have access to the latest LLMs and the freedom to discover which model is right for them, and their customers. "AWS is a partner that we can count on to keep pace with the rapidly evolving world of generative AI. If a new model is released, it's easy for us to switch. Everything we need is right there in Bedrock," says Hokiman.

---

## Related resources

- [How Proto is bringing cutting-edge avatars to life with Amazon Bedrock](/startups/learn/how-proto-is-bringing-cutting-edge-avatars-to-life-with-amazon-bedrock)
- [Leonardo AI drives tech evolution using generative AI on AWS](/startups/learn/leonardo-ai-drives-tech-evolution-using-generative-ai-on-aws)
- [Boosted.ai's generative AI portfolio manager surfaces near-instant finance insights with AWS](/startups/learn/boosted-ais-generative-ai-portfolio-manager-surfaces-near-instant-finance-insights-with-aws)

---

**Author:** Agung Sidharta

Agung Sidharta is a Startup Solutions Architect who loves to work with customers solving their problems. In his spare time, he enjoys traveling, reading IT-related contents, and walking in the surrounding environment with his family and little dog.
