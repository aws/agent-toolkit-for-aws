# IoT — Startup Decision Guide

## The IoT Cost Curve: Why Startups Get Surprised

IoT costs are multiplicative: `devices × messages/device × actions/message`. A fleet of 10,000 devices sending 1 msg/sec generates 864M messages/day. Startups that prototype with 10 devices don't see this coming.

### Cost at Scale (Monthly Estimates)

| Fleet size     | Msg frequency | IoT Core messaging cost | Storage cost (Timestream) | Total minimum |
| -------------- | ------------- | ----------------------- | ------------------------- | ------------- |
| 100 devices    | 1/min         | $4                      | $20                       | ~$50          |
| 1,000 devices  | 1/min         | $44                     | $200                      | ~$400         |
| 10,000 devices | 1/min         | $440                    | $2,000                    | ~$4,000       |
| 10,000 devices | 1/sec         | $26,400                 | $120,000                  | 🚨            |

**The lesson**: Message frequency is the cost multiplier. Design for the lowest frequency that meets product requirements. If you need 1/sec sensing but only 1/min cloud reporting, aggregate at the edge.

## Stage-Specific Architecture

| Stage                    | Fleet size | Architecture                                                              | What to skip                                                                   |
| ------------------------ | ---------- | ------------------------------------------------------------------------- | ------------------------------------------------------------------------------ |
| Prototype (< 50 devices) | < 50       | IoT Core → Rules → DynamoDB/S3. Done.                                     | Greengrass, SiteWise, Fleet Indexing, Device Defender                          |
| Pilot (50-1000 devices)  | 50-1K      | Add: Device Shadow, Fleet Provisioning, basic monitoring                  | SiteWise (unless industrial), multi-region, Greengrass (unless offline needed) |
| Scale (1K-100K devices)  | 1K-100K    | Add: Greengrass edge compute, Fleet Indexing, Device Defender, Timestream | Custom analytics platform (use Timestream + Grafana)                           |
| Enterprise (100K+)       | 100K+      | Full stack: multi-region, SiteWise if industrial, custom data lake        | Nothing — you need it all                                                      |

## Cost Traps Specific to Startups

### 1. Basic Ingest: The $1/Million Messages You Don't Need to Pay

Standard MQTT publish: $1.00 per million messages broker fee + rules engine fee.

<!-- markdownlint-disable-next-line MD033 -->

Basic Ingest (`$aws/rules/<rule-name>` topic): $0 broker fee, only rules engine actions charged.

**Use Basic Ingest for all high-volume telemetry that only needs to flow to the cloud (no device-to-device).** Most startup telemetry is one-directional. This saves 50% on messaging costs with a topic prefix change.

### 2. Timestream vs S3+Athena: When to Use Which

| Need                                     | Choice                                     | Monthly cost at 10K devices, 1 msg/min |
| ---------------------------------------- | ------------------------------------------ | -------------------------------------- |
| Real-time dashboards, sub-second queries | Timestream                                 | ~$2,000                                |
| Nightly batch analytics, ad-hoc queries  | S3 + Athena                                | ~$50-100                               |
| Both                                     | Timestream for last 24h, S3 for historical | ~$500 (short memory retention)         |

**Startup default**: S3 + Athena until you have a real-time dashboard requirement. Most seed-stage IoT startups query telemetry weekly, not in real-time.

### 3. DynamoDB for Telemetry: The $1,100/Day Mistake

10,000 devices × 1 msg/sec = 864M writes/day = ~$1,100/day on-demand DynamoDB.

**Never store raw time-series telemetry in DynamoDB.** Use it only for device metadata, latest-known state, and configuration. Route telemetry to Timestream (10-20x cheaper for time-series writes) or S3 ($0.023/GB/month).

### 4. OpenSearch for IoT Dashboards: The Always-On Cost

OpenSearch clusters run 24/7 (~$200-500/month minimum). If your dashboard usage is intermittent (operators check once/day), use:

- Timestream + Grafana (serverless-ish, cheaper for periodic access)
- S3 + Athena + QuickSight (fully serverless, pay per query)

### 5. Cellular Data Costs That Dwarf AWS Costs

Hardware startups often overlook this: a cellular modem (LTE-M/NB-IoT) costs $0.50-2.00/MB depending on carrier. A device sending 1KB every minute = 1.4MB/month = ~$1-3/device/month in CARRIER costs alone. At 10K devices, that's $10-30K/month before AWS sees a single byte.

**Optimization**: Aggregate readings on-device and send batched payloads every 5-15 minutes instead of per-reading. Compress with CBOR instead of JSON (40-60% smaller). This directly reduces your carrier bill — often your largest IoT cost at scale.

## Counterintuitive Advice for IoT Startups

### Don't Start with Greengrass

Greengrass adds significant operational complexity (component deployments, edge device management, Nucleus updates). Start with direct MQTT to IoT Core unless you have one of these hard requirements:

- **Must operate offline** (no cloud connectivity for hours/days)
- **Latency < 100ms for control loops** (cloud round-trip is 50-200ms)
- **Bandwidth costs dominate** (cellular data at $0.01/MB with high-frequency sensors)

**When to add Greengrass**: When your cloud ingestion bill exceeds the operational cost of managing edge infrastructure, OR when you have a hard offline/latency requirement.

### One Certificate Per Device (Even If It's Painful)

Shared certificates are tempting for prototypes ("just get devices connected"). But revocation of a shared cert disconnects your entire fleet. The migration from shared → per-device certs is painful at scale. Start with per-device certs from day one using Fleet Provisioning by Claim.

### Fleet Provisioning: Don't Overthink It

| Manufacturing capability                   | Method                             | Startup phase                           |
| ------------------------------------------ | ---------------------------------- | --------------------------------------- |
| Can't install unique certs (most startups) | Fleet Provisioning by Claim        | Use from day one                        |
| Have a mobile app for setup                | Fleet Provisioning by Trusted User | Consumer IoT                            |
| Factory installs unique certs              | JITP                               | Later stage, when you own manufacturing |

**Critical**: Always add a pre-provisioning Lambda hook to validate device serial numbers against an allow-list. Without it, anyone who reverse-engineers your firmware can provision unlimited devices.

### Your Firmware Update Story Is Your Company's Survival Story

IoT startups that can't OTA update their fleet die slowly. A bug in the field with no update path means:

- Hardware recalls ($50-200/device in logistics alone)
- Customer churn from unresolvable issues
- Inability to iterate on the product post-deployment

**From day one**: Even if you skip everything else, implement IoT Jobs-based OTA updates with rollback. Configure abort criteria (>5% failures = halt rollout). Test the update path before shipping your first 10 devices. The cost of getting this wrong at 1,000 devices is company-ending for a hardware startup.

## IoT + AI: When to Run ML at the Edge

| Signal                                   | Where to run inference          | Why                                                    |
| ---------------------------------------- | ------------------------------- | ------------------------------------------------------ |
| < 10 inferences/hour, small payload      | Cloud (Lambda or Bedrock)       | Simpler, no edge ML complexity                         |
| > 100 inferences/hour OR latency < 200ms | Edge (Greengrass + local model) | Bandwidth/latency requirements justify edge complexity |
| Camera/video data                        | Edge always                     | Streaming video to cloud is prohibitively expensive    |
| Model > 500MB, device has < 2GB RAM      | Cloud                           | Model doesn't fit on device                            |

## The Hardware-Software Timing Trap

Software startups iterate weekly. Hardware startups iterate quarterly (PCB rev cycles). This mismatch kills IoT startups that plan cloud architecture in lockstep with hardware timelines.

**What to do**: Over-provision your cloud capabilities relative to hardware. Your first PCB will be wrong. Your second will be better. Your cloud architecture needs to absorb both without re-architecture. Specifically:

- Design topic structures that accommodate device types you haven't built yet
- Use Device Shadow for ALL configuration (don't hardcode anything on-device that might change)
- Build your provisioning flow for "devices we haven't designed" — because you'll have 3 hardware revisions running simultaneously within 18 months

## The "Connected Product" vs "IoT Platform" Decision

Most IoT startups start thinking they're building a platform. They're not. They're building one connected product.

| You're building a... | Architecture approach                                  | Skip                                                                  |
| -------------------- | ------------------------------------------------------ | --------------------------------------------------------------------- |
| Connected product    | Single device type, simple rules, focused dashboard    | Multi-tenancy, device type abstraction, white-labeling infrastructure |
| IoT platform/SaaS    | Multi-tenant from day one, device-type-agnostic ingest | Nothing — but hire for this complexity                                |

**90% of seed-stage "IoT platforms" should be connected products first.** Build the platform abstraction only after you have 3+ customers wanting different device types. The premature platform trap wastes 6-12 months of engineering on infrastructure your first 5 customers don't need.

## Startup-Specific Gotchas: Investor & Go-To-Market

### The Pilot-to-Paid Chasm

IoT startups often give away 50-200 devices as "pilots." The architecture cost at pilot scale ($50-400/month from the tables above) is trivial. But the customer expects the same architecture when they order 10,000 devices — and that's $4,000+/month.

**Before the pilot**: Model the cost at the customer's target fleet size. If the unit economics don't work (cloud cost per device > willingness to pay), you have a business model problem, not a technology problem. Discover this before the pilot, not after.

### Hardware Margins Are Thin — Cloud Costs Eat Them

A typical hardware startup's BOM cost is $50-200/device with 40-60% gross margins on hardware sale. If your cloud cost is $5/device/month and customer pays $10/device/month for the "subscription" — your cloud COGS is 50% of recurring revenue before you pay for anything else.

**Model this explicitly for investors**:

- Hardware margin: X%
- Recurring revenue per device: $Y/month
- Cloud cost per device at target scale: $Z/month
- Net recurring margin: $(Y-Z)/Y

If Z > 30% of Y, optimize your architecture before scaling, not after.

### The "Free Tier Pilot" Illusion

IoT Core free tier: 500,000 messages/month for 12 months. That's ~11 messages/minute across your entire fleet. With 50 pilot devices sending 1 msg/min, you burn through free tier in 7 days.

Don't promise "zero cost pilot" to customers based on free tier math. It doesn't scale to even modest pilots.

## Anti-Patterns (Startup-Specific)

- **Designing for 1M devices at 100 devices.** The architecture for 100 devices (direct MQTT, no edge compute, DynamoDB for state) is radically different from 1M devices. Build for 10x your current fleet, not 10,000x. Premature scaling wastes months of engineering time.
- **HTTP polling from battery-powered devices.** A device polling every 5 seconds: 17,280 requests/day, drains battery in weeks. MQTT persistent connection: near-zero overhead when idle, battery lasts months. This is the #1 hardware startup mistake.
- **No error actions on IoT Rules.** Failed rule actions silently drop data. You won't know you're losing telemetry until a customer complains about missing data. Always route errors to S3 or SQS — takes 5 minutes to configure.
- **Timestream with default memory retention (24h) for dashboards needing 7-day views.** You'll query magnetic store (10x slower, different pricing model). Set memory retention to match your hot-query window.
- **Building a "device management portal" before device #100.** Your first 50 devices can be managed with AWS Console + CLI scripts. The custom portal takes 2-3 months of engineering time that should go toward the core product. Build it when operators (not engineers) need to manage the fleet.
- **Choosing WiFi-only when customers have industrial sites.** Consumer IoT = WiFi. Industrial/commercial IoT = often no reliable WiFi. If your customer is a factory, warehouse, or field operation, design for cellular (LTE-M/NB-IoT) from prototype. Retrofitting connectivity is a hardware redesign.
- **Not budgeting for device returns and RMA.** 5-10% of deployed IoT devices will have issues in year one. Your architecture needs: remote diagnostics (shadow + logs), remote remediation (OTA), and graceful decommissioning (cert revocation, thing deletion). Without these, every issue is a $50-200 truck roll or RMA.
- **Shared X.509 certificates across devices.** Revoking one shared cert disconnects entire fleet. One cert per device limits blast radius.

## Credits-Specific Guidance

- IoT Core messaging, Rules Engine actions, and Device Shadow operations are all credit-eligible
- **Timestream burns credits fast** — 10K devices at 1 msg/min with 7-day memory retention = ~$2K/month in credits consumed
- During credits: use Timestream generously to validate your real-time dashboard needs. If you discover nobody looks at real-time data, switch to S3+Athena before credits expire and save $2K/month
- Greengrass has no per-device cloud cost (it's edge software) — but the devices it runs on aren't free. Factor in the $15-50/device compute module cost in your BOM
