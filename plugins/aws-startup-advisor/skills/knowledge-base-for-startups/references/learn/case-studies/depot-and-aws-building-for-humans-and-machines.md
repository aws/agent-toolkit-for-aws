---
source_url: https://aws.amazon.com/startups/learn/depot-and-aws-building-for-humans-and-machines
title: "Depot and AWS: Building for humans and machines"
---

## Depot and AWS: Building for humans and machines

[Watch the video on YouTube](https://www.youtube.com/watch?v=Ly0X_-Av5vc)

[Depot](https://depot.dev/) is a build-acceleration platform that helps software teams ship at machine scale. Running on AWS, the startup launches millions of [Amazon EC2](https://aws.amazon.com/ec2/) instances daily and uses [AWS Graviton4](https://aws.amazon.com/ec2/graviton/) processors to deliver up to 30 percent faster build times.

---

Depot saves its customers an aggregate of 30 years of build time every week. The startup is working with AWS to provide the high-performance infrastructure that enables both developers and AI agents to build and test software at speed.

Jacob Gillespie, Co-founder and CTO at Depot, highlights a major shift in the software engineering space that is changing both how software is built and the demands on the infrastructure behind it. “Machines are becoming our users,” he explains. “Unlike before, where it would be an engineering team of a particular size, now it's an engineering team commanding the power of many different AI agents.”

Depot is building the infrastructure to support this new generation of users, relying on AWS services and infrastructure to deliver the scale, performance, and reliability required by its customers.

### Breaking the bottleneck

AI agents can generate code much faster than humans, but developers are still critical to this workflow, reviewing the code and being on hand to manage it when it breaks. This is creating a bottleneck, which has become more of a challenge in recent years due to the adoption of new tools.

Depot is a build-acceleration platform for CI/CD (continuous integration and continuous delivery), automating processes and allowing software teams to iterate more quickly and save time. Its solutions are powered by [Amazon Elastic Compute Cloud](https://aws.amazon.com/ec2/) (Amazon EC2), which provides secure and resizable compute capacity for virtually any workload. “We are launching millions of instances on EC2 per day to manage customer workloads,” says Gillespie, delivering computing power on demand.

Depot also uses [Amazon S3](https://aws.amazon.com/s3/), an object storage service that offers scalability, data availability, security, and performance. This powers Depot’s caching platform, enabling it to move around two petabytes of data per day between customer workloads and S3. By storing and retrieving outputs from previous builds, Depot allows developers and AI agents to reuse existing work rather than rebuilding software from scratch. This results in significant time savings and faster build times, with “pretty dramatic effects,” says Gillespie. “That could be anything from a 50 percent speedup to a 50x speedup.” Across Depot’s customer base, the impact is even more dramatic: “At the moment, we are saving our customers an aggregate of 30 years of build time every week.”

### Meeting compute demand

Working with AWS, Depot is continuing to refine and evolve its solution. The platform runs on [AWS Graviton](https://aws.amazon.com/ec2/graviton/) processors, which are designed to deliver the best price performance for cloud workloads running on Amazon EC2. When AWS Graviton4-based instances became available, Depot recognized an opportunity to enhance its competitive position.

The startup migrated its entire fleet from Graviton3 to Graviton4 instances, improving performance for teams using the platform without changing their existing workflows or configurations. Every one of its customers saw build times improve by around 30 percent, reducing the amount of compute time they needed and therefore lowering costs. “Many of the larger ones who monitor build performance very closely immediately reached out and were like, ‘Hey, our builds are 30 percent faster. Did you do something?’” says Gillespie. “And we're like, ‘Yes, we did!’ That's why we picked AWS to meet that compute demand.”

Depot's growth has been supported by [AWS Activate](https://startups.aws.com/join) and [AWS Credits](https://aws.amazon.com/startups/credits/), helping the startup scale without diverting focus from product. As demand from AI agents continues to grow, so will the infrastructure behind it. Depot plans to keep pace, integrating with the tools that both developers and agents will rely on. "We want to integrate with the tools that both tomorrow's software engineers as well as tomorrow's agents are going to use, and we're building it with AWS to realize that vision," says Gillespie.
