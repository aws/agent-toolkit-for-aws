---
source_url: https://aws.amazon.com/startups/learn/four-simple-steps-to-classify-your-data-and-secure-your-startup
title: "Four Simple Steps to Classify Your Data and Secure Your Startup"
---

## Four Simple Steps to Classify Your Data and Secure Your Startup

A data classification process allows you to distinguish between confidential data and data intended for public consumption, and lets you handle each set accordingly. A startup that has categorized its data can operate more efficiently and more confidently navigate compliance with laws such as the European Union's General Data Protection Regulation (GDPR) and the California Consumer Protection Act (CCPA).

Understanding your data types and their sensitivity levels ensures that your startup stays ahead of unintended data use or disclosures and satisfies compliance requirements.

To get you started, this post provides four simple steps to simplify and automate the data classification process for your startup.

## 1. Design Your Data Classification Framework

First, you'll establish who is allowed access to your startup's data by assessing how to classify and control your data.

### Assess and Classify Your Data

Data classification "involves identifying the types of data that are being processed and stored in an information system owned or operated by an organization," as defined by the [Data Classification](https://docs.aws.amazon.com/whitepapers/latest/data-classification/data-classification-overview.html) Amazon Web Services (AWS) whitepaper.

To design your data classification framework, you'll assess your data first. To do this, we recommend grouping data into as few categories as practical, because a simpler framework is easier to manage.

For most companies, these three tiers should cover the most common data classification use cases:

- **Unclassified** – For low-security data (such as public website data, course catalog, etc.)
- **Official** – For moderate-security data (such as official communication, internal memos, etc.)
- **Secret** – For the most sensitive data (such as financial records, intellectual property, legally privileged data, etc.)

How you classify your data and where your store it will be informed by the nature of your business and its legal requirements. For instance, if you process credit cards, you must comply with [payment card industry (PCI) standards](https://www.pcisecuritystandards.org/), which are classified as Secret.

Need some help classifying data? [Amazon Macie](http://aws.amazon.com/macie/) uses machine learning (ML) to automate the classification of sensitive and business-critical data. It uses machine learning (ML) and pattern matching to [detect sensitive information](https://docs.aws.amazon.com/macie/latest/user/data-classification.html) like credit card numbers, health data, and other kinds of personally identifiable information (PII).

### Determine Data Protection Controls

Data protection _controls manage how your data is used_, who has access to it, and how it is encrypted.

After you assign your datasets to the classification tiers, you'll determine what controls apply to each category. By carefully managing an appropriate data classification system, along with each workload's level of protection requirements, you can map the controls and level of access or protection appropriate for the data.

There are many types of data protection controls, but some common ones you need to know are:

- Using separate accounts to place workload resources per sensitivity level. [AWS Organizations](https://aws.amazon.com/organizations/) allows you to create and manage [multiple AWS accounts](https://docs.aws.amazon.com/accounts/latest/reference/welcome-multiple-accounts.html) with ease.
- Setting up IAM policies, Organizations service control policies (SCPs), [AWS Key Management Service (AWS KMS)](https://aws.amazon.com/kms/), and [AWS CloudHSM](https://aws.amazon.com/cloudhsm/), allows you to define and implement your policies for data classification and protection with encryption.
- Ensuring that your data is stored and processed in the appropriate AWS Region based on your compliance and data residency requirements. AWS never initiates the movement of data between Regions. Content placed in a Region will remain in that Region unless you explicitly enable a feature or use a service that provides that functionality.
- Using [AWS Config rules](https://docs.aws.amazon.com/config/latest/developerguide/managed-rules-by-aws-config.html) to check automatically that you are using encryption for data at rest, for example, for [Amazon Elastic Block Store (Amazon EBS) volumes](https://docs.aws.amazon.com/config/latest/developerguide/encrypted-volumes.html), [Amazon Relational Database Service (Amazon RDS) instances](https://docs.aws.amazon.com/config/latest/developerguide/rds-storage-encrypted.html), and [Amazon Simple Storage Service (Amazon S3) buckets](https://docs.aws.amazon.com/config/latest/developerguide/s3-default-encryption-kms.html).
- Enforcing encryption in transit. For instance, HTTP requests can also be [automatically redirected to HTTPS](https://docs.aws.amazon.com/AmazonCloudFront/latest/DeveloperGuide/using-https-viewers-to-cloudfront.html) in [Amazon CloudFront](https://aws.amazon.com/cloudfront/) or on an [Application Load Balancer](https://docs.aws.amazon.com/elasticloadbalancing/latest/application/load-balancer-listeners.html#redirect-actions).

Unclassified data, for instance, might be available to anyone in your organization or even externally, while Secret data might require authorized access to a key in order to decrypt.

## 2. Tag Your Data

For security purposes, [metadata tags](https://docs.aws.amazon.com/general/latest/gr/aws_tagging.html#tag-categories) can help you identify, categorize, and manage resources in different ways, such as by purpose, owner, environment, or other criteria. You can use security tags to identify and group your resources based on confidentiality and compliance requirements.

Now that you know how you'll classify and protect your data, you'll add metadata tags that designate its classification level. These tags provide a reference for your team and enable additional automation and controls. There are many [common tagging strategies](https://docs.aws.amazon.com/general/latest/gr/aws_tagging.html#tag-strategies), but the tags you might want to use for security include:

- **Confidentiality** – An identifier for the specific data confidentiality level a resource supports
- **Compliance** – An identifier for workloads that must adhere to specific compliance requirements

You can use tags to require encryption, for example, or restrict who can access data. If you do not already have tags for your existing resources, AWS offers tools to help manage resource tags across multiple services:

- [AWS Resource Groups](https://docs.aws.amazon.com/ARG/latest/userguide/) and the [Resource Groups Tagging API](https://docs.aws.amazon.com/resourcegroupstagging/latest/APIReference/) enable programmatic control of tags, making it easier to manage, search, and filter tags and resources.
- [AWS Identity and Access Management (IAM)](https://aws.amazon.com/iam/) allows you to [control access to resources using tags](https://docs.aws.amazon.com/IAM/latest/UserGuide/access_tags.html).

_Remember: It's fairly easy to change tags to accommodate changing business requirements, but consider the consequences of future changes. For example, changing access control tags means you must also update the policies that reference those tags and control access to your resources._

## 3. Redact Sensitive Data

Data redaction limits the places where sensitive data is stored and restricts access to those that need it, without hindering downstream environments.

Automating redaction limits the danger of inadvertent data releases and helps startups comply with privacy requirements as they navigate a growing volume of data.

[Amazon Comprehend](https://aws.amazon.com/comprehend/), in conjunction with [Amazon S3 Object Lambda](https://aws.amazon.com/s3/features/object-lambda/) access points, can detect more than a dozen types of PII, including passwords, addresses, phone numbers, and Social Security numbers and [automatically make redactions](https://aws.amazon.com/blogs/machine-learning/detecting-and-redacting-pii-using-amazon-comprehend/) in text documents.

## 4. Keep Up with Compliance

Data compliance identifies rules for data protection, security, and storage. It establishes policies, procedures, and protocols and ensures data is protected from unauthorized access and use.

In our final step, you'll monitor your data to ensure it maintains compliance. [AWS Config](https://docs.aws.amazon.com/config/latest/developerguide/evaluate-config.html) Rules and [AWS Foundational Security Best Practices](https://docs.aws.amazon.com/securityhub/latest/userguide/securityhub-standards-fsbp-controls.html) in [AWS Security Hub](https://aws.amazon.com/security-hub/) help you keep track of how your data settings are configured and notify you if they're changed. They enable you to continuously ensure your security standards are being met.

## Securing Your Startup with AWS

Almost every startup now operates in a global environment, and increasingly, they face differing requirements in each country in which they do business.

By identifying the data you have and implementing appropriate, automated controls, you can meet these requirements more easily, while also improving your security posture. For further reading, we recommend the [AWS Data Classification Whitepaper](https://docs.aws.amazon.com/whitepapers/latest/data-classification/data-classification.html). We also recommend reviewing the [AWS Well-Architected Framework](http://aws.amazon.com/architecture/well-architected/), which helps you understand the pros and cons of the decisions you make when building systems in the cloud and describes how to take advantage of cloud technologies to protect data, systems, and assets in a way that can improve your security posture.

---

**Author:** Neil DCruz

Neil DCruz is a startup solutions architect based in Mumbai, India. He helps startups on their AWS journey to build reliable, scalable, and cost-effective cloud architectures. He has over a decade of experience working in various consulting and development roles building enterprise applications, microservices, and data analytics and business intelligence workloads.
