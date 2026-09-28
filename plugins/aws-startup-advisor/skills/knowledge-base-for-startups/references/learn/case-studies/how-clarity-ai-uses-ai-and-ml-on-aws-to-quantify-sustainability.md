---
source_url: https://aws.amazon.com/startups/learn/how-clarity-ai-uses-ai-and-ml-on-aws-to-quantify-sustainability
title: "How Clarity AI uses AI and ML on AWS to quantify sustainability"
---

## How Clarity AI uses AI and ML on AWS to quantify sustainability

Building a sustainable company—from an environmental, social, and governance perspective—is a priority for many founders. But did you know a company's sustainability is becoming increasingly important to investors as well?

Global ESG fund assets—investments made based on how companies perform on environmental, social, and governance measures—jumped 12% in the fourth quarter of 2022 and were on track to reach [about $2.5 trillion](https://www.bankrate.com/investing/esg-investing-statistics/#stats) by the end of the year. With investors and executives increasingly factoring the environmental, social, and corporate governance impacts of organizations into their decision-making, using data to track and predict these impacts has become vital.

Today, [Clarity AI](https://clarity.ai/) offers a platform built on Amazon Web Services (AWS) that provides clear and actionable data on more than 70,000 companies, 360,000 funds, 198 countries, and 199 local governments for factors such as:

- Impact on people and the planet through the lenses of the United Nations Sustainable Development Goals
- Risk as linked to sustainability, and often through the industry consensus ESG framework supported by the standard of Sustainability Accounting Standards Board (SASB)
- Climate impact measured by carbon emissions and footprint, temperature, Net Zero alignment, and TCFD reporting (Task Force on Climate-Related Financial Disclosures) powered by [CDP data](https://www.cdp.net/en)
- Regulatory compliance (including the Sustainable Finance Disclosure Regulation (SFDR), EU taxonomy, and more)
- Biodiversity impact of the investments (including the Taskforce on Nature-related Financial Disclosures (TNFD) reporting requirements) in partnership with [GIST Impact](https://gistimpact.com/)

The platform covers screening of new investments, alignment of their sustainability mandates, portfolio monitoring and rebalancing, and automatic and customized reporting to inform internal or external stakeholders.

## All about analytics

How does "sustainability" of a company translate into numbers? With millions of potential data points on any given company, compiling and analyzing the metrics that are most significant can be a daunting task. Clarity AI uses artificial intelligence (AI) (including machine learning (ML)) and AWS to radically streamline and improve the process of measuring the impact of investments and organizations.

Until recent years, there were ambiguous standards of sustainability reporting that made it difficult to know what data to incorporate and how best to interpret it, explains Clarity AI's Board Director and Vice President of Product, Ángel Agudo. "It was difficult because people were making ratings about how good or bad the companies were, without providing the ability to understand exactly what that was based on," he says.

## Building their tech stack on AWS

To provide a full view of a company's sustainability footprint, you need to store and analyze a lot of data. To build an innovative product that does both of these things, Clarity AI decided to build with AWS.

> "We try to build on AWS managed services as much as possible because they allow us to focus on optimizing the time to market while minimizing the operational costs" explains Ángel.

From a technical perspective, Clarity AI's platform is divided into three sections:

- The first is the foundational platform, which includes cloud services, base services, and experimentation and development environments. Clarity AI manages their microservices using [Amazon Elastic Kubernetes Service (Amazon EKS)](https://aws.amazon.com/eks/), which allows their platform engineering team to offload the availability and scalability of the Kubernetes control plane. The entry point to this set of microservices happens through [Elastic Load Balancing (ELB)](https://aws.amazon.com/elasticloadbalancing/), specifically [Application Load Balancer](https://aws.amazon.com/elasticloadbalancing/application-load-balancer/). Storage services include [Amazon Simple Storage Service (Amazon S3)](https://aws.amazon.com/s3/) and [Amazon Elastic File System (Amazon EFS)](https://aws.amazon.com/efs/). Clarity AI uses purpose-built databases such as [Amazon Aurora](https://aws.amazon.com/rds/aurora/), [Amazon ElastiCache](https://aws.amazon.com/elasticache/), and AWS partner [MongoDB](https://partners.amazonaws.com/partners/001E000000U0VKNIA3/MongoDB). Clarity AI matches each database technology to the right use case to provide the best experience to their end users.
- The next section is the data platform, which captures data and transforms it so that AI algorithms can be applied. Clarity AI orchestrates these processes with Apache Airflow, using a combination of Python ETL jobs with [Amazon EMR](https://aws.amazon.com/emr/) clusters and [Amazon SageMaker](https://aws.amazon.com/sagemaker). Amazon S3 is the core storage technology.
- The last section is the customer-facing software as a service (SaaS), which includes all of the applications that are directly exposed to Clarity AI's customers.

## AI (and ML) are key

Clarity AI's algorithms pull data from official company sources such as sustainability reports, financial reports, and earnings calls, as well as research documents and other external sources. The platform can even parse unstructured data such as satellite images, allowing it to analyze the physical footprint of a company's operations.

In addition, its [large language models (LLMs)](https://aws.amazon.com/what-is/large-language-model/) use [natural language processing (NLP)](https://aws.amazon.com/what-is/nlp/) to parse millions of news articles for new information and trends.

"We are evaluating something like 1.4 million pieces of news from more than 30,000 trusted sources every day," Ángel explains. "These are sources that might be capturing issues that the companies are not going to report directly, but they can say a lot about how these companies are doing from a sustainability perspective."

Parsing the news automatically allows them to not only find new data points, but potential controversies as well. Using different NLP models, Clarity AI is able to extract the information, identify problems, and then evaluate the importance of the issues.

"A company might be named in the news for whatever reason. What we need to know is: Is this anything that might be putting the company at risk due to sustainability concerns? What is the specific issue?" says Ángel. This combination of data and contextualization gives Clarity AI an unparalleled view of exactly how a company is performing.

Automating this process allows for near-instant access to the very latest data via Clarity AI's API or web application. If a new earnings report or news article is released, it's incorporated immediately. AWS solutions such as SageMaker are instrumental in making this happen.

> "As we train proprietary NLPs, being able to run jobs with AWS GPUs while paying only for the compute time is crucial," says Ángel. "These NLP models enable us to efficiently collect the freshest quality data for the widest universe. We use SageMaker batch transform jobs to scalably process the inference of large numbers of documents and articles."

Using SageMaker, Clarity AI is able to process large data analytics and AI/ML workloads quickly and efficiently. This provides the most comprehensive and granular analysis possible, be it on an asset manager's entire portfolio or a founder's individual company.

This is only the beginning—as the Clarity AI team continues to innovate with how AI/ML can advance sustainability initiatives, they've also leveraged [Amazon SageMaker Studio](https://aws.amazon.com/sagemaker/studio/). This fully [integrated development environment (IDE)](https://aws.amazon.com/what-is/ide/) hosts Jupyter notebooks that facilitate the team's experimentation and collaboration.

## Better together

Along with meeting Clarity AI's technical needs, collaboration with AWS has helped Clarity AI to accelerate their business. Per Ángel, "The [AWS Activate](https://aws.amazon.com/activate/) program for startups has allowed us to accelerate experimentation and improve our time to market for new features."

As a member of AWS Activate, Clarity AI has participated in training and advisory sessions with AWS experts. "This has allowed us to introduce new services and capabilities with very little friction," says Ángel. "At the same time, AWS Activate has provided us with credits to carry out all of this experimentation with no additional cost." He explains, "These sessions have been crucial in introducing data science services, such as SageMaker, as well as in improving our operations and security."

AWS has also helped Clarity AI to use the [AWS Well-Architected Framework](https://aws.amazon.com/architecture/well-architected/?wa-lens-whitepapers.sort-by=item.additionalFields.sortDate&wa-lens-whitepapers.sort-order=desc&wa-guidance-whitepapers.sort-by=item.additionalFields.sortDate&wa-guidance-whitepapers.sort-order=desc) to evaluate their infrastructure. "Thanks to AWS, we've reinforced some decisions and created new initiatives within the engineering team to improve our platform," says Ángel. "Now, we've obtained [ISO 27001](https://www.iso.org/standard/27001) and SOC2 certifications and those sessions have proved extremely useful."

Together, Clarity AI and AWS are amplifying the importance of sustainability. Clarity AI recently presented "Sustainability Assessment Powered by Machine Learning," with support from AWS and NVIDIA, to attendees at Money20/20 in Las Vegas, Nevada. The two companies also co-hosted an ESG Opportunities panel at BattleFin's Discovery Day New York event.

## The future of better business choices

As sustainability has become increasingly valuable, investors and executives are looking for help navigating this fast-changing world. Clarity AI meets this need by using the [AWS Marketplace](https://aws.amazon.com/marketplace) as part of their go to market, offering their [ESG risk scores API](https://aws.amazon.com/marketplace/pp/prodview-fm47h2lm5pqgo?sr=0-1&ref_=beagle&applicationId=AWSMPContessa) directly to companies, funds, and portfolios.

"There's a strong relationship between AWS and financial institutions, so the more that we can use AWS to market to these institutions, the better," says Ángel.

And it's not just investors who are focusing on ESG issues; regulatory agencies around the world are preparing new rules on corporate environmental and social policies. As they do, a highly engaged public is paying closer attention than ever before.

"What we see on the horizon are strong and specific regulations that will force companies and financial institutions to be held accountable," predicts Ángel. Accountability means greater access to more accurate data, which Clarity AI is ready for.

---

> _Author: Megan Crowley, Senior Technical Writer on the Startup Content Team at AWS_
