---
source_url: https://aws.amazon.com/startups/learn/unlocking-the-value-of-unstructured-data-how-coactive-built-a-visual-analytics-platform-on-aws
title: "Unlocking the value of unstructured data: How Coactive built a visual analytics platform on AWS"
---

## Unlocking the value of unstructured data: How Coactive built a visual analytics platform on AWS

Coactive builds on AWS to bring structure to unstructured data through their innovative visual analytics platform.

---

It is said that a picture is worth a thousand words – and, according to Forrester Research, a minute of video may be worth [1.8 million words](https://www.forrester.com/report/how-video-will-take-over-the-world/RES44199). For businesses ranging from ecommerce to social media, visual content is worth more than the amount of words that it conveys: it is an opportunity to build customer engagement, increase trust and safety, enhance personalization, and glean actionable insights based on content engagement.

[Coactive AI](https://coactive.ai/), a visual data analytics startup founded by CEO Cody Coleman and Will Gaviria Rojas in 2021, is democratizing the opportunity for businesses to analyze images and videos.

Images and videos are [unstructured data](https://aws.amazon.com/what-is/structured-data/#:~:text=Unstructured%20data%20is%20information%20with,Video%20files)—information that has not yet been ordered in a predefined way—that traditionally require machine learning expertise, a robust technical infrastructure, and significant amounts of time to accurately analyze.

Coactive, the platform built by Coactive AI on Amazon Web Services (AWS) and available on the [AWS Marketplace](https://aws.amazon.com/marketplace/seller-profile?id=seller-4amrnunk7ek3o), helps data practitioners derive rapid insights from unstructured data at scale and with minimal supervision. Accessible by user interface or APIs, the platform's capabilities range from intelligent search to production analytics that use the full power of SQL.

## Proving what's possible in AI

Coactive's innovative solution results from intensive amounts of time, research, and determination. During 2018, while earning his PhD in Computer Science at Stanford, Cody recognized that "artificial intelligence and intelligent applications were going to be the future. The blocker was that you needed hundreds of thousands of dollars' worth of equipment and tremendous amounts of data to accomplish anything significant."

> Bothered by these limitations, Cody committed to lowering the barriers to entry for machine learning so that everyone could benefit from it: "My mission during graduate school was to use my passion for computer science to benefit society at large while serving as a leader for future generations."

Cody joined the Stanford DAWN research project, a group focused on making it dramatically easier to build AI-powered applications. One of the many [impressive breakthroughs](https://scholar.google.com/citations?user=OtJC70cAAAAJ&hl=en) from Cody's work was [DAWNBench](https://dawn.cs.stanford.edu/2017/11/29/dawnbench-intro/), the first end-to-end machine learning (ML) systems benchmark used by global technology companies as the industry standard. In its first year, DAWNBench reduced model training time by 500x and training cost by 20x. Galvanized by the progress he'd made in creating accessible AI, Cody tackled the next big question: What to do next?

At this time--by serendipity or coincidence--Cody's friend Will moved to the San Francisco Bay area to begin a career at a large technology company. With a friendship spanning 10 years since their time as undergrads at Massachusetts Institute of Technology (MIT), Cody helped Will move in. "Will asked me the two questions you should never ask a PhD student because they cause an immediate existential crisis," laughs Cody. "'When are you going to graduate?' and 'What are you going to do after?'"

Cody had considered options that ranged from joining a prestigious technology company, becoming a university faculty member, joining a startup, or building a company. "Without hesitation, Will told me to build my own company," says Cody. "He told me that it's the right time and I have the right knowledge. And that he'd love to join me in this journey."

Months of conversations, research, and studying the problem first-hand led Cody and Will to come to the same realization: People need a visual analytics platform to unlock the value of their content, and it's time to build it. With that decision, Coactive was founded.

## Creating a visual analytics solution for everyone

Machine learning advanced significantly during Cody's time at Stanford, but there was still much work to be done to make AI applications accessible to everyone: from the world's largest companies, to a startup designing their minimum viable product.

This was particularly true about machine learning that analyzed images and videos to derive actionable insights. For these unstructured data formats, the end-to-end workflow could require high-end large-scale compute in the form of GPUs, significant storage capacity, and large amounts of time and expertise due to the complexity of the process. A common workflow may include the following:

1. Data scientists complete data exploration and build computer vision models to analyze and understand the visual data.
2. ML engineers operationalize these models.
3. Software engineers plug the model predictions into real world applications for consumers.

To make visual content analysis more accessible, accurate, and efficient, Coactive pairs the breadth of existing large language models (LLMs) with the accuracy and automation that comes from applying a learning system to domain-specific data. After customers provide access to their large volumes of raw image and video files, Coactive uses pre-trained foundation models in conjunction with their proprietary active learning and classification system to embed and index the data. During this process, customers have the option to upload existing labels or provide a few examples so the Coactive platform can further learn any domain-specific nuances of their data.

> "One of the very powerful things about really large models is that we don't actually need to toss a massive quantity of data to fine-tune for specific tasks," explains Cody. "They call these large language models 'few-shot learners' for a reason. Rather than thinking about the quantity of data we toss at these systems, it's really about quality."

The result? Customers can use Coactive to query, search, filter, and analyze visual content rapidly and at massive scale.

## Partnering with AWS to accelerate success

As an innovative and rapidly-scaling startup, Coactive decided to migrate from their original cloud provider go all-in on AWS. Solutions offered by AWS align with Coactive's four primary cloud provider needs: Depth and breadth of services, optionality in tooling, availability to power the scaling of their product, and security-first offerings.

> "We needed to build our solution on a cloud provider that could handle enterprise scale while being flexible enough to let us create something entirely new. With AWS, we were able to do this while ensuring best-in-class security to our customers," says Cody.

## Building with AWS solutions

After migration, Coactive set to work building a cutting-edge web application using AWS solutions such as [Amazon Simple Storage Service (Amazon S3)](https://aws.amazon.com/s3/), [Amazon Aurora](https://aws.amazon.com/rds/aurora/), and [Amazon Elastic Container Service (Amazon ECS)](https://aws.amazon.com/ecs/). This web application helped Coactive establish their initial MVP and run proof of concepts for prospects.

For their data-centric machine learning jobs, Coactive benefits from using [Amazon Aurora PostgreSQL Serverless](https://aws.amazon.com/rds/aurora/serverless/) to serve low latency database requests without having to spend time managing their database infrastructure. Coactive's many petabytes of image and video data are stored using Amazon S3.

To front their web application, Coactive uses a combination of [Amazon CloudFront](https://aws.amazon.com/cloudfront/) as its content delivery network (CDN). The backend web application runs on Amazon ECS, communicating with their database and peripheral downstream services such as [Databricks on AWS](https://www.databricks.com/product/aws). Amazon ECS provides Coactive simplicity in managing the container infrastructure running on [Amazon Elastic Compute Cloud (Amazon EC2)](https://aws.amazon.com/ec2/).

Security and data privacy are critical aspects of machine learning workloads. To provide their customers with a secure analytics experience, Coactive uses [Amazon GuardDuty](https://aws.amazon.com/guardduty/), [Amazon Inspector](https://aws.amazon.com/inspector/), [AWS Key Management Service](https://aws.amazon.com/kms/), and more. With these solutions, Coactive achieved SOC2 cybersecurity compliance over the course of a single quarter.

## Bringing their product to market

It is important to ensure a successful go-to-market motion. To share their product with the global audience of AWS customers, Coactive joined the [AWS Partner Network (APN)](https://aws.amazon.com/partners/) and lists their product on the [AWS Marketplace](https://aws.amazon.com/marketplace/seller-profile?id=seller-4amrnunk7ek3o).

Coactive is also a member of the [AWS Global Startup Program (GSP)](https://aws.amazon.com/partners/programs/global-startup/), offered through the APN. This program pairs Coactive with an AWS Partner Development Manager who provides support in three key areas: product development, go-to-market, and co-selling.

## Accelerating success with AWS Startups

In addition to building with the help of AWS technical solutions and business support, Coactive leverages the [AWS Activate](https://aws.amazon.com/startups?lang=en-US) program. AWS Activate provides startups with resources ranging from credits and exclusive offers, to technical support and networking events.

In collaboration with the AWS Startups team, Cody and other AWS Activate members recently shared their expertise at AWS GenAI Day, a one-day virtual event showcasing how startups are building with generative AI on AWS. As part of the keynote panel "[Mapping the Trajectory of GenAI: From Learning to Impact](https://genaiday.virtual.awsevents.com/media/Mapping%20the%20Trajectory%20of%20GenAI%3A%20From%20Learning%20to%20Impact/1_ykvv1e2o)," Cody explained why data is a critical piece of generative AI and how recent breakthroughs in machine learning have the potential to significantly improve lives.

## Building for the future

Coactive continues to build a product that lowers the barrier to entry for machine learning and Cody notes that proving what's possible—and helping other people to prove it as well—is an important part of his mission. His [incredible story](https://hai.stanford.edu/news/cody-coleman-lowering-machine-learnings-barriers-help-people-tackle-real-problems) includes being born during his mom's incarceration, placed into foster care, and adopted by grandparents who raised him within the constraints of [economic inequality](https://www.hrw.org/united-states/poverty-and-economic-inequality).

As the first Black PhD student to graduate from Stanford in nearly 20 years, Cody is familiar with the challenges of being an underrepresented person in technology. He's committed to making diversity, equity, and inclusion core principles at Coactive. "How we succeed is just as important as the fact that we do succeed," says Cody.

> "Will has a great saying where he says his goal in life is to make ladders so it's easier for people to follow in his footsteps," Cody explains. "My mission in life in general is to demonstrate that regardless of where you come from, you can be successful. If I could do it, anyone can do it."

For people who are considering founding a startup, Cody shares that fear is normal: that you're not cut out for the CEO role, that it's a big risk to start a company, that things will be hard for a long time. His moment of confidence came when he realized, "I don't need to have everything figured out to get started. I just need to start to figure everything out."

Two years later, the success of this advice is evident. The Coactive team continues to level the AI playing field by bringing impactful visual analytics to their customers. Cody's commitment to making data useful remains strong. "One of the most amazing [use cases](https://arxiv.org/pdf/1711.06405.pdf) I've seen is fine-tuning a speech recognition model to recognize the signs of a dangerous respiratory condition in a baby's cry," he explains. Early detection using AI reduced the infant mortality rate and lowered the time, cost, and skill necessary to make an accurate diagnosis.

> "Sustainable and ethical AI has incredible potential to meaningfully improve lives," says Cody. "One of my biggest motivators to this day is that by democratizing AI with companies like Coactive and AWS, there are so many stories people are going to tell and questions they are going to answer. I'm excited to see it."

---

## Authors

### Megan Crowley

Megan Crowley is a Senior Technical Writer on the Startup Content Team at AWS. With an earlier career as a high school English teacher, she is driven by a relentless enthusiasm for contributing to content that is equal parts educational and inspirational. Sharing startups' stories with the world is the most rewarding part of her role at AWS. In her spare time, Megan can be found woodworking, in the garden, and at antique markets.

### Bonnie McClure

Bonnie is an editor specializing in creating accessible, engaging content for all audiences and platforms. She is dedicated to delivering comprehensive editorial guidance to provide a seamless user experience. When she's not advocating for the Oxford comma, you can find her spending time with her two large dogs, practicing her sewing skills, or testing out new recipes in the kitchen.

---

_Source: [AWS Startups](https://startups.aws/startups/learn/unlocking-the-value-of-unstructured-data-how-coactive-built-a-visual-analytics-platform-on-aws)_
