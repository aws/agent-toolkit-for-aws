---
source_url: https://aws.amazon.com/startups/learn/discover-four-pakistani-startups-at-the-forefront-of-ai-ml
title: "Discover four Pakistani startups at the forefront of AI/ML"
---

## Discover four Pakistani startups at the forefront of AI/ML

> _By Eunice Cheng_

[Amazon Web Services (AWS)](https://aws.amazon.com/) and [Epiphany](https://epiphanyofficial.co/) joined forces in 2021 to co-curate an artificial intelligence (AI)/machine learning (ML) bootcamp called [AI/ML Reactor](https://epiphanyofficial.co/ai-ml-reactor/). AI/ML Reactor is a rigorous 5-week virtual program aimed at driving AI/ML awareness and empowering startups in Pakistan.

We received an overwhelming response for this program. Twenty-five startups were chosen out of 250 startups that applied from all provinces in Pakistan. Participants had access to exclusive master classes, a group tech mentoring session, and one-on-one mentoring sessions with AWS specialists and thought leaders. At the end of the program, they presented their AI/ML solutions to a panel of judges (see [Demo Day](https://www.youtube.com/watch?v=81gwXE8gZdc)).

**Meet our winners from the 2021 Reactor!**

## Salesflo – 1st prize

Salesflo is one of Pakistan's fastest growing software as a service (SaaS) platforms. They build tools to improve in-field sales efficiency for consumer goods.

The Salesflo team embarked on AI/ML Reactor to build Salesflo Airstrike – an image recognition solution that automates the retail merchandizing process. It uses [Amazon Rekognition](https://aws.amazon.com/rekognition/), [Amazon SageMaker](https://aws.amazon.com/pm/sagemaker), [Amazon Elastic Compute Cloud (Amazon EC2)](https://aws.amazon.com/ec2/), and [AWS Lambda](https://aws.amazon.com/lambda/).

Currently, only 2% of Pakistan's 700,000 retail outlets are merchandized. This provides growth potential for fast-moving consumer goods (FMCG) companies to make their products available, visible, and engaging to consumers. Salesflo's winning solution enables a shop to be merchandized, providing greater store coverage, lower costs, and faster availability.

Since winning AI/ML Reactor in 2021, Salesflo has completed successful pilot tests with clients such as [Unilever](https://www.unilever.com/) and [Friesland Campina](https://www.frieslandcampina.com/). In addition, they have been working on embedding this module within their product [Engage](http://www.engage.salesflo.com/) to enhance merchandizing and optimize workflows. This past year, Salesflo has been working on optimizing the models that they are using and determining product divisions and pricing categories.

> _"The program is a step toward fulfilling the potential of the retail industry and bringing innovation to the up-and-coming tech sphere of Pakistan" – Hamza Khan, Head of Data & Engineering, Salesflo_

## Ozoned Digital Ltd ("Ozoned") – 2nd prize

[Ozoned](https://ozoneddigital.com/) is an [insurtech](https://www.investopedia.com/terms/i/insurtech.asp) startup that aims to digitally transform the insurance value chain. It services multiple stakeholders (insurers, insurance brokers, insurance agents, customers, and others) in the insurance ecosystem.

Ozoned joined the AI/ML Reactor program to develop solutions to overcome digital data entry errors and minimize high survey costs in the automotive insurance space. With [Amazon Textract](https://aws.amazon.com/textract/), Ozoned was able to extract data automatically from a customer's government-issued identification card to activate motor insurance coverage.

To help minimize insurance claims surveyor interaction during the initial stages of a claim, Ozoned used Amazon Rekognition with custom labels. This enabled identification of a vehicle and its damaged parts, reduced costs, and created efficiencies. The model was further trained to assess whether the vehicle damage was a partial or total loss. This assessment helped insurers generate an initial claim estimate for the damages, while reducing time and cost to the insurer.

Most recently, Ozoned has signed up one of the largest insurers in Pakistan – [Adamjee General Insurance](https://www.adamjeeinsurance.com/). Adamjee is deploying Ozoned across their motor insurance operations.

> _"The AI/ML Reactor program allowed Ozoned Digital to impart AI/ML training to its team and come up with a world class AI/ML technology solution in the insurtech space." – Nomaan Bashir, co-founder and CEO, Ozoned Digital Ltd_

## XpertFlow – joint 3rd prize

[XpertFlow](https://www.xpertflow.com/) is an AI-powered preventative healthcare company founded in 2019. Its mission is to reduce mortality from hospital acquired infections (HAIs) that eventually lead to sepsis.

In Pakistan, approximately 350,000 people are affected by sepsis each year, and more than 275,000 lose their lives. It costs public and private hospitals more than 10 billion PKR ($66 million) per year to treat sepsis. Without timely treatment, sepsis can rapidly lead to tissue damage, organ failure, and death.

During the AWS AI/ML Reactor program, the XpertFlow team used AWS services to forecast sepsis 6 hours before its onset:

- [Amazon Simple Storage Service (Amazon S3)](https://aws.amazon.com/s3/) stores raw time series data and the model artifacts.
- [Amazon SageMaker's Data Wrangler](https://aws.amazon.com/sagemaker/data-wrangler/) and notebook instance handles the entire pre-processing pipeline.
- [Amazon SageMaker Autopilot](https://aws.amazon.com/sagemaker/autopilot/) trains over 200 different iterations of the model, with different algorithms available on SageMaker. With Amazon SageMaker Autopilot, the team was able to select a model from several generated based on the [area under receiver operator curve (AUROC)](https://glassboxmedicine.com/2019/02/23/measuring-performance-auc-auroc/).
- An endpoint was generated from that model and connected to [Amazon API Gateway](https://aws.amazon.com/api-gateway/) using Lambda.
- The API was then connected to the demo interface on the team's [deepnostiX](https://deepnostix.com/)

The winning model delivered 97% accuracy in predicting sepsis 6 hours ahead of time. It acts as an early warning system that performs nearly continuous monitoring of patients in ICUs or wards, assigning a risk score based on a patient's vital signs.

After the AI/ML Reactor program, the sepsis AWS AI model is now fully tested and is being piloted at a few hospitals in Pakistan. XpertFlow has started using SageMaker to estimate blood pressure noninvasively, continuously, and without using arm cuffs. They are currently running trials for this new approach towards calculating blood pressure in a hospital in Islamabad, Pakistan.

> _"Being a CTO of a young startup, I am always looking out for tech-focused programs. After attending many programs and accelerators during the life of XpertFlow, this has been by far one of the best. The learning the team and I got from this, during a span of 5 weeks, was just incredible. We learned from the best on how to deploy our existing AI/ML solutions on the cloud and supercharge them using AWS AI/ML services. Huge shout to AWS and Epiphany for coming up with one-of-a-kind program, which was missing here in Pakistan." – Shan Ul Haq, CTO, XpertFlow_

## Trukkr – joint 3rd prize

[Trukkr](https://trukkr.pk/) provides financial services and technology for logistics in Pakistan. It gives both large and small businesses a comprehensive technology platform to manage and provide all their logistical needs. Trusted by some of the biggest companies in the country, Trukkr saves organizations time and money, while providing them with deep data and powerful insights.

In an effort to improve dropoff rates during sign up (see Figure 1), Trukkr investigated their onboarding process. During the AI/ML Reactor program, Trukkr delivered initial solutions to optimize their onboarding funnel. They extracted data from uploaded documents using Amazon Textract, and used that information to prefill a signup form.

The team was able to make an impact on improving the onboarding funnel, increasing their signup completion rates from 38% to 52%.

![Figure 1. Trukkr's dropoff rates during sign up](https://d22k7geae6sy8h.cloudfront.net/files/64a2f36573217a00082c8119/8ljn27hic-Figure-1.-Trukkrs-dropoff-rates-during-sign-up.png)

> _"This program helped us in further leveraging AI/ML to provide our customers with intelligent features that help them better manage and optimize their logistics. During the program, regular feedback from AWS expert mentors and the step-by-step architecture review sessions helped speed up the learning process, and deliver meaningful features to our customers." – Kasra Zunnaiyyer, co-founder and CTO, Trukkr_

---

## About the Author

### Eunice Cheng

Eunice Cheng currently leads Startup Marketing at Amazon Web Services in Southeast Asia. Leveraging her experience as a former startup operator and growth marketing consultant, she is dedicated to helping entrepreneurs grow and scale with AWS.
