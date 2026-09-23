---
source_url: https://aws.amazon.com/startups/learn/how-machine-learning-helps-fraud-net-to-build-a-modern-app-on-aws-to-combat-financial-fraud
title: "How Machine Learning Helps Fraud.net Build App to Combat Fraud"
---

## How Machine Learning Helps Fraud.net Build App to Combat Fraud

> Fraud.net outpaces and outsmarts the technology criminals use to commit fraud. Learn how they use AI/ML to give their banking and fintech customers peace of mind.

---

Startups know firsthand how better technology can improve the quality of life: From AI/ML allowing scientists to better predict patient health outcomes, to cloud computing driving life-saving innovation, and modern apps enhancing accessibility.

With better technology also comes the opportunity for criminals to commit more advanced levels of crime. Fraud, especially, is occurring with greater technical sophistication as society transitions into a digital-first world. Fraud and cybercrime are also growing at significant rates, and now cost businesses around the world over $6 trillion per year or an average of 5% of their revenues.

To outpace and outsmart the technology criminals use to commit fraud, former bankers Whitney Anderson and Cathy Ross founded [Fraud.net](https://fraud.net/), a modern fraud and compliance platform, in 2016. Fraud.net offers customers in the banking and fintech industries across the globe a serverless modern application that uses artificial intelligence and machine learning to rapidly identify fraud, leading to more efficient operations and higher customer satisfaction.

## Providing a Modern Solution to an Evolving Problem

As is the case with many successful startups, Fraud.net encountered a challenge and saw the opportunity to build a solution that helps themselves and other companies to overcome it.

"We were our own use case," explains Whitney. While operating companies in the digital commerce and payments world, "One of the greatest frustrations was experiencing multi-percent fraud rates, and payment processors not giving us access to the information we needed to solve the fraud."

To solve a problem that caused harm to companies and customers alike, he explains, "We started pooling together other players in the digital world: payment facilitators, merchants, and other ecosystem participants."

> **"By sharing secure and anonymized data, we were able to reduce fraud by more than by 66%. It was simple, immediate, and intuitive."**

One major finding was that the same people used the same technology-based methods to defraud multiple companies. "It's really difficult to fight fraud by yourself," says Whitney, "Sharing data in a safe and secure way let us understand a lot more about the bad actors and separate them with the goal of really delighting the 99% good customers."

Sharing an enormous amount of information within their cross-industry consortium meant that Fraud.net needed a rapid, scalable solution to unify their data and create real-time actionable insights.

Fraud.net chose to go all-in on Amazon Web Services (AWS).

## Building an Event-Driven Architecture on AWS

As a cloud-native modern app, Fraud.net uses an event-driven architecture that uses serverless components. Event-driven architecture makes it more efficient for startups to develop modern apps because they scale up to address events and scale down when no events occur. This can result in saving the startup resources and costs, which is critical as startups go to market. One benefit of Fraud.net's event-driven architecture is the scalability and speed with which their developers are able to bring products to market.

Fraud.net's AWS solutions include EC2 and Lambda for compute, S3 for highly scalable object storage, and DynamoDB as their noSQL serverless database.

Together, these solutions help them to unify and analyze three levels of data: customer-level data, institution-level data, and cross-institution data.

"Because of AWS' serverless technologies and other incredible innovations, we've been able to unify data for fraud prevention, anti-money laundering, and compliance functions," says Whitney.

Events from the Fraud.net platform arrive through a Fraud.net API that is managed by Amazon API Gateway. When the events arrive, they trigger an AWS Lambda function to process records from Amazon DynamoDB.

"Lambda functions have been a game-changer for us. We ask thousands of questions for each application or transaction submitted to us for risk assessment, based on different scenarios and risk profiles. All of those would have needed to be done in our own data center with tons and tons of servers," says Whitney. "Instead, Lambda and its serverless capacity help us answer those questions in milliseconds, and helps us achieve decision accuracy upwards of 99.9%. It's hugely efficient and cost-effective technology for us and our clients."

Fraud.net also uses Amazon Kinesis to process and analyze streaming data in real-time to give customers results based on the latest and most comprehensive data. Amazon Redshift is their data warehouse, which they use to conduct data analytics on incoming events, transactions, and more.

> **"AWS helps us process thousands of transactions per second, at a scale that was virtually impossible three or four years ago."** — Whitney Anderson

## Going Serverless for Scale and Speed

Whitney credits AWS serverless technology as a critical component in Fraud.net's mission to make every digital transaction safe. "In the past, providing a unified suite of microservices to fight fraud is something that hadn't been done, or certainly hadn't been done effectively," explains Whitney. "With some of the older siloed databases, it wasn't even possible to do."

"Serverless is also unbelievably quick and easy, relative to the old days with on-premise software when a bank could expect it to take six months to a year to integrate a system," says Whitney. Fraud.net accomplishes most of their customer onboarding with a simple set of no-code tools that leverage a suite of APIs to onboard a bank or fintech within 30 days, including the planning and training time.

> **"Because it's so cost-effective, we're 99% serverless."** — Whitney Anderson

Fraud.net offers one of their serverless products, Transaction AI—a transaction monitoring, fraud prevention, and revenue enhancement platform—on the [AWS Marketplace](https://aws.amazon.com/marketplace/pp/prodview-ojxruzi5mf7yi).

## Gaining Actionable Insights Using Machine Learning

Fraud.net uses Amazon SageMaker to create, train, and deploy the machine learning models that provide their customers with an average of an 80% reduction in fraud cases, a 92% reduction in false positives, and a 30% increase in approvals for good customers that were erroneously flagged as high-risk.

Machine learning allows Fraud.net to provide banks and fintechs with answers in under a second that otherwise may have taken employees hours of time-consuming tasks, such as manually cross-checking client information. Whitney explains, "AWS technology as a baseline, with Fraud.net's software layer on top, enables teams to be much more efficient and spend their time more wisely."

> **"The underlying technology, along with Amazon's pricing, enables us to ask about 20,000 questions about identities and behaviors every time we receive a new account application or transaction. All of that gets handed off to machine learning. We now routinely build clients custom ML risk models, with several hundred million features as inputs, because AWS has made it so relatively inexpensive to do."** — Whitney Anderson

## Teaming Up with AWS to Provide Value to Their Customers

Alongside the AWS technology that Fraud.net uses to give their customers rapid and accurate tools to fight fraud, they also work with AWS to optimize customer costs. Whitney explains, "Our customer's average return on investment (ROI) using Fraud.net is over 700%. That's largely due to AWS' efficiencies in cost structure. We leverage that and offer an incredible value to any company that uses Fraud.net."

Fraud.net also collaborates with AWS teams in retail payments, financial crime, and other teams to give their clients a safe and effective onboarding experience. "We get a lot of support from various AWS teams," says Whitney. "This is often a client's first interaction with the cloud environment. Some of our big financial services clients come from on-premises environments, and they specifically come to us because we prove out a super-strong ROI from using their first cloud-based project."

## Looking to the Future of Fighting Fraud

As a global fraud prevention management system, Fraud.net is, "all about scale at this point," says Whitney. With clients ranging from top-tier financial institutions all the way down to early-stage fintech startups, and across industries such as financial, e-commerce, travel, and more, Fraud.net's goal is to be the preeminent fraud and risk management layer for all digital enterprises.

For other founders looking to build a successful startup, Whitney advises three things that make a good entrepreneur:

1. Know an industry really well, see the gaps, and envision a better future for that industry.
2. Be a problem solver who gets excited about the prospect of fixing the problems that you see.
3. Have a deep reserve of energy and enthusiasm to get you through the good times and the bad.

For fintech startups in particular, Whitney advises that the upcoming FedNow Service launch in 2023 is likely to, "present a huge new set of risks and a need for risk to be solved immediately." The FedNow Service is a real-time payments network that will allow money to transfer in seconds instead of in days.

With this advance in payments technology, Whitney expects to see an enormous amount of beneficial innovation on AWS and in the fintech world as technology ramps up to outpace fraudsters.

> **"It returns back to simple trust enablement. For banks and companies, it's about restoring trust in your relationships with customers thousands of miles away that you'll never meet."** — Whitney Anderson

---

Curious about how AWS can help kick start your startup? Join [AWS Activate](https://aws.amazon.com/activate/) to build and scale your startup with the right resources at the right time.

## Related Fintech Startups Building on AWS

- [Building serverless on AWS to scale Ramp's fast-growing finance automation platform](https://aws.amazon.com/blogs/startups/building-serverless-on-aws-to-scale-ramps-fast-growing-finance-automation-platform/)
- [Alloy's global identity decisioning platform, built on AWS](https://aws.amazon.com/blogs/startups/alloys-global-identity-decisioning-platform-built-on-aws/)
- [How Gallus Insights builds on AWS to provide customers with tactical and strategic insights](https://aws.amazon.com/blogs/startups/celebrating-hispanic-heritage-month-with-hispanic-startup-founders-on-aws-part-2/)

---

**Author:** Megan Crowley\
_Megan Crowley is a Senior Technical Writer on the Startup Content Team at AWS. With an earlier career as a high school English teacher, she is driven by a relentless enthusiasm for contributing to content that is equal parts educational and inspirational. Sharing startups' stories with the world is the most rewarding part of her role at AWS._

---

_Source: [AWS Startups](https://startups.aws/startups/learn/how-machine-learning-helps-fraud-net-to-build-a-modern-app-on-aws-to-combat-financial-fraud)_
