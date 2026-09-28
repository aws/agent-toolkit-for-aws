---
source_url: https://aws.amazon.com/startups/learn/evolutionary-architectures-series-part-3
title: "Evolutionary Architectures Series: Part 3"
---

## Evolutionary Architectures Series: Part 3

> _"To the moon 🚀"_

"Evolutionary Architectures" is a four-part blog series that shows how solution designs and decisions evolve as companies go through the different stages of the startups lifecycle. In this series, we follow the aptly named Example Startup whose idea is to create a "fantasy stock market" application, similar to fantasy sports leagues. They envision holding four "tournaments" over the course of a year.

The second blog described how the startup started evolving their technical solutions while the founders were getting ready for fund raising. In part 3, we will see how Example Startup further progresses in maturing their tech stack and positioning themselves well for scale.

![Building a scalable tech stack is an iterative process for startups.](https://d22k7geae6sy8h.cloudfront.net/files/649dd56e371e0200080f5e9b/8ljhijr0v-AdobeStock_206672534.jpg)

## Scaling efficiently by transitioning to a microservices architecture

The fantasy stock trading team is growing and new components and solutions are being built. As the technical portfolio expands, certain cracks begin to appear that required the team's attention.

"Old habits die hard," and the team begins to see how this can cause problems for their startup's growth: The aggressive timelines and the enthusiasm to get more done with less is leading to increasing technical debt. One aspect of this technical debt is a gradual proliferation of monoliths, as opposed to the microservice architecture that the team had initially decided upon. Monolith concerns such as scalability and performance bottlenecks begin to show during testing and the introduction of new features. Luckily, the team quickly recognizes the challenges this monolithic approach poses to the optimal scaling of workloads. They decide to take a step back and reevaluate their development practices. One of the developers remembers that the AWS solutions architect (SA) had anticipated some of these problems in an earlier conversation. The Example Startup team schedules a call with AWS to get some help.

Breaking down monoliths and transitioning into a microservices-based paradigm is a broad topic so the AWS SA recommends an App Modernization Immersion Day for the team at Example Startup. The immersion day uses a related [workshop](https://catalog.us-east-1.prod.workshops.aws/workshops/f2c0706c-7192-495f-853c-fd3341db265a/en-US) as a backdrop, with a focus on workloads relevant to startups. The event is attended by nearly all developers at the company and ends up being a game-changer. Over the course of a single day, the team is able to learn how to properly define, design, and implement microservices. They also learn about charting a gradual migration path from a monolith application to a set of microservices without having to redo everything at once. The team is glad to catch their mistakes early on and learn some best practices that will help them going forward. The solutions architect also shares an [AWS whitepaper](https://docs.aws.amazon.com/pdfs/whitepapers/latest/migration-modernization-strategy-for-ies/migration-modernization-strategy-for-ies.pdf) focused on modernization strategies that can fill in any knowledge gaps on the Example Startup team.

The experience with app modernization provides so much value to Example Startup that the team decides to apply the same approach of leveraging existing best practices for different functional areas going forward. The engineers and product manager schedule a call to share their roadmap for the remainder of the year with AWS, in an effort to avoid duplicative work. Example Startup already signed a mutual non-disclosure agreement (MNDA) with AWS and there was a productive free flow of ideas across both sides during this conversation, as well as some great news: It turns out that a feature Example Startup was considering building out themselves is already on AWS' roadmap for the next quarter, and this frees up a chunk of engineering time for the team.

The next topic on Example Startup's list of areas to improve relates to Infrastructure as Code (IaC), continuous integration and continuous delivery (CI/CD), and automated testing. Two newly hired developer operations (DevOps) folks aren't satisfied with many of the current operational mechanisms at the startup, especially things like building and testing environments, as well as managing code artifacts. A growing team at Example Startup means that more people have access to these sensitive processes, thereby introducing unnecessary risk. The two new team members already have some experience with [Terraform](https://www.terraform.io/) as their approach to IaC. They are happy to learn that AWS is well supported by Terraform, and to discover other tools like [AWS CloudFormation](https://aws.amazon.com/cloudformation/) and [AWS CDK](https://aws.amazon.com/cdk/) in case an alternative is needed. However, they still need some help with their CI/CD setup. Their attempts insofar lack cohesion and it proves difficult to make their build tool work well with their deployment tool. Additionally, they are still looking for a suitable approach to manage their container images. The AWS team recommends looking at [AWS CodePipeline](https://aws.amazon.com/codepipeline/) because it meets their needs for integrating a build and a deployment tool seamlessly and also includes automated testing, all paired with support for various environments. Using CodePipeline allows integration with solutions that weren't necessarily built natively on AWS, as well as robust support for other tools such as [AWS CodeBuild](https://aws.amazon.com/codebuild/), [AWS CodeDeploy](https://aws.amazon.com/codedeploy/) and third-party tooling. Implementing CodePipeline allows Example Startup to check off another big item of their list.

With the team well on its path to a proper implementation of microservices, they feel empowered to work on some of the other complex challenges that remain outstanding. For one, the presence of multiple services operating independently naturally brings up the question of communication across these services. There is a big question mark around whether every cross-service call should be synchronous or asynchronous in communication, in addition to how the team can begin adopting best-practices patterns such as publish/subscribe (PubSub) messaging. The team understands broadly that adopting an event-driven architecture would be beneficial, especially with the move away from monoliths, but they are a little overwhelmed with the endless array of AWS services related to that architecture, including but not limited to Amazon EventBridge, Amazon Simple Queue Service (Amazon SQS), Amazon Simple Notification Service (Amazon SNS), and Amazon Managed Streaming for Apache Kafka (Amazon MSK). This time around, the team is able to find some resources themselves as a great starting point such as some very useful workshops and blogs on the topic. The "event driven" paradigm is slowly becoming another tool in the team's toolbox.

## Developing a stronger security strategy

Security continued being top of mind for our startup and tools like the AWS Startup Security Baseline (AWS SSB) help them to get started. Unfortunately, you can never have too much security. The initial implementation of AWS WAF was a good start, but the team needs to start thinking more proactively about prevention, detection, and remediation. They begin upskilling themselves on the many AWS services focused on security that can help them implement a strong security strategy.

The growing team and the involvement of partners makes access control, permissions, and governance other topics requiring an increasing amount of focus. The team is trying to implement best practices such as the principle of least-privilege when applying permissions. At a minimum, they want to move the production workloads into their own, separate accounts. As the team adopts these best practices, they see the increase in operational complexity due to the added layers of management and permissions they are now having to deal with. It becomes rapidly obvious that they need a mechanized approach to account structure. Someone mentions AWS Organizations, which seems like a step in the right direction so they reach out to their trusty AWS SA for a chat. The SA shares some relevant advice, like looking at AWS Control Tower as an easier approach to managing multiple accounts and AWS Organizations. Since this is the first of many steps towards achieving a robust multi-account strategy, the AWS SA also shared with the team the "Transitioning to multiple AWS accounts" prescriptive guidance. This guide includes best practices around account migration, user management, networking, security, and architecture when moving to a multiple accounts setup.

## Optimizing workloads for performance

The team is tackling some foundational pieces so the startup will be well poised to grow at the right pace. A few major items are crossed off the list and others have action plans in place. The developers are doing as much as they can to optimize their workloads for performance, but have identified some opportunities for further improvement that go beyond code, such as edge caching with Amazon CloudFront, caching on an application level with Amazon ElastiCache and Database caching. The team is increasingly growing reliant on AWS Managed Services to give them the functionality they need while keeping the associated operational complexity at a minimum. Another managed service that some of the developers discover and find surprisingly easy to use is AWS Batch. The initial feed processing approach with AWS Lambda is starting to hit its limits due to the exponential increase in the volume of data that needs to be processed. After some experimentation, developers are able to chart a path to using AWS Batch that allows them to keep growing with relatively little increase in operational burden and while keeping costs low.

![The updated AWS architecture diagram for Example Startup](https://d22k7geae6sy8h.cloudfront.net/files/6532afa6b08801000805d928/8lnyujczv-8ljhikl40-Ev-Arch_arch-diagram-part-3.jpg)

## Proving their startup's value proposition

All this good work at Example Startup does not go unnoticed. Building in an agile-yet-sustainable manner without reliance on short-term workarounds shows that the company is thinking about the long term, displays maturity, and has the capability to deliver. These traits along–with an innovative solution and a good product market fit—are at the core of the company's value proposition. The founders successfully convey their company's value to couple of different venture capital firms and close their first Series A funding round. Example Startup is on its way to the moon.

Check out the first blog and second blog in the Evolutionary Architectures series.

---

## Authors

### Aayzed Tanweer

Aayzed is a Solutions Architect at AWS, working with startup customers in the FinTech space and with a special focus on analytics services. Originally hailing from Toronto, he recently moved to New York City, where he enjoys eating his way through the city and exploring its many peculiar nooks and crannies.

### Justin Plock

Justin is a Principal Solutions Architect at AWS, focused on fintech startups. He regularly meets with fintech founders to help ensure their business is secure and compliant with industry regulations. Prior to AWS, he was a Director of Cloud Enablement at a Fortune 200 insurance carrier and a Director of Engineering at a cybersecurity firm. He is passionate about helping startups develop securely and efficiently on AWS. He lives in Connecticut with his wife and two daughters.

### Zoran Nakev

Zoran is a Senior Solutions Architect at AWS, working primarily with FinTech startups and helping them to build solutions on AWS. He uses his experience and passion for technology to assist startups in delivering on their goals. He lives in New Jersey with his family and enjoys spending his free time watching movies, listening to music, and taking long walks with his family dog.
