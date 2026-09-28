---
source_url: https://aws.amazon.com/startups/learn/next-generation-data-management-for-clinical-trials-research-built-on-aws
title: "Next generation data management for clinical trials & research built on AWS"
---

## Next generation data management for clinical trials & research built on AWS

> _Guest post by Steve Bilawey, Co-Founder & Chief Business Officer, Precision Digital Health_

## Data and Automation in Drug Development

The life sciences industry is absorbing a deluge of Real World Data (RWD). For the players who embrace technology and automation, this can revolutionize the clinical trials process, reducing time to market for life-changing treatments. Sponsors who can adapt their data management capabilities will see increased efficiencies across all phases of the clinical trial process, reducing drug development timelines, and generating more holistic patient views for better insights.

Cumbersome, disparate data sources in highly regulated environments have historically obstructed longitudinal patient views in clinical research. To help clients generate maximum evidence from trials, Precision Digital Health (PDH) developed a cloud-based platform capable of integrating and harmonizing disparate data assets in the R&D and life sciences industry. SUMMA is a fully compliant, next generation Platform-as-a-Service (PaaS) that enables data management for all aspects of the trials process, with self-service analytics and visualization tools to support next generation research needs. Built for rapid adoption and custom configuration, PDH's technology innovations accelerate clinical evidence, resulting in faster patient access to better care.

## Regulatory Compliant Data Management on SUMMA

SUMMA was designed and developed with patient and data security as its foundation to meet today's regulatory and compliance requirements globally. It was purpose built with protections in place to separate between de-identified data and Protected Health Information (PHI). PDH has deep experience building validated solutions with sensitive clinical data in compliance with a stringent, global network of regulators (FDA, GDPR, HIPAA, GxP).

To provide an automated longitudinal visualization of a patient's natural history, requires linking patient data across systems. To do so, PDH employs an FDA and HIPAA compliant, secure tokenization process. Tokenization impacts the entire clinical workflow from feasibility through the duration of the trial and prospectively.

![Visualization of a patient's natural history](https://d22k7geae6sy8h.cloudfront.net/files/64b007cd02decd00087f17e9/8lk18k2uh-PDH-diagram-1.png)

![End-to-end clinical trials workflow](https://d22k7geae6sy8h.cloudfront.net/files/64b007f902decd00087f17ea/8lk18l0so-PDH-Diagram-2.png)

## Interoperability and AWS Integrations

A key aspect of SUMMA is its ability to integrate various AWS services, mobile devices, and industry clinical data feeds to enrich various analytics, facilitate insights, and generate evidence from trials. The SUMMA platform aggregates data from disparate sources and then standardizes it into a common data model (CDISC, OMOP) for harmonization and curation (eg. auto-cataloging, auto-fill, elastic search). This approach provides rapid, automated, real-time solutions across the organization and every aspect of the trials process, thereby reducing resources and time to value for clients. Data asset integrations include: Electronic Health Records (EHR); current and historical clinical trials data (EDC); pharmacy & medical claims data; diagnostic & specialty data (e.g. genomics); mobile eCOA/ePRO solutions; medical devices & wearables data.

PDH's mobile solution facilitates a secure connection between clinicians and patients, regardless of geography. This expands research opportunities while improving data quality and patient experience. The direct-to-patient model flows into SUMMA as a single hub for all data including novel RWD endpoints such as sensor data, eCOA/ePRO and other patient centric metrics (e.g. food diaries).

Architecturally, SUMMA microservice framework provides an event driven data processing engine. SUMMA acts as an application layer that interoperates directly with key AWS components to provide highly customizable metadata driven microservices for various types of analytical and trial management workflows. These configurable data processing pipelines leverage a series of PDH custom connectors supporting key dataflows and AWS-based ingestion services. To adapt to any client size, SUMMA leverages containerized deployment using Kubernetes and Docker. This automated process using Terraform and Ansible allows us to deploy many different types of infrastructure configurations required to support various client needs. With this automation, clients can adjust the compute power they require in real-time without any downtime.

![Summa Real-World Evidence Platform](https://d22k7geae6sy8h.cloudfront.net/files/64b0082a02decd00087f17eb/8lk18m380-PDH-diagram-3.jpg)

As visually represented above, the SUMMA platform is an industry specific layer within the tech stack that provides full life cycle data management for clinical data. SUMMA is built on underlying AWS Technology and easily integrates with a variety of AWS tools to enable self-service analytics for end-users:

- [Amazon Comprehend](http://aws.amazon.com/comprehend) – apply NLP to unstructured data sources
- [Amazon SageMaker](http://aws.amazon.com/sagemaker) & Deep Learning – Machine Learning (ML)
- [Amazon QuickSight](http://aws.amazon.com/quicksight) – generate advanced reporting with visualizations and dashboards for multiple devices

## PDH Powered by AWS

PDH's SUMMA platform enables compliant evidence generation powered by AWS technology, with a configurable nature that keeps innovation at pace with the rapidly evolving healthcare and life sciences landscape. SUMMA is a repeatable, easily deployable PaaS that provides automated solutions for pharma and the broader healthcare industry. The microservices that underpin the platform enable rapid adoption and improvement of novel data sources and clinical workflows. SUMMA can work within existing client infrastructure or quickly bring new data lakes/capabilities to clients. SUMMA's innovative technology automates, integrates and extends to new research capabilities. The built-in machine learning and AI capabilities turn real-world data into actionable insights.

## Impact of Machine Learning & Advanced Analytics

SUMMA's powerful and precise data capabilities allow for the use of advanced ML/AI techniques. To establish new patterns and insights for clinical discovery, SUMMA's automation and linking capability enables broader impact across large volumes of data, in less time. SUMMA operationalizes ML/AI by automating and transforming the ML/AI into standard data flows that generate actionable predictive outputs for business users.

### Case Study: Machine Learning for Treatment and Prevention in Osteoarthritis

Using ML, PDH developed a model to identify predictive risk factors leading to early osteoarthritis diagnosis, accurate treatment, and prevention of knee replacement. The SUMMA platform prepared and transformed data to generate key clinical risk factors that would rapidly assess and risk stratify patients. The application of this model aided in early diagnosis and demonstrated a 90% accuracy rate in predicting osteoarthritis one year in advance. Additionally, SUMMA was able to automate the clinical workflow for targeting the patients accurately.

This discovery positively impacts multiple stakeholders through more efficient patient identification and treatment leading to decreased resource burden:

- Patient – physical benefits/quality of life, reduced spend and healthcare burden
- Health systems – early detection savings estimated at 25%
- Sponsor – improved patient targeting increases revenue 15-20%

## About Precision Digital Health

PDH is a Platform-as-a-Service (PaaS) business, founded in 2015 to provide software development and solutions for clinical research and trials to clients in the Life Science/Healthcare industry. Core customers are Contract Research Organizations (CRO) and Pharmaceutical, Biotech and Research Organizations. PDH utilizes cloud-based open architecture ("interoperability") with the most advanced technology and distributed computing to power SUMMA, a regulatory compliant, end-to-end data and analytics platform. Summa specializes in the use of Real World Data (RWD) to generate Real World Evidence (RWE) in support of clinical research, drug development, and improved health-related outcomes. Our platform is purpose-built with configurable data pipelines to preserve compliance across geographies and sectors. PDH services are available globally today, with support in over 30 countries.

To learn more about how PDH can power your clinical research, visit [https://precisiondigitalhealth.com/](https://precisiondigitalhealth.com/) or send us a message at info@precisiondigitalhealth.com

---

> _Author: AWS Editorial Team_

The AWS Startups Content Marketing Team collaborates with startups of all sizes and across all sectors to deliver exceptional content that educates, entertains, and inspires.
