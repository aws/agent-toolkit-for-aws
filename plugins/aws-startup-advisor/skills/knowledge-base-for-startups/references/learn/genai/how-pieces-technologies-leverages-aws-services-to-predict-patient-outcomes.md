---
source_url: https://aws.amazon.com/startups/learn/how-pieces-technologies-leverages-aws-services-to-predict-patient-outcomes
title: "How Pieces Technologies leverages AWS services to predict patient outcomes"
---

## How Pieces Technologies leverages AWS services to predict patient outcomes

HCLS startup Pieces Technologies uses AWS services to predict patient outcomes. Learn how their AI platform improves care and enhances efficiency.

---

What would you do if you could predict the future?

With the advancing capabilities of [predictive artificial intelligence (AI)/machine learning (ML) tools](https://docs.aws.amazon.com/whitepapers/latest/healthcare-data-analytics-framework-opioid-crisis/predictive-analytics-using-ai-and-ml.html), forecasting the future—at least probabilistically—may be in reach.

[Pieces Technologies, Inc.](https://piecestech.com/) (Pieces), a healthcare and life sciences startup, is blazing a trail in the predictive AI/ML space. Pieces is a software as a service (SaaS)-based AI platform integrated into a hospital's electronic health record (EHR). Their mission is to improve care by providing clinical insights along the patient journey. They offer predictions of health events such as projected discharge dates, anticipated clinical and non-clinical barriers to discharge, and risk of readmission, before they occur. Pieces also provides insights to healthcare providers in natural language, and optimizes the overall clarity of the patient's clinical issues so care teams can work more efficiently.

CEO and founder Dr. Ruben Amarasingham founded Pieces to help providers and patients achieve better outcomes. He explains, "Healthcare work is essential. Yet physicians, nurses, and other people are leaving medicine because of [burnout](https://www.hhs.gov/surgeongeneral/priorities/health-worker-burnout/index.html) and because of powerlessness. We see enormous technological sophistication in other parts of our lives—why can't we apply that to medicine?"

During his 13 years as a hospital physician, Ruben saw that "there were a number of patients that kept being readmitted to the hospital. They would come into the hospital, receive treatment, and then one to three weeks later they would be back." With post-graduate training in biomedical informatics and a focus on predicting clinical events, this trend inspired Ruben to help.

> "I saw an intersection between my research background, my clinical practice, and what was happening in the hospitals."

To apply his theory to a real-world use case, "We began to mathematically model—based on the characteristics of the patients—which patients might be readmitted. Then we applied clinical and non-clinical resources to the at-risk patient, including social determinants. And we found that we could identify and prevent re-hospitalization before it occurred."

The ability to predict patient rehospitalization led Ruben to found Pieces in 2016. The scope of Pieces' services for healthcare providers and patients has grown rapidly. Today, "We're looking at any kind of patient adverse event and saying, 'Are we able to predict it ahead of time?' If so, we deliver an insight to individuals on the ground ahead of time in a way that they can act on it."

To deploy and maintain their AI engine at scale, Ruben says Amazon Web Services (AWS) are integral: "We would not be able to do this work if we did not have an unbelievably dynamic, scalable cloud on which to do it. It's not possible on premises. You need to have these modeling systems learn from large datasets and you need the ability to manipulate or modify the AI performance at scale and across clients."

> After a brief period during their incubation when Pieces used an on-premises environment, "We switched to AWS and we haven't looked back. It's been terrific. We are incredibly grateful for the AWS environment."

The two most critical AWS services that Pieces uses to run their models in production and at scale are [Amazon Managed Workflows for Apache Airflow (Amazon MWAA)](https://aws.amazon.com/managed-workflows-for-apache-airflow/) and [Amazon Elastic Kubernetes Service (Amazon EKS)](https://aws.amazon.com/eks/). Ruben explains, "We use Amazon EKS to run Kubernetes instances of [Amazon Elastic Compute Cloud (Amazon EC2)](https://aws.amazon.com/ec2/) and [Amazon Relational Database Service (Amazon RDS)](https://aws.amazon.com/rds/)." The ability to monitor health system client sites in real time is critical for Pieces, so they use Amazon EC2 and [Amazon OpenSearch Service](https://aws.amazon.com/opensearch-service/) to log analytics for real-time application monitoring.

Ruben is passionate about creating AI/ML predictions that are relevant and accessible. "We're most excited about incorporating natural language generation into our software. That capability is the where Pieces is with AI right now." Pieces leverages natural language generation to give healthcare providers predictions within context and in plain language. Natural language makes it easier for healthcare providers to evaluate the AI's judgment for the most critical patient needs, while putting less critical predictions aside. This makes it easier to act on information in a timely and beneficial way.

> "Natural language generation can help providers and patients by translating information—at scale—in the way that they can best absorb it. Whether that's a clinical summary for a physician, or discharge instructions for a family member with, say, a seventh-grade education level."

In the near future, we can expect Pieces to launch a hand-off summary for physicians that allows them to pass their patient to another physician if needed. The summary is generated using some of the clinical data that AWS solutions allow Pieces to collect. According to the [Joint Commission](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC3312531/#i1949-8357-4-1-4-Joint2), physician hand-offs are a significant problem in healthcare because "an estimated 80% of serious medical errors involve miscommunication between caregivers when patients are transferred or handed-off." By automating this task, Pieces hopes to improve patient outcomes while also, "bringing joy of medicine practice into a system that is enormously complicated," explains Ruben.

For startups that want to follow in Pieces footsteps, Ruben advises, "Healthcare is highly regulated, very precise, and you have to test things more rigidly than, say, a retail startup. It's okay to take a slower course, and it's important to find investors and backers that understand the healthcare environment and the benefits of incremental progress."

The success is worth it, says Ruben, because, "If you can go through all of the steps, the impact is profound. You're doing good for the world."

## Related resources

- [AWS Activate: Get started on AWS](https://aws.amazon.com/activate/)
- [Healthcare & Life Sciences Startups](https://aws.amazon.com/startups/healthcare-life-sciences/)
- [Machine Learning for Startups](https://aws.amazon.com/startups/machine-learning/)

---

## About the Authors

### Dr. Ruben Amarasingham

Ruben Amarasingham, MD, MBA, is the Founder and CEO of Pieces, a healthcare AI firm that specializes in clinical decision sciences. He is also the Founder and past president of PCCI, a scientific research institute based in Dallas, Texas, whose focus is clinical trials and biomedical informatics, and gave rise to Pieces. Dr. Amarasingham is a national expert in the design of AI products for healthcare and public health. Prior to his role as CEO of Pieces, he was the Associate Chief of Medicine at Parkland Health & Hospital System, and a professor in the departments of General Internal Medicine and Clinical Sciences at the University of Texas Southwestern (UTSW) Medical Center, where he also served as the Director of the Biomedical Informatics Program for the NIH Clinical and Translational Science Award. Ruben is a past member of the national board of directors of HIMSS.

### Megan Crowley

Megan Crowley is a Senior Technical Writer on the Startup Content Team at AWS. With an earlier career as a high school English teacher, she is driven by a relentless enthusiasm for contributing to content that is equal parts educational and inspirational. Sharing startups' stories with the world is the most rewarding part of her role at AWS. In her spare time, Megan can be found woodworking, in the garden, and at antique markets.
