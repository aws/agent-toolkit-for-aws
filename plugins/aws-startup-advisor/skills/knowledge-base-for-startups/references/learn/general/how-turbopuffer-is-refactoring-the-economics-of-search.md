---
source_url: https://aws.amazon.com/startups/learn/how-turbopuffer-is-refactoring-the-economics-of-search
title: "How turbopuffer is refactoring the economics of search"
---

## How turbopuffer is refactoring the economics of search

> turbopuffer makes high recall, low-latency semantic search accessible—helping customers search more data, improve search quality, and save millions.

![turbopuffer](https://d22k7geae6sy8h.cloudfront.net/files/6932bdd4a58e50000bf6a91f/Luxid_2025_Q4_SUP_turbopuffer_ThumbnailImage.jpg)

Semantic search plays a key role in forging connections between businesses and customers. Unlike traditional full-text search, it interprets the context behind a search to make digital interactions more intuitive, relevant, and personalized. Where a traditional search for "red dress", for example, would restrict results to the exact words being used, semantic search can return meaningful products and content beyond the bounds of keywords. This includes those that are related and relevant to the query, such as items described as "burgundy dress" or "red evening gown".

Until recently, the sheer cost of storing and searching the data volumes needed for successful semantic search has stopped many from realizing its full benefits for their most important use cases. It's a challenge compounded by the explosion of large language models (LLM) use and the demand for high recall, low latency, agent-initiated search across documents, code bases, and websites. Witnessing this problem firsthand in his former role as Principal Engineer at Shopify and as a consultant helping companies scale their infrastructure, Simon Hørup Eskildsen obsessed over finding a solution. His intuition—and some napkin math—suggested that a fundamental shift in architecture could transform the economics of search dramatically.

Since then, Eskildsen and Justine Li co-founded [turbopuffer](https://turbopuffer.com/) to make high recall, low-latency semantic search accessible—helping customers search more data, improve search quality, and save millions. By building the database on top of object storage in [Amazon S3](https://aws.amazon.com/s3/), and leveraging AWS services such as [Amazon EKS](https://aws.amazon.com/eks/), and [Amazon EC2](https://aws.amazon.com/ec2/), the startup has fundamentally changed how companies like Cursor, Notion, and Linear implement search at scale.

## Making data searchable at scale

Whereas previous solutions used in-memory indexing or storage tiering, turbopuffer's semantic search engine cuts costs 10 times or more by fully leveraging an object storage native architecture. The object store is the source of truth while warm data can be cached in memory. Just as a puffer fish can inflate and deflate on demand, the business was so named because of its ability to puff up (or scale) a caching layer—with 'turbo' emphasizing the speed and efficiency of the algorithm.

Before this new approach, organizations had to pick and choose which data to search, limiting their product ambitions due to the high cost of storing vectors and a limited return on investment. Roko Kruze, Solutions Engineer at turbopuffer, explains that its mission is to "reduce the overall cost of storing and searching data, so people don't have to make that trade off." Many of turbopuffer's customers see improvements of over 20 percent in search quality. The impact is significant—better user experiences, higher satisfaction, and increased user loyalty.

turbopuffer's goal is to make every byte searchable. By separating compute and storage and using object storage, it can achieve a level of scalability that would otherwise be cost prohibitive with traditional vector database solutions. "We're allowing people to query over 100 billion vectors, and this is pretty much indexing the whole World Wide Web," explains Kruze. While it works with businesses like Notion who have millions of customers and over 10 billion vectors in production, turbopuffer is able to partition all of that data based on a given customer. "This is something we can pretty much do for free because of the way we're built on top of Amazon S3," says Kruze.

## Working hand-in-hand with AI

Beyond boosting scalability and search quality, turbopuffer is proving to be a powerful tool for AI workflows. The startup is seeing huge success in this area because LLMs are increasingly used to semantically search code bases, documents, and websites to generate better responses. This scale of AI-driven search workloads is orders of magnitude higher than in the past, and turbopuffer is uniquely built to solve it.

Many customers are taking advantage of turbopuffer for agentic AI workflows to help ensure that the information being fed to the LLM is specific, relevant, and high quality. "Some people will try to put as much data as possible into the context window and hope for the best," explains Kruze. "turbopuffer improves the overall performance of LLMs because it's less data that has to be parsed and we make that data very easily accessible to agentic systems," he adds.

Now serving over 500 customers, turbopuffer is supporting both small organizations and large enterprises including Cursor and Grammarly. The startup also takes the complexity out of search by offering its product as a managed service. With no need to handle underlying operations, customers can focus on building their applications.

## A partnership powering growth and efficiency

Close collaboration with AWS has helped turbopuffer both build a faster, more reliable database and connect with more customers. Kruze notes that "you go to where your customers are, and many are on AWS." The business participated in the [AWS Migration Acceleration Program (MAP)](https://aws.amazon.com/migration-acceleration-program/) to migrate its core infrastructure within just a few weeks, benefiting from AWS credits and specialist support on optimizing software for AWS deployment. As Kruze says, "AWS MAP bootstrapped our AWS offering, which is now used by over 200 customers." Running on AWS means that the business can reliably offer its product across the globe, thanks to a broad spread of AWS Regions.

Access to expertise and object storage services has also proved particularly valuable. By teaming up with Amazon S3 experts, turbopuffer has had the opportunity to shape major design features and implement them early on to enhance its solution. For example, Amazon S3's compare-and-swap feature allows turbopuffer to provide strongly consistent semantics—a table stakes feature for any serious database—without bringing in a dependency on another service. Historically, strong consistency required an additional dependency on a transactional database (e.g., Amazon RDS or Amazon DynamoDB), which adds a good deal of operational overhead. As Eskildsen says, "The S3 team have been great partners in providing access to beta features and soliciting API feedback to help make turbopuffer the first database at scale running exclusively on object storage."

As a small company of less than 20 people, balancing cost efficiency without compromising performance is key. To achieve this, turbopuffer is also using Amazon EC2 for secure and resizable compute and Amazon EKS to build, run, and scale Kubernetes applications together with [Karpenter](https://docs.aws.amazon.com/eks/latest/best-practices/karpenter.html). Commenting on the benefits, Kruze says, "Using EKS and Karpenter has allowed us the flexibility to optimize our compute costs across multiple instance classes with little effort. This has saved us countless hours of configuration and lets us provide the best performance possible to our customers at the best cost point."

## Seeking more avenues for search excellence

To build trust with a broad customer base, turbopuffer has proven its ability to meet businesses' strict security and data privacy policies. Kruze shares that customer managed encryption keys (CMEK) together with private connectivity through [AWS PrivateLink](https://aws.amazon.com/privatelink/) have been "a huge win." He adds that these security features mean turbopuffer can "onboard customers that just wouldn't be possible otherwise."

Looking ahead, turbopuffer plans to go after more—and even larger—search workloads. As Kruze says, "the next step is to open up more opportunities in the enterprise space, and we hope that AWS helps us throughout that journey." turbopuffer is in the process joining [AWS Marketplace](https://aws.amazon.com/marketplace) to increase reach and simplify the acquisition of its products. Meanwhile, it continues to build exposure by attending high-profile events such as [AWS re:Invent](https://reinvent.awsevents.com/).

As part of its expansion goals, the startup is also growing its reputation beyond vector search capabilities. "We are seeing more and more people become interested in our full-text search solution, and we really just want to become the default search platform for everybody," says Kruze. Currently hosting over one trillion documents and serving over ten thousand queries per second, turbopuffer is ready to take on more workloads and become the most scalable and reliable search engine in the world.

Many startups hold similarly bold ambitions, and they're on their way to achieving them with support from AWS. More than 350,000 startups around the world have joined [AWS Activate](https://aws.amazon.com/activate/activate-landing/) since its inception in 2013, accessing resources, personalized guidance, technical assistance, AWS Credits and more. Designed for founders and geared towards growth, AWS Activate helps startups build, launch and scale on AWS. Find out more and join today.

---

_Source: [AWS Startups](https://startups.aws/startups/learn/how-turbopuffer-is-refactoring-the-economics-of-search)_
