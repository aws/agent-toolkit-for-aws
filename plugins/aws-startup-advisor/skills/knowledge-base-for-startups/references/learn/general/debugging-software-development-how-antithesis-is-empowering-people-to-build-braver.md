---
source_url: https://aws.amazon.com/startups/learn/debugging-software-development-how-antithesis-is-empowering-people-to-build-braver
title: "Debugging Software Development: How Antithesis is Empowering People to Build Braver"
---

## Debugging Software Development: How Antithesis is Empowering People to Build Braver

> Source: [AWS Startups](https://startups.aws/startups/learn/debugging-software-development-how-antithesis-is-empowering-people-to-build-braver)

Software powers the critical infrastructure and services that we count on every day, from banks to airlines, emergency call centers, and much more. While this technology is integral to society, a single programming issue can create widespread disruption in the real world. This makes robust testing a non-negotiable step of software development.

The problem is, tracking down bugs is time-consuming, laborious, and unpredictable—especially in highly distributed systems. Even the most diligent developers often only discover bugs after software is released, because it's simply impossible to anticipate and test for every possible thing that could go wrong. As [Antithesis](https://antithesis.com/)'s Co-Founder and CEO Will Wilson says, "Most engineers report spending more than half their time testing, triaging, and fighting production fires." Not only does this stunt productivity, but it ultimately stops them building innovative solutions.

Determined to find a better way to catch bugs, Antithesis developed a platform for autonomous deterministic testing. The startup creates a digital twin of a customer's system in a simulation environment, then uses AI to explore every situation the system could encounter. This allows developers to discover even the unlikeliest—and most serious—problems before they're set free in the real world. "It functions like an incredible safety net. Having really powerful testing enables you to do things that you didn't even imagine you could do before," says Wilson. Leveraging AWS infrastructure, services, and support, Antithesis is now enabling developers to build without barriers and prevent production outages, security disasters, and customer data corruption.

## Tools to Tackle the "Unknown Unknowns"

Often the situations developers need to test against are the ones they never saw coming. Wilson describes these scenarios as the "unknown unknowns"—the unlikely scenarios that developers don't even think to test for. These hard-to-find bugs often slip past conventional tests, only to surface in production months later.

To stress-test software to its limits, Antithesis has designed its virtual world to be as hostile as possible. Wilson explains that it throws "every situation that you couldn't even dream up" at the software. It does this in a sandbox environment, rather than risking the potentially destructive testing live in production.

Unlike the real world, Antithesis's virtual world is also completely reproducible so that users can both identify and fix complex bugs. As Wilson says, "It's like you have a time machine. You can just go back with perfect fidelity and accuracy to figure out exactly what went wrong." And when the farthest edge-cases are discovered immediately, developers can debug while they still have full context on problems, rather than finding them months later, making debugging much faster.

Beyond fueling much more efficient and effective testing, Antithesis is helping customers rise above the consequences of traditional software testing practices. Wilson explains that "The hidden cost of bad software quality assurance is all the projects nobody is even attempting."

Rather than being held back by what would have previously seemed too risky, Antithesis's customers are free to focus on building exciting features for their customers. They can dare to do what they would never have done before and experiment with what previously seemed impossible. "You can try and make your code run faster by doing some dangerous refactor or performance optimization. It totally changes the way that you approach development, and it makes it more fun," Wilson adds.

## Managing Bursty Workloads with Bare Metal

Bringing its deterministic software testing platform to life was a highly technical challenge. The Antithesis platform is built around a deterministic hypervisor that's only possible on AWS bare metal, and Antithesis relies on managed services such as [Amazon S3](https://aws.amazon.com/s3/) for fully elastic cloud object storage and [AWS Lambda](https://aws.amazon.com/lambda/) for infrastructure management to scale.

The nature of Antithesis's workloads is highly unpredictable, with spikes where multiple customers want to test their software simultaneously and times when only a few are using its services. If the startup was managing this themselves, they would risk either buying too few machines and seeing queues and waiting lists at peak demand or overprovisioning with costly machines left sitting idle. AWS helps Antithesis navigate this challenge by offering accessible compute with convenient incremental pricing.

"AWS has enabled us to seamlessly scale as we've been growing very rapidly. We haven't had to go buy thousands of computers and rack them ourselves. We're able to just use common APIs and build our infrastructure as we need it," says Wilson. Leveraging bare metal instances through [Amazon EC2](https://aws.amazon.com/ec2/) ensures that it can provide customers with enough depth for their workloads, while flexible capacity provides a foundation for ongoing growth. "AWS is the only cloud provider that checks all those boxes," says Wilson. "Even if our business grows another ten times, or 100,000 times, we're still nowhere close to exhausting the computers that AWS has," he adds.

Having built something that already seems like science fiction to many developers, Antithesis is working to allow developers to test as fast as they can commit code. Central to this effort is a custom serverless database that the company has written on top of Amazon S3. "If we did not have Amazon S3, we would not have been able to write our own database," says Wilson. "It's like all these tricky parts of writing a database just sort of go away." Combined with the burst capability provided by AWS Lambda, this boosts performance and enables Antithesis to "deliver a whole new generation of improvements to our customers."

## Software Testing with a Built-in Safety Net

Antithesis's customers share their company's crown jewels on their platform, making security paramount. To maintain tight controls and prevent the risk of data leakage, each customer has its very own environment. "One of the great things about working with AWS is that we're able to very easily spin up a completely isolated, totally secure, dedicated set of infrastructure for every single customer, and that's really important," says Wilson.

Bolstering trust with security conscious customers is also made easier by hosting workloads in AWS data centers. As Wilson notes, "It's so nice to be able to say that our workloads are running in data centers that are known as the most secure on planet Earth. All the questions customers have about physical security are just automatically taken care of." As Antithesis continues its rapid growth journey, it's exploring new ways to expand reach and simplify how customers access their services.

## Partnering to Empower More Customers to Push Boundaries

From day one, Antithesis tapped into deep technical expertise from AWS to help it overcome complex challenges. "Even in our early days, we got connected to a human being who could answer our questions immediately," says Wilson. Beyond building its unique software on AWS and leveraging a breadth of services and support, the startup is now taking advantage of co-selling and co-marketing opportunities to help it scale.

Antithesis is in the process of listing on the [AWS Marketplace](https://aws.amazon.com/marketplace) and joining the [AWS Partner Network (APN)](https://aws.amazon.com/partners/). Wilson is optimistic about the strengthening relationship, describing it as a "very natural partnership" with a strong customer synergy. AWS customers often have a wealth of microservices and cloud heavy workloads which makes for "excellent Antithesis customers."

Participating in these initiatives requires Antithesis to undergo technical and security reviews. Wilson says that having this "AWS stamp of approval" not only appeases customers' security concerns, but it facilitates a faster route to offering a virtual private cloud for those seeking the solution on their own infrastructure. "What we can do is just deploy into their Amazon Virtual Private Cloud, which is a much lower lift for us and also much easier for them," explains Wilson. Working together, customers across different industries will feel confident that they can build cutting-edge proof-of-concepts while also keeping their data safe.

## Getting Developers Ready for the AI Revolution

Looking ahead, Antithesis anticipates a growing need to streamline testing as developers increasingly rely on generative AI to write code faster and scale software production. "It's going to speed up a lot of simple development tasks which is really great. But when it comes to code that really, really needs to function correctly all the time in the real world, it creates a whole set of issues."

"We're really excited to be working with AWS because it's at the forefront of solving these issues of how to verify and validate AI-generated code," says Wilson. Central to this is the ability for developers to test without slowing down, which means relying on AWS and their new database to boost platform performance. "We're going to be able to start offering people answers to the question 'does my software work?' in real time," explains Wilson.

Excited to quickly feed into developers' iteration loops and empower them to build braver than ever before, Wilson says: "Being able to show developers results in real time is going to make this way cooler, easier to sell, and better in every way. I think people will love it."

---

_Related: [Learn](/startups/learn)_
