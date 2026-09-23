---
source_url: https://aws.amazon.com/startups/learn/transforming-payments-how-startups-are-pioneering-stablecoin-infrastructure-on-aws
title: "Transforming Payments: How Startups Are Pioneering Stablecoin Infrastructure on AWS"
---

## Transforming Payments: How Startups Are Pioneering Stablecoin Infrastructure on AWS

_From emerging market innovations to Wall Street institutions, startups and enterprises are embracing stablecoins for faster, cheaper, and safer payment solutions._

---

Stablecoins have moved to the center of global finance. Today, they underpin trillions of dollars in transaction volume, from cross-border instant settlements to decentralized finance (DeFi), programmable treasury flows, and beyond. In 2024, stablecoins processed over USD $27.6 trillion in onchain volume. In April 2025, Citi's [Digital Dollars report](https://www.citigroup.com/global/insights/digital-dollars) forecast that, even at its base level, the total circulating supply of stablecoins could grow to USD $1.6 trillion by 2030. But the report also allows for that figure to climb as high as USD $3.7 trillion, adding that stablecoin issuers could become major holders of US Treasuries by 2030, with reserve requirements creating a significant new source of demand for dollar-denominated assets.

Why the appeal? Unlike volatile cryptocurrencies, stablecoins maintain stable value by pegging their price to reference assets—most commonly flat currencies like the U.S. dollar—with reserves typically backed by highly liquid assets such as government bonds, corporate debt, or other cash equivalents. The effectiveness of this stability depends heavily on the underlying collateral quality, reserve management, and peg mechanism used. They offer the flexibility of digital assets with the predictability of traditional finance. Stablecoins are built using smart contracts, which are pieces of programmable code running on blockchains. These smart contracts allow for automatic execution of instructions based on pre-defined conditions, without human intervention. For startups, they represent something even more valuable: an opportunity to build new financial and payment infrastructure.

Stablecoins are being used at scale. As of April 2025, the total outstanding supply of stablecoin had crossed USD $230 billion, an increase of 54 percent since April 2024. With the support of secure, scalable, and compliant infrastructure behind them, startups around the world are moving fast.

---

## Why Stablecoins Matter

For startups operating in or across emerging markets, financial friction is a familiar challenge: cross-border payments are slow, FX and wire transfer fees are high, and treasury management is inefficient. Today, most stablecoin volume comes from trading activity, with Citi estimating that this amounts to 90–95%. However, that share is expected to decline as new utility-driven use cases take hold. As Chris Dixon, founder of the a16z crypto investment fund, explains in [Stablecoins: Payments Without Intermediaries](https://a16zcrypto.com/posts/article/stablecoins-payments-without-intermediaries/), stablecoins can bypass costly legacy payment rails: "Stablecoins are our first real shot at doing for money what email did for communication: make it open, instant, and borderless."

"Consider [also] the evolution of text messaging. Before apps like WhatsApp, sending a text across borders meant paying 30 cents per message. Even then, you were lucky if it actually got delivered," adds Dixon. "Then came internet-native messaging: instant, global, free. Payments are now where messaging was in 2008: Fragmented by borders. Burdened by middlemen. Gatekept by design. Stablecoins offer a clean-slate alternative."

By enabling instant, low-cost settlement and programmable features, stablecoins unlock a new layer of financial access and innovation:

- Cross-border B2B payments with reduced FX friction
- Dollar-pegged payroll and treasury management in volatile economies
- Remittances with lower fees and faster settlement
- In-app programmable money and tokenized loyalty systems

With the right licensed infrastructure partner, companies can now integrate stablecoins without having to take on the additional regulatory lift in-house. On July 18, 2025, the U.S. President signed into law the GENIUS Act, establishing the first federal regulatory framework for payment stablecoins. The Act classifies them as payment tools that are neither securities nor commodities, and mandates full backing of payment stablecoins on a 1:1 basis with U.S. dollars, federal reserve notes, or short-term U.S. Treasury securities, along with transparency and monthly reserve reporting requirements, removing uncertainty for banks, fintechs, and their infrastructure partners. The Act also places oversight under banking regulators including the Federal Deposit Insurance Corporation (FDIC), Office of the Comptroller of the Currency (OCC), and Federal Reserve, depending on issuer type.

---

## Powering Stablecoin and Tokenization Infrastructure at Scale

[zerohash](https://zerohash.com) delivers the behind-the-scenes infrastructure that enables enterprises to launch crypto, stablecoin, and tokenization products in weeks as opposed to years. Through robust APIs and SDKs, the company abstracts away the complexity of multi-asset custody, liquidity, settlement, and regulatory compliance, allowing customers to focus on user experience while zerohash handles the rails. Today, it powers 75+ enterprise clients, 5M+ end-users verified through Know Your Customer (KYC) compliance processes, and over USD $60 billion in transactions.

Able to operate in 200+ jurisdictions worldwide (including every US state and territory) zerohash holds a US trust company charter, two New York BitLicenses, nationwide Money Transmitter Licenses, and FinCEN registrations, operating where others can't. Enterprise partners such as Interactive Brokers, Franklin Templeton, and Stripe use its infrastructure for everything from tokenized fund flows to global payment on-ramps.

Built on AWS, zerohash runs [Amazon EKS](https://aws.amazon.com/eks/) with managed [Karpenter](https://karpenter.sh) to optimize workloads, while [AWS Nitro Enclaves](https://aws.amazon.com/ec2/nitro/nitro-enclaves/) secures Multi-Party Computation (MPC) signing algorithms and attestation processes. This architecture delivers millions of transactions per second with API response times averaging 50ms and remaining under 200ms at the 99th percentile, and uptime exceeding 99.99 percent. By combining technical abstraction, enterprise-grade scalability, and unmatched regulatory reach, zerohash turns stablecoins into a practical, compliant, and high-performance tool for modern finance, bridging the gap between traditional systems and the onchain economy.

For [Yellow Card](https://yellowcard.io), stablecoins aren't just a technical innovation, they're a lifeline. Founded to tackle the high costs of sending money to and within Africa, Yellow Card has grown into the largest and first licensed stablecoin-based infrastructure provider in Africa. Operating in over 20 countries, the platform has processed more than USD $6 billion in transactions.

What began as a consumer-facing crypto app has evolved into a regulated infrastructure partner for global businesses. Yellow Card now enables cross-border payments, treasury management, and liquidity services for institutions navigating the continent's fragmented financial landscape.

"We run our core services on [AWS Lambda](https://aws.amazon.com/lambda/) and [DynamoDB](https://aws.amazon.com/dynamodb/)," says Yellow Card's CTO, Justin Poiroux. "That gives us serverless, auto-scaling infrastructure that responds in milliseconds, reduces our operational costs by 40–50 percent, and helps us maintain >99.9 percent uptime."

Gen AI tooling such as [Amazon Bedrock](https://aws.amazon.com/bedrock/) has enabled the company to develop in-house Agentic systems that power key operational workflows in a scalable, cost-effective manner. These systems, paired with [Amazon Relational Database Service](https://aws.amazon.com/rds/) (RDS), Amazon EKS, and [Amazon EC2](https://aws.amazon.com/ec2/) handling persistent workloads, enable Yellow Card to process real-time currency conversions and compliance checks across more than 20 markets.

AWS AI and machine learning tools sharpen risk management and deliver richer liquidity insights through the company's over-the-counter (OTC) desk and Treasury Portal.

The results are clear:

- Scaled to 20+ countries with no physical data centers
- Reduced operational costs by 40–50 percent
- Delivered stable, secure payment rails for enterprise partners including Coinbase and Visa

---

## Building Compliant Crypto Infrastructure for Enterprises

[Bastion](https://www.bastion.com) was founded to simplify the hardest parts of launching crypto-powered products: compliance, custody, and infrastructure. Created by the team behind Meta's now sunset Novi wallet, Bastion delivers white-label APIs for enterprises to issue and manage stablecoins, and securely manage digital assets.

From day one, Bastion identified a gap: most cloud infrastructure wasn't built for the unforgiving demands of regulated crypto key management. "When you're building systems that combine disaster recovery, secure compute, and regulated custody of high-value assets, you realize the existing playbooks don't go far enough," says Robert Coleman, Head of Security Engineering at Bastion.

The solution? Bastion uses [Amazon Elastic Kubernetes Service](https://aws.amazon.com/eks/) (EKS) to orchestrate services at scale and [Amazon CloudFront](https://aws.amazon.com/cloudfront/) to minimize latency for users worldwide. For key custody, they combine [AWS Nitro Enclaves](https://aws.amazon.com/ec2/nitro/nitro-enclaves/) with [AWS CloudHSM](https://aws.amazon.com/cloudhsm/) to isolate and protect cryptographic operations. Nitro Enclaves provides cryptographic attestation of enclave identity and integrity when accessing sensitive data, while CloudHSM's features include optional quorum-based authentication where multiple officers can be required to approve sensitive operations. That means no single individual can unilaterally move funds or alter controls.

Secure key ceremonies are another layer of defense: hardware is shrink-wrapped until the moment of use, and laptops are wiped and destroyed after configuration to eliminate any chance of compromise. "No one person can be given the power to undermine our entire company's security," says Coleman.

With AWS as the backbone, Bastion delivers a compliance-ready, enterprise-grade environment for launching stablecoin-powered features, enabling their customers to move fast, stay secure, and meet today's most demanding regulatory standards without building the complexity in-house.

---

## How AWS Supports Stablecoin Innovation

Behind every stablecoin company is a complex infrastructure challenge. How do you build platforms that move money, in real time, with zero tolerance for downtime or regulatory missteps? Startups like zerohash, Yellow Card, and Bastion all navigate these challenges with AWS because it allows them to move fast and meet the mission-critical demands of modern finance.

Stablecoin platforms need to maintain reserves, run continuous compliance checks, and process millions of micro-transactions across borders, all while keeping latency low and uptime near perfect. AWS helps by providing the security and scalability to safeguard reserves, the analytics and AI tools to monitor liquidity in real time, and the confidential computing environments to protect cryptographic keys that underpin stablecoin issuance and redemption.

Some of the ways AWS supports this include:

- **Global reach:** 117 Availability Zones across 37 Regions, 700+ CloudFront Points of Presence (POPs) for sub-100ms response times
- **Low latency performance:** up to 400 Gbps per network card with [AWS Nitro System](https://aws.amazon.com/ec2/nitro/), sub-millisecond Redis for real-time balance checks
- **Resilience at scale:** [AWS Auto Scaling](https://aws.amazon.com/autoscaling/), [Amazon RDS](https://aws.amazon.com/rds/) Multi-AZ failover in under 60 seconds, [AWS Global Accelerator](https://aws.amazon.com/global-accelerator/) for consistent cross-border performance
- **Security and compliance:** 140+ certifications (SOC, PCI, FedRAMP, and more), with [Amazon GuardDuty](https://aws.amazon.com/guardduty/), [AWS CloudTrail](https://aws.amazon.com/cloudtrail/), and [AWS Config](https://aws.amazon.com/config/) for real-time monitoring, all under AWS's [Shared Responsibility Model](https://aws.amazon.com/compliance/shared-responsibility-model/) continuously improving security posture
- **Prescriptive guidance:** AWS reference architectures and blueprints to accelerate the development of core stablecoin solution components, including [AWS Blockchain Node Runners](https://github.com/aws-samples/aws-blockchain-node-runners/blob/main/website/docs/getting-started/intro.md), [wallets](https://aws.amazon.com/blogs/web3/build-secure-multi-party-computation-mpc-wallets-using-aws-nitro-enclaves/), and crypto payment [workflows](https://github.com/aws-samples/sample-serverless-digital-asset-payments)

This support represents a real, in-reach opportunity to rethink payments, liquidity, and customer value. AWS provides the compliance frameworks, confidential computing, and automated threat detection that stablecoin platforms demand with the ability to go live in weeks. AWS has become the hub for Web3 projects, startups, software companies, and global exchanges; builders can use the [AWS Partner Network](https://aws.amazon.com/partners/work-with-partners/) and the broader ecosystem of fintech and crypto partners.

Accelerate your digital asset, stablecoin, or fintech startup with up to $100,000 in AWS cloud credits. Build secure blockchain infrastructure and leverage AI models on Amazon Bedrock to scale faster while extending your runway. Apply for [AWS Activate Credits](https://aws.amazon.com/startups/credits) today.

---

## About the Author

### Brad Feinstein

Brad Feinstein is a GTM leader who builds and scales businesses at the intersection of enterprise technology and startups, with a focus on cloud, AI, and Web3. He leads AWS's North America Startup FinTech & Web3 team, partnering with top startups and venture capital firms to accelerate market adoption and drive co-sell success. His experience includes leading GTM partnerships for international startups at AWS, serving as Head of Global Business Development at ConsenSys, and founding two venture-backed companies. Brad also held senior roles at Amex & Capgemini. He blends founder-level execution with enterprise scale to deliver customer success.

---
