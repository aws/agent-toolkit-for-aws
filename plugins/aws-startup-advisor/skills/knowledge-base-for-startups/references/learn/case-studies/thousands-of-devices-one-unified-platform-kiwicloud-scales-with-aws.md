---
source_url: https://aws.amazon.com/startups/learn/thousands-of-devices-one-unified-platform-kiwicloud-scales-with-aws
title: "Thousands of devices, one unified platform: KiwiCloud scales with AWS"
---

## Thousands of devices, one unified platform: KiwiCloud scales with AWS

[Watch the video on YouTube](https://www.youtube.com/watch?v=NZoYm0IJ60g)

Singapore-based startup [KiwiCloud](https://kiwi.cloud/) migrated its Unified Endpoint Management (UEM) platform to AWS, using services including [Amazon Elastic Kubernetes Service](https://aws.amazon.com/eks/) (EKS), [AWS IoT Core](https://aws.amazon.com/iot-core/), and [Amazon Managed Streaming for Apache Kafka](https://aws.amazon.com/msk/) (MSK), to support growth across global markets. With nearly 14,580 Device Shadows deployed globally and a policy reach rate of nearly 100 per cent, the AWS-powered platform has helped KiwiCloud secure commitments for nearly one million devices worldwide.

---

KiwiCloud enables enterprises to securely manage connected devices on a global scale, from a single Unified Endpoint Management (UEM) platform. Faced with latency and integration challenges, KiwiCloud decided to migrate its UEM to AWS. Working with the AWS team, the startup built the foundation to scale its UEM across regions while strengthening security and compliance capabilities required by its enterprise customers.

Many businesses already have to manage people and physical infrastructure across geographies and time zones. Now, they also have to manage a growing number of devices those people rely on. These include not only smartphones and tablets, but laptops, desktops, wearables, IoT devices and point-of-sale (POS) terminals. Each needs to be secure, compliant with industry standards and regulations, regularly updated, and available when needed. This presents a number of challenges to enterprises and their IT teams, many of which still rely on fragmented tools and manual processes to manage devices. Mixed device fleets are hard to centralize; there’s a risk of security gaps without unified policy enforcement; on-site IT support is costly; and delayed updates can disrupt operations.

### From POS terminals to IoT endpoints

KiwiCloud aims to solve these challenges. “Our mission is to simplify device management for enterprises worldwide,” says Xibang Lin, CEO of KiwiCloud. “Our unified endpoint management platform helps the company from POS terminal to IoT endpoint, all in one place.” Using the solution, teams can deliver remote installations, update and remove apps, as well as distribute corporate data. Content and app management also gives administrators control over access to data and content, strengthening security.

As KiwiCloud embarked on its mission to support enterprises across the world, it faced a challenge of its own. The legacy infrastructure powering its IoT service was not built for the global scale it had envisioned. “Previously we hosted our IoT service on another cloud which has created global latency and limited integration options,” explains Lin. “That prevented us from building a truly unified and scalable UEM platform.” Remaining with its legacy provider presented a barrier to growth, limiting both the evolution of KiwiCloud’s business and the level of service it could provide to its customers.

### Multi-phase migration

KiwiCloud partnered with AWS and embarked on a multi-phase migration. “AWS’s global infrastructure, mature service ecosystem, and enterprise-grade reliability made it the ideal choice to power our international coverage,” says Lin. The startup worked closely with the AWS team, deploying services including [Amazon Elastic Kubernetes Service](https://aws.amazon.com/eks/) (EKS), [AWS IoT Core](https://aws.amazon.com/iot-core/), and Amazon MSK, to build a cloud-native UEM solution with enhanced commercial device management efficiency and compliance support. “We built routing gateways to migrate legacy devices without replacing firmware, and created a multiple Availability Zones microservices architecture for fault tolerance and elasticity,” explains Lin. “For security and performance, we integrated AWS VPC Peering, [Elastic Load Balancing](https://aws.amazon.com/elasticloadbalancing/) (ELB), and [AWS Web Application Firewall](https://aws.amazon.com/waf/) (WAF).”

Enterprise IoT devices connect to AWS IoT Core and publish data to Amazon MSK, and microservices running on Amazon EKS consume that data in real time. ELB manages traffic distribution, WAF secures entry points, and VPC Peering keeps communication internal to AWS.

At the center of KiwiCloud’s UEM platform are its core applications. These run on Amazon EKS, which provides the scalable application infrastructure KiwiCloud requires to run and manage its platform as it expands across markets.

In addition to running the platform efficiently, KiwiCloud also needs to maintain a reliable link between its cloud-based UEM and the physical devices it manages. These devices must be managed even when they are offline, for example, if a POS terminal in a remote location loses connection. Using Device Shadows in AWS IoT Core, KiwiCloud can maintain a digital representation, of each device in the cloud. KiwiCloud’s UEM platform retains the device’s state and policies while it’s offline, then synchronizes them once connectivity is restored. Device fleets remain consistent and enterprises get a real-time view of policies and deployments across all of their endpoints. With nearly 14,580 Device Shadows deployed globally and a policy reach rate of nearly 100 per cent, this AWS-powered capability has helped KiwiCloud secure commitments for nearly one million devices worldwide.

### Reduced latency, higher uptime & consistent performance

KiwiCloud was able to build its platform while continuing to support its growing customer base. “With account support, we engaged AWS teams like the customer optimization and acceleration team to boost strong cost governance foundation during the migration,” says Lin. This gave KiwiCloud greater visibility and control over costs during the migration while helping it establish cost-governance practices from the outset, which it could carry forward as the platform scaled.

With AWS-backed infrastructure powering KiwiCloud’s UEM, its enterprise customers are now experiencing reduced latency for real-time device operations, higher uptime for mission-critical remote management, and consistent performance across global regions. “Whether a retail manager is updating POS terminals in Singapore or troubleshooting kiosks in Europe, KiwiCloud delivers the same fast, reliable experience, eliminating the regional performance gaps that plagued traditional setups,” says Lin.

Going forward, KiwiCloud plans to migrate its self-managed middleware to AWS-managed services such as [Amazon DocumentDB](https://aws.amazon.com/documentdb/), [Amazon ElastiCache](https://aws.amazon.com/elasticache/), and [Amazon OpenSearch Service](https://aws.amazon.com/opensearch-service/) to further enhance reliability and reduce maintenance complexity. “AWS will continue to empower KiwiCloud to deliver on its mission to redefine how enterprises manage connected devices in the cloud era,” says Lin.
