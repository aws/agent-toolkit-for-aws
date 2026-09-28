---
source_url: https://aws.amazon.com/startups/learn/how-rox-is-transforming-revenue-teams-with-ai-driven-integration-powered-by-aws
title: "How Rox is transforming revenue teams with AI-driven integration powered by AWS"
---

## How Rox is transforming revenue teams with AI-driven integration powered by AWS

> With infrastructure built from the ground up using a variety of AWS services, Rox benefited immensely from the robust expertise of AWS.

In order to compete in today's rapidly evolving business landscape, we have witnessed a transformational shift towards consumption-based pricing models. These models charge customers for the exact amount of a product or service they use, rather than a set fee. As a result, it is vital that revenue teams have access to their product usage data, so they can gain a holistic view of how customers interact with their products.

To achieve this, revenue teams are unlocking the power of their customer data by shifting their systems of record (SOR)—consisting of critical information from customer relationship management (CRM), support, and accounting systems—into centralized data warehouses. These warehouses allow product usage data to be combined with other business systems, enabling better data-driven analysis and decision-making.

## The need to streamline the revenue stack

With systems of record moved to data warehouses, businesses now face a sprawling array of new tools added to their systems of engagement (SoE)—the platforms used to capture the daily workflows of revenue teams.

These workflows include:

- Account research
- Pipeline generation
- Outreach
- Meeting recordings
- Transcripts
- Business review prep
- Monitoring usage
- Escalations
- Data entry into CRMs
- And more

An estimated 10,000+ tools have been designed to engage with these scattered and fragmented workflows across multiple systems of engagement.

This means revenue teams are spending valuable time navigating between tools, instead of focusing on revenue-generating activities.

After observing this first-hand in multiple leading B2B software as a service (SaaS) company, the founders of [Rox AI](https://www.rox.com/) dedicated themselves to creating a vertically-integrated stack. It consolidates both the systems of record and systems of engagement in a way specifically tailored to revenue teams. This unified platform promises to streamline workflows, reduce tool fatigue, and ultimately empower revenue teams to focus on what they do best: driving growth.

## How Rox leverages AWS to power the vertical revenue stack

Rox is a proud participant in the [Amazon Web Services (AWS) Startups Activate program](/startups), a program that helps startups bring their ideas to life with aligned business support and provided [Activate credits](/startups/credits).

With infrastructure built from the ground up using a variety of AWS services, Rox benefited immensely from the robust expertise of AWS. This freed them to focus on building and scaling their solution efficiently.

## Rox system of record

At the core of Rox's solution is a robust system of record. This integrates data from diverse sources to provide revenue teams with a unified view of customer information.

It works by collecting and consolidating into a central data lakehouse:

- Transactional data (through the Rox web app)
- Analytical data (shared by enterprise customers)
- Unstructured data (through content ingestion pipelines and meeting recordings from the Rox Mac app)

This validates that all customer related information is up-to-date, secure, and accessible in a single location, enabling seamless data management and analysis.

## Rox as a warehouse-native solution

To meet the diverse needs of enterprise customers, Rox provides two options for managing customer data:

1. **Amazon Redshift Data Share:** For enterprises that have already established data pipelines into [Amazon Redshift](https://aws.amazon.com/redshift/?nc2=type_a), Rox offers an Amazon Redshift data share option. Here, Rox sets up a consumer Amazon Redshift cluster, which solely manages compute resources, while the data remains on the customer's Amazon Redshift producer cluster. This arrangement maintains strict data security and compliance by never storing data at rest on Rox's infrastructure, providing customers peace of mind regarding data governance.

2. **Rox Managed Amazon Redshift:** For customers without dedicated data teams or existing pipelines, Rox also provides a fully managed Amazon Redshift solution. Through an extract, transform, load (ETL) provider, Rox collects data from various business systems, and consolidates it in an Amazon Redshift cluster managed by Rox.

In both setups, Rox constructs a private knowledge graph that combines data from multiple business systems, empowering revenue teams with enhanced insights and streamlined access to critical information.

## Rox public knowledge graph

Rox enriches its system of record by building a public knowledge graph using [AWS Lambda](https://aws.amazon.com/pm/lambda/). This large-scale knowledge extraction process continuously pulls and processes news articles, job postings, financial data, blog entries, press releases, and product launch information.

By combining this publicly available data with customer-specific insights, Rox maintains a knowledge graph that empowers revenue teams with broader contextual knowledge about clients and their industries. This external data, combined with meeting recordings and CRM data stored in [Amazon Aurora](https://aws.amazon.com/rds/aurora/) (with PostgreSQL compatibility), provides a comprehensive resource that fuels the AI-driven insights.

## Rox Agent Swarm

Rox's intelligent agent system, called [Agent Swarm](https://www.rox-ai.com/), is a fleet of AI agents that operates on top of Rox's system of record. Each agent is paired with a specific customer and account executive, continuously monitoring and managing relevant information. Event-driven and always on, these agents handle daily workflows autonomously, or assist as co-pilots, effectively working as an extension of the revenue team.

Rox leverages [Amazon SQS](https://aws.amazon.com/sqs/) for the workflow event management. Rox also has a robust context management framework for various workflows and leverages [Amazon Bedrock](https://aws.amazon.com/bedrock/) with [Llama models (from Meta)](https://aws.amazon.com/bedrock/llama/) for some of the agentic workflows. These agents enable large language models (LLMs) to act autonomously, performing tasks or providing assistance on behalf of users.

## Rox interaction layer

Rox's web app, Mac app, and API are central to its user interface, allowing revenue teams to interact with the system. The [AWS WAF](https://aws.amazon.com/waf/?nc2=type_a) and [Elastic Load Balancing (ELB)](https://aws.amazon.com/elasticloadbalancing/) manage and secure traffic to these applications, while [Amazon ElastiCache](https://aws.amazon.com/elasticache/) enhances application performance by providing caching capabilities. Rox relies on [Amazon ECS](https://aws.amazon.com/ecs/) for scalable and managed compute resources, hosting multiple ECS services within the Rox virtual private cloud (VPC). Amazon ECS enables Rox to handle various processing needs, including data transformations, AI workflows, and user request handling.

Rox AI CTO and Co-Founder Shriram Sridharan says, "We are incredibly happy to have chosen AWS as our cloud provider to build Rox on. The support provided for technical guidance, support and the tooling, especially for budding startups, was next to none. I am an AWS veteran myself (part of the Amazon Aurora team pre-launch) and would expect nothing less."

![Overview of the Architecture](/images/rox-architecture.png)

_The diagram outlines the Rox AI architecture, showcasing the integration between customer data systems and Rox's proprietary infrastructure, built on Amazon Web Services (AWS)._

## The future of revenue teams

As Rox looks to the future, it's clear that they've only just begun to explore the possibilities of a truly transformative revenue stack. The next generation of revenue systems will be fully event-driven, seamlessly integrating both structured and unstructured data and operating in an agentic manner.

Generative AI agents will play a central role in this progress, continuously monitoring accounts across both public and private information sources to deliver actionable insights and recommended next steps. These agents won't just advise, but will be empowered to take proactive steps in areas like prospecting, renewals, and churn prevention—automating critical actions to drive revenue growth.

While generative AI agents won't replace revenue teams, they will augment them, creating a generative AI-enabled workforce that is relieved of repetitive, non-value-adding tasks. This will allow revenue teams to focus on high-impact, strategic activities—elevating their productivity and effectiveness like never before.

You can try Rox AI by signing up now: [run.rox.com](https://run.rox.com/)

Contact an [AWS Representative](https://aws.amazon.com/contact-us/) for more information about how we can help accelerate your business.

---

### Further reading:

- Visit the AWS Startups [Learn](/startups/learn) page, featuring informational articles, technical guidance, and blogs showcasing other AWS-powered startups that are changing the game.
- Have the next best startup idea? Check out how [AWS Startups](/startups/build) can help you build it.
- Join [AWS Activate](/startups), our flagship startup program home to over 280,000 startups. Get personalized AWS expertise, access exclusive programs and discounts, and utilize a robust set of tech tools meant to power your innovation.
- Rox AI just secured $50M in funding from 40+ angel investors – learn more [about the Rox AI launch](https://www.rox.com/launch).

---

## Authors

### Andrew Brown

Andrew Brown is an Account Executive for AI Startups at Amazon Web Services (AWS) in Austin, Texas. With a strong background in cloud computing and a focus on supporting early-stage startups, Andrew specializes in helping companies scale their operations using AWS technologies.

### Ishan Mukherjee

Ishan is the Co-Founder/CEO of Rox, a Sequoia backed AI company. Before Rox, he was the CGO at New Relic which acquired his company Pixie Labs, led product at Siri Knowledge Graph at Apple, Lattice Data (acquired by Apple), Premise Data, and Amazon Robotics. Ishan was also an early engineer in Kiva (acquired by Amazon) where he joined after graduating from MIT.

### Shriram Sridharan

Shriram is the Co-Founder/Engineering Head of Rox, a Sequoia backed AI company. Before Rox, Shriram led the data infrastructure team at Confluent responsible for making Kafka faster and cheaper across clouds. Prior to that he was one of the early engineers in Amazon Aurora (pre-launch) re-imagining databases for the cloud. Aurora was the fastest growing AWS Service and a recipient of the 2019 SIGMOD systems award.
