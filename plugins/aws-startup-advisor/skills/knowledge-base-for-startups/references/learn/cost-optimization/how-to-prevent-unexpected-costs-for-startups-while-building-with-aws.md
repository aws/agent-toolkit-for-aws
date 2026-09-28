---
source_url: https://aws.amazon.com/startups/learn/how-to-prevent-unexpected-costs-for-startups-while-building-with-aws
title: "How to prevent unexpected costs for startups while building with AWS"
---

## How to prevent unexpected costs for startups while building with AWS

> _By Xuan Gao, Startup Solutions Architect, and Carole Suarez, Startup Solutions Architect_

As a startup, your days are filled with competing priorities: you want to focus your time on innovation and product market fit—not worrying about underlying infrastructure or unexpected costs. The cloud management firm Right Scale estimates that [wasted cloud spend averages about 35%](https://www.globenewswire.com/news-release/2017/11/13/1208218/0/en/RightScale-Estimates-Companies-to-Waste-More-Than-10-Billion-in-Cloud-Spending-Over-the-Next-Year.html), with small and medium-sized companies overspending the most. With this in mind, we've created this how-to guide to make sure your startup doesn't end up spending thousands of dollars due to a spike that could have been prevented through monitoring or an alarm. We'll cover best practices for new and existing AWS accounts when it comes to fundamental security, monitoring, and cost management. We'll also get into the nitty gritty when it comes to proactively setting up alerts on anomalous usage of services due to over provisioning of services and/or misconfiguration. By following these four recommendations, you can extend your runway and create a long-term strategy for cost management.

## Securing your account and workloads

**The principle of least privileges** is a security principle that entails granting only the permissions through Identity and Access Management (IAM) required to complete a task. Prohibiting unauthorized use of services allows you to more closely control access to your AWS Account and may prevent unauthorized charges. To do this, you'll need to decide which users or applications will perform a specific task and the exact permissions needed to complete it. For instance, under the principle of least privileges, Business Intelligence analysts would only be granted the access to analytics services, such as Amazon QuickSight and Amazon Athena.

**Regularly rotating access keys** is another way to prevent extraneous charges. Make sure that all of your account users—including yourself—regularly change their passwords. This will limit both the amount of time a compromised credential can affect your startup and ensure that users will not be able to access resources after they've left the company.

**Set up a multi-account AWS environment** with [AWS Organizations](https://aws.amazon.com/organizations/). This free AWS service will allow you to set up separate development and production accounts. As your workload grows and becomes more complex, you can remain flexible when it comes to billing, security controls, and budget requirements. We recommend dividing your workloads into production, testing, and development environments to more easily determine your operational costs, based on the regulatory and budget needs of your startup. This may also protect your production environment from unauthorized testing, which could lead to downtime or configuration errors.

## Monitoring cost and usage

**Use [AWS Budgets](https://aws.amazon.com/aws-cost-management/aws-budgets/) to set up daily budgets and alerts.** Daily—as opposed to monthly or weekly—granularity will alert you to upticks in charges via email and SNS. Daily alerts are especially useful if services are provisioned over the weekend. Daily alerts also allow you to manage resources appropriately, correct any misconfigurations before too much time has passed, and prevent unpleasant surprises at the end of the month.

**Use [AWS Cost Anomaly Detection](https://aws.amazon.com/aws-cost-management/aws-cost-anomaly-detection/) to detect anomalous usage of services automatically.** AWS Cost Anomaly Detection is effective in part because it's customizable. By segmenting spends—for instance, tracking AWS Lambda and Amazon Simple Storage Service (Amazon S3) separately—you get fewer false alerts. You can also choose the level of granularity used to analyze spending. Our founders have already found this useful; using Cost Anomaly detection, one customer noticed a 50% uptick in Amazon CloudWatch spend and was able to quickly get in touch with their AWS team and better understand their usage of services.

**Use [AWS CloudTrail](https://aws.amazon.com/cloudtrail/) to set alerts for service usage.** AWS CloudTrail is an easy-to-use tool that allows customers to review account activity and categorize it into "events"—essentially keeping a record of all related activity, which can help when troubleshooting the root cause of anomalous costs. For example, a user may have unauthorized access to a service and using AWS CloudTrail, you would be able to determine who, when and at what time the event occurred.

**Use Amazon CloudWatch to set monitoring alerts for high usage.** Through Amazon CloudWatch, you can enable billing alerts, create billing alarms, and receive SNS notifications when spending exceeds your threshold. Another benefit to Amazon CloudWatch is monitoring usage patterns over time and setting alerts, giving much-needed data when it comes to forecasting trends and optimizing spending going forward.

## Leveraging AWS for additional support

**Set up [AWS Trusted Advisor](https://aws.amazon.com/premiumsupport/technology/trusted-advisor/) for further security and cost optimization.** Trusted Advisor is a resource that provides you with a full set of checks that become available as the support plan is upgraded. For example, when Amazon Elastic Block Stores (Amazon EBS) are created, customers incur a charge—even when they're unattached or have low write activity. By implementing checks on Amazon EBS volumes, customers can determine which are under-utilized and remove them to cut costs. Similarly, [Savings Plans](https://aws.amazon.com/savingsplans/) will check customers' usage of Amazon EC2, AWS Fargate, and AWS Lambda over a 30-day period and provide recommendations for usage amounts for one- to three-year periods—at a discounted rate.

## Going forward with confidence

For startups looking to prevent unexpected costs while building on AWS, we highly recommend following the above steps. By securing your account, using monitoring tools to more closely manage service usage, and leveraging AWS Trusted Advisor, you're on your way to better financial management. Our Well-Architected Framework Review can help you implement a clear-eyed strategy for success, providing insight on how to architect for best practices and maximize cost optimizations. For customers who have already discovered cost spikes, we recommend reaching out to the AWS team for support. [You can view more information on support plans here](https://aws.amazon.com/premiumsupport/plans/).

---

_AWS Editorial Team - The AWS Startups Content Marketing Team collaborates with startups of all sizes and across all sectors to deliver exceptional content that educates, entertains, and inspires._
