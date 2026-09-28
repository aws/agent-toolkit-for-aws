---
source_url: https://aws.amazon.com/startups/learn/purple-ant-on-using-aws-to-transform-the-insurance-industry
title: "Purple Ant on using AWS to transform the insurance industry"
---

## Purple Ant on using AWS to transform the insurance industry

> _Guest post by Iman Nandi and Greeshma Nallapareddy, Solutions Architects, AWS_

Purple Ant is a subscription-based property monitoring platform that enables its customers to detect, prevent, and track damage to their homes using IoT devices. Pankaj Parashar (CEO and co-founder of Purple Ant) founded Purple Ant after his insurance company recommended he install a car device that collects driving data to price his insurance. Parashar quickly realized a similar device for houses could not only help to accurately and fairly price home insurance, but also keep his family safe. This started his journey into leveraging IoT (Internet of Things) and AWS to transform the home insurance industry.

## How It Works

Purple Ant leverages IoT with [AWS IoT Core](https://aws.amazon.com/iot-core), storage with [Amazon S3](https://aws.amazon.com/s3) and [Amazon DynamoDB](https://aws.amazon.com/dynamodb), and data routing through [Amazon API Gateway](https://aws.amazon.com/api-gateway/) to monitor home health effectively and prevent damage based on data collected. Data is used to find signs of potential future damage and provide immediate solutions. Purple Ant lowers the cost of insurance by lowering the risk of the property getting damaged. This benefits both insurance companies who assume the risk and home owners by sending alerts on how to prevent damages, using sensor data to detect damages, and sending help to fix damages.

## Leveraging AWS

Sensors from Purple Ant's smart home devices collect data signifying the occurrence, or lack thereof, of a disastrous event like a water leak or fire in near real-time. As shown in the ingestion architecture diagram below, there is data flow established starting with collecting data from smart home devices connected to IoT Core. As data is collected, the IoT Rules Engine sends data to [Amazon Kinesis Data Firehose](https://aws.amazon.com/kinesis/data-firehose/) for aggregating and organizing the data into various AWS data stores, including S3 and DynamoDB, using [AWS Lambda](https://aws.amazon.com/lambda/) functions.

As shown in the delivery architecture diagram, another Lambda function is utilized for sending alert messages and processed data to a React Native mobile application using API Gateway, as well as sending emails and text messages using [Amazon SNS](https://aws.amazon.com/sns/) and [Amazon SES](https://aws.amazon.com/ses/). An [Amazon RDS](https://aws.amazon.com/rds) PostgreSQL database is also present for storing and delivering metadata. About 1.5 MB of data per home device is collected daily with an average of 10K expected devices to send data, totaling 15 GB of data inflow per day. In the future for scalability, the data warehouse solution [Amazon Redshift](https://aws.amazon.com/redshift) will be utilized for data ingestion once the event volumes are large enough to impact the performance of the current setup.

### Ingestion

![Purple Ant Architecture Diagram - Ingestion](https://d22k7geae6sy8h.cloudfront.net/files/64b3e1bc831452000996205e/9lk5etvqj-Purple-Ant-Architecture-Diagram-Ingestion.jpg)

### Delivery

![Purple Ant Architecture Diagram - Delivery](https://d22k7geae6sy8h.cloudfront.net/files/64b3e1e5831452000996205f/9lk5eur4x-Purple-Ant-Architecture-Diagram-delivery.jpg)

## Enabling Scale and Differentiation

Manoj Narayanan, CTO at Purple Ant, says that leveraging AWS "dramatically increases incorporation of new features, allows global deployment, and scalable performance due to the ease of implementation available." Using AWS IoT Core lets Purple Ant scale as they increase their user base while still keeping security top-of-mind. Lambda functions are triggered when sensor state changes are detected and allow them to trade capital expense for operational expense.

## Insights

Throughout Purple Ant's journey, the company has found that intentional choices need to be made on how to scale and cost optimize their business. Visualization is one critical aspect of their IoT functionality that needs to be responsive at scale. "We started with Superset and realized soon that it will lead into performance issues especially in an IoT event scenario. We ended up leveraging Redshift to ensure that the performance met expectations. So even within AWS, we have to choose the right technology option based on the specific application functional/non-functional need," says Manoj. For scalability, a Redshift instance will be utilized to pull data onto their React dashboard rather than pulling data directly with Kinesis Data Firehose once event volumes are large enough to impact the performance of the current setup. When implementing in IoT Core, they found it easy to set up and use for their use case, eliminating the need to create any custom interfaces or integrations to make their architecture function as intended. Moreover, IoT Core was an out-of-the-box solution available for them to hook up to third-party hubs. "It was easy to create a 'thing' and establish a secure connection, and implementation went smoothly," says Manoj. A flexible AWS service with standard implementation options enabled them to cover most of their scenarios.

To allocate costs where most necessary, Purple Ant maintains a large focus around their AWS spend. A large aspect of that is being able to choose the appropriate types of infrastructure to match their workloads. "Given that we are a startup, cost optimization is a high priority area for us. This means that we need to continuously keep track of the [Amazon EC2](https://aws.amazon.com/ec2/) instances/sizes etc. amongst others to ensure that we are scaling to the right requirement," says Manoj. The team was introduced by the AWS team to [AWS Cost Explorer](https://aws.amazon.com/aws-cost-management/aws-cost-explorer/), which can be utilized for using reserved instances, taking advantage of the savings plans offered by AWS, and receiving other recommendations to reduce cost. "We use the Cost Explorer regularly to track the trend and adjust the costs where needed. The trend also helps us upgrade the infrastructure when needed so that performance doesn't suffer," says Manoj. Cost optimization is a continuous process for startups like Purple Ant that want to deliver the value of home monitoring to their customers in a successful way.

## Conclusion

By leveraging AWS, Purple Ant is able to transform the way home insurance is priced, how home owners care for their properties, and how they can enable continuous monitoring to prevent home damage. Ultimately, homeowner premiums and repairs in the United States can be reduced significantly by up to 15-20% with their property monitoring devices, which can result in savings of approximately 16-22 billion dollars for consumers.

---

## About the Author

### AWS Editorial Team

The AWS Startups Content Marketing Team collaborates with startups of all sizes and across all sectors to deliver exceptional content that educates, entertains, and inspires.

---

_Source: [AWS Startups](https://aws.amazon.com/startups/learn/purple-ant-on-using-aws-to-transform-the-insurance-industry)_
