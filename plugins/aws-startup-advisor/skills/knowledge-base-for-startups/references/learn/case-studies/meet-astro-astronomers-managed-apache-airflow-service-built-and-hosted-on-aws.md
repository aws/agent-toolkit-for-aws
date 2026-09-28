---
source_url: https://aws.amazon.com/startups/learn/meet-astro-astronomers-managed-apache-airflow-service-built-and-hosted-on-aws
title: "Meet Astro — Astronomer's managed Apache Airflow service built and hosted on AWS"
---

## Meet Astro — Astronomer's managed Apache Airflow service built and hosted on AWS

> **Source:** [AWS Startups](https://startups.aws/startups/learn/meet-astro-astronomers-managed-apache-airflow-service-built-and-hosted-on-aws)

![Astronomer Logo](https://d22k7geae6sy8h.cloudfront.net/files/64a2f5d59449f00008ef2403/8ljn2kvek-Logo-300x31.png)

For data to be useful in a modern enterprise, it must be collected and centralized from various sources, processed across a growing ecosystem of tools, and fed to systems across an organization in a way that's consumable across teams. This data orchestration —weaving business logic through the data stack for everything from dashboards to personalization algorithms — requires hundreds, if not thousands, of data pipelines.

Data orchestration is needed across all industries, in organizations of all sizes. With more than 2,200 contributors and over 12M monthly downloads, [Apache Airflow](https://www.astronomer.io/airflow/) has emerged as the open source standard for programmatically authoring, scheduling, and monitoring data pipelines. Data practitioners love Airflow because of its community, its flexibility, and its ability to provide a central view of a data ecosystem.

However, data teams naturally need more than open source Airflow on its own — they need test pipelines to ensure data quality, SDKs to make data practitioners productive, and observability plus lineage for the underlying data — even as they strive to minimize operational overhead. Data lineage provides the full context of the data by capturing in greater detail the relationships between data sources, where the data originated, and how it gets transformed and converged through the data lifecycle.

## Meeting the need for modern data orchestration

[Astronomer](https://www.astronomer.io/), a startup founded in 2018, has spent the last five years advancing Airflow as an open source project with tools that help data practitioners get the most out of data orchestration and data lineage. Astronomer's flagship product, [Astro](https://www.astronomer.io/product/), enables customers to build, run, and observe data pipelines on Airflow as a managed service, which allows data teams to spend more time focusing on writing business logic and expanding access to data.

"Many fundamental business processes that Astro orchestrates for our customers are powered by Amazon Web Services (AWS): [Amazon Simple Storage Service (Amazon S3)](https://aws.amazon.com/s3/), [Amazon Redshift](https://aws.amazon.com/redshift/), [Amazon EMR](https://aws.amazon.com/emr/), [Amazon SageMaker](https://aws.amazon.com/sagemaker/), and so many others," explains Viraj Parekh, Astronomer's Field CTO.

Co-founded by a small team that included three friends — Paola Peraza Calderon, Pete DeJoy, and Viraj Parekh — Astronomer describes its current mission as three-fold:

- Build products that increase the value that data teams get from data orchestration and data lineage.
- Cultivate the organic growth of the Airflow open source project and its community.
- Provide education, best practices, and support to data practitioners that enable their success with data.

![Pete DeJoy, product manager; Viraj Parekh, field CTO; Paola Peraza Calderon, product manager](https://d22k7geae6sy8h.cloudfront.net/files/64a2f63c9449f00008ef2404/8ljn2n21x-Founder-photos-1.png)

With more than 350 employees and a globally distributed team, both Astronomer and its customer base have grown quickly. "It started with people running open source Airflow and asking us for help with managing the infrastructure behind that," Pete says. "Now that we've solved infrastructure management, we're focused on the broader set of capabilities needed to take Airflow and use it as the foundation for a complete orchestration platform."

## Building and scaling on AWS

The market's need for Astronomer products, as well as the company's potential for success, was evident early on. Viraj laughs as he shares a story about their early days. "We were all hands on deck for a proof-of-concept with a large gaming company. The company relied on Astronomer to orchestrate the flow of data for its biggest launch of the year. The morning after the launch, there were no support tickets," says Viraj. "And I thought, 'Oh no, did something go wrong?' Turns out, something went right. Everything worked. We were handling 100% of the data ingest that was coming from one of this company's biggest launches, and everything ran without a hitch."

> _Why did Astronomer build its startup on AWS? "I can't say it was a decision. It was the obvious choice—AWS has been the cornerstone of our cloud strategy," says Paola. "As a baseline, the ubiquity of AWS services across countries and regions allows us to work with organizations around the world. It single-handedly unlocks our market."_

To meet the broadening needs of its customer base, Astronomer builds interfaces that allow data practitioners to get the most out of Airflow as they develop data pipelines and form a singular view of their ecosystem. Viraj explains: "We're merging data orchestration through any system you want—using whatever tools and services your team uses—with data lineage. Not only can you orchestrate data across all your systems, but you can see how that data moves."

As shown in the architecture diagram, Astro is built with a multi-plane architecture that consists of a control plane hosted by Astronomer and a data plane that can run in your cloud or in a single-tenant account hosted by Astronomer:

![The Astro architecture diagram](https://d22k7geae6sy8h.cloudfront.net/files/64a2f6659449f00008ef2405/8ljn2nyet-Astro-architecture-diagram-1024x746.png)

As Astronomer grows, the company has scaled its AWS footprint to meet the needs of its customers. Today, Astronomer relies on [Amazon Elastic Kubernetes Service (Amazon EKS)](https://aws.amazon.com/eks/) to run Astro as a managed service within a customer's corporate network, and supports tools like [AWS Transit Gateway](https://aws.amazon.com/transit-gateway/) and [AWS Private Link](https://aws.amazon.com/privatelink/) to securely connect to other data services in their network. Astro uses [AWS CloudFormation](https://aws.amazon.com/cloudformation/) to provision new Kubernetes clusters and Amazon S3 to store logs, and makes node instance types available for customers to choose the most optimal hardware to run their pipelines. This gives data practitioners optionality, performance, and efficiency where they need it.

"We're confident that as our market and customer base grows, AWS can grow with us. Being able to fine-tune AWS services to fit our needs helps us make Astro faster, more cost effective, and easier to run for our customers," says Paola.

## Building a successful startup

For startups looking to replicate their success, the Astronomer founding team agrees that it's critical to spend time with [early adopters of the product](https://www.forbes.com/sites/abdoriani/2020/08/06/how-to-identify-your-startup-early-adopters/?sh=49fdb851d0a7). This creates a tight feedback loop that improves your product early on, and often results in strong personal relationships that will guide you throughout the company-building journey.

> _"Especially for early-stage startups, the people who adopt your product first are most likely to understand the problem you're trying to solve. Curate those relationships over time, because these customers have been thinking about your problem and using your solution as long as you have." – Viraj Parekh_
>
> _"Ask a lot of questions — and put in the work. So much about taking a company through its early stages is about rolling up your sleeves, letting yourself iterate, and rallying a small team alongside you. As simple as it sounds, execution ultimately differentiates so many successful ventures." – Paola Peraza Calderon_
>
> _"As your company grows, the list of things to do will never end. It's a real skill to learn how to identify what the high-priority items are on the list and focus on accomplishing those." – Pete DeJoy_

## What's next for Astronomer?

As for what's next for Astronomer, Pete explains: "We want to build a generational company that creates real customer value, while cultivating talent among our employees, and allowing them to self-actualize in their careers. And we're going to get there by driving tangible, meaningful customer outcomes on a day-to-day basis."

---

## Authors

### Paola Peraza Calderon

Paola is a product manager and proud Astronomer co-founder. She's spent her 5+ years at Astronomer wearing many hats, but her core is in product management and developer documentation. She's made most of her impact by curating developer experiences across Astronomer's cloud service and leading a team of technical writers to make data engineering more accessible. Paola is a graduate of Georgetown University and spent 5 years in Cincinnati, Ohio, as a Venture for America Fellow. Originally from Mexico City, she currently lives in Brooklyn and is excited to keep growing Astronomer's footprint.

### Ganapathi Krishnamoorthi

Ganapathi Krishnamoorthi is a Senior ML Solutions Architect at AWS. Ganapathi provides prescriptive guidance to startup and enterprise customers helping them to design and deploy cloud applications at scale. He is specialized in machine learning and is focused on helping customers leverage AI/ML for their business outcomes. When not at work, he enjoys exploring outdoors and listening to music.

### Megan Crowley

Megan Crowley is a Senior Technical Writer on the Startup Content Team at AWS. With an earlier career as a high school English teacher, she is driven by a relentless enthusiasm for contributing to content that is equal parts educational and inspirational. Sharing startups' stories with the world is the most rewarding part of her role at AWS. In her spare time, Megan can be found woodworking, in the garden, and at antique markets.

### Pete DeJoy

Pete is a hands-on product manager and proud co-founder at Astronomer. He has spent the last five years working on solving data engineering problems. Throughout the journey, he has done just about every job imaginable, but his passion is at the intersection of technological innovation and product/market fit. In a past life, he played football at the collegiate level and was a competitive ski racer. He spent his academic years toiling with physics and chemistry, but most of that mental real-estate has since been replaced by Stack Overflow answers.

### Viraj Parekh

Viraj leads ecosystem efforts and is a proud Astronomer co-founder. Throughout his 6+ years at Astronomer, he's helped build and manage product, helped win customers, and scaled teams throughout the organization. Currently, he's focused on creating a first-class experience with Airflow/Astronomer and the rest of the data stack. Now a Brooklyn resident, Viraj spent 3 years living in Cincinnati, Ohio, as a Venture for America Fellow.
