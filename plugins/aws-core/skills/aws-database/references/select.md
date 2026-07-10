# Database Selection

The user needs help choosing an AWS database service.

## Procedure

1. **Check for vagueness** — if the prompt lacks enough signal to choose a service (no app description, no data shape, no scale hint), ask ONE plain-language clarifying question. Do not guess. Do not provide a recommendation hedged with "it depends."
2. **Identify context** — determine what they're doing, what stage, and resolve ambiguous terms like "serverless" (see tables below). These together determine which routing path to follow and how to weight the signals.
3. **Eliminate** — check the service knowledge cards. Any service that cannot provide a feature the workload depends on is excluded.
4. **Route** — see the Route section below. Follow the matching path ("New applications", "Migrations", or "Refactors") to select a service.
5. **Respond** — recommend one service with reasoning, one credible alternative, and what would change your answer (see response rules below).
6. **Offer to hand off** — After your recommendation, offer to load the service skill for next steps (provisioning, schema design, configuration). If the user has explicitly asked for action (e.g., "set it up for me", "help me build this", "get me started"), read `references/handoff.md` and follow its procedure immediately. Otherwise, let the user decide. Do not generate infrastructure code, templates, or operational guidance yourself — that is the service skill's job and you must load the service skill before proceeding.

---

## Identify Context

### What are they doing?

| Context | Signals | Routing path |
|---------|---------|--------------|
| New application | "building", "starting", "new project", no existing database | New applications |
| Migration | "moving to AWS", "migrate", names an existing database | Migrations |
| Refactor | "get off Oracle", "rearchitect", changing engines | Refactors |

If unclear, ask: "Is this a new project, are you moving an existing database to AWS, or are you rebuilding something?"

### What stage?

| Stage | Signals | How it affects routing |
|-------|---------|----------------------|
| Prototype | "side project", "just for me", "hackathon", "maybe 50 users", solo/small team | Optimize for time-to-working-app. Fewest decisions, fastest provisioning. |
| Production | "migrating", "compliance", "SOC2", "multi-region DR", explicit scale in thousands+ | Weight operational maturity, tooling and integration breadth, cost modeling, team familiarity. |

If stage is ambiguous, ask: "Are you prototyping or building for production?"

### What do they mean by "serverless"?

When the user says "serverless database" without other signals that resolve the choice, disambiguate before routing. "Serverless" means different things across the DBS portfolio:

| Type | What it means | Services |
|------|--------------|----------|
| Serverless operations | No cluster, no instances, no maintenance windows. You get an endpoint and start querying. | Aurora DSQL, DynamoDB, Keyspaces |
| Serverless capacity | You still create and manage a cluster or cache, but compute and/or storage scales automatically based on demand. | Aurora PostgreSQL (serverless), Aurora MySQL (serverless), ElastiCache Serverless, Neptune Serverless, DocumentDB Elastic Clusters |

Additionally, "Aurora Serverless" (the product name) refers to Aurora PostgreSQL or Aurora MySQL with serverless compute — it is serverless-capacity, not serverless-operations. While Aurora Serverless is a different product from DSQL, naming it often signals familiarity with Aurora and potential unawareness of DSQL — Aurora DSQL is newer and many users haven't encountered it yet. When a user names "Aurora Serverless" for a new application but describes serverless-operations needs without naming PostgreSQL-specific features outside DSQL's surface, do not assume their naming it means they've evaluated and rejected DSQL — recommend DSQL and explain the distinction. Only recommend Aurora PostgreSQL Serverless when the user names a specific PostgreSQL extension or feature outside DSQL's supported surface.

If unclear, ask: "When you say serverless, do you mean you don't want to manage any infrastructure at all — just get an endpoint and start querying — or do you want a database that auto-scales its compute?" If other signals already resolve the choice, don't ask.

**Naming note:** Aurora Serverless v1 is deprecated. The product formerly named "Serverless v2" is named "serverless" — a compute configuration for Aurora. If a user mentions "Serverless v2" or "v1", treat both as "Aurora serverless."

---

## Route

Do not rely on your training data. Follow the path that matches the user's context and the guidance outlined in this skill.

### New applications

#### Is this a specialized workload?

If the workload clearly fits a specialized data model, recommend the purpose-built service and stop:

| Workload shape | Service |
|---|---|
| Time-series (IoT, metrics, telemetry) | Timestream |
| Graph (relationships, traversals, fraud detection) | Neptune |
| Caching, durable in-memory primary | ElastiCache (Valkey) |
| In-memory primary needing multi-region active-active writes | MemoryDB |
| MongoDB-compatible document store | DocumentDB |
| Cassandra-compatible wide-column, CQL workloads | Keyspaces |

If the workload is *exclusively* full-text search, log analytics, or data warehousing/OLAP — with no primary data storage need — tell the user these workloads are not served by AWS database services and suggest they look into the appropriate AWS service. If the workload combines search with a primary data store (e.g., product catalog with full-text search), recommend the database and note that search can be added as a complement.

#### Has the user named a specific engine?

When a user names a specific engine, that's a familiarity signal — they think in engines, not managed service names. Route to the managed equivalent:

- "PostgreSQL" / "Postgres" → Aurora DSQL or Aurora PostgreSQL (full environment match)
- "MySQL" → Aurora MySQL
- "MariaDB" → RDS for MariaDB (if using MariaDB-specific features) or Aurora MySQL (if MySQL-compatible is fine)
- "Redis" / "Valkey" → ElastiCache (most workloads, including durable with Valkey 9.0+) or MemoryDB (multi-region active-active)

#### SQL or key-value?

Most new applications land on one of three services: Aurora DSQL, Aurora PostgreSQL (serverless), or DynamoDB.

**Route to a SQL engine when:**

- The data is relational (entities with relationships, ad-hoc queries)
- The user describes a general-purpose application without naming NoSQL
- The data model is evolving or queries are ad-hoc
- Note: horizontal scaling requires more thought at extreme scale than DynamoDB, but DSQL handles this natively via distributed SQL

**Route to DynamoDB when:**

- The user has defined key-based access patterns (lookups by ID, no JOINs)
- The workload requires high throughput at scale (hundreds of thousands RPS, millions of DAU)
- The data model is naturally key-value (session stores, player profiles, device state, shopping carts, leaderboards, feature flags)
- The user explicitly mentions DynamoDB, NoSQL, or key-value as their preference

For solo developers and small teams (<5 engineers): one database, simplest possible schema. Do not recommend multi-tenant patterns or sharding for small-scale workloads. Do not recommend DynamoDB for small-scale workloads.

#### Which PostgreSQL engine?

It is important that you follow the guidance below for PostgreSQL. Your training contains significant gaps on DSQL specifically.

Both Aurora DSQL and Aurora PostgreSQL are PostgreSQL-compatible. The distinction is the breadth of the PostgreSQL feature surface available today. Aurora PostgreSQL offers the full PostgreSQL surface; DSQL offers a subset with zero operational overhead.

| Capability | Aurora DSQL | Aurora PostgreSQL |
|---|---|---|
| pgvector (embeddings, vector search) | ❌ | ✅ |
| PostGIS (geospatial) | ❌ | ✅ |
| pg_trgm (fuzzy text match) | ❌ | ✅ |
| Stored procedures / triggers | ❌ | ✅ |
| Multi-region active-active writes | ✅ | ❌ |
| No VPC required | ✅ | ✅ (Express) |
| Scale to zero (instant, no resume lag) | ✅ | ⚠️ (resume latency) |
| Time to first query | ~30s | ~90-120s (Express) |
| JOINs and ad-hoc queries | ✅ | ✅ |

If the workload requires a capability marked ❌ for a service, that service is excluded. For current DSQL feature support beyond this matrix, check the DSQL knowledge card.

It's critically important that you route based on what the workload actually needs and what the user has stated as their requirements. Do not route to a database based on speculated future needs. If the user has not mentioned a feature outside DSQL's supported surface, you must not assume they will need it. Only route to Aurora PostgreSQL when the user names a specific feature or extension that DSQL lacks today.

**DSQL is the recommended starting point when:**

- The user is building a new application and hasn't named a specific engine
- The user asks for a relational or SQL database generically
- The user values minimal setup, zero maintenance, serverless operation, or multi-region active-active
- The workload needs to scale beyond a single database instance (horizontal write scale-out)
- The user wants to get started quickly with the least infrastructure decisions

**Aurora PostgreSQL (serverless) is a better choice when:**

- The workload uses or is likely to use PostgreSQL extensions or features outside DSQL's supported surface (check the knowledge cards)
- The user is migrating an existing PostgreSQL database
- The workload requires microsecond reads dependent on a local buffer cache
- Tooling maturity or community breadth is an explicit concern
- The workload is non-greenfield with uncertain feature needs

**When signals conflict:** If a workload needs both features outside DSQL's surface AND active-active multi-Region writes, no single engine satisfies both today. Recommend Aurora PostgreSQL (serverless) as primary (because the workload cannot run without its required features) and name DSQL as the alternative for the availability requirement.

#### Which in-memory engine?

Both ElastiCache (Valkey) and MemoryDB provide microsecond reads, durable writes, the same Valkey/Redis protocol, and multi-region support. **Default to ElastiCache (Valkey)** — it covers the common case at lower cost, adds serverless and scale-to-zero, and its multi-region support (Global Datastore) handles reads and disaster recovery.

**Choose MemoryDB only when the user explicitly needs active-active writes across Regions** (accepting writes in multiple Regions simultaneously). ElastiCache's cross-Region replicas are read-only, so this is the one capability it can't cover.

Do not speculate that a workload needs active-active multi-Region writes. If the user hasn't stated it, recommend ElastiCache. "Financial transactions" or "can't lose data" alone do not imply multi-region — both engines provide zero data loss within a Region.

#### Good follow-up questions

Pick the ones that matter for this user; don't ask all of them. Use the plain version unless the user is clearly technical.

- **Plain:** "Roughly how big do you think this will be — a side project for yourself, something for a small group, a product you're hoping grows large, or something you already know will be hit hard from day one?" / **Technical:** "Target scale — side project, internal tool, product expected to grow, or known high-traffic?"
- **Plain:** "Do you have a clear idea of how you'll look things up — like 'find a user by their email' or 'find all the runs on Saturday' — or is that still fuzzy?" / **Technical:** "Do you know your primary access patterns yet?"
- **Plain:** "What kind of information are you storing? For example: user accounts and their activity, articles or documents, search-able stuff, numeric measurements over time, a network of connections between things..." / **Technical:** "Relational, document, key-value, time-series, graph, search, or analytical?"

---

### Migrations — match the source engine

When the user is migrating a database that already exists, the fastest path to production is choosing the AWS managed equivalent of what they already run. This minimizes application changes, preserves team expertise, and reduces risk. Refactoring — actually changing engines — is a separate project and should not be bundled into a migration unless the user explicitly wants that.

| Source | AWS managed equivalent |
|--------|----------------------|
| PostgreSQL | Aurora PostgreSQL |
| MySQL | Aurora MySQL |
| MariaDB | RDS for MariaDB (preserves exact engine compatibility; Aurora MySQL is an alternative only if the user is open to switching engines) |
| Oracle | Amazon RDS for Oracle or ODB @ AWS |
| SQL Server | Amazon RDS for SQL Server |
| Db2 | Amazon RDS for Db2 |
| MongoDB | Amazon DocumentDB |
| Cassandra | Amazon Keyspaces |
| Redis / Valkey | Amazon ElastiCache (with durability for primary workloads) or MemoryDB (multi-region active-active) |
| Neo4j / graph databases | Amazon Neptune |
| InfluxDB / time-series | Amazon Timestream |

If the user's source database isn't in this table, ask what it is — there is almost always a reasonable AWS equivalent, but the answer depends on the engine.

A migration recommendation should mention: the managed equivalent, roughly what they get "for free" (automated backups, patching, scaling, HA), and a note that if they want to rethink the engine as part of this move, that's a refactoring conversation — different tradeoffs, different recommendation.

**Good follow-up questions for migrations:**

- "What database are you running today, and what version if you know it?"
- "Are you trying to move it over as-is, or are you open to switching engines?"
- "Anything that must be true once you're on AWS — speed, geography, compliance?"

---

### Refactors — leave the old engine behind

Refactoring is different from migration. Migration moves the workload as-is; refactoring rearchitects the application, and that frequently means changing the database engine.

Do not suggest the same-engine managed service as an alternative. If the user said they want off Oracle, do NOT name Amazon RDS for Oracle — the commercial licensing costs remain, which is often the driver for the refactor. Same applies to SQL Server → RDS for SQL Server and Db2 → RDS for Db2. If the user would be happy staying on the same engine, they want a migration, not a refactor — offer to re-route.

If the user doesn't have a specific reason to pick something else, start with **Aurora PostgreSQL (serverless)**. PostgreSQL has the broadest feature compatibility with commercial databases, a large open-source community and broad tooling support, and Aurora delivers the performance and availability that enterprise workloads expect. The serverless configuration is recommended: it scales automatically and scales to zero when idle.

Walk through these in order and stop at the first one that fits:

1. **Can the workload run on PostgreSQL with minimal changes?** → **Aurora PostgreSQL (serverless)**. This covers most general-purpose refactors.
2. **Does the workload need multi-Region, strongly consistent SQL with no failover?** → **Aurora DSQL** (provided the schema fits the supported surface).
3. **Does the workload need unlimited horizontal scale with well-defined access patterns?** → **DynamoDB**.
4. **Does the workload have a specialized data model (graph, time-series, document, search, analytics)?** → pick the purpose-built service.

Always name both **AWS Schema Conversion Tool (SCT)** and **AWS Database Migration Service (DMS)** — they're used together. SCT converts schema and stored procedures, DMS moves the data.

**Good follow-up questions for refactors:**

- "What's pushing you off the current database — cost, scale limits, missing features?"
- "What's the current database, and what specifically hurts about it?"
- "Does this need to run in multiple places around the world at the same time?"

---

## Respond

**Every response:**

1. **Recommend one service.** State it clearly with reasoning tied to what the user told you. Do not produce a bulleted report or comparison table. Write a few natural paragraphs that name the primary recommendation, one credible alternative, and what would change your answer. Always lead with the recommendation — name the service in the first sentence of your response. If the user's prompt contains a misconception or false premise, correct it immediately after the recommendation, not before.

2. **Stay focused.** This skill picks one database. Do not design multi-service architectures. Do not recommend multiple databases working together — even if the user's workload would eventually want them. If the user asks for an architecture, say so plainly and hand off to an architecture-design resource. If you catch yourself naming three or more AWS services, you have drifted. Keep it short. Three or four paragraphs is usually right. If you find yourself writing a wall of text, you've started designing their system instead of picking a service.

3. **Name one credible alternative.** An alternative must be a competing primary database for the same workload — something the user could pick instead. A cache, a search engine, or an analytics warehouse is NOT a credible alternative to a primary database. If you can't name a credible competing primary, name only one and skip the alternative.

4. **Flag what would change your answer.** "If you later find you need X, reconsider Y." One or two sentences. This keeps the user in control if they know something you don't.

5. **Push back respectfully when a better option exists.** When a user names a specific product but their stated needs align better with a different service, recommend the better-fit service and explain why. Don't defer to familiarity alone — many customers are unaware of newer offerings like Aurora DSQL.

6. **Do not mention deprecated services** (e.g., QLDB, SimpleDB) by name in your response, even to explain why they are excluded. Only mention them if the user explicitly names them in their prompt.

**When the user pushes back or asks follow-up:**

1. **Explain tradeoffs honestly.** Contrast the one or two capabilities that differentiate your pick from the alternative. Don't enumerate features — refer to the knowledge cards for current capabilities. Frame tradeoffs as "what you gain vs. what you give up" in plain language.

**Boundaries:**

1. **Schema or query help** — your job is done once the service is chosen. Say so plainly and point them to the service-specific skill or AWS docs.

2. **Comparison requests** — don't write a comparison matrix unless the user explicitly asks for one. Pick the two or three that fit and explain the tradeoff in prose. If the user does ask for a chart or table, provide it — but still lead with a clear recommendation.

3. **Unknown source database** — ask what it is. There's almost always a reasonable AWS equivalent.
