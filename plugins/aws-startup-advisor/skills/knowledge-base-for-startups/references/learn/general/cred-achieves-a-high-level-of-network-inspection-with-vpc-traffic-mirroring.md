---
source_url: https://aws.amazon.com/startups/learn/cred-achieves-a-high-level-of-network-inspection-with-vpc-traffic-mirroring
title: "CRED achieves a high level of network inspection with VPC traffic mirroring"
---

## CRED achieves a high level of network inspection with VPC traffic mirroring

**September 8, 2021**: Amazon Elasticsearch Service has been renamed to Amazon OpenSearch Service. [See details](https://aws.amazon.com/opensearch-service/).

> _Guest post by Himanshu Das, Security Lead, CRED_

_CRED seeks to empower people to upgrade their lives through its members only credit card benefits, exclusive rewards, and experiences from premier brands. CRED, a high-trust community of creditworthy individuals, merchants, and institutions, has reimagined the credit card experience for people serving around millions of credit card payers._

_Dealing with tons of sensitive transactions and data, CRED has always kept its focus on security. There are two types of companies: one where security is seen as an after-thought and the other where security is of the utmost importance. What about the in-betweeners, you ask? At CRED, we genuinely believe that there are no in-betweeners to the above rule. And that's probably why we belong to the latter camp. CRED is a security first company, keeping security their utmost priority at every time._

_"Using AWS has not only helped us in keeping our infrastructure always stable and highly available but also made sure that security is present at each layer" ~ Avinash Jain, Security Engineering, CRED._

## AWS VPC Traffic Mirroring: Monitoring Network Intrusion in public VPC Subnet Using NIDS

COVID has hit everyone and affected people in their own way. As far as organizations are concerned, employees have been asked to work from home (WFH), and because many industries are now working remotely, the pattern of user connections to the enterprise network has turned upside down. Instead of most users connecting locally, now most are connecting remotely. And for allowing employees to access critical business functions, there is mandatory VPN connectivity.

Since the VPN instance is kept in a demilitarized zone (DMZ) to allow employees around the globe to connect to it and access internal applications, there is an unexpected flood of WFH connections, which makes VPN networks more vulnerable to all kinds of Layer7/Layer3 attacks.

In this blog post, we will walk through how we have strengthened security and monitoring over our public VPN instance, which was kept in the public VPC, keeping an ever-watchful eye out for unusual traffic patterns or content that could signify a network intrusion using [AWS VPC Traffic Mirroring](https://docs.aws.amazon.com/vpc/latest/mirroring/traffic-mirroring-how-it-works.html) and a network intrusion detection system.

VPC traffic mirroring duplicates inbound and outbound traffic for [Amazon EC2](https://aws.amazon.com/ec2/) instances within a VPC without the need to install anything on the instances themselves. The idea is to send this duplicated traffic to the network intrusion detection system (NIDS) for analysis and monitoring. Here is how the architecture diagram of monitoring network intrusion looks like:

![AWS VPC Traffic Mirroring](https://d22k7geae6sy8h.cloudfront.net/files/64b4797e93900b0009d315ad/9lk61yjx5-CRED-1.png)

Any traffic that comes to the VPN server is sent to the mirror target (network load balancer) that serves as a destination for the mirrored traffic. VPC traffic mirroring provides a great feature of mirror filters where one specifies the inbound or outbound (with respect to the source) traffic that is to be captured (accepted) or skipped (rejected). From the mirror target, we send the duplicated traffic to the NIDS system using Suricata, which is an open source network threat detection engine that provides capabilities including intrusion detection (IDS), intrusion prevention (IPS), and network security monitoring. The reason we picked Suricata was that it does extremely well with deep packet inspection and pattern matching, making it incredibly useful for threat and attack detection. It also has multi-threading, which provides the theoretical ability to process more rules across faster networks, with larger traffic volumes, on the same hardware.

For greater resiliency and availability, we send duplicate traffic to an EC2 instance with a Suricata setup. We use Amazon EC2 T3 Instances for this purpose. This was intentionally chosen since we knew that there would be a high amount of traffic at any time and performance and efficiency were the other 2 criteria that we wanted to achieve. All of these were met by T3 instances that provide a baseline level of CPU performance with the ability to burst CPU usage at any time for as long as required.

### Monitoring and Logging

The Suricata instances have Filebeat agent installed, which is a lightweight shipper for forwarding and centralizing log data. Suricata performs continuous monitoring over the traffic, Suricata rules (/etc/Suricata/rules) will trigger alerts, and then Filebeat sends alert logs to ELK stack where logstash processes the JSON data. We are using the Suricata module in the self hosted Amazon [OpenSearch Service](https://aws.amazon.com/opensearch-service/) (successor to Amazon Elasticsearch Service), which performs the following tasks for us:

- Uses ingest node to parse and process the log lines, shaping the data into a structure suitable for visualizing in Kibana
- Deploys dashboards for visualizing the log data

We can monitor the geographical distribution of traffic coming into our system using Kibana's Coordinate Map visualization. The event_type field indicates the Suricata log type. With the help of a pie chart visualization, we can see a breakdown of the top log types recorded in the system.

As can be seen in the image, we have categorized the alerts based on their severity as High, Medium, and Low. Categorization of events are handled at two places:

1. One at VPC "Mirror Filters"
2. Second using Suricata rules to identify protocol and categorize anomalies in events.

For now, we are using the default rule set provided by Suricata. It includes malicious IP reputation check, suspicious User agent, signature based intrusion, policy violation, traffic anomaly and much more. One of the examples given in the pie chart visualization shows where Suricata found some tor activity on the network along with some other network anomaly. The remediation process goes through central logging, alerting, and decision framework. We have configured the below parameters for the visibility over the dashboard:

- Alert count
- Alert top 10 signature
- Alert top 20 source IP
- Alert top 20 destination IP
- Alert severity
- Alert timeline
- DNS event over time

![Final Outcome](https://d22k7geae6sy8h.cloudfront.net/files/64b47a2a93900b0009d315af/9lk6228vk-CRED-3.jpg)

### Final Outcome

VPC traffic mirroring makes it much easier for us to monitor network traffic within our AWS VPCs. With the help of VPC traffic mirroring, we are now effectively able to monitor network traffic, analyze traffic patterns, and proactively detect malicious traffic. Some of the benefits it provides are:

- **Detect network & security anomalies** – Extracting traffic of interest from any workload in a VPC and routing it to the detection tools of your choice and detecting and responding to attacks more quickly than is possible with traditional log-based tools.
- **Gain operational insights** – Using VPC traffic mirroring to get the network visibility and control that will let you make security decisions that are better informed.
- **Implementation of compliance & security controls** – Meeting regulatory & compliance requirements that mandate monitoring, logging, and so forth.

Suricata is a great open source option for monitoring networks for malicious activity. We will be enhancing our Suricata integration with additional rules and dashboards going forward.

---

> _Author: AWS Editorial Team_

_The AWS Startups Content Marketing Team collaborates with startups of all sizes and across all sectors to deliver exceptional content that educates, entertains, and inspires._

---

_Source: [AWS Startups](https://startups.aws/startups/learn/cred-achieves-a-high-level-of-network-inspection-with-vpc-traffic-mirroring)_
