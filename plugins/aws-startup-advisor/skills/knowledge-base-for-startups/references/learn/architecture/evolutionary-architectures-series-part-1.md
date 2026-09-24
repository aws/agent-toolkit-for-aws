---
source_url: https://aws.amazon.com/startups/learn/evolutionary-architectures-series-part-1
title: "Evolutionary architectures series: Part 1"
---

## Evolutionary architectures series: Part 1

_Discover the key steps of building a successful startup in the Evolutionary Architectures series. Dive into the process of delivering the first MVP and beyond!_

---

![A team evaluates an initial startup idea.](https://d22k7geae6sy8h.cloudfront.net/files/64a2e448db295100084079a6/8ljmzwka7-People-with-an-idea.jpg)

> _"I've got this great idea!"_

Every startup begins as an idea. Before you start worrying about funding or staff or distribution or any of the other myriad things, you have your fresh, new idea—a product or service that you think has potential.

If your idea will rely on the cloud, you'll need a cloud architecture. This blueprint will help usher your great idea into reality and, if built well, can evolve alongside your business as it grows.

To help you build a robust blueprint for your idea, this four-part series, Evolutionary Architectures, will show you how one company, the aptly named Example Startup, puts their idea into practice. In part 1, we'll see how they built a minimum viable product (MVP) to test customer interest and market fit. Later in the series, we'll look at how their designs and decisions evolve as they move through [startups lifecycle](https://www.investopedia.com/articles/personal-finance/102015/series-b-c-funding-what-it-all-means-and-how-it-works.asp) to deliver a fully-fledged, scalable, secure, highly available, and redundant solution.

## Delivering your first MVP

The first few product deliveries by a startup usually follow a phased approach. They're dictated by funding, time, resources, team size, and knowledge and experience.

In this stage it's extremely important to not let perfect get in the way of the good and to deliver simple but functional solutions. To do this, you'll need to know how to identify [1-way door and 2-way door decisions](https://www.inc.com/jeff-haden/amazon-founder-jeff-bezos-this-is-how-successful-people-make-such-smart-decisions.html), [fail fast and pivot when necessary](https://venturebeat.com/business/heres-what-fail-fast-really-means/), manage cost, and speed up time to market.

Let's check in on Example Startup and see how they approach this process.

### The idea

Example Startup's idea is to create a "fantasy stock market." They used fantasy sports leagues as a baseline and applied the idea of stock market investing. They envision holding four "tournaments" over the course of a year.

At the beginning of every quarter, a new cohort of investors starts with the same amount of funds. The fantasy stock market allows these investors to make their investment choices (based on companies and symbols from real stock markets) over the following 3 months. At the end of the quarter, participants are ranked and winners are announced.

### The preparation

To make their idea a reality, the two founders [bootstrapped](https://www.uschamber.com/co/start/startup/bootstrap-funding-pros-and-cons) their startup: they gathered their savings and borrowed money from friends and family.

One founder, an experienced developer, got 3 months leave from her job. This allows her to focus on the technical solution, which is helpful. However, it also defines the timeline for their first delivery.

Now, in just three months, she and her co-founder, who has a background in finance, must decide which features to include in the MVP and build their product. To get started, they decide on 1) what features are absolutely necessary for a usable product and 2) what features will allow them to measure market fit and customer interest.

![Stock market analysis for the product](https://d22k7geae6sy8h.cloudfront.net/files/64a2e469db295100084079a7/8ljmzx9r2-Stock-market-1.jpg)

They decide on the following:

- An import process for real-world stock market symbols/companies that investors can trade on
- Daily market prices feed
- Signup mechanism for users
- Portfolio management user interface (UI)
- Daily process for end-of-day portfolio calculations
- A daily process that calculates rankings

### The build

After defining their scope, it's time to make some technical decisions about which technologies and components the fantasy stock market needs. Then, they'll create an implementation plan with milestones for the MVP launch.

#### Framework

As a developer, one of Example Startup's founders has experience in [React](https://reactjs.org/), a JavaScript library for building user interfaces. Considering that a big portion of the MVP deliveries involve UI development, she thinks [AWS Amplify](https://aws.amazon.com/amplify/) looks like a great fit. With Amplify, the team gets built-in support for building and hosting React.js applications with lots of reusable components. Amplify can help with the backend as well—it can manage different databases like [Amazon DynamoDB](https://aws.amazon.com/dynamodb/), a great flexible option to start with, and it can use [AWS AppSync](https://aws.amazon.com/appsync/) to easily connect the front-end with data sources and develop the business logic.

#### Domain

With the framework taken care of, it's time to get a domain name. [Amazon Route 53](https://aws.amazon.com/route53/) helps Example Startup to configure a [DNS (Domain Name System)](https://aws.amazon.com/route53/what-is-dns/) service that has good integration with the services they were already using, as well as with the process of domain registration.

#### Experimentation and Cost Management

The team is able to meet most of their initial needs by simply picking an AWS service that aligns with their use case. The breadth of AWS services allows Example Startup to quickly experiment with multiple options and make decisions based on the experience.

Although many of the AWS services have a free tier, some of Example Startup's experimentation may be overly enthusiastic. When the first month's bill arrives, the team realizes that they need to pay more attention to cost. Like in many other cases, there is an AWS solution for that: they start using the free service [AWS Budgets](https://aws.amazon.com/aws-cost-management/aws-budgets/). It helps the team improve on their planning and cost management and define alerts that conveniently bring to their attention anything that might not align with their expectations.

![AWS Budgets sends budget alerts.](https://d22k7geae6sy8h.cloudfront.net/files/64a2e489db295100084079a8/8ljmzxyie-AWS-Budgets-1024x377.png)

#### Data

A month in, Example Startup already has a lot of the UI and some related features working with sample data. Next, they'll need batch processes that will do the heavy lifting with some real data.

After finding data sources to provide the information they need, the team wants to automatically ingest the data. Continuing with JavaScript as their programming language of choice, they want to run it with something that makes the operational aspect as simple as possible.

This leads them to [AWS Lambda](https://aws.amazon.com/lambda/). The team doesn't want to worry about operating servers and scaling, so they take a serverless approach, using the [Schedule AWS Lambda functions using EventBridge](https://docs.aws.amazon.com/eventbridge/latest/userguide/eb-run-lambda-schedule.html) tutorial.

With that, as shown in the initial architecture diagram, they have a design in place for the data-related services they need to run.

![Initial architecture diagram](https://d22k7geae6sy8h.cloudfront.net/files/64a2e5dddb295100084079a9/8ljn058he-Initial-architecture-diagram-1024x353.png)

#### Testing

The team is making great progress. Their architecture is growing, and they feel good about the 3-month deadline.

However, as the number of people testing the solution grows, they notice an issue. Someone on the team asked: "How many people are active users and what's the average number of transactions per user?" But they couldn't really come up with a meaningful answer. They agree on "winging it" by temporarily running queries directly on the [DynamoDB console](https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/ConsoleDynamoDB.html) and start a "wish list" for the next iteration.

### The launch

Example Startup made their deadline and launched the MVP. Before long, the team sees a huge list of registrations. They realize they are onto something, but they need help to improve their product and scale their business.

A friend of a friend mentions [AWS Activate](https://aws.amazon.com/activate/), a program that offers startups a number of benefits, including AWS credits, AWS support plan credits, and architecture guidance.

![The benefits of AWS Activate.](https://d22k7geae6sy8h.cloudfront.net/files/64a2e5ffdb295100084079aa/8ljn05yrf-Activate-Gif-2.gif)

They apply to AWS Activate to get the help they need for the next phase of their journey.

## Conclusion

A lot has happened with Example Startup in just a few months. During the process of delivering the first MVP, many startups face challenges that are similar to those that Example Startup overcame.

We will continue with their journey in upcoming blogs in the Evolutionary Architecture series. Learn how their needs, challenges, and goals change as the company builds and scales.

---

## Authors

### Zoran Nakev

Zoran is a Senior Solutions Architect at AWS, working primarily with FinTech startups and helping them to build solutions on AWS. He uses his experience and passion for technology to assist startups in delivering on their goals. He lives in New Jersey with his family and enjoys spending his free time watching movies, listening to music, and taking long walks with his family dog.

### Aayzed Tanweer

Aayzed is a Solutions Architect at AWS, working with startup customers in the FinTech space and with a special focus on analytics services. Originally hailing from Toronto, he recently moved to New York City, where he enjoys eating his way through the city and exploring its many peculiar nooks and crannies.

### Justin Plock

Justin is a Principal Solutions Architect at AWS, focused on fintech startups. He regularly meets with fintech founders to help ensure their business is secure and compliant with industry regulations. Prior to AWS, he was a Director of Cloud Enablement at a Fortune 200 insurance carrier and a Director of Engineering at a cybersecurity firm. He is passionate about helping startups develop securely and efficiently on AWS. He lives in Connecticut with his wife and two daughters.
