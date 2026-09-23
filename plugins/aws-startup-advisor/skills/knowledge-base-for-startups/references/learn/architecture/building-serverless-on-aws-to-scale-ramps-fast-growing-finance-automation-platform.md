---
source_url: https://aws.amazon.com/startups/learn/building-serverless-on-aws-to-scale-ramps-fast-growing-finance-automation-platform
title: "Building serverless on AWS to scale Ramp's fast-growing finance automation platform"
---

## Building serverless on AWS to scale Ramp's fast-growing finance automation platform

For startups, coming full circle is a milestone defined by partnering with the [programs](https://aws.amazon.com/startups/startup-programs/) used during early stage growth, or providing [resources](https://amer.resources.awscloud.com/aws-startup) that help other startups succeed as well.

[Ramp](https://ramp.com/), a B2B fintech startup founded in 2019 by veteran founders Eric Glyman and Karim Atiyeh, does both. Ramp is a tech-first finance automation platform whose serverless modern application–in conjunction with its corporate card–allows businesses to more efficiently manage their finances.

In the startup's early days, founders Eric and Karim prioritized talking to customers to learn their pain points, priorities, and what aspects of a corporate card really mattered. Informed by customer needs, they tailored their product to offer:

- Physical and virtual corporate cards with unlimited 1.5% cash back
- Zero touch expenses to help control, analyze, and optimize organization-wide spending
- Fast bill payments for businesses to pay invoices how and when they want, around the globe
- Intelligent insights, reporting, and perks to maximize saving and cut spend

Within one year of launching publicly, Ramp reached [unicorn status](https://fintechmagazine.com/venture-capital/us-company-ramp-latest-fintech-hit-unicorn-status) and became America's fastest-growing corporate card. The company has since significantly scaled its business operations and AWS architecture to reach 12,000+ customers. To date, Ramp has saved businesses over $300 million and 3.5 million hours.

> _"The problem we solve is, 'How can we save businesses time and money, while empowering their employees to spend, but ensuring that it's done in a controlled and efficient way?'"_ — Alexis Gordon, leader of Ramp's product partnerships team

## Building a modern architecture on AWS

To support the startup's need for a scalable modern architecture, high developer productivity, multi-region availability, and optimized cloud costs, Ramp built its platform's core infrastructure on AWS.

### A scalable modern architecture

"This is the modern decade of thinking about cloud infrastructure, instead of the bare bones approach to cloud computing," explains Lewis Drummond, head of infrastructure at Ramp.

> _"I'm very proud of how few legacy-type virtual machines we have and that we leverage more advanced, completely serverless, technologies from AWS. It serves us very well."_ — Lewis

Ramp uses an [Amazon Aurora](https://aws.amazon.com/rds/aurora/) database cluster, as well as [Amazon ElastiCache for Redis](https://aws.amazon.com/elasticache/redis/) to provide sub-millisecond latency for Ramp's caching needs and to accelerate application and database performance. Jun Isaji, director of cloud infrastructure at Ramp, explains, "AWS solutions allow us to be flexible to meet demand and add components to increase system robustness. They also help us reduce complexity throughout the system by utilizing the features built into AWS solutions."

## Improved developer productivity

Ramp's architecture uses [Elastic Load Balancing (ELB)](https://aws.amazon.com/elasticloadbalancing/?nc=sn&loc=0), specifically [Application Load Balancer](https://aws.amazon.com/elasticloadbalancing/application-load-balancer/), to distribute incoming application traffic. Behind that, their web servers run on Amazon [Elastic Container Service (Amazon ECS)](https://aws.amazon.com/ecs/) on [AWS Fargate](https://aws.amazon.com/fargate/), which allows Ramp engineers to focus on building their application instead of managing their servers.

> _"AWS really helps by abstracting away the details of running all of our components. Our developer velocity across the organization has significantly increased from using AWS."_ — Jun

Ramp also increases developer velocity by using the flexibility of AWS' managed services to quickly and easily spin up stacks that allow them to experiment, and then spin down the stacks when they're no longer needed.

"AWS' managed services allow us to do proof of concepts quite easily and quickly," explains Lewis.

"About a year ago we were looking to test Airflow, which can be a pain to set up by yourself." To make the testing easier, Ramp leveraged [Amazon Managed Workflows for Apache Airflow](https://aws.amazon.com/managed-workflows-for-apache-airflow/).

> _"AWS helps a long way to getting us up off the ground more quickly. Being able to go from zero to one in a matter of days instead of weeks, as well as the lower effort there, helps us to iterate quickly."_ — Lewis

## Availability across multiple regions

In addition to using AWS for its high scalability and benefits to developer productivity, Ramp uses AWS' multi-region availability. For startups, multiple regions can improve the user experience by providing low latencies across the globe and by creating more resilient cloud architecture.

Lewis explains, "These managed services within AWS work very strongly with our multi-region requirement. Having all of these managed services, which also support cross-region, has been very useful to us." Ramp uses [Amazon Aurora Global Database](https://aws.amazon.com/rds/aurora/global-database/) for cross-region with Aurora, [Global Data Store in ElastiCache](https://aws.amazon.com/elasticache/redis/global-datastore/) for cross-region with ElastiCache, [AWS Secrets Manager](https://aws.amazon.com/secrets-manager/) cross-region, and [Amazon S3](https://aws.amazon.com/s3/) cross-region.

One of the most essential components of Ramp's architecture is called the authorizer, which approves or denies credit card transactions. "Because the authorizer is so critical for us, we have a warm standby multi-region configuration," says Jun. "We can spin up the authorizer compute within our disaster recovery region, then route requests to that compute if our primary region were to go down"

## Optimizing the costs of cloud computing

Saving money on cloud spend is a priority for many startups. With the help of AWS tools and their AWS account team, Ramp has been able to decrease their cloud spend.

> _"Our account manager Xavier was very proactive about reaching out to us about how to reduce costs. I'm definitely happy with AWS proactively reaching out and saying, 'Here are some ways to reduce costs.' That's great."_ — Jun

One cost-optimization success that grew from a meeting between Ramp and their account team was implementing AWS Graviton processors for Ramp's databases. "Graviton was a big success for us in increasing performance relative to cost," says Jun. "We're also in the process of working with our account team to review our reserved capacity for compute."

Tools such as [AWS Cost Explorer](https://aws.amazon.com/aws-cost-management/aws-cost-explorer/), "make it pretty easy to understand the costs and where you might be wasting money," Jun says. "We use AWS Cost Explorer often. It allows us to understand and trace back any big jumps or spikes in spend to a certain component or a certain change in the system."

Using [AWS Savings Plans](https://aws.amazon.com/savingsplans/), which offer a flexible pricing model, "is definitely a big cost reduction as well," Jun says.

## Integrating AWS Activate into Ramp's go to market strategy

As Ramp continues to succeed at building the next generation of finance tools, they've engaged with [AWS Activate](https://aws.amazon.com/activate/) for each stage of their startup journey. AWS Activate is a free program specifically designed for startups that offers resources for getting started on AWS.

"Activate has helped Ramp succeed from the product perspective," says Lewis. "The overall program has been instrumental in both Ramp's success and also that of some of our customers."

As Ramp grew, they joined [AWS Activate Providers](https://aws.amazon.com/activate/providers/), a program for startup-enabling organizations to provide AWS Activate benefits to their affiliated startups. As an AWS Activate Partner, Ramp offers AWS Activate benefits to their customers, as well as a $500 [sign-up offer](https://ramp.com/partners/aws-activate) for their product.

Alexis explains, "Through Activate Providers, we're able to offer up to $100k of AWS credits for Ramp clients. There's a strong overlap in our target customer base and it's a great lever for us to deliver more time and money savings to our customers, in line with our core mission."

## Tips for developing on AWS

For developers who want to build on AWS, Lewis and Jun share some insight and best practices that serve them well at Ramp:

- **To gain speed, keep it simple.** "Following the established patterns on AWS allows you to innovate really quickly; there's a well-trodden path for developers wanting to start companies on AWS," advises Jun. "In particular, I've had good experiences working with the solutions architects. When we have questions, they give us a lot of good insight into what's the simplest way and how they've seen it work in the past."

- **Harness the appropriate permissions and resource sizing from the beginning.** "Six months later, when your startup is off the ground, that sets you up for success in the long run," advises Lewis. "It helps you to pass security audits and ensure your company's finances—and your $100k in Activate credits–last you longer."

## The future of fintech and Ramp

Ramp expects the list of fintech innovations to continue to grow: Buy-now-pay-later, embedded finance options, flexible payment terms, and revenue-based financing (to name a few) are simply the beginning.

> _"The emergence of fintech as an industry sparked change in a financial services sector that had been dominated by large banks for hundreds of years. Agile, nimble, customer-focused startups like Ramp came into play to create great customer experiences and products."_ — Alexis

Ramp's upcoming plans include increasing automation, streamlining processes, and providing enhanced insights into spending data. "The innovation in fintech has been unbelievable and continues to be that way," says Alexis. "There's more to come."

---

## Authors

### Megan Crowley

Megan Crowley is a Senior Technical Writer on the Startup Content Team at AWS. With an earlier career as a high school English teacher, she is driven by a relentless enthusiasm for contributing to content that is equal parts educational and inspirational. Sharing startups' stories with the world is the most rewarding part of her role at AWS. In her spare time, Megan can be found woodworking, in the garden, and at antique markets.

### Alexis Gordon

Alexis leads Product Partnerships at Ramp. She oversees some of Ramp's most critical, inter-company relationships and is focused on accelerating Ramp's roadmap by creating delightful experiences through strategic alliances, product partnerships, and integrations. Prior to Ramp, she was at Deloitte Consulting driving post-merger integration efforts at leading financial services companies. She holds a BA from Vanderbilt University and an MBA from Columbia Business School. She lives in New York City.

### Jun Isaji

Jun Isaji is Director of Cloud Infrastructure at Ramp, responsible for managing the AWS infrastructure and for helping other software engineers utilize the platform. He was previously at Affirm, working on the checkout funnel, payment processing, and AWS infrastructure. Jun started his career at AWS, working on the Storage Gateway team in Boston. He lives in Miami.

### Lewis Drummond

Lewis is Head of Infrastructure at Ramp and oversees several teams. He has over twenty years of experience in architecting and deploying scalable, secure, and resilient cloud infrastructure, most often within AWS. Alongside financial services, Lewis has previously run large environments in a variety of industries, including education, fashion, healthcare, media, and technology. He lives in New York City.
