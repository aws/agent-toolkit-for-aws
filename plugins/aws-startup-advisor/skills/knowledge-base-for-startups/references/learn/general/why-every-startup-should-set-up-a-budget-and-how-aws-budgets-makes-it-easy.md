---
source_url: https://aws.amazon.com/startups/learn/why-every-startup-should-set-up-a-budget-and-how-aws-budgets-makes-it-easy
title: "Why every startup should set up a budget — and how AWS Budgets makes it easy."
---

## Why every startup should set up a budget — and how AWS Budgets makes it easy.

_Discover why every startup needs a budget and how AWS Budgets can help you track costs and optimize your AWS spend. Start maximizing your resources today._

## Do I really need a budget?

As a startup, chances are you're prioritizing speed to build fast and get your product onto the market as soon as possible. While being laser-focused on your product is essential, it also means it's easy to overlook your AWS spend, especially if you're running off credit programs like [AWS Activate](https://aws.amazon.com/activate/). You might also have team members wearing many different hats in their roles, making it difficult to spare headcount or attention toward managing costs.

But in a space where one surprise bill can break the business, freshly launched startups must be frugal from the get-go and keep a close eye on costs in order to maximize runway. According to CBInsights, [the number one reason startups fail is because they run out of money](https://www.cbinsights.com/research/startup-failure-reasons-top/) – so not establishing good cost-control habits from the beginning could end up being a big mistake.

Although monitoring costs on AWS might seem like an arduous task (and make it tempting to ignore the process altogether), it doesn't have to be. With AWS Budgets, it takes just a few minutes to set up a budget, which can help you catch surprise bills before they happen. You'll also be able to monitor costs and usage over time, allowing you to optimize your monthly bill and maximize usage of the perpetual AWS free tier once you've transitioned off of credits.

## What is AWS Budgets?

[AWS Budgets](https://aws.amazon.com/aws-cost-management/aws-budgets/) lets you set budgets to track your costs and usage, and you'll get notifications when budgets are exceeded at self-defined thresholds. AWS is built to handle workloads of any size, from early-stage startups to full-blown enterprises, so it's important to have a method in place to catch cost overruns or unexpected spend before you reach enterprise size. Putting a budget in place early on sets you up for success and helps you build good cost-hygiene habits from the start.

## Set it up

### 1-click deployment

Setting up a budget through the AWS console will take no more than a few minutes. If you'd like to follow along and learn the process, start at step 1. Otherwise, you can 1-click deploy a budget with the AWS CloudFormation template below. If you haven't used CloudFormation templates before, follow along [with the AWS CloudFormation getting started walkthrough](https://docs.aws.amazon.com/AWSCloudFormation/latest/UserGuide/GettingStarted.Walkthrough.html).

> **AWS Startup Advisor verification note (added to this snapshot):** The links below come from the [AWS source article](https://aws.amazon.com/startups/learn/why-every-startup-should-set-up-a-budget-and-how-aws-budgets-makes-it-easy); the citation alone does not establish current bucket ownership or template integrity. Before deployment:
>
> - Verify the hosting owner and template integrity with the publisher, for example using a checksum or signature obtained through an independently trusted publisher channel.
> - Review the template's resources and IAM permissions. To deploy the reviewed artifact, use [Upload a template file](https://docs.aws.amazon.com/AWSCloudFormation/latest/UserGuide/cfn-console-create-stack.html) or a publisher-verified, version-specific URL instead of fetching an unchecked mutable URL again.
> - Use the Launch Stack shortcuts only when the referenced artifact satisfies those checks. If you cannot access or verify the template, follow the manual console steps below.

| Region                  | View                                                                       | View in Designer                                                                                                                                                                | Launch                                                                                                                                                                                                    |
| ----------------------- | -------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| US East (N. Virginia)   | [View](https://aws-budgets-quickstart.s3.amazonaws.com/simple-budget.yaml) | [View in Designer](https://console.aws.amazon.com/cloudformation/designer/home?region=us-east-1&templateURL=https://aws-budgets-quickstart.s3.amazonaws.com/simple-budget.yaml) | [Launch Stack](https://console.aws.amazon.com/cloudformation/home?region=us-east-1#/stacks/new?stackName=BudgetQuickStart&templateURL=https://aws-budgets-quickstart.s3.amazonaws.com/simple-budget.yaml) |
| US East (Ohio)          | [View](https://aws-budgets-quickstart.s3.amazonaws.com/simple-budget.yaml) | [View in Designer](https://console.aws.amazon.com/cloudformation/designer/home?region=us-east-2&templateURL=https://aws-budgets-quickstart.s3.amazonaws.com/simple-budget.yaml) | [Launch Stack](https://console.aws.amazon.com/cloudformation/home?region=us-east-2#/stacks/new?stackName=BudgetQuickStart&templateURL=https://aws-budgets-quickstart.s3.amazonaws.com/simple-budget.yaml) |
| US West (N. California) | [View](https://aws-budgets-quickstart.s3.amazonaws.com/simple-budget.yaml) | [View in Designer](https://console.aws.amazon.com/cloudformation/designer/home?region=us-west-1&templateURL=https://aws-budgets-quickstart.s3.amazonaws.com/simple-budget.yaml) | [Launch Stack](https://console.aws.amazon.com/cloudformation/home?region=us-west-1#/stacks/new?stackName=BudgetQuickStart&templateURL=https://aws-budgets-quickstart.s3.amazonaws.com/simple-budget.yaml) |
| US West (Oregon)        | [View](https://aws-budgets-quickstart.s3.amazonaws.com/simple-budget.yaml) | [View in Designer](https://console.aws.amazon.com/cloudformation/designer/home?region=us-west-2&templateURL=https://aws-budgets-quickstart.s3.amazonaws.com/simple-budget.yaml) |                                                                                                                                                                                                           |

### Step 1 – Select a target amount

The first step is to establish a monthly budget value. Here's how to determine what that value should be:

- **Do you already have a set amount to spend monthly on infrastructure?** If so, use this for your budget value.
- **If not, have you run workloads on AWS for the last six months?** If so, go to the [AWS Cost Explorer home page](https://aws.amazon.com/aws-cost-management/aws-cost-explorer/), and the default view will show your overall spend from the last six months. Take the average of this monthly value, and use this figure for your budget value.
- **If you have less than six months of spend history, figure out your pain point.** What amount of monthly spend would break the bank? Use this figure for your budget value.

The purpose of a budget is to alert you before an unexpectedly costly bill causes substantial financial hardship. But once you start receiving notifications that you're exceeding your targets, it means you're already headed down a perilous path. For a budget to be effective, you'll want to come up with a sweet-spot value where you're not getting too many notifications, but just enough to provide visibility and give you time to correct any accidental misconfigurations.

### Step 2 – Create the budget in AWS Budgets

After you've determined your target value, go to [AWS Budgets](https://console.aws.amazon.com/billing/home#/budgets) and create a budget. Since the goal is to make sure you don't spend too much money across all services, choose the **Cost budget**, which will keep track of your dollar spend.

Select the following options when setting the budget amount:

- **Period**: Monthly
- **Budget effective date**: Recurring budget
- **Choose how to budget**: Fixed
- **Start month**: Leave as default
- **Budgeted amount**: The target amount you determined above

After setting the budget amount, you'll have the option to scope your budget, which lets you create budgets that apply only to specific sets of services, tags, regions, accounts, and more. For this example, however, the budget you're creating is acting as your "runaway spending budget," which is intended to catch cost overruns at a high level. Therefore, no scopes need to be applied.

However, as a general best practice you should have a separate budget for every workload you're running. You can use the budget scopes to help monitor things like testing and development costs on new services or Amazon Elastic Compute Cloud (Amazon EC2) instance types, or to set budgets for different teams within your organization. Additional examples of custom budgets you can set to avoid unexpected charges can be found [in the AWS checklist for avoiding unwanted charges](https://docs.aws.amazon.com/awsaccountbilling/latest/aboutv2/checklistforunwantedcharges.html).

### Step 3 – Set up notifications

You can configure alerts so that you'll get notifications if your spending reaches defined thresholds. You want to monitor spend, but you also don't want so many notifications that you start ignoring them. Therefore, we recommend that you start by creating two alert thresholds, so that you'll receive an email when you've hit 50% and 75% of your budgeted amount.

For a more advanced setup, you can [pipe notifications across other channels via Amazon Simple Notification Service (Amazon SNS)](https://docs.aws.amazon.com/sns/latest/dg/sns-create-topic.html), which will lets you expand notification methods to SMS, HTTP endpoints, and more. If you like to use Slack, you can connect Amazon SNS to AWS Chatbot to get your budget alerts sent directly to your Slack channel. For details on how to connect your Amazon SNS topic to [AWS Chatbot](https://aws.amazon.com/chatbot/) for Slack, follow along [with the AWS Chatbot getting started guide](https://docs.aws.amazon.com/chatbot/latest/adminguide/getting-started.html).

## Conclusion

Regardless of size or funding stage, every startup should have a budget to catch runaway spend at an account level. By investing just a few minutes of your time to set up this budget, you'll be able to avoid cost overruns, maximize your runway, and get in the habit of monitoring costs over the long term.

And while establishing this budget is an important step, [it's not the only action you can take toward managing costs](https://aws.amazon.com/blogs/startups/quick-cost-optimization-strategies-for-early-stage-startups/). Once you've established your first budget, consider expanding to include other budgets that track different dimensions – like tracking specific costs to each developer, or making sure you stay under a certain amount of machine learning training hours on a particular Amazon EC2 instance type. Even as your startup grows in size and complexity, AWS Budgets makes it fast and easy to keep tabs on costs without needing to invest hours tracking them by hand – and can help you avoid potentially expensive mistakes in the future.

---

## Authors

### AWS Editorial Team

The AWS Startups Content Marketing Team collaborates with startups of all sizes and across all sectors to deliver exceptional content that educates, entertains, and inspires.

### Melissa Kwok

Melissa Kwok is a Solutions Architect at AWS, where she helps customers of all sizes and verticals build cloud solutions according to best practices. When she's not at her desk you can find her in the kitchen experimenting with new recipes or reading a cookbook.

---

_Source: [AWS Startups](https://aws.amazon.com/startups/learn/why-every-startup-should-set-up-a-budget-and-how-aws-budgets-makes-it-easy)_
