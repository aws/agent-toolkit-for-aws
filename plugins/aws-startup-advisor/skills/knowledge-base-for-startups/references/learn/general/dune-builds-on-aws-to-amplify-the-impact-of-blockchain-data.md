---
source_url: https://aws.amazon.com/startups/learn/dune-builds-on-aws-to-amplify-the-impact-of-blockchain-data
title: "Dune builds on AWS to amplify the impact of blockchain data"
---

## Dune builds on AWS to amplify the impact of blockchain data

By migrating from their multi-cloud setup to go all-in on AWS, Dune significantly lowered their costs while optimizing their ability to build and scale.

---

Startups are often founded by fearless individuals who face a problem and—instead of being deterred—set out to solve it for themselves and for everyone else.

[Dune](https://dune.com/home), a web3 analytics [unicorn](https://dune.com/blog/started-from-the-bottom) founded in 2018, is one such startup. While building Ethereum prototypes on the blockchain, co-founders Fredrik Haga and Mats Olsen recognized that disparate sources of crypto data are a major impediment to web3 development. Mats, who is also Dune's chief technology officer (CTO), explains: "While building, one of our biggest pain points was getting structured information back from the blockchain. It's a database that's optimized for writing, but not for reading."

Dune is proving it's possible to simplify the consolidation and analysis of blockchain data. Dune builds on Amazon Web Services (AWS) to provide a web-based platform that allows people to query public blockchain data and aggregate it into shareable dashboards. Users can take cross-chain data (data from separate blockchains) for multiple [tokens, wallets, and protocols](https://www.coinbase.com/cloud/discover/dev-foundations/networks-protocols-tokens-coins) and build a dashboard that makes the data more transparent and actionable.

In the beginning, Dune focused on taking crypto data and making it easily available and accessible to other web3 developers. As Mats explains, "Startups in the space had to duplicate a lot of work and engineering hours just to ask questions like, 'How many users do I have?'" As Dune went to market with a product that made crypto data easier to understand and use, they began adding visualization and dashboarding elements to their platform to make the data even more actionable.

> "In crypto, a lot of people say that the data is available and you can just look at it. It's true that the data is available, but Dune makes it practical to use it," says Mats. "I'm proud of the transparency and accessibility we've brought into this space."

Today, Dune is known for dashboards created by community members that are shared virally across social media, crypto news websites, and on [Dune itself](https://dune.com/browse/dashboards). "One of the most interesting aspects of the crypto space is the viral aspect of it," Mats says. "There's a so-called stakeholder explosion happening where public blockchain usage data is valuable to the product owners, but also to its investors, competitors, and regulators. It's an interesting phenomenon."

## Building and scaling by migrating to AWS

As Dune's user base expanded and their technical needs grew, Mats and team decided that it was time to migrate to an all-in-one cloud provider from their multi-cloud setup. Dune chose to go all-in on AWS.

One of Dune's primary reasons for migrating was to host workloads in a single location with services that could meet both their present and future needs. Mats explains, "The fact that AWS has such a wide range of offerings was really important for us. AWS does services really well—like [Amazon DynamoDB](https://aws.amazon.com/dynamodb/), for instance. We don't use it a whole lot right now, but it's in our future plans."

Along with offering over [200 fully featured services](https://aws.amazon.com/what-is-aws/#:~:text=computing%20with%20AWS-,Amazon%20Web%20Services%20(AWS)%20is%20the%20world's%20most%20comprehensive%20and,services%20from%20data%20centers%20globally.)—more than any other cloud provider—AWS is the most broadly adopted cloud. Like most startups, Dune wants their engineers to be able to innovate and build as quickly as possible.

> "AWS is so well-known and so prolific in the engineering landscape. It's easy because most of our engineers have used it before. There's no ramp-up time and that is really helpful," says Mats.

Dune leveraged the [AWS Migration Acceleration Program (MAP)](https://aws.amazon.com/migration-acceleration-program/) and [AWS Activate](https://aws.amazon.com/activate/) to migrate to AWS. Credits helped Dune migrate to AWS with no costs in the first three months.

Today, Dune's tech stack includes [Amazon Simple Storage Service (Amazon S3)](https://aws.amazon.com/s3/)—object storage that allows any amount of data to be retrieved from anywhere–to host the enormous amounts of data that contribute to their dashboards. To process this data, Dune uses Apache Spark and then queries the data with Trino. They also run a lot of Kubernetes clusters, which is why most of Dune's applications use [Amazon Elastic Kubernetes Service (Amazon EKS)](https://aws.amazon.com/eks/). To implement secure and scalable customer identity and access management, Dune uses [Amazon Cognito](https://aws.amazon.com/cognito/).

By building on AWS, Dune gets support from the AWS Startups team for everything from infrastructure and optimization, to go-to-market and networking. "We've always been very happy with the help we've gotten from AWS," says Mats. "It's nice to know the support is there for us, be that with the solutions architects or commercial opportunities."

## Focusing more on product and less on spend

Dune is all about the data, including when it comes to their cloud costs: "The biggest thing for us is understanding where we spend money and how much value that adds for our customers," says Mats.

To reduce cloud costs and make the most of their spending, Dune worked with their [account team](/startups/learn/meet-your-aws-account-team) to choose options that made the most financial sense for their technical needs. These include [AWS Graviton](https://aws.amazon.com/ec2/graviton/) processors and [Karpenter](https://karpenter.sh/), an open-source Kubernetes cluster autoscaler.

Additionally, Dune was able to save 26% on their [Amazon EC2 Reserved Instances](https://aws.amazon.com/ec2/pricing/reserved-instances/) (when compared to on-demand usage). They accomplished this by automating the purchasing of these instances with [Zesty](https://aws.amazon.com/marketplace/seller-profile?id=87c6edf2-bb6d-404e-9fa5-38143934f082) and by using [Savings Plans](https://aws.amazon.com/savingsplans/), which is a flexible pricing model for AWS compute usage. Mats also notes that, "[Spot Instances](https://aws.amazon.com/ec2/spot/) have also been a big part of our strategy to reduce cloud costs because they help with our high Kubernetes use."

AWS Activate—a program that offers startups free tools, resources, and more—are also a key to Dune's ability to focus less on spend and more on product. "The credits were incredibly helpful for us to worry less about optimizing our cloud workloads," says Mats. With the credits they received from AWS Activate, Dune was able to provide their customers with a better product and increase innovation.

> "What the credits most importantly allowed us to do was focus on product market fit. To focus on improving our products for our users' needs, instead of worrying about managing spend," Mats explains. "Credits lowered the barrier to trying out and experimenting with new products because we didn't immediately have a bill for them, so to speak."

## Lessons for founding a successful startup

As Dune showed with their use of AWS Activate credits, building products that solve a problem for your customer is rule number one. Mat explains, "The only thing that matters are your users. If you don't have any, find some." The best way to do this is to find a problem and solve it for yourself, as well as the people in that space. He advises that listening to your customers is equally important, as is balancing their feedback with the long-term vision that you have for your product.

Founding a successful startup is not an easy process. "Most startups die because you give up," advises Mats. "You have to stay in the game if you want to win." He recounts how in the early days, Dune's team members worked for nearly a year without a salary, they had only three customers, and at one point the company was weeks away from closing their doors. They didn't give up, though, and an investment came through that allowed Dune to keep building and growing.

## BUIDLing the future of web3 together

Dune's first five years were an exciting time. Alongside supporting the data needs during two major consumer waves in crypto—DeFi (decentralized finance) and NFTs (non-fungible tokens)—Dune simultaneously scaled from an idea to a unicorn in only three years. Now, says Mats, the time has come for technology to be "more important than ever" in contributing to web3 innovation, currencies, and how people store value.

Dune plans to rise to the occasion. With more than 40 employees, they have the capacity to incorporate new features to make crypto data even more accessible to their users. "The ability to scale compute on our backend to meet our users' needs is important," says Mats. "We're investing a lot in making autoscaling provide an even better customer experience."

What else does the future hold? "What I'm most excited about is generative AI," shares Mats. "In June, I began leading an initiative to experiment with how large language models can allow users to interact with our database without using SQL." The ability to generate SQL queries from natural language text, known as text-to-SQL, will lower Dune's barrier to entry: This will allow users who do not know how to write and run SQL to interact with their database.

Generative AI is a new lever that can help to democratize web3 by allowing more people than ever before to aggregate and visualize cross-chain data. "When we're ready to experiment with open source large language models, hosting them and fine-tuning them on AWS makes the most sense for us," says Mats.

Whether it's optimizing their tech stack with the help of AWS, building new products, or innovating with technological advancements—Mats knows the Dune team is ready to tackle all opportunities the future brings.

> "What sets us apart from a lot of other companies is our ability to take technology and modify it to our needs. We're not afraid to use open source tooling and we're happy to get deep into the weeds. All of this leads to a better user experience," Mats says.

---

## About the Author

### Megan Crowley

Megan Crowley is a Senior Technical Writer on the Startup Content Team at AWS. With an earlier career as a high school English teacher, she is driven by a relentless enthusiasm for contributing to content that is equal parts educational and inspirational. Sharing startups' stories with the world is the most rewarding part of her role at AWS. In her spare time, Megan can be found woodworking, in the garden, and at antique markets.
