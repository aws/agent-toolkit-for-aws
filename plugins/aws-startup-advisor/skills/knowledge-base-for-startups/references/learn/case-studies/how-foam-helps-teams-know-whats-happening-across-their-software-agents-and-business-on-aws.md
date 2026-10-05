---
source_url: https://aws.amazon.com/startups/learn/how-foam-helps-teams-know-whats-happening-across-their-software-agents-and-business-on-aws
title: "Anyone can ask, everyone gets answers: how Foam helps teams know what’s happening across their software, agents, and business on AWS"
---

## Anyone can ask, everyone gets answers: how Foam helps teams know what’s happening across their software, agents, and business on AWS

![Perla Gámez, Foam](https://d22k7geae6sy8h.cloudfront.net/files/6a9ed117213939000e2f73a2/foam-ai-headshot.jpg)

After years of pulling all-nighters to ship products and features on time, [Foam](https://foam.ai/)’s founders set out to build a platform that lets anyone ask what their software, agents, and business are doing and get an evidence-backed answer. Built on AWS and powered by [Amazon Bedrock](https://aws.amazon.com/bedrock/), Foam installs itself, collects and enriches telemetry across apps, agents, and infrastructure, and puts AI agents to work on everything from root-causing an issue to providing insights into the product and business​​. There is no configuration needed or learning curve: teams just ask.

---

### Where Foam started

Asking was not an option for Perla Gámez. Knowing what software was doing meant hopping between a dozen different tools, digging through logs and traces by hand, and stitching fragments into an answer, often at 2am. At a Buy Now, Pay Later (BNPL) company, Gámez built revenue-generating products and user-facing features as ​an IC, helping decide which features to build in the first place. That gave her visibility across the whole product while also being in charge of keeping the lights on. Most of that job required context switching across tools.

Fast forward to today and observability tools are still fragmented, and as a result they come with gaps. Most teams have at least 4 different observabilities, with bigger companies having dozens. This results in fragmented data and a lack of context for humans and agents.

“It’s insufficient and ineffective," explains Gámez, Foam’s co-founder and engineer. “How is this not already a solved problem, and how can I possibly build faster and cooler products with this setup?”

### Observability that installs itself

Founded in 2025 after raising funding led by Khosla Ventures, Foam gives every team member — from engineers to customer support to non-technical founders — a way to know what’s happening across their software, agents, and business.

For some, the obvious shortcut is to wire an AI into the monitoring tools a team already has. But that only automates the gluing: it does not address the limiting factor of observability fragmentation and gaps.

Rather than presenting data for humans to analyze, Foam enables AI agents to do the work directly. Foam reads the customer’s codebase, builds a custom Open Telemetry (OTEL) package tailored to each service’s stack, and opens the pull requests that install it, so the team just reviews and merges. Installation is hands-off and takes two to five hours, after which Foam runs test traffic and keeps monitoring for new gaps. Because Foam ensures that the instrumentation is well installed, nothing is missing: every log, trace, and metric arrives connected through unifying IDs, so answers are complete and provable.

Questions don’t always come from engineers. Non-technical staff may have questions about the state of things. Today they lack the specialist knowledge to find the answers they need. With Foam, Support can ask why a customer hit an error, Finance can ask what a feature costs to run, and Product can ask whether the company’s agents are making users happy. Everyone asks in plain language, and everyone gets answers from the same data, backed by the same evidence.

CEO Gámez adds that the pitch to non-engineers is that they don’t have to know anything: “They get cameras and sensors everywhere into the products. And all the data gets translated into customer support language framed to be relevant and easy to read for someone who’s not skilled in coding.”

Another differentiator for Foam is customer-friendly pricing. Incumbent tools get more useful the more telemetry a team sends, but they also get more expensive so teams are incentivised to throttle back what they send. Foam has removed that trade-off: customers pay for AI credits and storage; everything else is included.

“The incentives are messed up,” says Gámez. “The more data you send, the more value you can retrieve from it … but they punish you for sending it. We don’t have that pricing model.”

### A foundation for growth

As a cloud-native startup, Foam built on AWS from day one. The team uses [Amazon Elastic Container Service (ECS)](https://aws.amazon.com/ecs/) and [Amazon Elastic Compute Cloud (EC2)](https://aws.amazon.com/ec2/) to run workloads, [Amazon Simple Storage Service (S3)](https://aws.amazon.com/s3/) for storage, [Amazon Virtual Private Cloud (VPC)](https://aws.amazon.com/vpc/) to isolate customer environments, and [Amazon Route 53](https://aws.amazon.com/route53/) for networking. AWS gave the startup a mature platform that engineers already understood, making it easier for a small team to build fast without deep infrastructure expertise.

“It was a match made in heaven,” explains Gámez. “We really value that AWS is a hardened product with this amazing ecosystem that we can connect to more and more as we grow. And it’s a language other engineers understand, so it’s easy to bring new people on.”

That same foundation lets Foam move quickly as its product evolves. Because everything runs on AWS, reshaping the architecture takes days rather than months. "AWS gives you the components to build complex architectures," says Gámez. "You make the instance bigger, or add something off the shelf from AWS, and you get something new that is very powerful."

### Scaling AI with Amazon Bedrock

Foam relies on Amazon Bedrock to give its AI platform the flexibility, availability and scale it needs to support customers in production. “Bedrock is an awesome product for us,” says Gámez. “We love to change models as soon as they come out. We switch regularly to fine tune all our solutions.”

Rather than integrating directly with model providers, Foam uses Bedrock for its availability and operational consistency. And as demand has increased, Foam has required higher token throughput. “There were a couple of times where we needed more tokens per minute, and no one was able to help us except AWS,” Gámez adds. As Foam’s customer base grows, Bedrock has become a critical part of its ability to scale reliably while continuing to evolve AI capabilities.

[AWS Activate Credits](https://aws.amazon.com/startups/credits/) also underwrite the research behind the product. Foam publishes its findings, including a root-cause-accuracy benchmark and a study of clustering and noise reduction across eleven production environments. “We run a lot of experiments,” says Gámez. “No way could we afford that without the $100,000 USD we’ve received in AWS Credits.”

### Building trust through isolation, and sandboxes at scale

For enterprise customers, intelligence alone isn’t enough, and AI agents must also operate securely. Foam’s agents therefore need to remain isolated from sensitive systems and credentials, while still having visibility into customer codebases and telemetry.

The self-installing product raised the stakes on that work. Because Foam writes the instrumentation itself, it needs a sandbox that mirrors what each customer runs in production so that installation and verification can be rehearsed safely before a pull request lands. Foam builds these per-customer sandboxes on AWS, using Amazon ECS and snapshots to stand them up and keep them consistent. The capability is already live and expanding as the product grows.

“Customers have offered us direct AWS accounts and said, ‘Build all your infrastructure here so there’s isolation from our systems and from their systems’,” Gámez adds. “So, AWS is the key language when it comes to security for these companies. They know that if we’re on AWS, we have the right encryption.”

### Moving at startup speed

As an early-stage startup in one of AI’s fastest-moving areas, Foam relies on AWS to keep pace with rapid growth. Gámez says having direct access to the AWS Startups team enables the company to answer technical questions quickly and adapt as requirements change.

“We move so fast” she says. Through a dedicated Slack channel and regular engagement with AWS Solution Architects, the Foam team can validate its infrastructure decisions and get valuable guidance as the startup continues to scale. “To have a direct line to the AWS team has been really nice,” says Gámez. “They’ve even come in to take a look at our infrastructure and give us tips.”

For Gámez, the fact that AWS rarely comes up is the point. “The absence of thoughts about AWS means they’ve delivered. I never have to think about it, I just use it. And if I ever need an increase in request limits, the people in the channel are responsive. It’s awesome, AWS is the only provider we have a channel with.”

### Looking to an agent-first future

For its founders, Foam is building a future where AI agents are active participants in software as well as business operations. That vision continues to shape Foam’s product roadmap. “We’re not happy with a product that just works, or a product that’s useful,” she says. “We aim to build a product that’s delightful to use.” Gámez sees AWS as a key part of that journey. "You couldn't hope to have a better partner than AWS."
