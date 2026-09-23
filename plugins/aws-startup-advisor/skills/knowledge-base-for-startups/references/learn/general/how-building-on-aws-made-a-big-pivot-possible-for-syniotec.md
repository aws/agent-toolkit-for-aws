---
source_url: https://aws.amazon.com/startups/learn/how-building-on-aws-made-a-big-pivot-possible-for-syniotec
title: "How building on AWS made a big pivot possible for syniotec"
---

## How building on AWS made a big pivot possible for syniotec

_syniotec aspired to be "the Airbnb" of construction rentals." Feedback from their customers gave them a better idea. Learn how a pivot to microservices made it possible._

---

A few months after syniotec launched its first product, the team realized they had a problem. The Germany-based startup was ready to revolutionize the construction industry by becoming the Airbnb of construction rentals. They wanted to help machinery owners around the world optimize efficiency by renting out their equipment that wasn't currently in use.

As it turned out, their product was ready—but their customers were not. Co-founder and Chief Operating Officer Rezi Chikviladze fielded early feedback from construction clients who were excited about the possibilities of the service, but saw it as too futuristic for an industry not known for its digitization.

"We don't know where our machines are, how our machines are planned, whether the construction site managers need those machines," was the refrain Rezi kept hearing from potential customers.

From there, syniotec went on to find out that not only did potential customers not have tracking devices on their assets, but many lacked the digital infrastructure to implement a software solution in the relevant working areas. It wasn't uncommon for Rezi to chat with construction companies who used old systems like Excel-based lists to dispatch equipment to job sites.

Customers may have been eager about the cost saving potential of renting out their unused assets, but they simply did not have the systems or processes to accommodate syniotec's idea. The company came to a new conclusion: Before becoming the Airbnb of machinery rentals, they had to build the basis that would help construction companies into a new era of digitization.

## Building a new foundation

After that, syniotec began evaluating the most urgent problems construction companies needed to solve. They heard from potential customers who were managing as many as 200,000 pieces of equipment in more than 25 countries.

These giant companies had no centralized system to manage their fleets, keep up with complex scheduling issues, and track maintenance and compliance checks. It wasn't uncommon for companies to completely lose track of entire pieces of equipment, or be unequipped to optimize their fleet's usage.

"The difference between planning and real usage on the construction site is huge," said Rezi. "And at other times, machines are standing there on the site not utilized, and this is of course a financial loss for the company."

Those losses can make a huge dent in a company's reputation—and can add up quickly. So, syniotec customers were eager for solutions that optimized costs by even a small percentage, since that still had the potential to make a giant impact on bottom lines.

## Introducing SAM

syniotec packaged their solution as a Smart Asset Manager they dubbed SAM. SAM is a web and mobile app designed to manage all the moving parts of fleet management in one, centralized location. Construction companies can use SAM to dispatch construction equipment to proper locations, track where any piece of equipment is and monitor its usage or inactivity, more accurately plan equipment scheduling and manage machinery transport.

A drastic reduction in dispatch call times has been one feature of SAM that excites customers, says Rezi. Previously, when calls came in to request for a certain machine at a construction site, it could take the dispatchers a lot of time to sort through paperwork or slow systems in order to correctly assign out a piece of equipment to a site. But now, dispatchers utilizing SAM have been able to decrease the average call from 30 minutes to just three.

Regulatory and technical checks are also more efficient with SAM. Rather than tedious equipment checks and mountains of paperwork, customers can simply scan their machine with their phone and upload and store the relevant data to their AWS profile.

SAM can even work as a people manager. The unified system makes it easier for companies to calculate hours worked on site, acting as a type of enterprise resource planning (ERP) platform that helps to cut costs and reduce the time it previously took to manage payment calculations.

Additionally, syniotec is leveraging Internet of Things (IoT) capabilities to help construction companies have constant eyes on their equipment, no matter where it is located worldwide. By using the IoT via a small electronic device, companies can easily collect data on every operating aspect of their fleet.

Details like current voltage and the hours worked at specific sites can give companies the tools they need to stay on top of routine maintenance, be prepared for compliance checks, and ultimately save tons of money making sure each piece of equipment is operating at its top capacity. Thanks to the newly acquired IoT data, one customer was even able to finally track down equipment that had been stolen—right down to the garage where it sat—helping the police to find stolen goods worth more than €300,000.

## Migration from monolith

syniotec's pivot wasn't only a transformation on the business side—it also meant a complete overhaul of the technical infrastructure that powered their product. The company's original rental facilitator idea could have been served by monolith architecture. But as they transformed their business and began offering a far wider variety of services to their customers, syniotec recognized the need to switch to a microservices architecture that could offer greater agility and scalability.

The pivot was only possible with AWS, Rezi says. Building elsewhere "would have cost us a huge amount of resources to make such a huge change fundamentally." But since they had used AWS for their monolith, already had the support of the AWS team, and could choose from such a large portfolio of offerings, syniotec could transition with ease.

Newly situated on [Amazon Elastic Kubernetes Service (Amazon EKS)](https://aws.amazon.com/eks/), syniotec was far better positioned for reliable scaling. With the Kubernetes auto scaling group and [Amazon CloudWatch](https://aws.amazon.com/cloudwatch/), the team's developers could better observe their microservices' behavior, ensuring a more transparent and efficient process.

![Syniotec EKS Infrastructure](https://d22k7geae6sy8h.cloudfront.net/files/649c87c9314172000843e6a6/8ljg3p1xh-syniotec-EKS-infrastructure.jpg)

In doing so, they could also be more on top of any system issues, and hoped to minimize their response and resolution times. They considered configuring elastic search on their own, but found that using [Amazon OpenSearch Service](https://aws.amazon.com/opensearch-service/) allowed them to save tons of time and resources. Plus, using OpenSearch Service gave them the peace of mind that their critical operational data was backed by the AWS commitment to security.

That commitment to security is also on display with syniotec's backend services. By using a Amazon Virtual Private Cloud (Amazon VPC) link and an [Elastic Load Balancing (ELB)](https://aws.amazon.com/elasticloadbalancing/) Network Load Balancer, AWS connects the company's backend services in a private network only accessible via [Amazon API Gateway](https://aws.amazon.com/api-gateway/). The team can create private integrations and custom domain names to make obtaining and renewing certificates simpler and more affordable.

![Syniotec API Gateway](https://d22k7geae6sy8h.cloudfront.net/files/649c87f0314172000843e6a7/8ljg3pw5t-syniotec-API-Gateway-1.jpg)

With the increased ability to scale, the syniotec team is now managing over 50,000 assets. This means managing the live operative data coming in from its IoT telematics solutions connected to construction equipment worldwide, plus data collected directly from equipment managers. Additionally, the company receives more than 2.5 million messages in a single day.

Keeping up with that volume of data and requests at speeds necessary to accommodate the construction industry was not an easy task. But syniotec has found the answer with [Amazon Simple Queue Service (Amazon SQS)](https://aws.amazon.com/sqs/). The team chose it for its high reliability, safety, and performance speed, and has found it a necessary tool, especially when they need to handle increased demands in a short period of time.

Along with making their customers happy and their jobs easier, transitioning away from monolith architecture had a huge impact on syniotec's bottom line. Thanks to increased productivity and efficiency, the switch to Amazon EKS meant lowering their provisioning time and slashing costs by half.

## Paving new paths worldwide

Now that syniotec has overhauled and scaled their infrastructure and can offer customers the solutions they need in the current construction climate, they are looking ahead to new ways to drive digitization in the industry.

But first, they're focusing on expanding their suite of solutions that meet current industry needs. The team is looking forward to exponential growth both in their current operating countries of Germany, Austria, and Latvia, as well as beyond those borders.

The company is aware of the great need they will be able to fill as the construction landscape evolves. More companies and regulatory bodies are now pushing for sustainable and innovative building to accommodate a warming planet and a growing population, including moving to electric equipment. But without more digital tools, many construction companies will be unequipped to provide the level of transparency and efficiency that evolution would require.

---

## About the Author

### Bonnie McClure

Bonnie is an editor specializing in creating accessible, engaging content for all audiences and platforms. She is dedicated to delivering comprehensive editorial guidance to provide a seamless user experience. When she's not advocating for the Oxford comma, you can find her spending time with her two large dogs, practicing her sewing skills, or testing out new recipes in the kitchen.

---

_Source: [AWS Startups](https://startups.aws/startups/learn/how-building-on-aws-made-a-big-pivot-possible-for-syniotec)_
