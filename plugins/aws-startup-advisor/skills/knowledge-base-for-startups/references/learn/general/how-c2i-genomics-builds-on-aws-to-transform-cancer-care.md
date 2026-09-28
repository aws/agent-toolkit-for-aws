---
source_url: https://aws.amazon.com/startups/learn/how-c2i-genomics-builds-on-aws-to-transform-cancer-care
title: "How C2i Genomics builds on AWS to transform cancer care"
---

## How C2i Genomics builds on AWS to transform cancer care

_Source: [AWS Startups](https://aws.amazon.com/startups/learn/how-c2i-genomics-builds-on-aws-to-transform-cancer-care)_

---

Healthcare and life sciences (HCLS) startups recognize that technology is an impactful vehicle for advancing human health at speed and scale. More importantly, HCLS startups are working to do something about it. [C2i Genomics](https://c2i-genomics.com/), founded in 2019, is one such startup: C2i Genomics is building a whole genome intelligence platform to improve cancer monitoring.

Using [artificial intelligence (AI) and machine learning (ML)](/startups/machine-learning/) solutions, C2i Genomics' platform analyzes sequenced genome data to detect the tumor burden of cancer patients via a simple blood test. Its cancer surveillance system can track tumors on the genomic level, giving extensive insight into a patient's cancer treatment journey. The platform can eliminate the reliance on imaging technology while improving the accuracy of cancer screenings and treatment recommendations.

The biggest benefit of this approach is that it allows for "high-precision personalized medicine," says Boris Oklander, co-founder and chief technology officer (CTO) of C2i Genomics. "The treatment the patient gets is not just arbitrary protocol, but tailored for their specific case."

## Overcoming challenges using AWS

As they built their whole genome-based intelligence platform, the team at C2i Genomics quickly discovered a significant technological challenge: large data volume. Each blood sample collected from a patient translates into files that's roughly 100 gigabytes. Patients may have several samples taken throughout the course of their cancer diagnosis and treatment. As their company scaled, data volumes expanded rapidly, and C2i Genomics—despite being a young company—began working with multiple petabytes of data. Making that much data available for processing and analysis is a formidable task for any company.

Beyond that, C2i Genomics faced a complicated legal landscape. Genomic data is sensitive material, subject to privacy laws worldwide, but the specific regulations governing its use can vary from country to country.

By working with Amazon Web Services (AWS), C2i Genomics found assistance with both of these complicating factors. It's a collaboration that enabled C2i Genomics to manage potential issues efficiently and cost effectively, and it put the company on track to impact healthcare worldwide.

> _Boris says that building on AWS was "really a key factor in our success."_

## Activating success

To help jumpstart their business, AWS provided C2i Genomics with credits through the AWS Activate program. Boris notes that these credits were an essential resource during the company's early stages. C2i Genomics put its credits toward data storage and computation solutions—crucial components of its genome intelligence platform that would otherwise prove costly for an early-stage startup.

AWS also introduced C2i Genomics to the [BeyondBio SCALE](https://www.beyondbio.co.il/home) startup accelerator program, a program with AstraZeneca and several other organizations. As a participant in BeyondBio SCALE, C2i Genomics received expert guidance from leaders in the healthcare and life sciences sector. The team gained critical insight into the process of scaling up development and deployment of cloud-based medical services, data privacy and compliance, and how to avoid common mistakes that can trouble emerging companies in the field.

After C2i Genomics' platform went through the due diligence process, AstraZeneca selected the platform to be used in their own labs, cementing a relationship that AWS helped facilitate.

## Optimizing costs and solutions

Creating a pioneering diagnostic solution can be an expensive undertaking, even with the early credits assistance. "The costs associated with processing these volumes of genomic data are huge," says Boris. "And in the current economic environment, we have become much more sensitive to the costs."

To better manage their expenses, C2i Genomics worked closely with the solutions architect at AWS to identify and explore three key areas of cloud optimization.

### Automatically optimizing storage costs

The first area of optimization involved using Amazon S3 Intelligent-Tiering, which monitors data for changes in access patterns and automatically moves data to the most cost-effective access tier. This can produce significant savings for companies such as C2i Genomics, who have variable data access patterns.

### Choosing the AWS solutions to meet their use cases

Next, C2i Genomics and AWS worked together to find the most efficient AWS solutions for their use cases. To allow C2i Genomics' researchers to launch experiments and evaluate algorithms results quicker, they implemented [Amazon Managed Workflows for Apache Airflow (Amazon MWAA)](https://aws.amazon.com/managed-workflows-for-apache-airflow/). C2i Genomics also chose to use [Amazon FSx for Lustre](https://aws.amazon.com/fsx/lustre/) for more efficient storage.

During the course of maximizing efficiencies, the team recognized an opportunity to optimize costs by transferring some on-demand instances of [Amazon Elastic Compute Cloud (Amazon EC2)](https://aws.amazon.com/ec2/) to [spot instances](https://aws.amazon.com/ec2/spot/)—in some cases, crafting solutions tailored to C2i Genomics' unique data needs.

### Securing genomic data on the cloud

The third major optimization challenge involved with uploading personalized genomic data to cloud storage—a centerpiece of C2i Genomics' platform. C2i Genomics needed to assure their customers that they handle their data responsibly while navigating a complex global regulatory environment. "We needed to work both on the technological side but also on legal to make this happen," says Boris. "The help of the AWS team was really crucial here."

By adopting [Amazon GuardDuty](https://aws.amazon.com/guardduty/), [AWS Config](https://aws.amazon.com/config/), [AWS Systems Manager](https://aws.amazon.com/systems-manager/), and third-party solutions, C2i Genomics succeeded in building a regulated environment in which to host their genomics platform. The alternative would have required deploying their platform on-premises for each customer rather than via the cloud—a costly, non-scalable option. By collaborating with the AWS team, C2i Genomics was able to turn its vision of a global diagnostic ecosystem into a reality.

## Using Amazon Omics

A recent product launch meant that AWS was uniquely positioned to assist C2i Genomics in their endeavor: In 2022, AWS launched [Amazon Omics](https://aws.amazon.com/omics/), a service designed specifically for [companies](https://aws.amazon.com/omics/customers/) in the healthcare and life sciences space. Omics provides a venue for storing, querying, and analyzing biological data, including genomics. By bringing all of this data onto one accessible platform, Omics fosters collaboration among teams and expedites scientific innovation.

By including Omics in their tech stack, C2i Genomics is able to rely on AWS for its genomic data storage and processing infrastructure. Omics is developed to specifically handle the kinds of workloads required to generate insights from huge volumes of genomic data, relieving C2i Genomics of a significant amount of engineering stress. C2i uses Omics as an on-demand service—it's available immediately as needed, but the startup's engineers don't have to worry about maintaining this expansive layer of infrastructure on their own.

In addition, Omics is General Data Protection Regulation (GDPR) compliant and Health Insurance Portability and Accountability Act (HIPAA) eligible, which allows C2i Genomics to focus on tackling problems in cancer diagnosis and treatment, rather than on regulatory frameworks.

## Proving what's possible with AWS

The impact of C2i Genomics' platform has the potential to ripple across the global healthcare industry, transforming what it means for someone to receive a cancer diagnosis. It can lead to more personalized treatments and better health outcomes. By monitoring a patient's progress throughout treatment, a healthcare team can make informed decisions about whether to continue an aggressive form of therapy, switch to another, or discontinue treatments that may no longer be necessary.

> _"We've the help of AWS, we have achieved a point where we not only have a medical device, but it's clinical grade," Boris says. "It's not only for research; it's actually ready for providing results in short turnaround times for real patients."_

Similarly, C2i Genomics' platform offers the ability to detect whether a form of treatment has successfully eliminated a cancer. This can help prevent the need for surgeries that remove organs, which are sometimes performed preventatively due to a lack of available information about how far a cancer has spread.

C2i Genomics' ambition is nothing less than making this kind of personalized medicine available to all patients across the globe. It aims to scale its platform so that any lab with the right equipment can take advantage of these innovations in cancer care, getting diagnostic screening results in record time. The company knows that doing this will require designing its service and implementation in close collaboration with AWS, a prospect Boris looks forward to.

> _"On the AWS side, they understand that we are on a mission to transform cancer treatment," says Boris. "It's a unique position where C2i Genomics can utilize AWS' advanced cloud-based technology to save lives."_

Ready to begin your startup journey? Join [AWS Activate](https://aws.amazon.com/activate/) to build and scale your startup with the right resources at the right time.

---

## Related Resources

Learn more about how startups are using AI/ML solutions on AWS:

- [How machine learning helps Fraud.net to build a modern app on AWS to combat financial fraud](https://aws.amazon.com/blogs/startups/how-machine-learning-helps-fraud-net-to-build-a-modern-app-on-aws-to-combat-financial-fraud/)
- [How startups lower AI/ML costs and innovate with AWS Inferentia](https://aws.amazon.com/blogs/startups/how-startups-lower-ai-ml-costs-and-innovate-with-aws-inferentia)
- [How Amazon SageMaker helps Widebot provide Arabic sentiment analysis](https://aws.amazon.com/blogs/startups/how-amazon-sagemaker-helps-widebot-provide-arabic-sentiment-analysis/)

---

## About the Authors

### Megan Crowley

Megan Crowley is a Senior Technical Writer on the Startup Content Team at AWS. With an earlier career as a high school English teacher, she is driven by a relentless enthusiasm for contributing to content that is equal parts educational and inspirational. Sharing startups' stories with the world is the most rewarding part of her role at AWS. In her spare time, Megan can be found woodworking, in the garden, and at antique markets.

### Boris Oklander

Boris Oklander, co-founder and CTO of C2i Genomics, has driven the company's technological evolution and successfully secured over $100m in funding. With a career exceeding 20 years, his experience includes CTO roles in defense and AI-based diagnostics, along with developing mission-critical systems as an R&D Officer in the IDF. Oklander earned his Ph.D. in Electrical Engineering from the Technion and undertook a post-doctoral research position in cognitive systems at Imperial College London. His professional achievements are reflected in various patents and publications.

---

_AWS Activate updates program benefits regularly, and credit offerings and/or the offerings reflected in this blog post may differ from current Activate offers. For the most up to date information about Activate benefits, please visit [https://aws.amazon.com/activate/](https://aws.amazon.com/activate/)_
