---
source_url: https://aws.amazon.com/startups/learn/evolutionary-architectures-series-part-4
title: "Evolutionary Architectures Series: Part 4"
---

## Evolutionary Architectures Series: Part 4

> "Would you like coffee with that?"

"Evolutionary Architectures" is a four-part blog series that illustrates how solution designs and decisions evolve as companies go through the different stages of the [startups lifecycle](https://www.investopedia.com/articles/personal-finance/102015/series-b-c-funding-what-it-all-means-and-how-it-works.asp). In this series, we follow the aptly named Example Startup whose idea is to create a "fantasy stock market" application, similar to fantasy sports leagues. They envision holding four "tournaments" over the course of a year.

The [third blog post](/startups/learn/evolutionary-architectures-series-part-3) described how the startup began evolving their architecture into one that included tooling such as CI/CD pipelines and infrastructure-as-code, as well as implementing best practices, especially around security and authorization. In part 4, we'll see Example Startup formalizing their security and backup posture to meet various compliance standards. They also set a data strategy for the organization and explore additional lines of business to diversify their product portfolio.

## Using Series B Funding to Hire, Expand, and Scale

Things are going as well as they can for Example Startup. They recently closed a Series B round of funding that they expect to fuel some much-needed hiring, expansion, and scaling. With the funding and customer adoption has also come increased competition. Well-established players in the space are beginning to see them as serious competitors, and ramping up their marketing efforts.

Example Startup begins hiring to grow out functional areas and create dedicated teams for site reliability engineering (SRE), platform, analytics, and data science. With the competitive labor market and the startup's lack of a dedicated human resources department, they once again reach out to their AWS account team to ask about finding technical talent that is proficient with AWS. It turns out that the account team has already helped other startup customers in similar situations by suggesting [AWS Partners](https://aws.amazon.com/partners/work-with-partners/) that can assist with their hiring needs. Soon the startup has emails from multiple vetted candidates with AWS experience in their inbox. Fortunately, many of the interviews turn into job offers and the Startup is able to check hiring off of their to-do list.

The hiring spree leads to a technical problem: Teams are complaining that Example Startup's platform team is taking too long to set up new accounts for testing purposes and this is stifling innovation. The platform team explains that they don't have the bandwidth to build individual accounts any time someone gets a new idea for a feature. At this point in their AWS journey, the platform team has a biweekly meeting with their AWS account team and they bring up their dilemma. The AWS solutions architect (SA) recommends setting up a [Sandbox dedicated Organizational Unit (OU)](https://docs.aws.amazon.com/whitepapers/latest/organizing-your-aws-environment/sandbox-ou.html) within their AWS organization to rapidly provision temporary resources and environments for other teams that want to test new AWS services and features. Additionally, to keep costs under control, the SA recommends using automation to automatically stop resources such as [Amazon EC2](https://aws.amazon.com/ec2/) instances outside of normal business hours. The platform team at Example Startup follows the SA's advice. They're able to quickly spin up accounts for the different teams across the startup and do so in a cost-controlled manner.

Following this, the newly hired SRE team realizes that the startup can be better positioned from an availability and disaster recovery (DR) standpoint. They recognize that the startup is growing rapidly and as it begins to target larger customers, the startup will be faced with more stringent security requirements such as audits and compliance reviews. This meant a need for some infrastructural change. Luckily, a lot of the disaster recovery heavy-lifting was accomplished when Example Startup templatized their infrastructure into Terraform and transitioned into a multi-account architecture [in part 3](/startups/learn/evolutionary-architectures-series-part-3) of the series.

As a first step, the Example Startup team familiarizes themselves with the [AWS Resilience Hub](https://aws.amazon.com/resilience-hub/) to learn more about building resilient applications on AWS. The team still has some outstanding questions so they connect with their AWS account team, who introduces them to a SA with expertise in resiliency. The SA works with Example Startup to specify their recovery time objective (RTO) and recovery point objective (RPO) requirements and do a cost/benefit analysis of different [disaster recovery scenarios](https://aws.amazon.com/blogs/architecture/disaster-recovery-dr-architecture-on-aws-part-ii-backup-and-restore-with-rapid-recovery/). After a few calls with the SA and a lot of internal deliberation, the SRE team decides that their RTO/RPO requirements do not call for a multi-region setup as of yet. They make the decision to move their transactional data from [Amazon RDS for PostgreSQL](https://aws.amazon.com/rds/postgresql/) into [Amazon Aurora for PostgreSQL](https://aws.amazon.com/rds/aurora/), primarily for the higher availability it offers as well as the [Amazon Aurora Global Database](https://aws.amazon.com/rds/aurora/global-database/) functionality that is important for their production database. The startup also uses [AWS Audit Manager](https://aws.amazon.com/audit-manager/) to evaluate their adherence to the relevant compliance standards for the upcoming audit. Its automated evidence collection functionality saves them a lot of manual effort.

## Building a Better Customer Experience

After sifting through product feedback from various customers, the chief technology officer (CTO) realizes that the dashboarding capabilities offered to traders in Example Startup's trading application are lacking. Competitors allow users to easily see a visual representation of trading history and performance (compared to other traders) at a per trade level. The CTO flags this as a critical feature gap and the work was assigned to the new analytics team. Additionally, the CTO wants the team to allow traders to generate trading reports at will.

The analytics team has prior experience with [Amazon QuickSight](https://aws.amazon.com/quicksight/) so the dashboard component will be straightforward to enhance, including an [anomaly detection](https://docs.aws.amazon.com/quicksight/latest/user/anomaly-detection-function.html) feature to help traders find specific trades that are outliers. The reporting request is more complex as they do not want to upset the developer teams by running those reports on the production database (nor would that be considered good practice). After consulting the [Modern Data Architecture on AWS whitepaper](https://docs.aws.amazon.com/whitepapers/latest/modern-data-architecture-rationales-on-aws/modern-data-architecture-on-aws.html), the analytics team realizes that the best way to go about this is to load the Amazon RDS for PostgreSQL data into [Amazon Redshift](https://aws.amazon.com/redshift/), a data warehouse. By using Amazon Redshift's massive parallelism, they'll be able to run complex aggregations against this transactional data with far less latency and with the added advantage of not bottlenecking the production database. The analytics team is pleased to discover that since Amazon Redshift is built on top of the PostgreSQL engine, they can re-use most of their queries.

## Adding a New Line of Business to the Startup

As all of these changes take place, the chief executive officer (CEO) attends a meeting with one of her ex-colleagues at a major trading firm. She learns that there is a dearth of effective traders in the market and this is negatively affecting the trading firm's hiring pipeline and future projects. The CEO calls up a few of her friends at trading firms who confirm this to be an industry-wide shortage. The CEO starts to form an idea: Example Startup has plenty of traders who perform well. What if Example Startup provides their traders with some sort of cohort-based training which would then feed into a talent pipeline for these trading firms? It would give the traders a chance to enter the job market and the trading firms would have new talent.

Since a key portion of the training would be recommending the correct trades to new trainees, the CEO sets up a call with the data science team to learn how quickly they can build a machine learning (ML) model. Fortunately, some of the data science team has prior experience building, training, and deploying models with [Amazon SageMaker](https://aws.amazon.com/sagemaker/). Since Amazon Redshift is one of the available data sources for SageMaker, the data science team won't have to setup a complex extract, transform, and load (ETL) pipeline. Members of the data science team who were less experienced with SageMaker were invited to a SageMaker-focused immersion day by their AWS account team to quickly upskill. Soon they too were on their way to creating training jobs, building accurate models, and deploying the models to endpoints. Anticipating the call from Example Startup's finance team regarding the increasing compute costs, the data science team did some research and found that they could actually run their training jobs (which account for approximately 80% of their total costs) on [spot instances](https://docs.aws.amazon.com/sagemaker/latest/dg/model-managed-spot-training.html). By doing so, they were able to significantly reduce their costs.

As news of this talent development initiative as a new line of business and revenue stream spreads among the industry, more venture capital (VC) firms began expressing interest in Example Startup–even before the startup expresses intent to start another fundraising round!

A few quarters later, guided by marketing efforts, co-marketing efforts with AWS, and some word of mouth from existing customers, the talent development initiative of Example Startup had grown rapidly. As exciting as the growth in customer base is, more exciting is the fact that the startup is, for the first time since inception, in the green! Recruitment turns out to be a profitable business for the startup and it grows by the day. The executive team realizes this steady profitability stream could fuel the rest of their business. They work diligently on further expansion and innovation plans, excited by the incredible future ahead.

## Summary

Over the course of this four-part series, Example Startup cycles through the main stages of a startup from nascency to a matured company. Most startups begin with little more than a bold idea and a dedicated founding team. They build a minimum viable product (MVP) with serverless infrastructure that allows them to test their idea in a way that the founding team can manage on their own.

As the startup acquires paying customers and secures post-seed funding, they move onto the "being onto something" phase, where their architecture evolves and they start to think seriously about scaling, security, and development agility. This means improvements such as using build tools and setting up monitoring and purpose-built databases.

One of the most important lessons during these stages is to engage with the AWS team early and often, even before starting projects, to help evaluate options and save time. Access to both business and technical resources can accelerate timelines and help early stage startup teams achieve their goals.

After the product market fit stage, startups may begin hiring more and focus primarily on scaling – the "to the moon" phase. At this point, they start looking at a multi-account strategy, using service-oriented architecture, caching, and other architectural tweaks to optimize their application and improve the customer experience from a technical perspective.

Finally, they enter the hyper-scale stage where they may begin extensive hiring and build out additional lines of business. From a technical perspective, the startup has invested a lot of time and engineering effort in improving things like security and controls and permissions for their environment. They likely have a codified version of their environment which they can leverage for rapid international expansion and disaster recovery, among other use cases. They've also built out a data strategy and are in the process of using analytics and machine learning to better understand their customer and business. This final phase can vary. Some startups will be on the path to an acquisition, whereas others may pursue profitability and market dominance.

Ready to begin your startup journey? Join [AWS Activate](https://aws.amazon.com/activate/) to build and scale your startup with the right resources at the right time.

## Related Articles in this Series

- [Evolutionary Architectures, Part 1 – "I've got this great idea!"](/startups/learn/evolutionary-architectures-series-part-1)
- [Evolutionary Architectures, Part 2 – "I think we may be onto something."](/startups/learn/evolutionary-architectures-series-part-2)
- [Evolutionary Architectures, Part 3 – "To the moon."](/startups/learn/evolutionary-architectures-series-part-3)

---

## Authors

### Aayzed Tanweer

Aayzed is a Solutions Architect at AWS, working with startup customers in the FinTech space and with a special focus on analytics services. Originally hailing from Toronto, he recently moved to New York City, where he enjoys eating his way through the city and exploring its many peculiar nooks and crannies.

### Justin Plock

Justin is a Principal Solutions Architect at AWS, focused on fintech startups. He regularly meets with fintech founders to help ensure their business is secure and compliant with industry regulations. Prior to AWS, he was a Director of Cloud Enablement at a Fortune 200 insurance carrier and a Director of Engineering at a cybersecurity firm. He is passionate about helping startups develop securely and efficiently on AWS. He lives in Connecticut with his wife and two daughters.

### Zoran Nakev

Zoran is a Senior Solutions Architect at AWS, working primarily with FinTech startups and helping them to build solutions on the AWS platform. He uses his experience and passion for technology to assist startups in delivering on their goals. He lives in New Jersey with his family and enjoys spending his free time watching movies, listening to music, and taking long walks with his family dog.
