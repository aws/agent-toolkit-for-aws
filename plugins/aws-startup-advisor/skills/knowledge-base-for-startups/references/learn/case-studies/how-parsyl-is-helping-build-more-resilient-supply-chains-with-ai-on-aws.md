---
source_url: https://aws.amazon.com/startups/learn/how-parsyl-is-helping-build-more-resilient-supply-chains-with-ai-on-aws
title: "How Parsyl is helping build more resilient supply chains with AI on AWS"
---

## How Parsyl is helping build more resilient supply chains with AI on AWS

![Parsyl team](https://d22k7geae6sy8h.cloudfront.net/files/6a43d72588de33000cbf3216/parsyl-happy-hour-headshot-denver.jpg)

[Parsyl](https://www.parsyl.com/) protects the world’s essential supply chains. Founded in 2017, the business provides insurance for critical goods, ranging from medicines and food to semiconductors and solar panels. The company operates the first AI- and mission-driven syndicate at Lloyd’s of London, the world’s largest insurance market for complex risks.

---

As the startup expanded from supply chain technology into specialty insurance, Parsyl saw an opportunity to rethink how risks are assessed and managed. By combining proprietary supply chain data, generative AI, and AWS services including [Amazon Bedrock](https://aws.amazon.com/bedrock/), [Amazon SageMaker](https://aws.amazon.com/sagemaker/), and more, Parsyl has streamlined underwriting and risk analytics significantly.

Reducing quote turnaround from weeks to hours, Parsyl helps underwriters deliver fast, tailored pricing with ongoing risk insights to reduce the chance of losses occurring. Now, the company is using AI to reinvent specialty insurance, from underwriting to claims settlement, to help businesses build more resilient global supply chains.

## The path to insurance innovation

Parsyl didn’t start its journey as an insurer. The company’s founders, Mike Linton, Ben Hubbard, and Alex Haar, instead came from supply chain technology and global development backgrounds. United by a shared interest in solving real-world challenges, Parsyl’s founders were initially focused on vaccine delivery and global health supply chains.

Parsyl started out by building Internet of Things (IoT) technology to monitor vaccines and other sensitive goods as they moved through supply chains, helping customers identify where products were being damaged and uncover the causes of these disruptions. From the outset, the mission was clear: making sure critical medication reached those who depended on it.

In addressing these challenges, the founders discovered an opportunity to make an even bigger impact. Linton, co-founder and CTO of Parsyl, explains, "As we were deploying technology across different markets, we kept hearing the same thing from customers: 'This is great, but you should talk to our insurers.' They could see that insurers would benefit from this granular data to better understand supply chains. That set us on the journey into specialty insurance."

The team realised that while data was helping them identify problems, insurance could create the incentive to solve them. This led Parsyl to Lloyd’s of London, where much of the global specialty insurance market operates. After working with Lloyd’s to develop insurance solutions for COVID-19 vaccine distribution, Parsyl began to expand into broader cargo and supply chain insurance.

![Parsyl team](https://d22k7geae6sy8h.cloudfront.net/files/6a43d72888de33000cbf3218/parsyl-team-group-photo-company-gathering.jpg)

## Transforming supply chain insurance

However, entering the insurance market revealed a significant challenge. Cargo insurance underwriting remained extremely manual, requiring customers to submit large amounts of information that could take weeks to review and quote.

And speed was only one part of the problem. Traditional underwriting relies on broad, generic risk categories, grouping businesses by geography or commodity type rather than representing how they actually operate. A fruit exporter in South America, for example, might receive the same outcome as another similar business, despite using different trade routes, commodity seasonality, shipping partners, or management processes. For Parsyl, this represented a missed opportunity. “Instead of just rating a customer as “a fruit shipper out of South America”, we wanted to understand their business at a much more granular level. They might avoid trans-shipments, for example, or heavily invest in risk management. They should get credit for those things,” explains Linton. “And if a customer has struggled with losses, we can work with them to understand what is causing those losses and share insights to improve over time.”

By combining insurance expertise with granular supply chain data, Parsyl saw an opportunity to provide customers with tailored pricing, faster underwriting decisions, and practical insights that would help reduce claims and losses over time. The next challenge was building a technology platform that could make this vision a reality.

## Building a tech-first insurer with AWS

Parsyl needed a technology platform that could process large volumes of data, support complex insurance workflows, and scale as the business expanded into new areas. AWS had already powered Parsyl's earlier IoT platform, making it a natural foundation as the company evolved into insurance.

Starting with the platform’s startup-friendly pricing and flexibility, Parsyl expanded its use of AWS to build a proprietary technology stack, encompassing underwriting, policy administration, and claims management. Today, the business relies on a wide range of AWS services, such [as Amazon Relational Database Service](https://aws.amazon.com/rds/) (Amazon RDS) for core relational data storage, [AWS Lambda](https://aws.amazon.com/lambda/) for serverless processing, and [Amazon Simple Storage Service](https://aws.amazon.com/s3/) (Amazon S3) for storage.

In 2023, the team began exploring generative AI to automate key underwriting workflows and reduce the manual effort of processing customer submissions. Amazon Bedrock played a key role in this transformation, providing access to multiple foundation models through its single managed service. “That flexibility was really key for us, and it continues to be today because, as everyone knows, the industry changes rapidly,” says Linton. “Running the models within a set of infrastructure that we were comfortable with was really important for us.”

With Bedrock and Anthropic Claude models, Parsyl built Chauncey, its AI-powered underwriting agent. Chauncey automates many of the manual underwriting tasks involved in submission ingestion, document management, and sanctions screening, and loads this data into its underwriting workbench for final review by underwriters. It also pulls in catastrophic risk data, working with Parsyl’s proprietary pricing engine to generate customer quotes.

Parsyl also uses Amazon SageMaker to develop faster and more tailored risk assessments for customers. “We build our own machine learning models around specific commodities,” explains Linton. “So if we see a fruit risk come in, we’ll use our proprietary model to predict the amount of loss we expect on that particular risk, and we use SageMaker to develop and run those models.”

Unlike many insurers that rely on third-party vendors and legacy systems, Parsyl builds most of its technology in-house. "We build the vast majority of our own technology because we believe that's the only way we’re going to achieve the level of innovation our industry needs,” says Linton. “AWS is a critical part of that strategy. Instead of building infrastructure from the ground up, we can leverage AWS services and managed capabilities to get new functionality into production very quickly."

![Parsyl team](https://d22k7geae6sy8h.cloudfront.net/files/6a43d72908d9da000c7ec3d4/parsyl-team-hiking-retreat-mountain-group-photo.jpg)

## Reimagining risk management

Results have shown a huge impact for both Parsyl and its customers. The startup can process a submission in 8 minutes and has reduced the time from submission to quote by over 75 percent. Customers receive tailored quotes faster, while underwriters can spend more time understanding client needs and operations to deliver greater value. Linton explains, “Speed is the first thing customers notice. But the bigger benefit is that our underwriters can spend more time with clients and better understand how their businesses operate.”

By automating over 80 administrative tasks traditionally associated with underwriting, Parsyl has enabled its teams to focus less on manual processes and more on customer engagement, consultation, and business growth. Armed with richer operational data and a deeper understanding of how customers operate, underwriters can assess exposure more accurately, recognize risk management practices that might be overlooked by traditional underwriting processes, and deliver more tailored pricing.

Rather than relying on periodic policy renewals, Parsyl provides ongoing visibility into risk conditions throughout the policy lifecycle, helping underwriters and customers identify emerging issues early and take action before they result in additional claims.

The result is a more collaborative approach to risk management, where insurers and customers share a common incentive to reduce losses, improve overall resilience, and enable better outcomes across the supply chain.

Now, Parsyl is expanding coverage to address a broader range of specialty risks across the globe. To support these new lines of business and an increasingly diverse range of risk data sources, the company is continuing to scale its platform on AWS and expand its use of AI. This includes exploring new capabilities in Bedrock, such as managed agents, to accelerate the development of AI-driven workflows for policy administration and claims processes.

Looking ahead, Parsyl sees an opportunity to do more than improve specialty insurance. "We have the opportunity to influence how the world's supply chains operate,” says Linton. “When risk becomes more visible, customers have a reason to change their behavior and ultimately build more resilient supply chains. That's what we're working toward."
