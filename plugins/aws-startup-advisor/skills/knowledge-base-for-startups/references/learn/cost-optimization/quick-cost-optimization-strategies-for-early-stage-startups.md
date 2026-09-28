---
source_url: https://aws.amazon.com/startups/learn/quick-cost-optimization-strategies-for-early-stage-startups
title: "Quick Cost Optimization Strategies for Early Stage Startups"
---

## Quick Cost Optimization Strategies for Early Stage Startups

Cost optimization is a top of mind consideration for any startup and can be achieved with a wide variety of techniques, but how you tackle it depends on the stage of your business's growth. Unlike enterprise companies, startups are laser-focused on product development. This can force startups to choose between time spent building extra functionality to manage costs, like reorganizing account structures or building cost analytics pipelines, and prioritizing low-effort-to-high-impact architectural changes to keep your momentum up.

In this post, we'll share three easy-to-implement cost optimization strategies to help you quickly understand and optimize your spend, then get back to building features that will drive value for your customers. The three main concepts to focus on are spend awareness, architecture adjustments, and usage discounts.

## Spend Awareness

Before making any changes, it's important to understand what and where you're currently spending. [AWS Cost Explorer](https://aws.amazon.com/aws-cost-management/aws-cost-explorer/) and [AWS Budgets](https://aws.amazon.com/aws-cost-management/aws-budgets/) are the most efficient tools to help you make informed cost decisions.

## Understand the Trends

AWS Cost Explorer helps you understand general spending trends quickly. As your business scales, so will your infrastructure costs, and Cost Explorer gives you a bird's-eye view of that spend. The home view of Cost Explorer shows your last six months of spend grouped by service, which will help you assess the following:

- _Where should I start my cost optimization efforts?_ The default view will show the top five services contributing to monthly spend, which is helpful if you're wondering which service you should start cost-optimizing and looking to make the biggest impact on spend.
- _Am I spending a significant amount on a service that doesn't fit normal patterns?_ Your answer may be workload-dependent, but, for example, storage costs are typically lower than compute costs, so you may not expect EBS volume spend to be significantly higher than your spend on Amazon Elastic Compute Cloud (Amazon EC2).

### Set a Budget

Even if you don't have a fixed budget for your infrastructure spend, we still recommend implementing AWS Budgets to track costs and get alerts when you've reached certain spend thresholds. Accidental misconfigurations could result in a painful bill, and alerts can help you catch and remedy mistakes before they snowball. If you don't have any budgeting alerts set up, take a few minutes to follow along with [this tutorial](https://aws.amazon.com/blogs/startups/how-to-set-aws-budget-when-paying-with-aws-credits/) to set one up.

## Architecture Adjustment

Once you understand your costs, you'll want to consider streamlining your architecture to be more cost-efficient. The changes we've highlighted below could yield the largest savings for the smallest amount of effort, so you can quickly get back to building your product.

### Turn Off Resources When Not in Use

This advice may sound obvious, but the easiest, fastest, and most impactful way to achieve cost savings is to turn off resources when they're not being used. In an average workweek, 70% of the hours are non-working hours. Imagine how much you could save by turning off non-production resources during that time! Tips to help you identify what to turn off:

- _Use tags:_ Use tags to determine what to turn off and differentiate between production and non-production resources.
- _Check Trusted Advisor:_ The [Cost Optimization pillar of Trusted Advisor](https://aws.amazon.com/premiumsupport/knowledge-center/trusted-advisor-cost-optimization/) will show idle resources, and is a good starting point to check for resources that can be turned off if you haven't tagged anything.
- _Identify non-constant workloads:_ Workloads that aren't constantly running can be turned off and turned back on again when needed. For example, you can stop Amazon SageMaker notebooks when not in use. Amazon Redshift has a [pause and resume feature](https://aws.amazon.com/blogs/big-data/lower-your-costs-with-the-new-pause-and-resume-actions-on-amazon-redshift/) to make this even easier.

Even if you know what needs to be turned off, that won't yield savings unless you actually turn them off. If you struggle with this, automate the process by leveraging solutions like the [AWS Instance Scheduler](https://aws.amazon.com/solutions/implementations/instance-scheduler/) to configure start and stop schedules for Amazon EC2 and Amazon RDS.

### Use the Newest Offerings

A simple way to reduce costs while maintaining performance is by using the latest and greatest of what AWS has to offer, including:

- _Using the latest generation of an instance type:_ Using the latest version of an instance type, for example, moving from m4 to m5, will improve price performance.
- _Exploring new instance types like the ARM-based AWS Graviton2 instances:_ Graviton2 processors offer up to 40% better price performance compared to current-generation x86-based instances. In addition to EC2, Graviton2 instance types are available for use with managed services like Amazon RDS, Amazon Aurora, Amazon ElastiCache, Amazon OpenSearch, and Amazon EMR. Because managed services eliminate infrastructure management tasks, switching to Graviton2 is a great way to yield cost savings without application code changes.

## Usage Discounts

If you're running a steady-state workload, you can confidently generate commitment numbers for a usage discount. But what if you're in your early stages of growth, or have unpredictable usage? [Compute Savings Plans](https://aws.amazon.com/savingsplans/compute-pricing/) help you strike a balance between evolving usage and getting savings for what you already use.

- _Why Compute Savings Plans and not EC2 Instance Savings Plans? What about Reserved Instances?_ Compute Savings Plans give you more flexibility than EC2 Instance Savings Plans and Reserved Instances, making them the ideal choice if you're still in the process of making architectural changes. They offer a percent discount on any compute usage (Amazon EC2, AWS Fargate, and AWS Lambda), meaning you can always use the newest generation of hardware while still getting savings. It's also an ideal option if you think you may switch instance types or re-architect between self-managed compute and serverless.
- _How big of a commitment should I make?_ The [Savings Plan recommendations](https://docs.aws.amazon.com/savingsplans/latest/userguide/sp-recommendations.html) provided in AWS Cost Management give a baseline value of how much to commit to. Because Savings Plans are a dollar-per-hour commitment, the recommendation is sized against the minimum amount of compute you use every hour. You can stack multiple Savings Plans, so it's good practice to start off with a conservative plan, and add more plans later if you continue to hit 100% use.

## Conclusion

Cost optimization is a continuous process and should be a part of your software development lifecycle. These suggestions are only the beginning of how early stage startups should be thinking about the process of cost optimization. Your development teams should consider cost when deploying new features, and your AWS account team can also be a great source to guide you in through the optimization process. By understanding your spend using AWS Cost Explorer and AWS budgets, turning off resources not in use, adopting the newest hardware, and leveraging Compute Savings Plans for flexible usage discounts, you can stay agile, while streamlining costs.

---

## Authors

### AWS Editorial Team

The AWS Startups Content Marketing Team collaborates with startups of all sizes and across all sectors to deliver exceptional content that educates, entertains, and inspires.

### Melissa Kwok

Melissa Kwok is a Solutions Architect at AWS, where she helps customers of all sizes and verticals build cloud solutions according to best practices. When she's not at her desk you can find her in the kitchen experimenting with new recipes or reading a cookbook.

### Faisal Farooq

Faisal Farooq is Solutions Architect at AWS on the Startups team. He routinely hosts customer open forums to help Startups to discuss the industry wide challenges. In his prior role, he worked with Fortune 100 companies as a cybersecurity consultant. He is passionate about helping startups use AWS more efficiently and securely.
