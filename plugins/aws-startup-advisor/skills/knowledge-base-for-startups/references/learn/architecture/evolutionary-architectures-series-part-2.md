---
source_url: https://aws.amazon.com/startups/learn/evolutionary-architectures-series-part-2
title: "Evolutionary architectures series: Part 2"
---

## Evolutionary architectures series: Part 2

> _"I think we may be onto something."_

"Evolutionary Architectures" is a four-part blog series that shows how solution designs and decisions evolve as companies go through the different stages of the [startups lifecycle](https://www.investopedia.com/articles/personal-finance/102015/series-b-c-funding-what-it-all-means-and-how-it-works.asp). In this series, we follow the aptly named Example Startup whose idea is to create a "fantasy stock market" application, similar to fantasy sports leagues. They envision holding four "tournaments" over the course of a year.

The [first blog](/startups/learn/evolutionary-architectures-series-part-1) describes how Example Startup reached their first major milestone by delivering a minimum viable product (MVP). In part 2, we will see how Example Startup continues evolving their solutions to meet an increase in requirements and growth.

## Building on the success of the beta launch

Things are starting to look up for Example Startup. The launch of their first MVP was a huge success for two reasons:

- The number of people that signed up for the beta cohort of fantasy investors grew exponentially after word about the product got out on social media.
- The startup got their first sponsors to chip in with some nice rewards for the winners of the beta cohort.

It is clear that the founders are onto something. Now, the startup needs some help before the next cohort begins and the company gets its first paying customers. It's time to start hiring. Example Startup needs engineers that can take over the platform development while the founders pivot to leadership roles and start taking care of everything needed to get their startup to the next stage.

The great news from Amazon Web Services (AWS) couldn't come at a better time. Example Startup is accepted into the [AWS Activate](https://aws.amazon.com/activate/) program which means they can now access free credits to cover their growing cloud expenses. This give them some much needed runway. While the credits are much appreciated, the AWS Activate program also includes a number of other perks like a [Premium Support Plan](https://aws.amazon.com/premiumsupport/), as well as a relationship with an [AWS account team](https://aws.amazon.com/blogs/startups/meet-your-aws-account-team/) that put technical and business expertise directly at their disposal.

With a couple of engineers joining the team, it is time to evaluate the solution that got them through the MVP and to begin planning for the next release. The technical founder starts the handoff to the engineers, which spurs many discussions around what went well and what needs more work. After documenting all the existing needs, gaps and questions, the team feels lost. There are so many options, so many decisions to make, and so little time. The technical founder decides it is time to talk to AWS again for some guidance.

## Enabling growth with more AWS services and features

One of the first things on Example Startup's list is [business reporting](https://www.sisense.com/glossary/data-reporting/). During the beta period, the founders didn't have much insight into metrics like user signups that would give them a better sense of how their beta release was going.

The AWS solutions architect suggests [Amazon QuickSight](https://aws.amazon.com/quicksight/) – a cloud-native, serverless business intelligence (BI) service. QuickSight has the ability to seamlessly integrate with their current database but also other data source they might need such as raw data in Amazon S3 or even data from external 3rd party providers. Building their first dashboards is a breeze with the user-friendly web interface allows them to quickly iterate to build what they want to see. Features like scheduled email reports allow them to wake up every morning with all the important information already in their e-mail inboxes. QuickSight also boasts threshold alerts that inform the team whenever any new milestones in subscriptions are achieved. What initially seemed like a huge undertaking was resolved in a matter of days.

The next big-ticket item for the team is accepting payments. This is something no one in the team has experience with. Following a couple of informative sessions with the AWS team, the team has a well-defined set of requirements that they send out to couple of different [AWS Partners](https://aws.amazon.com/partners/) who provide payment processing services. After a few introductory conversations, the team finds a partner who they believe is technically well-poised to take this important task off their plate.

With some of these agenda item out of the way, the team could finally focus on other technical decisions that will help them to sustain their expected growth. [AWS Amplify](https://aws.amazon.com/amplify/) served them well during the beta stage: It helped them a lot with preparing user interfaces suitable for mobile devices. They decide to continue relying on it for building and maintaining all of their current and future front-end applications. On the backend, they want to have more control over how they build their application services and the persistence layers they rely on. With the expectation of dealing with much larger volumes of data and to prepare for the new features they are planning, the team decides to take the advice of the AWS solutions architect and start looking into some purpose-built databases. [Amazon DynamoDB](https://aws.amazon.com/dynamodb/) did great, but with the long term plans of increasing the frequency of processing market data and calculating portfolios more often they start looking at time series databases like [Amazon Timestream](https://aws.amazon.com/timestream/) and some relational databases like [Amazon RDS for PostgreSQL](https://aws.amazon.com/rds/postgresql/). These purpose-built database services will allow the team to use the database engine that is best-suited to their different workloads.

On the application development side, the team wants to start implementing more complicated business logic without having to worry about increased operational overheads. They know they wanted to [containerize](https://www.docker.com/resources/what-container/) their workloads but aren't certain about which option will best fit their small team. The AWS team earns Example Startup's trust and becomes a frequent participant in the brainstorming sessions and decision-making process. AWS' recommendation on the container orchestration is [Amazon ECS](https://aws.amazon.com/ecs/) with capacity provided by [AWS Fargate](https://aws.amazon.com/fargate/) – the serverless compute for containers. The appeal of Fargate is that it provides a flexible scaling approach because of its pay-per-use functionality, without having to worry about patching the underlying operating system. Given the lack of certainty around the start date for the next cohort, this is a welcome option that gives the team more time to focus on their development activities.

Security is another topic gaining prominence on Example Startup's list of priorities. With the payment solution buildout underway, the platform will include a higher risk exposure. As part of the continuous efforts of anticipating startup needs and meeting them in a proactive way, AWS has recently published the [AWS Startup Security Baseline (AWS SSB)](https://docs.aws.amazon.com/prescriptive-guidance/latest/aws-startup-security-baseline/welcome.html) document. AWS SSB is a set of controls that create a minimum foundation for businesses to build securely on AWS without hindering agility. The team had some of their work cut out for them.

![The current architecture diagram for Example Startup.](https://d22k7geae6sy8h.cloudfront.net/files/649c7aa1a7e82b00086e771b/8ljg1ov9k-Architecture-diagram_part-2.png)

## Optimizing for cloud costs with AWS

The team is busy experimenting with ideas, implementing new technology, and learning how to use the services and features they might need. With [AWS Budgets](https://aws.amazon.com/aws-cost-management/aws-budgets/) already setup, the technical founder decides to get familiar with more tools to give them better oversight and control over their AWS spend. She learns about tools like [AWS Cost Anomaly Detection](https://aws.amazon.com/aws-cost-management/aws-cost-anomaly-detection/), an automated cost anomaly detector and root cause analysis with built-in machine learning (ML) and alerts. Diving deeper into the details, she learns about [AWS Cost Explorer](https://docs.aws.amazon.com/cost-management/latest/userguide/ce-what-is.html), a tool that provides the ability to view and analyze costs and usage details.

## Raising capital to support the startup's growth

The [AWS Activate](https://aws.amazon.com/activate/) credits helped with the AWS cost, but the team is growing and other expenses start piling up as well. The initial bootstrap funds are near depletion, gradually limiting the team's ability to experiment. It is time to start thinking about raising some capital. The founders have been getting ready for this moment for some time, with a deck almost ready. This is not something they have prior experience with, nor the contacts that would be able to help. They do have AWS on their side. The AWS team facilitates conversations with the Business Development teams, who are happy to help with advice and introductions to investors and venture capital firms. Exciting times are ahead.

_Check out the [first blog](/startups/learn/evolutionary-architectures-series-part-1) in the Evolutionary Architectures series._

---

## Authors

### Aayzed Tanweer

Aayzed is a Solutions Architect at AWS, working with startup customers in the FinTech space and with a special focus on analytics services. Originally hailing from Toronto, he recently moved to New York City, where he enjoys eating his way through the city and exploring its many peculiar nooks and crannies.

### Justin Plock

Justin is a Principal Solutions Architect at AWS, focused on fintech startups. He regularly meets with fintech founders to help ensure their business is secure and compliant with industry regulations. Prior to AWS, he was a Director of Cloud Enablement at a Fortune 200 insurance carrier and a Director of Engineering at a cybersecurity firm. He is passionate about helping startups develop securely and efficiently on AWS. He lives in Connecticut with his wife and two daughters.

### Zoran Nakev

Zoran is a Senior Solutions Architect at AWS, working primarily with FinTech startups and helping them to build solutions on the AWS platform. He uses his experience and passion for technology to assist startups in delivering on their goals. He lives in New Jersey with his family and enjoys spending his free time watching movies, listening to music, and taking long walks with his family dog.
