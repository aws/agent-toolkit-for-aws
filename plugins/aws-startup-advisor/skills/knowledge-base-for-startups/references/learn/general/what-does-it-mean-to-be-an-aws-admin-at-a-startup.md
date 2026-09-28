---
source_url: https://aws.amazon.com/startups/learn/what-does-it-mean-to-be-an-aws-admin-at-a-startup
title: "What does it mean to be an AWS Admin at a startup?"
---

## What does it mean to be an AWS Admin at a startup?

> _Guest Post by Faisal Farooq, Startup Solutions Architect and Abhi Singh, Sr. Security Solutions Architect_

Most startups work at a high velocities, which can mean that release timelines often overshadow the security foundation. A frequent byproduct of this fast-paced culture can mean that the responsibilities of an Account Admin are not as defined or the role is distributed among several team members. As the team size grows and the company gains momentum, a startup's customers often require the company to enforce least privilege and clearly define who and what an Admin should do, leaving founders to backtrack architecture-level decisions that were made early on, creating friction and disrupting the business. In this blog post, we will define what an Account Admin's responsibilities should look like, the training that person, referred to hereafter as an Admin, should have to be effective in their role, and the continuous impact they make on the company.

## Overview

An Account Admin is the second most powerful user in the company after the root account. As a result, it's important to define what that person or entity can do to assign appropriate privileges to the person. Some of the key responsibilities include:

- Providing effective utilization of AWS resources and services.
- Installing and maintaining your AWS environment by following best practices.
- Configuring and maintaining adequate security parameters.
- Implementing an information assurance policy, procedures, and reporting.

## Admin responsibilities

As mentioned above, the Admin is a trusted advisor for the development teams and founders. Some of the key tenets for a solid Account Admin are:

### Provide effective utilization of AWS resources and services

An Account Admin should be the internal trusted advisor and a subject matter expert on AWS. He or she needs to stay up-to-date on recent service announcements and help management realize the most efficient and effective usage of their AWS investment. Day-to-day activities for an Admin include:

- Consulting and advising development and product teams on architectural design patterns, and choosing appropriate services with appropriate features to meet business objectives, such as caches, buffering, and replicas.
- Building metrics and corresponding alarms using AWS Services, like [Amazon CloudWatch](https://aws.amazon.com/cloudwatch/) to monitor the resource usage and patterns.
- Leveraging data from Cost Usage Reports to recommend [cost optimization strategies](https://docs.aws.amazon.com/whitepapers/latest/aws-overview/aws-cost-management.html), such as [Amazon S3](https://aws.amazon.com/s3/) storage tiers, [Amazon EC2](https://aws.amazon.com/ec2/) instances, and [AWS Lambda](https://aws.amazon.com/lambda/) resources.
- Identifying the opportunities to use [AWS Managed Services and Solutions](https://aws.amazon.com/managed-services/).
- Developing deployment strategies to meet business objectives, including resource provisioning, application migration or deployment, and patch management.

### Install and maintain the AWS environment by following the AWS Well-Architected Framework

An AWS Admin strives to keep the startup's environment closely aligned to AWS best practices relative to the Services consumed and [Well-Architected Framework](https://aws.amazon.com/architecture/well-architected/?wa-lens-whitepapers.sort-by=item.additionalFields.sortDate&wa-lens-whitepapers.sort-order=desc), paying close attention to the following:

- Architect an automated, cost-effective back-up solution that supports business continuity across multiple AWS Regions.
- [Determine an architecture](https://aws.amazon.com/blogs/compute/building-well-architected-serverless-applications-managing-application-security-boundaries-part-1/) that provides application and infrastructure availability and recoverability in the event of a service disruption or failure.

### Configures and maintains adequate security parameters

Security is a top priority for the Account Admin. As a result, they are responsible for performing the following key activities to maintain the startup's environment to the required security standard:

- Establish user and resource baselines.
- Establish security boundaries between the organization's resources and partners, customers, and internet.
- Evaluate the organization's AWS environment for security and configuration vulnerabilities.
- Based on the organization's security and compliance requirement, deploy appropriate security controls for public facing web applications, enforcing least privileges across AWS accounts, users, and applications, managing credentials securely. Refer to the [Security Pillar](https://docs.aws.amazon.com/wellarchitected/latest/security-pillar/welcome.html) for reference.
- Deploy automated solutions to notify and correct the baseline deviations, including anomalous access to resources and defining data flow patterns.

The [AWS Security Pillar](https://docs.aws.amazon.com/wellarchitected/latest/security-pillar/welcome.html) provides detailed guidance on how to configure an Account. Consider testing your configuration using the Well-Architected labs in a sandbox environment for more hands-on training.

### Implements the information assurance policy, procedures, and reporting

External regulations and standards may apply to the startup, along with internal ones. The Admin is responsible for identifying appropriate mechanisms, such as [AWS Audit Manager](https://aws.amazon.com/audit-manager/), [AWS Config](https://aws.amazon.com/config/), or [AWS Security Hub](https://aws.amazon.com/security-hub/) to enforce the security and compliance reporting requirements such as NIST 800-83, HIPAA, FedRamp, PCI etc. to enable continuous compliance. They may also automate the compliance reporting to appropriate parties. AWS provides several services and solutions that can enable the Admin achieve the [compliance and assurance goals](https://aws.amazon.com/compliance/solutions-guide/). Based on the needs of the startup, the Admin can leverage these turn-key solutions and guides that align with AWS's guidance.

### Continuously improves the AWS environment for efficiency, effectiveness, security, and cost

Depending on the level of understanding of AWS and the startup's business, the Admin continuously reviews the existing environment and identifies improvement opportunities. They should review the performance metrics against the target and suggest improvements, identify the bottlenecks and recommend alternate strategies. They may also test the automated deployment and rollback strategies, and leverage and promote infrastructure as code and CI/CD pipeline-based deployment. The Admin will regularly review security related issues and develop automated mitigation mechanisms such as alternate architectures for repetitive items, and lastly, maintain Runbooks and Playbooks for common tasks highlighted above. The AWS Well-Architected Framework has an [Operational Excellence pillar](https://docs.aws.amazon.com/wellarchitected/latest/operational-excellence-pillar/welcome.html) that can help Admin's with continuous improvement.

## How can you innovate in your role as an AWS Admin?

AWS routinely provides guidance and architecture patterns, based on trends across the industry. This guidance along with the items listed below will help Admins invent and simplify on behalf of your customers:

- Review the AWS latest guidance via [re:Invent](https://reinvent.awsevents.com/), [whitepapers](https://aws.amazon.com/whitepapers/), and [Tech Talks](https://aws.amazon.com/events/online-tech-talks/) to identify new patterns.
- Automate day-to day-tasks using [AWS SDKs](https://aws.amazon.com/tools/), services like [SSM Documents](https://docs.aws.amazon.com/systems-manager/latest/userguide/sysman-ssm-docs.html), and [SSM Automation](https://docs.aws.amazon.com/systems-manager/latest/userguide/systems-manager-automation.html).
- Coach application teams on newly released services and design and architecture patterns.
- Reduce costs by working with your AWS Account teams on leveraging different mechanisms such as [Reserved Instances](https://aws.amazon.com/ec2/pricing/reserved-instances/), [Saving Plans](https://aws.amazon.com/savingsplans/), service-specific volume discounts like the [CloudFront security savings bundle](https://docs.aws.amazon.com/AmazonCloudFront/latest/DeveloperGuide/savings-bundle.html), and [Enterprise Discount Programs](https://aws.amazon.com/pricing/enterprise/).
- Automate a [Business Continuity and Disaster Recovery strategy](https://docs.aws.amazon.com/whitepapers/latest/disaster-recovery-workloads-on-aws/disaster-recovery-workloads-on-aws.pdf).
- Develop automation for site reliability against defined targets.
- Conduct periodic Well-Architected Reviews on your workloads.

## Conclusion

Startup management often grapple with defining and outlining an AWS Admin's responsibilities. With these resources, founders and stakeholders can hire and develop the best, while maintaining an appropriate level of separation of duties that often plague a startup's growth and scalability. By following the practices defined above, AWS Admins can balance performing day-to-day activities effectively, help their startups adopt good security hygiene practices often required as part of third-party assurance, and optimize infrastructure costs.

---

## Authors

### AWS Editorial Team

The AWS Startups Content Marketing Team collaborates with startups of all sizes and across all sectors to deliver exceptional content that educates, entertains, and inspires.

### Faisal Farooq

Faisal Farooq is Solutions Architect at AWS on the Startups team. He routinely hosts customer open forums to help Startups to discuss the industry wide challenges. In his prior role, he worked with Fortune 100 companies as a cybersecurity consultant. He is passionate about helping startups use AWS more efficiently and securely.

### Abhi Singh

Abhi Singh is a Senior Solution Architect who specializes in security and compliance within AWS. He has over 20 years of experience in information technology consulting and leadership experience.

---

_Source: [AWS Startups](https://startups.aws/startups/learn/what-does-it-mean-to-be-an-aws-admin-at-a-startup)_
