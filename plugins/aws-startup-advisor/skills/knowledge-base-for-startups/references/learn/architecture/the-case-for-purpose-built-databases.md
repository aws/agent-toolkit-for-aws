---
source_url: https://aws.amazon.com/startups/learn/the-case-for-purpose-built-databases
title: "The case for purpose-built databases"
---

## The case for purpose-built databases

_By Cullen Dejean, Sr. Solutions Architect at AWS, and Matthew de Anda, Startup Solutions Architect at AWS._

As an early-stage startup, you have many technical decisions to make while you pursue product-market fit. Some of these technical decisions are reversible, while others are critical junctures with long-term impacts. Picking a database tends to fall into the latter category, which is why a one-size-fits-all approach with a relational database no longer works. You need to take a step back and review the exact use cases you have before jumping into selecting a database. Change your expectation that one database can do everything, and instead choose the database service best fit for the task at hand. AWS offers a broad and deep portfolio of [purpose-built databases](https://aws.amazon.com/products/databases/?nc2=h_ql_prod_db) that support diverse data models and allow you to build data-driven, highly scalable, distributed applications. In this blog post, we'll cover the factors an early-stage startup should consider when reviewing database options on AWS.

## Factors to consider when selecting a database

### Experience

Early-stage startups have to focus on building a minimum viable product and demonstrating traction and growth, so any decisions should be made with an eye toward speed to market and available skills. Picking a technology that your team doesn't have experience with will often increase timelines and result in MVPs that are harder to make changes to in response to user feedback. This is a common reason why using a relational database can continue to be the right approach in the beginning. If your team has experience with a specific data service (e.g. relational, document, etc.) then starting there can be the right choice.

### Future scale

Future scale is another factor of which early stage startups must be mindful. Choosing a familiar technology to enable quicker delivery needs to be balanced out by re-analyzing the use case and determining future scaling needs. Being able to leverage solutions that scale automatically with you while continuing to perform as expected can be a force multiplier. It's always possible to migrate to a different technology later on, but keep in mind that migrations will become more complex as your data grows. Some migrations, like those between Amazon Relational Database Service (Amazon RDS) and Amazon Aurora, are reversible—what we call "two-way door decisions." Two-way door decisions allow for faster experimentation and embrace a "fail fast" approach. In the next section, we'll discuss database services such as Amazon RDS and Aurora further.

## Purpose-built databases and their use cases

For a long time, relational databases like MySQL and Postgres dominated the database landscape. Now, there are a lot more database types to choose from. To make an informed decision, it's helpful to assess databases according to their access characteristics and the shape of the data.

### Relational databases

A relational database is self-describing, because it enables developers to define the database's schema, as well as relations and constraints between rows and tables in the database. Developers rely on the functionality of the relational database and not the application code to enforce the schema and preserve the referential integrity of the data within the database. Some typical use cases for a relational database include web and mobile applications. Startups use [Amazon RDS](https://aws.amazon.com/rds/) and [Amazon Aurora](https://aws.amazon.com/rds/aurora/) for high-performance and scalable applications on AWS. Both RDS and Aurora are fully managed and scalable databases.

### NoSQL: Key-value and document databases

As your system grows, large amounts of data are often in the form of key-value data, where a single row maps to a primary key. Key-value databases are highly partitionable and allow horizontal scaling at levels that other types of databases cannot achieve. Use cases such as gaming, ad tech, and IoT lend themselves particularly well to the key-value data model, where the access patterns require low-latency Gets/Puts for known key values.

[Amazon DynamoDB](https://aws.amazon.com/dynamodb/) is a fully managed, serverless, key-value NoSQL database that delivers single-digit millisecond performance at any scale. For highly performant key-value use cases, we also offer [Amazon Keyspaces](https://aws.amazon.com/keyspaces/), a scalable, highly available, and managed Apache Cassandra–compatible database service.

Another relevant database type is a document database. Document databases are intuitive for developers to use, because the data in the application tier is typically represented as a JSON document. Document databases are popular for use cases such as storing and querying content management system data, as well as managing user profiles, preferences, and requests to generate recommendations and enable transactions.

For document data, developers can persist data using the same document model format that they use in their application code, using the flexible schema model of [Amazon DocumentDB](https://aws.amazon.com/documentdb/) (with MongoDB compatibility), a fully managed and durable database to achieve developer efficiency and support millions of document reads per second while scaling compute and storage independently.

### Data warehouses

When determining the need for data warehouses, it's important to distinguish between transactional (OLTP) and analytical (OLAP) databases. OLAP databases are larger databases for warehousing and data archiving. For many early stage startups, considering Amazon Athena to handle OLAP use cases can be the right choice. [Amazon Athena](https://aws.amazon.com/athena/) is a serverless SQL query interface that allows you to analyze data stored in [Amazon Simple Storage Service (Amazon S3)](https://aws.amazon.com/s3/) with standard SQL.

When your applications begin to require more complex queries and stricter SLAs, this is where the power of data warehouses can help scale your data strategy and requirements. [Amazon Redshift](https://aws.amazon.com/redshift/?nc=sn&loc=0) is a fully managed, petabyte-scale data warehouse service in the cloud.

### In-memory databases

In-memory databases are used for applications that require real-time access to data delivered at microsecond latency. Financial services, ecommerce, web, mobile, and gaming applications have used in-memory databases to build leaderboards, session stores, caching, and real-time analytics. In-memory databases can ease the load off your relational databases, deliver lower-latency results, or replace the relational database and be a primary in-memory key-value data store.

[Amazon ElastiCache](https://aws.amazon.com/elasticache/) makes it easy to set up, manage, and scale an in-memory data store or cache environment. Amazon ElastiCache works with both the Redis and Memcached engines. [Amazon MemoryDB](https://aws.amazon.com/memorydb/features/) for Redis is a Redis-compatible, durable, in-memory database service that delivers ultra-fast performance. It is purpose-built for modern applications with microservices architectures. One way of deciding between these offerings depends on whether your use case is ephemeral or requires more durability. Amazon ElastiCache is often used as a stand-alone database, but only for applications that do not require durability. In contrast, MemoryDB is designed to be a primary database. The other factor would be your team's familiarity with Redis or Memcached engines.

### Search

Search databases deliver near real-time analysis and search. Common use cases for search databases include log analytics, real-time application monitoring, and clickstream analytics.

[Amazon OpenSearch Service](https://aws.amazon.com/opensearch-service/) makes it easy for you to perform interactive log analytics, real-time application monitoring, website search, and more. Amazon OpenSearch Service supports OpenSearch and legacy Elasticsearch OSS.

### Graph databases

A graph database's purpose is to make it easy to build and run applications that work with highly connected data sets. Typical use cases for a graph database include social networking, recommendation engines, fraud detection, and knowledge graphs. Deciding if a graph database is the right choice starts with determining whether the data can be best represented as graph structure. Are the breadth and depth of relationships increasing? Queries for relational databases will become slower as the relationships become more complex. Are the models themselves changing enough that schema changes are becoming a burden on your team? Finally, will you need to answer questions about relationships in your data? Graph databases provide this kind of flexibility while delivering complex queries of these relationships. [Amazon Neptune](https://aws.amazon.com/neptune/) is a fast, reliable, and fully-managed graph database service.

### Ledger databases

Ledger databases can help track data's entire lineage. [Amazon Quantum Ledger Database (QLDB)](https://aws.amazon.com/qldb/features/) is a fully managed ledger database that provides a transparent, immutable, and cryptographically-verifiable transaction log ‎owned by a central trusted authority.

### Time series databases

Time series databases handle use cases where applications are dealing with time series data and need to quickly analyze this data using built-in analytic functions. [Amazon Timestream](https://aws.amazon.com/timestream/) is a fast, scalable, and serverless time series database service for IoT and operational applications.

## Database Types Summary

| Database Type | Use Cases                                                                                | AWS Service                                          |
| ------------- | ---------------------------------------------------------------------------------------- | ---------------------------------------------------- |
| Relational    | Traditional applications, ecommerce, OLTP transactions                                   | Amazon Aurora, Amazon RDS                            |
| Key-value     | High-traffic web applications, ecommerce systems, gaming applications, financial trading | Amazon DynamoDB, Amazon Keyspaces                    |
| Document      | Content management, catalogs, user profiles                                              | Amazon DocumentDB, Amazon Athena, Amazon ElastiCache |
| In-memory     | Caching, session management, gaming leaderboards, geospatial applications                | Amazon MemoryDB for Redis                            |
| Search        | Consolidated logging, personalized search                                                | Amazon OpenSearch                                    |
| Graph         | Fraud detection, social networking, user profiles                                        | Amazon Neptune                                       |
| Ledger        | Systems of record, supply chain, registrations, banking transactions                     | Amazon QLDB                                          |
| Time series   | IoT, DevOps, industrial telemetry                                                        | Amazon Timestream                                    |

## Conclusion

As an early-stage startup, one of the more critical decisions you will make is what type of database technology to use. When reviewing the purpose-built databases that AWS offers, start with the use case and define the needed requirements to help filter which database services are a good fit. Then, layer on speed to market and your team's available skills, but make sure to balance those factors against your future needs. It's important to spend the time now considering these factors and selecting the database service that's best for the job.

---

> _AWS Editorial Team_

The AWS Startups Content Marketing Team collaborates with startups of all sizes and across all sectors to deliver exceptional content that educates, entertains, and inspires.
