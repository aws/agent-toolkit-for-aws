---
source_url: https://aws.amazon.com/startups/learn/building-a-serverless-dynamic-dns-system-with-aws
title: "Building a serverless dynamic DNS system with AWS"
---

## Building a serverless dynamic DNS system with AWS

_This post was originally published in December 2015. It was updated July 2023 to make the solution more cost-effective and efficient. This post has been updated to replace [Amazon API Gateway](https://aws.amazon.com/api-gateway/) with [AWS Lambda function URLs](https://docs.aws.amazon.com/lambda/latest/dg/lambda-urls.html) and [Amazon Simple Storage Service (Amazon S3)](https://aws.amazon.com/s3/) with [Amazon DynamoDB](https://aws.amazon.com/dynamodb/). Using Lambda function URLs reduces the overall cost of the solution. This feature comes at no extra cost when using the Lambda service, and it provides a RESTful HTTPs endpoint that our client interacts with. Replacing Amazon S3 with DynamoDB increases the efficiency of the solution and reduces the overall latency when querying data._

Early-stage startups, small businesses, and home networks often have dynamic public IP addresses that can change without notice. Because of this changing address, you can't reliably access systems on these networks from the outside. For startups in the early stages of their life cycle, it's important to provide a reliable and highly available service in order to gain trust with your first set of customers.

[Dynamic DNS](https://aws.amazon.com/what-is/dynamic-dns/) systems solve this problem by running a software agent inside your network to keep a DNS record updated with the latest public IP address. As long as the DNS record is up to date, you can find your network and customers can reliably access your service.

In this post, we describe how to build your own dynamic DNS system by using serverless AWS services. Building a serverless system using nothing but Amazon Web Services (AWS) services and a few lines of code is simple, cost-effective, and scalable, and allows you to focus on the core business logic of your startup, rather than worrying about scaling and maintaining the underlying infrastructure.

## AWS services we use in our dynamic DNS system

In the next sections, we show you how to use the following AWS services to build a dynamic DNS solution:

- The [AWS Lambda](https://aws.amazon.com/lambda/) service allows you to run code without having to manage the underlying servers. Your code is always ready to run, but you are charged only per invocation of the function, in 1 millisecond increments. The Lambda service can interact with other AWS services through [AWS SDKs](https://aws.amazon.com/developer/tools/).
- Lambda function URLs provide a dedicated HTTPS endpoint for your Lambda function. This allows you to directly invoke the function from your client application without the need to use an AWS SDK or invoke the function via an additional proxy service. This feature comes at no additional cost to the Lambda service.
- [Amazon Route 53](https://aws.amazon.com/route53/) is a managed DNS service that allows you to register and host domains and DNS zones from a global network of DNS servers. As with all AWS services, Route 53 can be managed through APIs.
- DynamoDB is a fully managed, serverless, key-value [NoSQL database](https://aws.amazon.com/nosql/) designed to run high-performance applications at any scale. DynamoDB offers built-in security, continuous backups, automated multi-Region replication, in-memory caching, and data import and export tools.

## Logical flow of the dynamic DNS system

Figure 1 shows how a client finds its own IP address by making an API request to a service built using a Lambda function and its attached function URL.

![Figure 1. Request flow for client to retrieve IP address of its running service](https://d22k7geae6sy8h.cloudfront.net/files/65773dbd79391400087544db/8lq15g5pz-Figure-1.-Request-flow-for-client-to-retrieve-IP-address-of-its-running-service.jpg)

As shown in Figure 2, now that the client knows its public IP, it makes another request to our service to set a DNS record. The Lambda function first consults the record stored in our DynamoDB table to validate the request. If the check passes, the Lambda function then sets the DNS entry in Route 53 via an API call. Now the network's current IP is in public DNS and can be found by a standard DNS query.

![Figure 2. Request flow to set update DNS record with new IP](https://d22k7geae6sy8h.cloudfront.net/files/65773ddf79391400087544dc/8lq15gwb3-Figure-2.-Request-flow-to-set-update-DNS-record-with-new-IP-1.jpg)

## Benefits of dynamic DNS with Lambda and Route 53

Here's some advantages you will gain by running a serverless dynamic DNS system:

- **Easier to set up.** There is a sample client along with all the code, configuration, and instructions to set this up in your own AWS account.
- **Thin to no client.** It takes three commands to update the API. You can write your own client in most languages and run it on platforms, including Windows, Linux, macOS, Raspberry Pi, Chrome OS, and [DD-WRT](http://www.dd-wrt.com/site/index)/[Tomato USB](http://tomatousb.org/) router firmware.
- **Support for arbitrary number of clients, hostnames, and domains.** Route 53 service limits and quotas can be found in the "[Quotas](https://docs.aws.amazon.com/Route53/latest/DeveloperGuide/DNSLimitations.html)" section of the Route 53 Developer Guide.
- **Cost-effective–$1 to $2 per month.** Route 53 zones each cost $0.50 per month, 1,000,000 DNS queries cost $0.40, and 10,000 Lambda function requests to update DNS cost under $0.01.
- **Serverless architecture.** Serverless technologies feature automatic scaling, built-in high availability, and a pay-for-use billing model to increase agility and optimize costs.
- **Granular permissions allow only authorized clients to update their own hostname.** Clients can update the system only from the address that is being added to DNS.
- **Minor changes required for your current DNS setup.** You can leave your primary .com zone with your current DNS provider and use a secondary [dynamic.example.com](http://dynamic.example.com/) zone in AWS. Refer to "[Creating a public hosted zone](https://docs.aws.amazon.com/Route53/latest/DeveloperGuide/CreatingHostedZone.html)" in the Route 53 Developer Guide for more information on creating hosted zones in Route 53.

## Prerequisites

You'll need two things to build this solution:

1. **[An AWS account](https://portal.aws.amazon.com/billing/signup?nc2=h_ct&src=header_signup&redirect_url=https%3A%2F%2Faws.amazon.com%2Fregistration-confirmation#/start/email).** New accounts are eligible for the [AWS Free Tier](https://aws.amazon.com/free/).
2. **A domain you own, hosted on Route 53 or another provider.** You can [register domains](https://aws.amazon.com/about-aws/whats-new/2014/07/31/amazon-route-53-announces-domain-name-registration-geo-routing-and-lower-pricing/) through Route 53 if needed from as little as $3.00. Refer to [Amazon Route 53 Pricing for Domain Registration](https://d32ze2gidvkk54.cloudfront.net/Amazon_Route_53_Domain_Registration_Pricing_20140731.pdf) for a full range of prices.

## How to build a dynamic DNS system in your account

At this point, you have enough information to start building your own copy of the system. If you want to learn more about how it works, read on.

If you want to start building, [Route 53 dynamic DNS with Lambda](https://github.com/awslabs/route53-dynamic-dns-with-lambda) is available on GitHub. It provides illustrated instructions and all the necessary code and configuration.

## How the new system works

First, the client needs to find the public IP assigned to its network. If you make a request from your network to a service on the internet, that service sees the request coming from your external IP address.

Then, the client makes an `HTTP POST` request to the Lambda function URL with a request body of `{"execution_mode":"get"}`, and gets a response containing the current public IP address:

```
HTTP POST
> https://.....lambda-url.eu-west-1.on.aws
```

```json
{ "return_message": "176.32.100.36", "return_status": "success" }
```

During this process, the Lambda function URL converts the `HTTP` request to JSON, including all request parameters, and passes the requestor's source IP address to a Python Lambda function. The Lambda function then sends a JSON response with the IP back to the client.

![Figure 3. Request to get a public IP](https://d22k7geae6sy8h.cloudfront.net/files/65773e8d79391400087544dd/8lq15kmam-Figure-3..jpg)

The client now builds a request token by linking the public IP address returned from the `HTTP POST` request, the DNS hostname, and a shared secret. For example, if your IP address is `176.32.100.36`, your hostname is `host1.dyn.example.com`, and your shared secret is `shared_secret_1`, the linked string will be the following:

```
176.32.100.36host1.dyn.example.comshared_secret_1
```

Next, the client generates a `SHA-256` [hash function](https://www.techtarget.com/searchdatamanagement/definition/hashing) from the string:

```bash
echo -n 176.32.100.36host1.dyn.example.comshared_secret_1 | shasum -a 256
```

```
Hash: 96772404892f24ada64bbc4b92a0949b25ccc703270b1f6a51602a1059815535
```

The client then requests the DNS update by making a second `HTTP POST` request. It passes the plain text hostname as a key and the hash function as the authentication token within the request body:

```
HTTP POST > https://....lambda-url.eu-west-1.on.aws
```

```json
{
  "execution_mode": "set",
  "ddns_hostname": "host1.dyn.example.com",
  "validation_hash": "96772404892f24ada64bbc4b92a0949b25ccc703270b1f6a51602a1059815535"
}
```

The Lambda function URL then passes the request parameters back to the Lambda function.

After that, the Lambda function queries its JSON configuration record from DynamoDB using the [AWS SDK for Python (Boto3)](https://boto3.readthedocs.org/en/latest/). In this system, interactions between the Lambda service, DynamoDB, and Route 53 use Boto3, which is pre-built into the Lambda service runtime environment.

Once our Lambda function queries the configuration record from DynamoDB, it uses the hostname as a key to find the shared secret, and other configuration associated with that record, similar to the following example record:

```json
{
  "host1.dyn.example.com.": {
    "aws_region": "us-west-2",
    "route_53_zone_id": "MY_ZONE_ID",
    "route_53_record_ttl": 60,
    "route_53_record_type": "A",
    "shared_secret": "SHARED_SECRET_1"
  },
  "host2.dyn.example.com.": {...}
}
```

The client passed `host1.dyn.example.com` as the key, so the Lambda function reads `SHARED_SECRET_1` from the configuration, and rebuilds the hash function token using the hostname, the requestor's IP address, and the shared secret. If the hash function calculated by the Lambda function and the hash function received from the client match, then the request is considered valid.

Once the request is validated, the Lambda function uses the information from the configuration to make an API call to Route 53 to see if the DNS hostname is already set with the client IP. If no change is necessary, the Lambda function responds to the client and exits:

```json
{
  "return_message": "Your IP address matches the current Route53 DNS record.",
  "return_status": "success"
}
```

If there is no record, or if the current record and the client IP do not match, the Lambda function makes an API call to Route 53 to set the record, responds to the client, and exits:

```json
{
  "return_message": "Your hostname record host1.dyn.example.com. has been set to 176.32.100.36",
  "return_status": "success"
}
```

![Figure 4. Request flow to set hostname](https://d22k7geae6sy8h.cloudfront.net/files/65773f4179391400087544de/8lq15ohe4-Figure-4..jpg)

### How is this system secured?

- All communications using Lambda function URLs are encrypted.
- The shared secret is never transmitted across the internet.
- Client request rate can be throttled using the [reserved concurrency](https://docs.aws.amazon.com/lambda/latest/dg/configuration-concurrency.html) feature of the Lambda service.
- The authentication mechanism is multi-factor because the client presents the shared secret ("something it has") and its own public IP address ("something it is").
- The configuration file can be encrypted at rest via DynamoDB server-side encryption.
- Your AWS credentials are not used, so they cannot be leaked.

## Conclusion

The dynamic DNS system we describe in this post shows how to create your own serverless solution on AWS to solve a real-world problem—DNS is susceptible to change and you might not be aware!

Use this solution to run your own dynamic DNS on AWS. Or, use it as an example to learn how you can use AWS services to create your own serverless solutions at any scale.

Visit the [Route 53 dynamic DNS with Lambda](https://github.com/awslabs/route53-dynamic-dns-with-lambda) repository on GitHub for a complete set of code, configuration, and instructions on how to deploy.
