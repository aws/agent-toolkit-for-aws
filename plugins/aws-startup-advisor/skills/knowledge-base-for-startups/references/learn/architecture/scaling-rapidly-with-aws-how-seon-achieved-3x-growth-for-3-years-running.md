---
source_url: https://aws.amazon.com/startups/learn/scaling-rapidly-with-aws-how-seon-achieved-3x-growth-for-3-years-running
title: "Scaling rapidly with AWS—How SEON achieved 3x growth for 3 years running"
---

## Scaling rapidly with AWS—How SEON achieved 3x growth for 3 years running

> SEON scaled rapidly for three consecutive years, achieving triple growth each year. Learn how they did it, all without major refactors to their architecture.

---

[Scaling](https://aws.amazon.com/blogs/startups/how-to-scale-your-business-like-amazon/) a startup successfully involves increasing profit margins exponentially while keeping costs low. Most startups combine a variety of approaches to scale, based on their growth stage and needs. Techniques to scale include finding processes that work and applying them across the board, focusing on customers and building a product that is in high demand, and harnessing AWS cloud technology to [move fast](https://aws.amazon.com/blogs/startups/when-should-startups-use-a-managed-service/) and [optimize your costs](https://aws.amazon.com/blogs/startups/how-to-prevent-unexpected-costs-for-startups-while-building-with-aws/).

[SEON](https://seon.io/), a Hungarian fraud prevention startup founded by Tamás Kádár and Bence Jendruszák in 2017, is a model of successful startup scaling: Without major refactors of their architecture, SEON has scaled rapidly for three consecutive years, achieving triple growth each year by building on cloud services offered by AWS. In 2021 alone, SEON more than tripled its annual recurring revenue, grew its headcount by 4X, and opened new offices in Austin, Texas and Jakarta, Indonesia.

## Building a scalable and cost-optimized architecture on AWS

A key driver of SEON's successful scaling, according to their Chief Architect Adam Berkecz, is their use of over 30 AWS solutions regularly.

> _"The traditional approach of provisioning environments without AWS cloud solutions is expensive and has the hidden cost of time needed to launch. With AWS, we have more than 100 engineers delivering customer value on a diverse technical portfolio," explains Adam._

The stars of SEON's architecture include AWS solutions such as [Amazon Elastic Compute Cloud (Amazon EC2)](https://aws.amazon.com/ec2/), [Amazon Relational Database Service (Amazon RDS)](https://aws.amazon.com/rds/), [Amazon API Gateway](https://aws.amazon.com/api-gateway/), and [AWS Lambda](https://aws.amazon.com/lambda/), which allow them to handle real-time transactions for more than 5,000 customers.

The flexible scaling of these AWS solutions enables SEON's architecture to thrive, even during elongated periods of high load. This flexibility was on display when SEON launched the fraud browser detection feature in their device fingerprinting solution and enabled it instantly for their customers' millions of end-users. SEON served over 10,000 requests in the first minute without any scalability issues.

In addition to granting flexibility, SEON's AWS solutions help them to [keep costs predictable](https://aws.amazon.com/startups/cost-optimization/). By employing AWS [Savings Plans](https://aws.amazon.com/savingsplans/) and [Amazon EC2 reserved instances](https://aws.amazon.com/ec2/pricing/reserved-instances/), SEON ensures that they are not overpaying for their compute resources. In addition to that, SEON stays on top of their spending by regularly monitoring [AWS Cost Explorer](https://aws.amazon.com/aws-cost-management/aws-cost-explorer/) and its granular view on linked accounts, services, and usage types. Finally, for infrequent and event-driven compute tasks, SEON opted to go serverless by using AWS Lambda: This allows them to save more on costs and at the same time not need to provision any instances, nor manage them.

## Key tips for enabling rapid growth with AWS

**1. Keep it simple.** When looking for a minimum viable product (MVP) or a market fit with a new product offering, stick to the most easy-to-use AWS services like [AWS Elastic Beanstalk](https://aws.amazon.com/elasticbeanstalk/). Simple yet powerful offerings like Elastic Beanstalk enable your organization to focus on building products rather than invest time in managing services. For SEON, it is important that developers stay as productive as possible to propel the company's growth.

> _"With AWS Elastic Beanstalk and Lambda solutions, we are able to have developers working in various languages (Java, TypeScript, Python, Golang, and others) while focusing on writing code and not on managing servers and databases. With this approach, we can spin up new environments in minutes," says Adam._

**2. Invest in a multi-AZ and multi-region architecture.** When clients send SEON's tools a transaction to review, a customer at the other end is hoping to sign up for a new service or place an order. Every second that passes will affect their overall customer experience.

By investing in [multi-AZ](https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/Concepts.MultiAZ.html) and [multi-region architecture](https://aws.amazon.com/solutions/implementations/multi-region-application-architecture/), SEON is able to maintain approximately 2–3 second response times around the world. Furthermore, SEON maintains excellent service availability even in the rare cases of service degradation in one zone or another.

**3. Support experimenting with new services.** SEON's architecture is constantly evolving. This evolution is possible as their leadership supports innovation and testing new AWS technologies. By using a [sandbox account](https://aws.amazon.com/blogs/mt/best-practices-creating-managing-sandbox-accounts-aws/), SEON's engineers can build small architectures and proof-of-concepts that may be eventually propagated into production. For example, experimenting with serverless technologies like Lambda and different flavors of RDS databases allowed SEON to realize that they can improve their application architecture with these changes and they consequently mirrored them in their production environment.

## What's next for SEON?

Having raised $94 million in Series B funding in April 2022, SEON is looking to expand its presence in North America, Latin America, and the Asia Pacific region. SEON continues to build partnerships with leading ecommerce platforms, heighten product functionality, and integrate additional data sources to help customers better fight fraud.

> _"With AWS continuously providing and updating futuristic services for AI, containerization, and message streaming, we do not see ourselves slowing down," says Adam. "Managed services like Amazon Aurora and managed Kafka are on our technological roadmap, and we look forward to what we can accomplish further with them."_

---

## About the Author

### Bilal Dayeh

Bilal Dayeh is a Senior Technical Account Manager on the AWS Enterprise Support team. Previously a system engineer and subject-matter expert in cloud infrastructure, he deployed telecommunication solutions all over Europe, Africa, and the Middle East. Bilal is most passionate about leveraging the cloud to achieve customer goals and drive innovation. In his spare time, Bilal can be found on the basketball court or enjoying a good book.

---

_Source: [AWS Startups Learn](/startups/learn)_
