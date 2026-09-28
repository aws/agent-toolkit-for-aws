---
source_url: https://aws.amazon.com/startups/learn/fast-reliable-and-cost-efficient-builds-tests-at-scale-with-engflow-remote-execution-on-aws
title: "Fast, reliable, and cost-efficient builds/tests at scale with EngFlow Remote Execution on AWS"
---

## Fast, reliable, and cost-efficient builds/tests at scale with EngFlow Remote Execution on AWS

**Authors:** Christian Mueller, Luis Pino

_Gain a competitive advantage and discover EngFlow's platform for large-scale builds and tests on AWS, enabling fast and cost-effective software development._

---

Even as modern engineering organizations adopt microservice architectures and decompose their monolithic applications, large and complex code bases are common. More code leads to longer build/test cycles, which degrades developer productivity and increases cost. In addition, finite [continuous integration](https://aws.amazon.com/devops/continuous-integration/) (CI) compute budgets cause execution queuing, which further saps engineering productivity.

EngFlow helps modern organizations improve their build and test cycles to maximize productivity of software development teams through [Remote Execution and Caching](https://docs.engflow.com/docs/re.html).

To provide performant, reliable, and cost-effective solution to its customers, EngFlow followed the best practices from the [AWS Well-Architected Framework](https://aws.amazon.com/de/architecture/well-architected/). In this post, we'll focus on the practices that helped improve the price-performance ratio and improve availability.

## EngFlow Remote Execution service's architecture

EngFlow customers interact with the Remote Execution service over a secured and private channel, protected on several layers using different network technologies like [Network Load Balancer](https://aws.amazon.com/elasticloadbalancing/network-load-balancer/) and virtual private cloud (VPC) endpoints, subnets, and security groups (see Figure 1).

Schedulers, which run on [Amazon Elastic Compute Cloud (Amazon EC2)](https://aws.amazon.com/ec2) instances with [Amazon Elastic Block Store (Amazon EBS)](https://aws.amazon.com/ebs) volumes, divide each build/test request into independent parts and place the individual build/test jobs on existing worker instances, which fulfill the build/test job compute/memory requirements. [AWS Auto Scaling](https://aws.amazon.com/autoscaling) is used to provide self-healing capabilities by maintaining a fixed number of running scheduler instances. Failed Amazon EC2 scheduler instances are replaced automatically without the need for human intervention.

EngFlow's Remote Execution software distributes build/test actions across hundreds or even thousands of Worker instances, which all run on EC2 instances with mounted EBS volumes. Here, EngFlow uses AWS Auto Scaling to scale the required compute capacity in and out based on demand, minimizing waste and maximizing utilization. To support different customer needs and offer a cost-efficient solution, Worker instances can run on [EC2 On-Demand](https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/ec2-on-demand-instances.html) or [Spot Instances](https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/using-spot-instances.html). EngFlow provides the ability to fall back to On-Demand instances for greater reliability.

Remote Execution pairs with EngFlow's Remote Caching solution to prevent work duplication. By caching all build/test artifacts on local storage performed by an organization, EngFlow allows teams to download previous build/test artifacts rather than to re-execute the build/test themselves. This shortens the build/test time and decreases the cost per build/test. As instances in the cloud come and go, the build/test artifacts are durably and cost-efficiently synced to [Amazon Simple Storage Service (Amazon S3)](https://aws.amazon.com/s3) for persistent access.

To support operations when deployed into a customer account, EngFlow's Remote Execution solution uses AWS standard services like [Amazon CloudWatch](https://aws.amazon.com/cloudwatch) Logs, Metrics, and Alarms.

![Figure 1. EngFlow Remote Execution solution architecture on AWS](https://d22k7geae6sy8h.cloudfront.net/files/64a2f47773217a00082c811b/8ljn2dcnp-Figure-1.-EngFlow-Remote-Execution-solution-architecture-on-AWS-1.png)

> _Figure 1. EngFlow Remote Execution solution architecture on AWS_

Let's take a deeper look at how EngFlow enables fast, reliable, cost-efficient builds on AWS and how they identified areas to improve their Remote Execution solution when working through their Well-Architected review.

### Performance

Many EngFlow customers consider build/test speed as one of EngFlow's primary value propositions. It translates to increased developer productivity, faster time-to-market and the ability to run more experiments at the same time, just to name a few. Running a CI build/test in the cloud and using distributed compute nodes from the latest and most powerful CPU generation instead of a local workstation helped customers like [Blue River Technology](https://www.engflow.com/caseStudies/bluerivertechnology) achieve a 9 times performance gain for their CI build/test.

EngFlow engineers help their customers select the most performant and cost-efficient EC2 instance that best fit their unique requirements, like the [latest generation AWS Graviton3 processors](https://aws.amazon.com/ec2/instance-types/c7g/). They use the latest EBS gp3 volumes, which provide the latest general purpose SSD volumes generation to customers to ensure builds/tests are as fast as possible. This was possible by analyzing the unique customer workload, leveraging standard and custom CloudWatch metrics.

In addition, the ability to fine-tune the AWS Auto Scaling configuration for Worker instances helps EngFlow find the optimal balance between capacity and cost so their customers always having enough compute and storage capacity to start a new scheduled build/test immediately, while not wasting money on idle resources.

### Reliability

EngFlow has been following AWS best practices for providing a reliable service from the start to run time-critical build/tests for thousands of developers.

Their AWS Auto Scaling configuration spans across three [AWS Availability Zones](https://aws.amazon.com/about-aws/global-infrastructure/regions_az/) in the selected AWS Region to scale based on a customer's demand, withstand a local service disruption, and provide self-healing capabilities by replacing failed Amazon EC2 instances automatically. Amazon S3 complements the solution as a durable and highly available storage service for build/test artifacts.

During the Well-Architected review, EngFlow discovered an area to improve the reliability of their service. [Amazon EC2 Auto Scaling](https://aws.amazon.com/ec2/autoscaling/) uses termination policies to determine which instances it terminates first during scale-in events. Termination policies define the termination criteria that are used by Auto Scaling when choosing which instances to terminate.

By default, the termination policy selects the Availability Zone with the most instances. It terminates the instance that was launched from the oldest launch template or launch configuration. If the instances were launched from the same launch template or launch configuration, Amazon EC2 Auto Scaling selects the instance that is closest to the next billing hour and terminates it.

EngFlow observed that this default termination policy sometimes terminated EC2 instances that were in the middle of executing valuable work for our customers. While EngFlow Remote Execution automatically retried the job, it led to longer build/test executions, higher cost, and customer inquiries. By [creating their own custom termination policy](https://docs.aws.amazon.com/autoscaling/ec2/userguide/lambda-custom-termination-policy.html) in combination with [using instance scale-in protection](https://docs.aws.amazon.com/autoscaling/ec2/userguide/ec2-auto-scaling-instance-protection.html), EngFlow was able to increase their reliability and improve efficiency.

### Cost efficiency

EngFlow customers run CI builds/tests at large scale, using hundreds or even thousands of EC2 instances concurrently at peak time. This workload makes a sweet spot to look for cost optimization opportunities on behalf of our customers.

To save up to 90% on compute costs compared to on-demand, in our Well-Architected review we discussed with EngFlow the ability to enable Spot Instances for their Remote Execution, based on [Amazon EC2 Spot Fleet](https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/spot-fleet.html).

> _"This feature is a huge opportunity for our customers and us to become more cost-efficient when running in AWS. We loved implementing it. By design, our Worker instances are stateless and handle spontaneous termination with a robust retry mechanism. AWS Spot Instances were a perfect fit, saving EngFlow and our customers 70% on compute costs on average."_ — Yannic Bonenberger, Engineer at EngFlow

While working on the Spot Instance integration, EngFlow also improved the overall EC2 instance resource utilization by improving our Worker instance scheduling algorithm, resulting in additional cost savings for our customers.

After EngFlow integrated Spot Instances, they listened to the [Spot Instance interruption notices](https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/spot-instance-termination-notices.html), which are issued two minutes before Amazon EC2 stops or terminates your Spot Instance. With this, they could avoid scheduling new build/test jobs on instances that will get reclaimed soon. Similar to this, the AWS Solution Architect also recommended listening to the [EC2 instance rebalance recommendations](https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/rebalance-recommendations.html) to avoid scheduling new build/test jobs on instances with a high likelihood of getting reclaimed soon as well. After implementing these recommendations, EngFlow customers observed fewer build/test job retries because of premature EC2 instance terminations.

## A promising approach to modern builds/tests

Large, nimble technology organizations such as social media platforms, short-term travel marketplaces, and auto manufacturers rely on EngFlow's platform to keep engineers in flow and maintain the necessary agility for modern software development. AWS is at the core of EngFlow's success, giving them flexible architecture and cost efficiency, which directly translates into competitive advantage for end customers.

> _"It's incredible how much power you get at your fingertips. This is the first time in history that you can get 1,000 machines as a single developer and try something out at scale."_ — Ulf Adams, CTO at EngFlow
