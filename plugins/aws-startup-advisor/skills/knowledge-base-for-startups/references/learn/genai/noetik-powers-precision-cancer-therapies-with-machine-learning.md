---
source_url: https://aws.amazon.com/startups/learn/noetik-powers-precision-cancer-therapies-with-machine-learning
title: "Noetik powers precision cancer therapies with machine learning"
---

## Noetik powers precision cancer therapies with machine learning

Together with Amazon Web Services (AWS) and NVIDIA, Noetik is using advanced machine learning techniques to power a new generation of precision cancer treatments.

---

The AI frontier is quickly becoming home to all manner of medical breakthroughs and scientific advancements. Innovative startups like [Noetik](https://www.noetik.ai/) are using AI to transform healthcare and life sciences by accelerating research, uncovering novel treatments, and facilitating more tailored care. Together with Amazon Web Services (AWS) and NVIDIA, Noetik is using advanced machine learning techniques to power a new generation of precision cancer treatments.

## Opening the way to a new generation of treatment

Founded in 2022, Noetik is an AI-native biotechnology company leveraging advanced machine learning methods to discover and develop cancer therapeutics. "Cancers are more complex than we can define as humans, and really this is a problem for machine learning," says Ron Alfa Co-founder and CEO. The Noetik team is building a future of precision immunotherapies that begin with the patient.

The company combines self-supervised learning with the industrial-scale generation of human multimodal data—because the best model system for cancer is the patient. This approach enables Noetik to create novel foundation models for virtual cell and tissue biology that drive therapeutic development. "The field has made tremendous progress with simple genomic definitions of cancer to enable targeted therapeutics," says Alfa. "But we believe that the future of cancer biology is going to depend on more complex definitions that will unlock precision therapeutics that we haven't even imagined yet."

"In less than two years, we've already generated close to a petabyte of data. This is one of the largest, deepest profiled human tumor biology datasets of its kind—we are profiling human tumors from the level of the tissue to the genome," says Alfa. "This proprietary data enables the development of frontier multimodal models of virtual cell and tissue biology that are unprecedented in the industry. With a truly unique dataset, we are able to train models that can understand human biology unlike any other approaches out there."

## Scalable infrastructure built for demanding AI workloads

Storing, processing, and building models on multimodal data is a significant technical undertaking. "We've collected data on over a thousand tumor samples, more than 200 million cells worth of really carefully crafted, precise, multimodal data to train AI models on," says Lacey Padrón, CTO. "Processing all the multimodal data that we're generating in the lab requires a really sophisticated infrastructure and a lot of compute. We've built this infrastructure from day one on AWS and NVIDIA technologies."

![Noetik team member looks at data on screen](https://d22k7geae6sy8h.cloudfront.net/files/680906ff0d4846000b8e0fad/AWS_NVIDIA_Noetik_Web_Full_Cut_Still006.jpg)

"One of the core reasons why we chose to work with AWS is the robustness of the ecosystem and the AWS cloud infrastructure that allowed us to build very quickly," says Alfa. "We were a very small team at the start with significant data needs. We had to build the infrastructure to process all those data sets very quickly. AWS allows us to do that."

Noetik leverages multiple AWS services for automated data processing and scalability. "We automate data ingestion from our lab, and we process it in automated pipelines that we've built in the cloud," says Padrón. Noetik uses [Amazon Elastic Compute Cloud (Amazon EC2)](https://aws.amazon.com/ec2/) instances, in combination with other AWS services and [Karpenter](https://karpenter.sh/), for secure and resizable compute capacity, as well as [Amazon Athena](https://aws.amazon.com/athena/) for serverless data analysis at scale. "This allows our scientists, our front end, and our machine learning models, to easily query that processed data and use it for downstream tasks," says Padrón.

The Noetik team is also using [Amazon SageMaker HyperPod](https://aws.amazon.com/sagemaker-ai/hyperpod/) to scale model development more efficiently. SageMaker HyperPod reduces the time needed to train foundation models (FMs) by providing a purpose-built infrastructure for distributed training at scale. SageMaker HyperPod offers a resilient training environment by actively monitoring cluster health and automatically replacing faulty nodes and resuming training jobs, saving up to 40 percent of training time.

"Amazon SageMaker HyperPod has been really transformative for us in being able to scale training workloads across hundreds of compute instances seamlessly," says Alfa. Noetik trains its largest models using [NVIDIA Hopper](https://www.nvidia.com/en-gb/data-center/technologies/hopper-architecture/) GPUs which are purpose-built for AI workloads including analytics, training, and inference. "We're currently running 256 [NVIDIA H100s](https://www.nvidia.com/en-gb/data-center/h100/) and we're continuing to scale," says Padrón. "SageMaker HyperPod has made that process effortless."

## Dedicated programs and proven expertise

The collaboration between Noetik, AWS, and NVIDIA goes beyond technology. For example, the Noetik team participated in the [AWS Generative AI Accelerator](https://aws.amazon.com/startups/programs/generative-ai), a global 10-week hybrid program helping AI startups prove what's possible in their industry. With less than a 2 percent acceptance rate, participants receive up to $1 million USD in AWS credits, as well as access to proven expertise from AWS and program partners like NVIDIA.

"We've been really thrilled to be part of the AWS Generative AI Accelerator. One of the main aspects of the program that's been incredibly exciting is meeting great startups that are solving hard problems in the healthcare space," says Alfa. "We've also had the opportunity to work very closely with AWS on scaling our compute needs for model training as well as working with their business development teams around go-to-market opportunities." Access to external technical expertise helped the Noetik team resolve some initial challenges with data loading bottlenecks. "We worked really closely with NVIDIA and AWS and used a number of different solutions to first figure out what was going on and then solve the issue," says Padrón.

Noetik is also participating in [NVIDIA Inception](https://www.nvidia.com/en-gb/startups/), a program designed to help startups accelerate technical innovation and business growth at all stages. Inception is free and supports members of its global community with valuable benefits from NVIDIA and partners. "A lot of what we're doing at Noetik is thinking about ways to train really large, novel foundation models and being part of Inception allows us to connect with technical leaders at NVIDIA that have been working with us hand-in-hand on some of these challenges," says Alfa.

"We've collaborated with multiple teams across the NVIDIA ecosystem that are working on important problems for healthcare and life sciences. For example, some of the applications of our models are in the space of single-cell biology. NVIDIA has teams that are deeply experienced and excited about building models in that space," says Alfa. "We've also been working with potential partners that can help us accelerate our business."

## Life-saving breakthroughs within reach

Collaborating with AWS and NVIDIA has helped Noetik scale its models and overcome technical challenges. "Using Amazon SageMaker HyperPod and having access to technical experts at both AWS and NVIDIA has helped us to scale up our training with a really small team," says Padrón. Going forward, the team will continue to improve their infrastructure and ramp up their efforts. "In the future, we'll move to [NVIDIA H200 GPUs](https://www.nvidia.com/en-gb/data-center/h200/) and hopefully double our training throughput," says Padrón.

With access to cutting-edge technology and proven expertise, Noetik is primed to open new possibilities in cancer treatment. "I'm a cancer survivor myself, and I was really fortunate to have a diagnosis that was treatable," says Padrón. "But there are so many patients who just don't have great options. The dream is new and more efficacious therapies and being able to know exactly which patients those will work for." Alfa adds: "We're at the point right now where AI can make an impact on science at scale, at speed. Now we're envisioning that next step. The work we do today can impact patients and help save lives."

---

_Source: [AWS Startups](https://aws.amazon.com/startups/learn/noetik-powers-precision-cancer-therapies-with-machine-learning)_
