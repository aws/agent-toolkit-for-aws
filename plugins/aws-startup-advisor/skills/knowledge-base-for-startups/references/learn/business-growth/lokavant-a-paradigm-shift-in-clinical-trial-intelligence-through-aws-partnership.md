---
source_url: https://aws.amazon.com/startups/learn/lokavant-a-paradigm-shift-in-clinical-trial-intelligence-through-aws-partnership
title: "Lokavant creates a paradigm shift in clinical trial intelligence with AWS"
---

## Lokavant creates a paradigm shift in clinical trial intelligence with AWS

_Guest post by Brian Monroe, Lokavant Senior Director IT and DevOps, and Rohit Nambisan, Lokavant CEO._

One in six clinical trials of investigational drugs fail regulatory review by agencies such as the Federal Drug Administration (FDA) and the European Medicines Agency (EMA) due to issues stemming from the way data are managed and interpreted — problems that have nothing to do with the safety or efficacy of a drug candidate. Drugs that fail in regulatory review are marred by delayed timelines and budget overruns; indeed, the average cost to develop an approved drug has [more than doubled to $2.6 billion over the last ten years](https://www.scientificamerican.com/article/cost-to-develop-new-pharmaceutical-drug-now-exceeds-2-5b/). The consequences of these operational failures can cost tens of millions of dollars for sponsors of clinical trials and their Contract Research Organizations (CROs) in direct cost and much more in opportunity cost from lost sales due to late market entry. Those who suffer most, however, are the patients, who have access to fewer treatment options and are burdened by higher drug prices.

[Lokavant](https://www.lokavant.com/) is a Clinical Trial Intelligence company with the mission to decrease the time and cost of developing drugs. Lokavant was spun out of [Roivant Sciences](https://roivant.com/), a NASDAQ-listed biopharmaceutical company with tens of drugs in development. The team at Lokavant noticed that companies like Roivant – despite investing hundreds of millions into their R&D pipelines – struggle with operational risk in their trials. The best way to mitigate operational risk in clinical trials is to enable clinical teams to be proactive and predictive rather than reactive. That's where Lokavant and its products – Oversight and Insight – come in. Both products collect, correlate and deliver data insights on clinical trials. Oversight is Lokavant's risk-based quality management application, alerting study teams and executives of emerging risks at the study-, country-, site- and patient-level. Insight enables sponsor and CRO customers of Lokavant to benchmark the performance of their trials against Lokavant's proprietary repository with data from >2,000 past trials. Lokavant's products are easy to use for study teams, deliver machine learning models to generate forward looking insights, and are reliable, secure, and scalable. Lokavant deploys its products on top of its Clinical Intelligence platform, a foundational technology layer that ingests and harmonizes data in a source agnostic and real-time manner to surface actionable insights earlier than ever before.

When we first began developing our products and platform there was a need to find a partner that helped provide the best environment to start building and deploying without bogging down the business with unnecessary costs and effort. Lokavant quickly realized that AWS could help provide the solutions that we urgently needed. Working with AWS has helped Lokavant cut the time spent on infrastructure-related work and provided the time and resources to let the technical teams focus on building Lokavant's growing suite products. It also has allowed Lokavant to allocate spend where most appropriate to the company's current maturity. AWS provided the solutions that Lokavant needed to be stable, to scale at the right pace for the company, and to deliver solutions much faster.

Our microservices architecture sits on top of Amazon Elastic Container Service (Amazon ECS), with Snowflake supporting our backend data marts and analytics stores. Amazon ECS, with autoscaling capabilities, allows us to easily deploy containerized business logic and micro-service interfaces exposed through Elastic Load Balancers (ELB) that scale up and down as needed. AWS Fargate descopes our effort, allowing us to focus on container-based solutions without having to worry about our own infrastructure and operating system complexity.

To complement our core backend services running on Amazon ECS and ELB, we distribute our customer-facing applications on Amazon CloudFront and expose composite services on Amazon API Gateways, where we leverage AWS Lambda to quickly deploy business logic that integrates with multiple back-end AWS services. The ability to deploy these user interfaces in multiple regions around the world via Cloudfront provides faster access to our international customers. Lokavant also uses Amazon Cognito to authenticate our application and APIs, and this allows us to seamlessly integrate with our customers who leverage SAML2 and OIDC Single-Sign On federation, which is a core requirement of many sponsors and CROs.

![Application runtime architecture diagram](https://d22k7geae6sy8h.cloudfront.net/files/64aa1222cb86a5000861911a/8ljus0s7z-Lokavant-a-paradigm-shift-in-clinical-trial-intelligence1.jpg)

_Fig. 1: A high level representation of the application runtime architecture. The application single page React front-end is delivered through Cloudfront and all business logic is maintained in the microservice layer which is deployed either in AWS ECS Fargate or AWS Lambda. Microservice endpoint management is done either through an Elastic Load Balancer or via API Gateway. API end points are secured using oauth integration with AWS Cognito. Application auto-scaling is managed using auto-scaling policies defined in AWS Cloudwatch tied to CPU usage metrics._

On the backend, Lokavant is delivering novel and innovative analytics, not only in static point-in-time insights, but also with predictive analytics. These analytics leverage our ability to mine and correlate data and outcomes from historical clinical studies to build and train models that deliver leading indicators of study risk. Currently, we deliver our model engines in separate containers that provide preparation, ETL and data mart creation, and then deploy models built in a wide variety of Python-based packages that train and execute in parallel. Lokavant drives all data ingestion and data lake management via AWS Managed Apache Airflow, which directly interfaces with Amazon Simple Storage Service (Amazon S3) and Snowflake to prepare and synchronize multiple dependent workflows requiring a high degree of correlation.

With the use of containerized model engines, Lokavant is configuring robust atomic building blocks to work in distributed ECS Fargate, executed through Managed Apache Airflow. These containerized engines also allow us to leverage new capabilities with bring-your-own container integration via notebook-driven interfaces on Amazon SageMaker. These additional tools will help Lokavant run investigative data science in combination with existing model outputs to identify new trends and data patterns that will ultimately enhance our products and improve trial operations for our customers.

![Data and analytics workflows architecture diagram](https://d22k7geae6sy8h.cloudfront.net/files/64aa124dcb86a5000861911b/8ljus1pt8-Lokavant-a-paradigm-shift-in-clinical-trial-intelligence2-1024x644.jpg)

_Fig. 2: A high-level representation of the architecture supporting data and analytics workflows. Customers deliver data through secure S3 interfaces. Managed Workflows for Apache Airflow is leveraged to create multi-step orchestrations to detect, organize, and load data. The respective DAGS where the workflow orchestration resides is delivered to MWAA through AWS CodePipeline and managed in Github. More complex business logic including data ingestion ETL and data mart ETL, as well as model training occurs in containers that run in AWS ECS Fargate. These containers are also built and deployed through AWS CodePipeline._

In addition to deployment and execution environments, Lokavant has invested heavily in Continuous Integration and Continuous Deployment (CICD). We are constantly improving our stakeholder productivity, and we are creating automated delivery channels for our application development, data engineering and data science groups. Lokavant makes use of the AWS CodePipeline and AWS CodeBuild to integrate our GitHub repos and automate deployment to our auto-scaled ECS and Lambda infrastructure. All our pipeline configurations are driven from AWS Systems Manager parameter stores, and our ability to spin up a completely new vertical stack is measured in hours, not days or weeks. Our build pipelines work interactively through AWS Chatbot and Slack to keep our developers apprised on the status of builds and deploys, as well as any required approvals or gated interactions for our higher-level environments.

## Conclusion

Operational risk ultimately stems from the way data are managed and interpreted in clinical trials. In the past decade, there has been a proliferation in the data that are being generated by clinical trials as well as the e-clinical systems that are being used to collect these data. One would expect that more data are always better, but fragmentation of data across e-clinical systems are pervasive and such legacy solutions have certainly not been designed for the growing influx of data from disruptive innovations like decentralized clinical trials.

Lokavant and its products have helped small and large sponsors and CROs turn this data challenge into a data advantage. In one study, Lokavant improved the quality of the study by saving >12 patients from loss to follow-up, a significant risk for the study that would have cost >$1M. In a separate study, Lokavant prevented a 6-month delay by unearthing site non-compliance issues months before traditional methods for site management would have. Through its continued investment in data science and analytics, Lokavant has also built machine learning models that improve the accuracy of enrollment forecasts by up to 70x – a common source of mistakes during the planning phase of a new trial.

As we continue to scale across thousands of news trials and build new products in clinical intelligence, we will continue to leverage AWS as a core partner in our mission to cut the time and cost of clinical development.

## Related Content

- [How Citus Health Uses AWS to Provide Secure and Real-Time Virtual Patient Care](https://aws.amazon.com/blogs/startups/how-citus-health-uses-aws-to-provide-secure-and-real-time-virtual-patient-care/)
- [How Emerald Cloud Lab Is Revolutionizing the Laboratory Using AWS](https://aws.amazon.com/blogs/startups/how-emerald-cloud-lab-is-revolutionizing-the-laboratory-using-aws/)
- [AWS Healthcare Accelerator in the UK Announces 12 Startups Selected for the Inaugural Programme](https://aws.amazon.com/blogs/startups/aws-uk-healthcare-accelerator-announces-12-startups-selected-for-the-inaugural-program/)

---

## Authors

### AWS Editorial Team

The AWS Startups Content Marketing Team collaborates with startups of all sizes and across all sectors to deliver exceptional content that educates, entertains, and inspires.

### Rohit Nambisan

Rohit Nambisan is a product leader with management experience across multiple healthcare technology domains, including Big Pharma, medical devices, personalized medicine, Health IT, health data and analytics, and AI. Prior to leading Lokavant, Rohit was most recently the Head of Digital Product at Roivant and the Head of Product at Prognos.

### Brian Monroe

Brian Monroe has been designing, building, securing, and supporting DevOps and IT infrastructure for over 20 years in multiple industries including B2B SAAS, Financial Services, Retail Pharmacy and now at Lokavant. Brian has a very deep and diverse background in multiple technology domains supporting all facets of the application eco-system.
