---
source_url: https://aws.amazon.com/startups/learn/saas-founder-series-dremios-journey-to-unicorn-status
title: "SaaS Founder Series: Dremio's Journey to Unicorn Status"
---

## SaaS Founder Series: Dremio's Journey to Unicorn Status

> _Guest post by Afza Wajid, Bill Tarr, and Mark Birch, AWS_

With the proliferation of systems of engagement and intelligence, there is an increasing emphasis on delivering data insights throughout modern organizations. However, in order for data to be analyzed effectively, specialized skills and expensive custom code are required to centralize data across disparate storage systems before it can be analyzed. With the advent of open-source distributed data storage frameworks like Hadoop, developers were able to directly query distributed data sources, but data scientists and analysts still could not derive value from data in a self-service manner.

[Dremio](https://www.dremio.com/), a Series D funded unicorn startup founded in 2015, simplifies the analytics stack with a high-performance, highly-efficient query engine that enables data consumers to directly query petabyte-scale cloud data lake storage, while eliminating massive data transfers and vendor lock-in, and mitigating security risks. Additionally, a semantic self-service layer that connects data sources to intelligence tools improves time to value for data scientists and analysts. Dremio is now extending the reach of its solution with the launch of [Dremio Cloud](https://www.dremio.com/platform/cloud/), a cloud-native data lake as a service that simplifies the customer experience.

The AWS SaaS Factory team invited Founder and Chief Product Officer of Dremio, [Tomer Shiran](https://www.linkedin.com/in/tshiran/), to discuss Dremio's journey to software-as-a-service and to share key learnings for businesses building SaaS and platform-as-a-service (PaaS) offerings on AWS. Shiran, an entrepreneur with over 15 years experience in enterprise software, has held positions in product management and engineering at Hewlett Packard, Microsoft, and IBM Research. Prior to Dremio, he was VP of Product at MapR and helped grow the company from five employees to nearly 400 employees and hundreds of enterprise customers. Read on to learn more about Dremio's journey to unicorn status.

## SaaS Factory: Tomer, thank you for taking the time to speak with us today. To start, please tell us a bit about the value proposition on which Dremio was founded.

**Tomer Shiran:** Everyone wants more data. But the more data there is, the harder it is to efficiently derive meaningful insights from it. Cloud data lake storage like Amazon S3 has become the destination of choice for storing high volumes of data because it is inexpensive, scalable, and simple to manage. However, to analyze that data, companies have historically needed to move and copy that data into proprietary data warehouses — a process that is costly, complex, risky, and inflexible.

Dremio's data lake engine sits between cloud data lake storage and data consumers, enabling them to directly query data for high-performing dashboards and interactive analytics without needing to copy the data into proprietary data warehouses, then subsequently needing to create aggregation tables, extracts, cubes, or other derivatives. Dremio also provides a shared semantic layer that empowers data analysts to discover, curate, analyze, and share datasets in a self-service manner, and centralizes data security and governance for data teams. The result is a simpler and more streamlined data architecture that reduces time to value while enhancing data security and eliminating vendor lock-in.

More broadly, open-source innovation and industry thought leadership is pivotal to the Dremio value proposition. For instance, Apache Arrow was originally our own internal memory format that we decided to open source. It's now the standard for in-memory computing, with over 20 million downloads each month. More recently, we created Project Nessie, which brings Git-like version control to the data lake, accelerating the agility of data engineering, data science and analytics.

## SaaS Factory: This week, you launched the Dremio Cloud. Tell us why you chose the unique architectural approach you took.

**Tomer Shiran:** Dremio Cloud is a cloud-native data lake query engine delivered as a service that scales with customer workloads. Increasingly, companies want fully-managed services that enable them to focus on deriving value from data instead of worrying about system setup and administration. So, developing a Dremio SaaS offering was a natural progression in our story.

Dremio Cloud provides high concurrency and low latency queries directly on Amazon S3, and a semantic layer that makes data consumable, consistent, and secure for analysts and data scientists. It consists of an always-on control plane that receives queries from clients and is responsible for query planning and engine management, and a data plane comprised of compute engines that are responsible for query execution.

The multi-tenant control plane is central to the Dremio Cloud customer experience, hosting all client-facing interactions, including the user interface, REST API, and data query endpoints. When a business user wants to run an analysis with Dremio Cloud, they connect their preferred BI tool such as Tableau, Power BI, SageMaker, Looker, or a Jupyter notebook, to the control plane at app.dremio.cloud. The control plane securely delegates query execution to compute engines automatically provisioned in the customer's AWS account, so all data processing happens within the customer's account.

The data plane architecture is comprised of multiple right-sized compute engines to support different workloads. Built on this multi-engine architecture, Dremio Cloud introduces the capability for engines to dynamically scale based on workload size, helping companies tackle any level of concurrency while maintaining consistent performance. All data is stored and processed within the customer account, and encrypted in transit and at rest, ensuring that customers have full control of their data. There are also no inbound connections into the data plane, so customers don't have to poke holes in their firewalls/security groups. These features result in a stronger security and governance story for our customers.

The approach we took required significant technical innovation, including using end-to-end Apache Arrow to dramatically increase query performance. Without Arrow, serializing and deserializing data structures is inefficient, and results in wasted memory and CPU resources. Arrow allows Dremio to combine the benefits of columnar data structures with in-memory compute, providing performance benefits and the flexibility of complex data and dynamic schemas.

## SaaS Factory: Who are your core customers, and how does this change with the introduction of Dremio Cloud?

**Tomer Shiran:** Dremio has always been designed to work for any company that wants to use its enterprise data strategically. Hundreds of enterprises across all industries use Dremio to power their cloud data lakes, including financial institutions like Standard Chartered Bank, pharmaceutical companies like Johnson & Johnson, and manufacturers like Honeywell. Amazon itself uses Dremio to analyze and power business intelligence on data in its internal data lake, such as supply chain data.

Even so, we have designed Dremio Cloud to be bi-directionally scalable, so that venture-backed startups that have a lot of data to be analyzed but don't necessarily have the resources to operate their own data infrastructure or prefer not to burn hard-earned venture dollars on a cloud data warehouse, can use it effectively.

**SaaS Factory:** The addition of a SaaS product involves a comprehensive business and organization transformation. How have different functions of the organization evolved to better align with the SaaS business and delivery model?

**Tomer Shiran:** Indeed. On the product engineering front, we created hundreds of thousands of automated tests and a comprehensive CI/CD process. We expanded our product development organization to include site reliability engineering (SRE), DevOps and security teams, with leaders from companies such as Google and Salesforce. As a result, we're now able to release updates to Dremio Cloud on a daily basis.

In addition to the changes on the product engineering team, we aligned our customer facing teams within the company to support a self-service adoption model. Our sales and marketing teams focus on driving high quality leads to the Dremio Cloud offering online, while our customer success and support teams leverage operational data and automation to provide proactive and targeted support to ensure strong customer satisfaction. The icing on the cake is that we can use Dremio internally on our own data as the foundation for this!

## SaaS Factory: How did you engage AWS as you were developing Dremio Cloud?

**Tomer Shiran:** We've always had a special relationship with Amazon, partnering with multiple teams within the company. We work closely with numerous AWS services teams, such as [Amazon S3](https://aws.amazon.com/s3), [AWS Glue](https://aws.amazon.com/glue), and [Amazon Lake Formation](https://aws.amazon.com/lake-formation/), to deliver integration between our services and to collaborate on new features. We partner with the [AWS Marketplace](https://aws.amazon.com/marketplace/seller-profile?id=3453894e-35e5-4f27-ae14-7623d63203a4) team to distribute Dremio through the marketplace, enabling companies to consume our product while paying through AWS. Our sales and marketing teams work with the [AWS Partner Network](https://aws.amazon.com/partners/) and AWS sales organizations to bring Dremio to AWS customers, thereby enabling AWS customers to build next-generation data lakes/lakehouses.

We've also had the privilege of working with the AWS SaaS Factory team over the last couple of years. When we embarked on our journey to build Dremio Cloud, we wanted to leverage state-of-the-art technology and best practices to create a best-in-class cloud service. As numerous SaaS and PaaS services have been built on AWS in the last 10 years, including AWS' own services, we wanted to avoid the challenges and limitations that other services experience, while capitalizing on what worked well. To do so, we partnered with the SaaS Factory team to develop an architecture that delivers unparalleled scalability, security and performance and to develop a flexible usage-based pricing strategy to ensure an optimized SaaS delivery model for customers across all segments.

## SaaS Factory: Dremio is now officially a 'Unicorn' based on your most recent series D funding round in January 2021. If you were speaking to aspiring founders, what would be your advice to them?

**Tomer Shiran:** If there's a significant need in the market that you're excited about, don't hesitate to launch your own startup. But take the time to build the best product in that category. For instance, in the data infrastructure space, a significant amount of intellectual property is required to deliver a solid product. We spent a good five years at Dremio building what we thought would truly be a next-generation data lake engine from the ground up, with a focus on innovation and customer success. Once you build a strong foundation, exponential growth will be easier to realize. Today, six years after its founding, Dremio powers the cloud data lakes of many of the world's largest enterprises and have raised over $200M in venture funding in the last year.

Dremio and AWS are excited about the future of data management, and the innovation we are delivering with Dremio Cloud. If you're interested in learning more, please check out the [Dremio Cloud page](http://dremio.com/platform/cloud)!

## About AWS SaaS Factory

[AWS SaaS Factory](https://aws.amazon.com/partners/saas-factory?utm_source=apn&utm_medium=blog&utm_campaign=sf_home) helps organizations at any stage of SaaS journey. Whether looking to build new products, migrate existing applications, or optimize SaaS solutions on AWS, the AWS SaaS Factory Program can help. SaaS builders and operators are encouraged to reach out to their account representative to inquire about engagement models and to work with the AWS SaaS Factory team.

Visit the [AWS SaaS Factory Insights Hub](https://aws.amazon.com/partners/saas-factory?utm_source=apn&utm_medium=blog&utm_campaign=in_hub#AWS_SaaS_Factory_Insights_Hub) to discover more technical and business content and best practices. [Sign up](https://partners.awscloud.com/SaaS.html?utm_source=apn&utm_medium=blog&utm_campaign=opt_in) to stay informed about the latest SaaS on AWS news, resources, and events.

---

> _Author: AWS Editorial Team_

The AWS Startups Content Marketing Team collaborates with startups of all sizes and across all sectors to deliver exceptional content that educates, entertains, and inspires.
