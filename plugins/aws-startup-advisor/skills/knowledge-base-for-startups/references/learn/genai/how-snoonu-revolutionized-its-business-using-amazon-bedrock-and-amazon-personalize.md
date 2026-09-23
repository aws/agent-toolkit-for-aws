---
source_url: https://aws.amazon.com/startups/learn/how-snoonu-revolutionized-its-business-using-amazon-bedrock-and-amazon-personalize
title: "How Snoonu revolutionized its business using Amazon Bedrock and Amazon Personalize"
---

## How Snoonu revolutionized its business using Amazon Bedrock and Amazon Personalize

[Snoonu](https://www.snoonu.com/) is Qatar's leading e-commerce platform, offering 15 essential services through a single comprehensive application. These services range from quick meals to urgent pharmacy runs, grocery shopping, and personal shopping assistance (Snoosend). Innovation and excellence are Snoonu's guiding principles as it strives to deliver the best shopping and delivery experience in Qatar. "We are going to launch a lot of new services inside the Snoonu application, and we are expanding internationally," said Nikita Gordeev, CTO at Snoonu. "Using [Amazon Bedrock](https://aws.amazon.com/bedrock/) helps us to launch one of our new services."

## Human-Intensive Categorization and Real-Time Recommendations

As a fast-growing e-commerce marketplace, Snoonu faced two primary challenges: 1) the need for accurate categorization, and 2) the need for contextually accurate, real-time personalized recommendations.

Snoonu had a rapidly growing set of marketplaces, with each having its own catalog structure, which presented a challenge as the volume of products grew. "A single human can't make a fast enough decision as to what category a product should be assigned. We had about a million products that weren't categorized at all," said Gordeev. "If we're doing it manually, it can take up to two human-years of work." The company also lacked a way to automatically detect inappropriate content on its marketplaces.

"As we scale, optimizing the ranking and recommendation of products and merchants across the app has become increasingly critical to enhance user experience and drive growth," said Gordeev. Snoonu initially opted for a single global model covering products from all verticals – restaurants, groceries, and marketplace – that tracked core interactions such as product views, cart additions, and purchases. While this setup led to improved conversion metrics, it was still limited to weekly updates, which meant that users were presented with the same suggestions for consecutive days, limiting product discovery. The company addressed this by moving to daily updates and creating vertical-specific models, making results more contextually accurate and boosting performance. "While this was a valuable iteration, the 24-hour lag still fell short of the level of responsiveness Snoonu strives for as a company," said Gordeev. Snoonu then realized it was time to level up the product.

## Streamlined Product Categorization Powered by Amazon Bedrock

Snoonu unveiled a generative AI solution, powered by Amazon Bedrock and Anthropic Claude 3.5 Sonnet, in order to streamline product categorization and improve user experience. The company integrated [Amazon Bedrock Knowledge Bases](https://aws.amazon.com/bedrock/knowledge-bases/) to transform its product categorization by giving foundation models contextual information from its private data sources to deliver more relevant, accurate, and customized responses. The solution uses AI models to improve new catalog entries, by using the image, name, and description to automatically categorize the product into a 3-level hierarchy defined by the business. The solution reduced the effort from two human-years to around a month.

If a partner places a new product on Snoonu's marketplace, Snoonu's solution can immediately classify it. The solution leverages Amazon Bedrock Knowledge Bases for enhanced and customized automatic categorization. By significantly reducing manual labor, the company has freed up staff time previously spent on tedious checks and catalog updates, so the team is able to build new features. Snoonu is also building an automated content moderation system, which leverages generative AI for precise content flagging, creating a safer user environment. "With power of AI, we're continuing improving it on a monthly basis with the help of teams at AWS," said Gordeev.

## Real-time Personalization

To elevate user engagement and deliver dynamic, session-aware suggestions, Snoonu took on its next challenge: implementing real-time personalization. To achieve this, the company built an architecture that seamlessly integrates user interactions, batch training, and real-time recommendations using [Amazon Personalize](https://aws.amazon.com/personalize/). Amazon Personalize is a fully managed deep learning (DL) service that leverages a company's data to generate product recommendations for its users. A retailer provides data about end-users including events (e.g., views, signups, adds-to-cart), item metadata (e.g., descriptions, price), and user metadata (e.g., device type, country). Amazon Personalize uses this data to train custom, private models that generate recommendations that can be surfaced to the application via an API.

"Our architecture consists of data collection using Amplitude Analytics to capture user interactions across our app, filtering relevant events by business vertical. Filtered events stream in real-time through [Amazon Kinesis](https://aws.amazon.com/kinesis/), while daily exports to BigQuery store historical data for model retraining. For Batch Model Training, we store structured datasets of users, items, and interactions in BigQuery, which are processed daily in Databricks. After validation and feature transformation, the data is exported to Amazon S3 and used to retrain the model through AWS Personalize. This daily pipeline ensures our recommendation engine stays fresh and aligned with the latest user behavior and context. For real-time recommendations, we have an AWS Lambda function validating schema, updating Amazon Personalize, and triggering recommendation updates," said Gordeev. "Our journey with Amazon Personalize has been a testament to our mindset: Starting simple, learning fast, and scaling smart."

## Time Savings, Growth, and Automated Detection

The product categorization project impact is:

- Almost 2 human-years savings for initial categorization
- 55 person-day savings each month for new product categorization
- 10% growth in sales conversion rate
- 1.5x increase in order volume

The real-time recommendation project impact from July to December 2024 is:

- $2.6 million (USD) in incremental Gross Merchandise Value (GMV), highlighting its strong contribution to revenue growth
- Add-to-Cart events boosted by up to 1,600% through cart recommendations, with conversion rates continuing to improve over time
- A 47x return on investment in GMV
- An average of 30% contribution to the basket size in orders with at least one recommended product

Finally, Snoonu is poised to achieve its goal of international scale.

"AWS allows us as a startup to switch from a very basic deployment during the startup stage, to an architecture to scale the business internationally." says Gordeev. "For example, it's very easy to move from virtual machines to [Amazon ECS](https://aws.amazon.com/ecs/) (Elastic Container Service), and then to [Amazon EKS](https://aws.amazon.com/eks/) (Elastic Kubernetes Service). We're always changing our infrastructure to use more top solutions, such as [Amazon Aurora Serverless](https://aws.amazon.com/rds/aurora/serverless/) as a database for scale, and we can migrate to it without any disruption to our business. We trust that building services on AWS helps us to empower our customer needs today, tomorrow, and in 10 years."

---

## About the Authors

### Nikita Gordeev

Nikita is the Chief Technology Officer at Snoonu which is the fastest growing technology company in Qatar. He has over 10 years of dedication to software development and leadership roles in the Banking, Telecommunication and E-Commerce sectors. Empowered by a master degree in Information Security and Advanced Studies at MIT. He is always open and eager to share knowledge and insights for those who are interested.

### Chris Saleski

Chris Saleski is the AWS Global Customer References Lead for Migration & Modernization. Chris previously worked for Microsoft, where he was in charge of leading co-marketing campaigns with DevOps and big data partners to grow their businesses and bring their customers to Microsoft Azure. Prior to Microsoft, Chris was a Marketing Director for Intel, in charge of helping state-of-the-art software developers in gaming and HPC to optimize their applications for new and emerging storage. Chris holds an MBA and Mechanical Engineering degree from University of Michigan.

---

_Source: [AWS Startups](https://startups.aws/startups/learn/how-snoonu-revolutionized-its-business-using-amazon-bedrock-and-amazon-personalize)_
