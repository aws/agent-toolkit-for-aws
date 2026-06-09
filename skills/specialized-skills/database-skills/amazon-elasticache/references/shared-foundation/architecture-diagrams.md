# Architecture Diagrams

Mermaid diagrams for common ElastiCache deployment patterns.

---

## 1. Default Application Caching (Cache-Aside Pattern)

Standard cache-aside pattern with ElastiCache Serverless Valkey in front of a relational database. The application checks the cache first; on a miss, it queries the database and populates the cache.

```mermaid
flowchart LR
    subgraph VPC
        App["Application<br/>(Lambda / ECS / EKS / EC2)"]
        subgraph ElastiCache["ElastiCache Serverless Valkey"]
            Cache["Valkey<br/>TLS + Auth"]
        end
        subgraph Database["RDS / Aurora"]
            DB["PostgreSQL / MySQL"]
        end
    end

    App -->|"1. GET key<br/>(TLS, auth)"| Cache
    Cache -->|"2a. Cache HIT<br/>return value"| App
    App -->|"2b. Cache MISS<br/>query DB"| DB
    DB -->|"3. Return rows"| App
    App -->|"4. SET key + TTL<br/>populate cache"| Cache

    style Cache fill:#2563eb,color:#fff
    style DB fill:#7c3aed,color:#fff
    style App fill:#059669,color:#fff
```

**Key characteristics:**

- Serverless Valkey is the default cache layer (deploys in under a minute)
- TLS is always on for all serverless caches (Valkey, Redis OSS, and Memcached)
- Application handles cache-miss logic (lazy loading)
- TTL controls staleness tolerance
- Write-through on database updates for active invalidation (optional)

---

## 2. RDS/Aurora Read Acceleration

ElastiCache sits between the application and the database, accelerating reads with optional write-through invalidation.

```mermaid
flowchart TB
    subgraph VPC
        subgraph AppLayer["Application Layer"]
            App["Application<br/>(ECS / EKS)"]
        end

        subgraph CacheLayer["Cache Layer"]
            Writer["Cache Writer<br/>(write-through)"]
            Reader["Cache Reader<br/>(read-through)"]
            Cache["ElastiCache<br/>Serverless Valkey"]
        end

        subgraph DataLayer["Data Layer"]
            Primary["RDS Aurora<br/>Primary (writes)"]
            Replica["RDS Aurora<br/>Read Replica"]
        end
    end

    App -->|"Read request"| Reader
    Reader -->|"1. Check cache"| Cache
    Cache -->|"2a. HIT"| Reader
    Reader -->|"2b. MISS<br/>query replica"| Replica
    Replica -->|"3. Return data"| Reader
    Reader -->|"4. Populate cache"| Cache
    Reader -->|"Return to app"| App

    App -->|"Write request"| Writer
    Writer -->|"1. Write to DB"| Primary
    Primary -->|"2. Confirm"| Writer
    Writer -->|"3. Invalidate/update cache"| Cache
    Primary -.->|"Replication"| Replica

    style Cache fill:#2563eb,color:#fff
    style Primary fill:#7c3aed,color:#fff
    style Replica fill:#7c3aed,color:#fff
    style App fill:#059669,color:#fff
    style Writer fill:#d97706,color:#fff
    style Reader fill:#059669,color:#fff
```

**Key characteristics:**

- Reads go through cache first (significantly faster than direct DB queries; per AWS published benchmarks, results vary by workload)
- Writes go to the database primary, then invalidate or update the cache
- Aurora read replicas handle cache misses and complex queries
- Reduces Aurora read replica load and RDS costs significantly (per AWS published benchmarks, results vary by workload)
- TTL prevents stale data from persisting if invalidation fails

---

## 3. AI/GenAI Architecture (Semantic Cache + Vector Search)

ElastiCache Valkey 8.2 or above (node-based) provides semantic caching and vector search for LLM applications, reducing Bedrock inference costs and latency.

```mermaid
flowchart TB
    subgraph VPC
        App["AI Application<br/>(Lambda / ECS)"]

        subgraph ElastiCache["ElastiCache Node-Based<br/>Valkey 8.2+"]
            SemCache["Semantic Cache<br/>(prompt embeddings)"]
            VecSearch["Vector Search Index<br/>(knowledge base)"]
            Memory["Agent Memory<br/>(conversation history)"]
        end

        subgraph AI["AI Services"]
            Bedrock["Amazon Bedrock<br/>(Claude / Titan)"]
            EmbModel["Embedding Model<br/>(Titan Embeddings)"]
        end

        subgraph Data["Data Sources"]
            S3["S3<br/>(documents)"]
            DB["RDS / Aurora<br/>(structured data)"]
        end
    end

    App -->|"1. User prompt"| SemCache
    SemCache -->|"2a. Semantic HIT<br/>return cached response"| App

    SemCache -->|"2b. Semantic MISS"| EmbModel
    EmbModel -->|"3. Prompt embedding"| VecSearch
    VecSearch -->|"4. Relevant context<br/>(RAG retrieval)"| App

    App -->|"5. Retrieve conversation<br/>history"| Memory
    Memory -->|"6. Relevant past turns"| App

    App -->|"7. Prompt + context +<br/>memory -> LLM"| Bedrock
    Bedrock -->|"8. Response"| App

    App -->|"9a. Cache response<br/>with embedding"| SemCache
    App -->|"9b. Store conversation<br/>turn"| Memory

    S3 -->|"Ingest + embed"| VecSearch
    DB -->|"Ingest + embed"| VecSearch

    style SemCache fill:#2563eb,color:#fff
    style VecSearch fill:#2563eb,color:#fff
    style Memory fill:#2563eb,color:#fff
    style Bedrock fill:#f59e0b,color:#000
    style EmbModel fill:#f59e0b,color:#000
    style App fill:#059669,color:#fff
    style S3 fill:#7c3aed,color:#fff
    style DB fill:#7c3aed,color:#fff
```

**Key characteristics:**

- **Semantic cache**: Stores prompt embeddings and LLM responses. On a new prompt, computes embedding similarity to find cached answers. Significantly reduces inference cost and latency (per AWS published benchmarks, results vary by workload).
- **Vector search**: Stores document chunk embeddings for RAG. Retrieves semantically relevant context to ground LLM responses and reduce hallucinations.
- **Agent memory**: Stores conversation turns as vectors. Retrieves only relevant past interactions per LLM invocation to avoid context window overflow.
- **Deployment**: Requires node-based Valkey 8.2 or above (recommend 9.0; vector search is not available on serverless or on data tiering instances such as r6gd node types).
- **Data flow**: Documents are embedded and stored during ingestion. At query time, the embedding model converts the prompt to a vector, which is used for both semantic cache lookup and RAG retrieval.

---

## 4. Network Architecture (VPC Layout)

Common VPC layout showing how ElastiCache integrates with compute resources and security boundaries.

```mermaid
flowchart TB
    subgraph VPC["VPC (10.0.0.0/16)"]
        subgraph PublicSubnets["Public Subnets"]
            ALB["Application<br/>Load Balancer"]
            NAT["NAT Gateway"]
        end

        subgraph PrivateSubnetsA["Private Subnet AZ-a"]
            ECS_A["ECS Tasks /<br/>EKS Pods"]
            Lambda_A["Lambda<br/>ENIs"]
        end

        subgraph PrivateSubnetsB["Private Subnet AZ-b"]
            ECS_B["ECS Tasks /<br/>EKS Pods"]
            Lambda_B["Lambda<br/>ENIs"]
        end

        subgraph CacheSubnets["Cache Subnets (private)"]
            Cache_A["ElastiCache<br/>Node AZ-a"]
            Cache_B["ElastiCache<br/>Node AZ-b"]
        end

        SG_App["SG: App<br/>(outbound 6379/6380)"]
        SG_Cache["SG: Cache<br/>(inbound 6379/6380<br/>from SG: App)"]
    end

    ALB --> ECS_A
    ALB --> ECS_B
    ECS_A -->|"TLS :6379"| Cache_A
    ECS_B -->|"TLS :6379"| Cache_B
    Lambda_A -->|"TLS :6379"| Cache_A
    Lambda_B -->|"TLS :6379"| Cache_B
    Cache_A <-.->|"Replication"| Cache_B

    SG_App -.-> ECS_A
    SG_App -.-> ECS_B
    SG_App -.-> Lambda_A
    SG_App -.-> Lambda_B
    SG_Cache -.-> Cache_A
    SG_Cache -.-> Cache_B

    style Cache_A fill:#2563eb,color:#fff
    style Cache_B fill:#2563eb,color:#fff
    style ECS_A fill:#059669,color:#fff
    style ECS_B fill:#059669,color:#fff
    style Lambda_A fill:#059669,color:#fff
    style Lambda_B fill:#059669,color:#fff
    style ALB fill:#d97706,color:#fff
```

**Key characteristics:**

- ElastiCache runs in private subnets only (no public internet access)
- Security groups restrict inbound to port 6379 (and 6380 for serverless reader endpoint) from the app security group
- Multi-AZ deployment with nodes/endpoints in at least 2 availability zones
- Lambda requires VPC attachment and ENI capacity in the private subnets
- For local development, use SSM port forwarding or a jump host (no direct access)
