---
source_url: https://aws.amazon.com/startups/learn/connectcarehero-uses-kiro-to-accelerate-development-and-help-people-in-senior-care-stay-connected-
title: "ConnectCareHero uses Kiro to accelerate development and help people in senior care stay connected"
---

## ConnectCareHero uses Kiro to accelerate development and help people in senior care stay connected

![ConnectCareHero team](https://d22k7geae6sy8h.cloudfront.net/files/6ac50a2aeda2b6000e1eb5d4/connectcarehero-team-group-photo.jpg)

[ConnectCareHero](https://connectcarehero.com/) is using agentic AI to help older adults stay engaged and socially connected. Built on AWS, the startup uses [Kiro](https://kiro.dev/) to help its lean engineering team develop and ship new capabilities faster. With Kiro, ConnectCareHero has reduced its engineering effort by 55 percent while simultaneously increasing the speed of development, accelerating projects by up to 70 percent.

---

In 2015, Osvaldo Montelongo made the decision to move his father, Abraham, who was suffering with advanced dementia, into a senior care facility. Immediately, he noticed a decline in his father’s condition. Abraham spoke only Spanish, meaning many of the facility’s employees couldn't communicate with him. And as staff changed frequently, he spent more and more time alone.

“That’s really when Osvaldo started to see his dad cognitively decline,” says Bob Lee III, CTO and Co-Founder at ConnectCareHero. “When people couldn't interact with him on a daily basis and when he was alone in his room without any interaction.”

This experience exposed Osvaldo to a broader problem: older adults can become isolated even when they’re surrounded by other people. Social isolation is associated with a 50 percent higher risk of developing dementia, highlighting the importance of connection as we age.

At the same time, care providers are under mounting pressure to deliver engaging experiences with limited staff capacity. 80 percent of senior living staff report critical burnout, making it increasingly important to find ways to boost engagement without adding to their mental load.

Osvaldo founded ConnectCareHero to address this challenge, helping care providers deliver better experiences for the people they look after. Today, ConnectCareHero has expanded across six states, reaching more than 10,000 older adults through senior care communities, home care organizations, and adult day centers. Its Telly platform delivers live and on-demand engagement experiences designed to help older adults stay active, connected, and engaged, while giving care teams scalable tools to support their communities.

More recently, ConnectCareHero has been exploring the potential of AI to make Telly’s experiences more interactive, including an AI-powered avatar that interacts with users through conversation and social activities like trivia.

### Moving fast with a lean team

Building new AI capabilities can be resource-intensive, particularly for a small startup with a lean engineering team. With one full-time developer and two part-time engineers, finding ways to make the development process more efficient was increasingly important.

Previously, large projects followed a lengthy development process. The team would build a project plan in Google Drive, hand it to a UI/UX specialist to create Figma designs, and then pass those designs to Lee to be built. Limited time for testing meant larger projects could still resemble traditional waterfall deployments, with significant code changes and few test cases.

The process could take months, and the team had limited capacity to test components and potential edge cases. “It was a long, grueling process that led to a complicated deploy at the end,” says Lee.

To help the team move quickly, ConnectCareHero turned to Kiro. The agentic AI development tool has become a critical part of Lee’s daily development process, helping him move from an initial idea to a detailed specification and, eventually, implementation. Lee uses Kiro’s spec-driven workflow to map out what he wants to build before writing any code. “I was able to go to Kiro, give it a use case, and then it was able to give me suggestions on what I could look into and what I could build,” he says.

The specifications can then be pushed into GitHub, where ConnectCareHero’s non-technical co-founders can review the proposed functionality before any code is written. This creates an opportunity to catch potential issues with the product or user experience much earlier in the process. “Before even a line of code is written, we can go back and forth, and so much time is saved,” says Lee.

Kiro can also work from the project documentation, design decisions, and infrastructure repositories that ConnectCareHero has built up over time. When the team needed to set up a Secure File Transfer Protocol (SFTP) server for an HR integration, for example, Lee could use Kiro to work from the company’s existing Terraform repository rather than starting his research from scratch.

For Tornu Ngwayah, Co-founder and CMO at ConnectCareHero, the benefits extend far beyond the engineering team. “Kiro has become one of those tools that quietly changes how a team works,” he says. “From a marketing perspective, I’ve seen it help us take ideas, turn them into organized projects and documentation, and collaborate more efficiently without creating a mountain of meetings and follow ups. And honestly, judging by the tech team’s screen time, Kiro may officially be one of our most reliable members of the team.”

### Faster development, greater human connection

For ConnectCareHero, Kiro’s impact is reflected in both the amount of engineering effort required and the pace at which the team can develop. Since adopting Kiro, the company has reduced its engineering effort by 55 percent, while continuing to develop and ship new capabilities. Lee estimates that some projects have been accelerated by as much as 70 percent. “It really has helped to save time and even increase velocity, which has been pretty impressive to see,” he says. “My team jokes that Kiro is a part of my engineering team as well. So, you know, it’s Bob and Kiro.”

Kiro doesn’t just enable ConnectCareHero to ship code faster. It also gives the team more scope to build functionality that directly supports its mission of helping older adults stay connected. One of ConnectCareHero’s planned functionalities will make it easier for older adults to connect with loved ones through the platform. Someone in a care facility in the US, for example, could connect with a family member overseas who can't visit regularly.

For Lee, Kiro’s app means work can continue even when he’s away from his desk. “One evening, while I was grilling chicken for my family, I was using the iOS app in order to keep the autonomous web agent going and working on the project,” explains Lee. “When I next opened up my laptop, I had three pull requests ready for me to look at and review.” As Lee puts it: “Everybody needs to eat dinner. And everybody needs to get work done.”

Kiro is also helping ConnectCareHero strengthen the product as it develops. Rather than focusing solely on writing new functionality, Lee uses Kiro to generate tests and add safeguards for existing capabilities. For a small engineering team, this provides an additional layer of confidence when preparing to ship. “It’s hardening what we already have,” says Lee. “And that helps me sleep a lot better at night.”

### Building the AI experience

With Kiro helping the team build and iterate more quickly, ConnectCareHero is continuing to develop the technology behind its AI avatar. ConnectCareHero built the first version of its avatar in partnership with [GoML](https://www.goml.io/), an AWS Partner, after a member of the AWS team connected the two companies. The project was also funded in part by AWS, helping the startup move from experimentation to a working MVP much faster. For Lee, the support was pivotal: “We would not have the AI avatar if it wasn't for the partner solution and the AWS Startups project that we were able to put together,” he says. “It would just be an idea that was on a piece of paper if it wasn't for AWS.”

The resulting technology is built entirely on AWS. ConnectCareHero uses [Amazon Bedrock](https://aws.amazon.com/bedrock/) for its AI capabilities, alongside [Amazon Elastic Container Service (Amazon ECS)](https://aws.amazon.com/ecs/) and [Amazon Elastic Compute Cloud (Amazon EC2)](https://aws.amazon.com/ec2/) to deploy and run its containerized applications, [Amazon Simple Storage Service (Amazon S3)](https://aws.amazon.com/s3/) for storage, and [Amazon DynamoDB](https://aws.amazon.com/dynamodb/) and [Amazon Relational Database Service (Amazon RDS)](https://aws.amazon.com/rds/) for data.

At the heart of the avatar tool is [Amazon Nova 2 Sonic](https://aws.amazon.com/nova/models/), which handles speech-to-speech interactions between older adults and the avatar. With 55 percent of older adults saying they want more culturally appropriate services, multilingual engagement is of growing importance for ConnectCareHero’s experience. While the first MVP was English-speaking, Nova 2 Sonic is now providing ConnectCareHero with a way to generate conversations in multiple languages. This next iteration is called Abraham, a tribute to Osvaldo’s father. “He's always been the inspiration for what we've been building here at ConnectCareHero,” Lee explains.

ConnectCareHero is also looking to make those interactions more personalized. The startup is integrated with PointClickCare, an electronic health record system used by senior care providers, which gives it access to information including a user’s primary and secondary languages. In the future, ConnectCareHero plans to use that information to automatically select the right language and provide the avatar with relevant background about the person it’s interacting with. This would enable an older adult to connect with Abraham in Spanish, for example, without a member of staff having to manually configure the experience.

### A partner for the startup journey

For ConnectCareHero, AWS has become more than the infrastructure underpinning its platform. It has been a source of technical expertise, resources, and connections that have helped the company turn ideas into products. “The support that I have felt from the startup team… gives me goosebumps,” says Lee. “I have felt so heard by the team and that's been incredible.”

That support has taken different forms as the company has grown, from [AWS Activate Credits](https://aws.amazon.com/startups/credits/) to the GoML partnership and, more recently, [Kiro Startup Credits](https://kiro.dev/startups/). “I likely would have tried Kiro even if I didn't have credits, but I would have had to start a conversation with my team and sell it to them,” Lee says. “Instead, with the credits, I could show them what Kiro can do and the power that it brings.”

### What’s next for ConnectCareHero

Looking ahead, ConnectCareHero is continuing to develop Abraham, with plans to expand its multilingual capabilities, develop new ways for users to connect with their families, and explore AI memory to make conversations more meaningful over time. As ConnectCareHero continues to scale, the goal is to make those interactions increasingly personal, helping older adults connect with the people, conversations, and experiences that matter most to them.
