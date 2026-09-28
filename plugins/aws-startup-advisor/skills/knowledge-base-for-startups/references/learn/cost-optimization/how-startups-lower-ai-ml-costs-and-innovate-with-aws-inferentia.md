---
source_url: https://aws.amazon.com/startups/learn/how-startups-lower-ai-ml-costs-and-innovate-with-aws-inferentia
title: "How Startups Lower AI/ML Costs and Innovate with AWS Inferentia"
---

## How Startups Lower AI/ML Costs and Innovate with AWS Inferentia

> Want to reduce AI/ML costs and achieve high performance? Learn how Actuate and Finch Computing use AWS Inferentia to do just that.

As a machine learning (ML) startup, you're probably aware of the challenges that come with training and deploying ML models in your applications ("ML productization"). ML productization is challenging because startups are simultaneously working to achieve high application performance, create a delightful user experience, and manage costs efficiently–all while building a competitive and sustainable startup.

When choosing the infrastructure for their ML workloads, startups should consider how to best approach training and inference. Training is process by which a model is built and tuned for a specific task by learning from existing data. Inference is the process of using that model to make predictions based on new input data. Over the last five years, AWS has been investing in our own purpose-built accelerators to push the envelope on performance and compute cost for ML workloads. [AWS Trainium](https://aws.amazon.com/machine-learning/trainium/) and [AWS Inferentia](https://aws.amazon.com/machine-learning/inferentia/) accelerators enable the lowest cost for training models and running inference in the cloud.

AWS Inferentia-based [Amazon EC2 Inf1 instances](https://aws.amazon.com/ec2/instance-types/inf1/) are ideal for startups that wish to run ML inference applications such as:

- Search
- Recommendation engines
- Computer vision
- Speech recognition
- Natural language processing (NLP)
- Personalization
- Fraud detection

For training and deploying more complex models such as generative AI models (large language models and diffusion models), your startup may want to check out the new AWS Trainium-based [Amazon EC2 Trn1 instances](https://aws.amazon.com/ec2/instance-types/trn1/) and AWS Inferentia2-based [Amazon EC2 Inf2 instances](https://aws.amazon.com/ec2/instance-types/inf2/).

In this post, we will cover use cases from two startups–Actuate and Finch Computing–and the success they've seen with Inferentia-powered Inf1 instances.

## Actuate | Threat detection using real-time AI video analytics | 91% savings on inference costs

**Use case:** [Actuate](https://actuate.ai/) provides a software-as-a-service (SaaS) platform meant to convert any camera to a real-time threat-detecting smart camera to instantly and accurately detect guns, intruders, crowds, and loitering. Actuate's software platform integrates into existing video camera systems to create advanced security systems. With Actuate's artificial intelligence (AI) threat detection software, customers receive real-time alerts within seconds, and can act rapidly to secure their premises.

**Opportunity:** Actuate needed to ensure high detection accuracy. This meant constantly retraining their models using more data, which took up valuable developer time. Additionally, because they needed fast response times, they depended on GPU-based infrastructure which was cost-prohibitive at scale. As a startup with limited resources, minimizing inference costs and developer time could help Actuate use those resources to build better capabilities and provide more value to its end-users.

**Solution and impact:** First, Actuate implemented [Amazon SageMaker](https://aws.amazon.com/sagemaker/) to train and deploy their models. This reduced their deployment time–as measured from labeled data to deployed model–from 4 weeks to 4 minutes. In the next phase, they migrated the ML models across the entire suite of their products from GPU-based instances to AWS Inferentia-based Inf1 instances. This migration required minimal developer involvement as they didn't need to re-write application code and only needed a few lines of code changes. Actuate saw out-of-the-box cost savings of up to 70% with AWS Inferentia. On further optimization, they reduced inference costs by 91%. This allowed them to use their resources to focus on user experience improvements and fundamental AI research.

**Resources:** To learn more about Actuate's use case, you can [watch their presentation at reInvent](https://www.youtube.com/watch?v=dVlNobmvoTg&t=615). To get started with a computer vision model on Inf1 instances, visit the [Neuron documentation page](https://awsdocs-neuron.readthedocs-hosted.com/en/latest/) and explore [this notebook for Yolov5 model on GitHub](https://github.com/aws-neuron/aws-neuron-samples/blob/master/torch-neuron/inference/yolov5/Yolov5.ipynb).

## Finch Computing | Real-time insights using NLP on informational assets | 80% savings on inference costs

**Use case:** [Finch](https://finchcomputing.com/)—a combination of the words "find" and "search"—Computing serves media companies and data aggregators, US intelligence and government organizations, and financial services companies. Its products use natural language processing (NLP) algorithms to provide actionable insights into huge volumes of text data across a variety of informational assets. An example of this is sentiment assignment, which involves identifying a piece of content as positive, negative or neutral and returning a numeric score indicative of the sentiment level and type.

**Opportunity:** After adding support to their product for the Dutch language, Finch Computing wanted to scale further to support French, German, Spanish, and other languages. This would help existing clients with content in these languages, and also attract new customers across Europe. Finch Computing had built and deployed its own deep learning translation models on GPUs, which were cost-prohibitive to support additional languages. The company was looking for an alternate solution that could allow them to build and run new language models quickly and cost-effectively.

**Solution and Impact:** In just a few months, Finch Computing migrated their compute-heavy translation models from GPU-based instances to Amazon EC2 Inf1 instances powered by AWS Inferentia. Inf1 instances enabled the same throughput as GPUs, but helped Finch save more than 80% on its costs. Finch Computing supported the three additional languages and attracted new customers. Today all their translation models run on Inf1 and they plan to explore Inf2 instances for new generative AI use cases such as text summarization and headline generation.

**Resources:** To learn more about Finch Computing's use case, you can read this [case study](https://aws.amazon.com/solutions/case-studies/finchcomputing-case-study/). To get started with a translation model, visit the [Neuron documentation page](https://awsdocs-neuron.readthedocs-hosted.com/en/latest/) and see this [notebook for MarianMT model on GitHub](https://github.com/aws-neuron/aws-neuron-samples/blob/master/torch-neuron/inference/marianmt/MarianMT.ipynb).

## AWS Inferentia for cost-effective, high performance ML inference

In this blog, we looked at two startups who cost-effectively deployed ML models in production on AWS Inferentia, while achieving high throughput and low latency.

Are you ready to get started with Inf1 instances? You can use AWS Neuron SDK, which integrates natively with popular ML frameworks such as PyTorch and TensorFlow. To learn how, please visit the [Neuron documentation page](https://awsdocs-neuron.readthedocs-hosted.com/en/latest/) and explore this [sample model repository on GitHub](https://github.com/aws-neuron/aws-neuron-samples/tree/master/torch-neuron).

Check out how more AIML startups are building and scaling on AWS 🚀:

- [How machine learning helps Fraud.net to build a modern app on AWS to combat financial fraud](https://aws.amazon.com/blogs/startups/how-machine-learning-helps-fraud-net-to-build-a-modern-app-on-aws-to-combat-financial-fraud/)
- [Alloy's global identity decisioning platform, built on AWS](https://aws.amazon.com/blogs/startups/scaling-ai-ml-and-accelerating-ai-development-with-anyscale-and-aws/)
- [AWS and Hugging Face collaborate to make generative AI more accessible and cost efficient](http://aws%20and%20hugging%20face%20collaborate%20to%20make%20generative%20ai%20more%20accessible%20and%20cost%20efficient/)

---

_Author: Shruti Koparkar - Senior Product Marketing Manager at AWS. She helps customers explore, evaluate, and adopt Amazon EC2 accelerated computing infrastructure for their machine learning needs._
