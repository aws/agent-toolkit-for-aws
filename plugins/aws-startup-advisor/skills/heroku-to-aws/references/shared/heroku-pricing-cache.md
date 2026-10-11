# Heroku Pricing Cache

**Last updated:** 2026-10-05 (dyno rates re-verified against devcenter.heroku.com/articles/dyno-sizes and heroku.com/pricing — Eco $5 flat, Basic $7, Standard-1X $25, Standard-2X $50, Performance-M $250, Performance-L/L-RAM $500 all unchanged; no rate changes this refresh); 2026-10-xx added Heroku Postgres Advanced Tier compute-month rates and storage-overage rate (4G/8G/16G/32G-Performance confirmed; 64G-1536G-Performance marked `unverified` — see Advanced Tier section)
**Source:** https://elements.heroku.com/addons/heroku-postgresql, https://elements.heroku.com/addons/heroku-redis, https://elements.heroku.com/addons/heroku-kafka, https://devcenter.heroku.com/articles/dyno-sizes, https://devcenter.heroku.com/articles/postgres-advanced-usage-billing, https://devcenter.heroku.com/articles/heroku-postgres-plans, https://devcenter.heroku.com/articles/provisioning-postgres-advanced, https://www.heroku.com/blog/new-era-managed-databases-announcing-heroku-postgres-advanced/
**Currency:** USD
**Accuracy:** ±5% for dynos (published flat rates); ±10% for data services (Elements "Max of" pricing, actual may vary by usage pattern)

> Use this cache to derive current Heroku monthly costs when billing data is unavailable. Look up each discovered resource's plan in the tables below, multiply by quantity where applicable, and sum. If a plan is not found in this cache, set `heroku_cost_source: "unavailable"` for that resource and exclude from total.

---

## Dynos (Cedar Common Runtime)

Source: https://devcenter.heroku.com/articles/dyno-sizes

| Plan              | $/month (per dyno) | Notes                                                                 |
| ----------------- | ------------------ | --------------------------------------------------------------------- |
| Eco               | 5                  | Flat fee for shared 1000 dyno-hour pool. Do NOT multiply by quantity. |
| Basic             | 7                  |                                                                       |
| Standard-1X       | 25                 |                                                                       |
| Standard-2X       | 50                 |                                                                       |
| Performance-M     | 250                |                                                                       |
| Performance-L     | 500                |                                                                       |
| Performance-L-RAM | 500                |                                                                       |
| Performance-XL    | 750                |                                                                       |
| Performance-2XL   | 1500               |                                                                       |

**Eco dyno rule:** Eco is a shared pool — cost is always $5/month total regardless of how many Eco dynos run. Do NOT multiply by formation quantity.

## Dynos (Cedar Private Spaces)

| Plan          | $/month (per dyno) |
| ------------- | ------------------ |
| Private-S     | 125                |
| Private-M     | 250                |
| Private-L     | 500                |
| Private-L-RAM | 500                |
| Private-XL    | 750                |
| Private-2XL   | 1500               |

## Dynos (Cedar Shield Spaces)

| Plan         | $/month (per dyno) |
| ------------ | ------------------ |
| Shield-S     | 150                |
| Shield-M     | 300                |
| Shield-L     | 600                |
| Shield-L-RAM | 600                |
| Shield-XL    | 900                |
| Shield-2XL   | 1800               |

---

## Heroku Postgres

Source: https://elements.heroku.com/addons/heroku-postgresql

### Essential Tier

| Plan        | $/month | Storage | Connections |
| ----------- | ------- | ------- | ----------- |
| essential-0 | 5       | 1 GB    | 20          |
| essential-1 | 9       | 10 GB   | 20          |
| essential-2 | 20      | 32 GB   | 40          |

### Standard Tier (Classic)

| Plan       | $/month | RAM    | Storage | Connections |
| ---------- | ------- | ------ | ------- | ----------- |
| standard-0 | 50      | 4 GB   | 64 GB   | 200         |
| standard-2 | 200     | 8 GB   | 256 GB  | 500         |
| standard-3 | 400     | 15 GB  | 512 GB  | 500         |
| standard-4 | 750     | 30 GB  | 768 GB  | 500         |
| standard-5 | 1400    | 61 GB  | 1 TB    | 500         |
| standard-6 | 2000    | 122 GB | 1.5 TB  | 500         |
| standard-7 | 3500    | 244 GB | 2 TB    | 500         |

### Premium Tier (Classic)

| Plan      | $/month | RAM    | Storage | Connections |
| --------- | ------- | ------ | ------- | ----------- |
| premium-0 | 200     | 4 GB   | 64 GB   | 200         |
| premium-2 | 350     | 8 GB   | 256 GB  | 500         |
| premium-3 | 750     | 15 GB  | 512 GB  | 500         |
| premium-4 | 1200    | 30 GB  | 768 GB  | 500         |
| premium-5 | 2500    | 61 GB  | 1 TB    | 500         |
| premium-6 | 3500    | 122 GB | 1.5 TB  | 500         |
| premium-7 | 6000    | 244 GB | 2 TB    | 500         |

### Private Tier (Classic)

Private-tier pricing matches Premium-tier pricing. The Private Space base fee is charged separately.

| Plan      | $/month | RAM    | Storage | Connections |
| --------- | ------- | ------ | ------- | ----------- |
| private-0 | 200     | 4 GB   | 64 GB   | 200         |
| private-2 | 350     | 8 GB   | 256 GB  | 500         |
| private-3 | 750     | 15 GB  | 512 GB  | 500         |
| private-4 | 1200    | 30 GB  | 768 GB  | 500         |
| private-5 | 2500    | 61 GB  | 1 TB    | 500         |
| private-6 | 3500    | 122 GB | 1.5 TB  | 500         |
| private-7 | 6000    | 244 GB | 2 TB    | 500         |

### Shield Tier (Classic)

Shield-tier pricing matches Premium-tier pricing. The Shield Space base fee is charged separately.

| Plan     | $/month | RAM    | Storage | Connections |
| -------- | ------- | ------ | ------- | ----------- |
| shield-0 | 200     | 4 GB   | 64 GB   | 200         |
| shield-2 | 350     | 8 GB   | 256 GB  | 500         |
| shield-3 | 750     | 15 GB  | 512 GB  | 500         |
| shield-4 | 1200    | 30 GB  | 768 GB  | 500         |
| shield-5 | 2500    | 61 GB  | 1 TB    | 500         |
| shield-6 | 3500    | 122 GB | 1.5 TB  | 500         |
| shield-7 | 6000    | 244 GB | 2 TB    | 500         |

### Advanced Tier

**NOT a flat monthly plan fee.** Heroku Postgres Advanced bills compute by the
**compute-month**, prorated to the second (`compute_cost = rate_per_compute_month
× (seconds_instance_existed / seconds_in_30_day_month)`). On Heroku's own
platform, each instance pool (leader, plus up to 5 follower pools, 1-13
instances per pool) is priced independently at its own level, and a
high-availability leader's standby is a second full-rate instance of the same
level (effectively doubles that pool's compute cost). See Usage Rules below
for the full-month assumption this cache uses when deriving an estimate
(Discover does not capture partial-month usage).

**Known limitation (Discover does not capture instance pools):** `schema-discover-heroku.md`'s
`addon` resource carries exactly one `plan` string per `heroku-postgresql` addon
and has no field for instance pool count, pool role (leader/follower), or
per-pool instance count. This cache's formula therefore prices **one instance
at the discovered level** (`instance_count = 1`), not the full leader+follower
topology described above. A multi-pool Advanced cluster (HA leader, or any
follower pools) will be **under-priced** by this formula until Discover is
extended to capture per-pool level and instance count — treat any Advanced-tier
estimate as a floor, not a ceiling, when the live `pg:info` output shows more
than one instance.

Source: https://devcenter.heroku.com/articles/postgres-advanced-usage-billing, https://devcenter.heroku.com/articles/heroku-postgres-plans, https://devcenter.heroku.com/articles/provisioning-postgres-advanced, accessed 2026-10-xx (pages last updated October 06, 2026)

| Plan Level (`--level`) | vCPU | RAM     | $/compute-month |
| ----------------------- | ---- | ------- | ---------------- |
| 4G-Performance           | 2    | 4 GB    | 150               |
| 8G-Performance           | 2    | 8 GB    | 300               |
| 16G-Performance          | 2    | 16 GB   | 500               |
| 32G-Performance          | 4    | 32 GB   | 900               |
| 64G-Performance          | 8    | 64 GB   | unverified        |
| 128G-Performance         | 16   | 128 GB  | unverified        |
| 256G-Performance         | 32   | 256 GB  | unverified        |
| 384G-Performance         | 48   | 384 GB  | unverified        |
| 512G-Performance         | 64   | 512 GB  | unverified        |
| 768G-Performance         | 96   | 768 GB  | unverified        |
| 1536G-Performance        | 192  | 1536 GB | unverified        |

> Rates marked "unverified" could not be confirmed from Heroku's public
> documentation as of 2026-10-xx (the Elements Marketplace calculator renders
> them via JavaScript, not in the static page). Do not price these levels from
> this cache — mark the resource `"unpriced_heroku"` and fall through to rung 4
> (ask the user) exactly as the existing fallback rule does for any other cache
> miss.

**Storage overage:** 100 GB-month included per cluster (not per pool), prorated
for partial months the database existed. Overage beyond the included amount is
billed at **$0.20 per GB-month**:
`storage_cost = max(0, data_size_gb - 100) × 0.20`, using the addon's
live-enrichment `data_size_gb` field (`schema-discover-heroku.md`) as the
point-in-time stand-in for Heroku's own month-averaged storage figure (Discover
does not capture a month-averaged value, so this cache uses the latest captured
snapshot instead).

### Deprecated Plans (Aliases)

| Plan        | Maps To     | $/month                     |
| ----------- | ----------- | --------------------------- |
| hobby-dev   | essential-0 | 0 (was free; grandfathered) |
| hobby-basic | essential-1 | 9                           |

---

## Heroku Key-Value Store (Redis)

Source: https://elements.heroku.com/addons/heroku-redis

### Premium (Common Runtime)

| Plan       | $/month | RAM    | Connections |
| ---------- | ------- | ------ | ----------- |
| mini       | 3       | 25 MB  | 20          |
| premium-0  | 15      | 50 MB  | 40          |
| premium-1  | 30      | 100 MB | 80          |
| premium-2  | 60      | 250 MB | 200         |
| premium-3  | 120     | 500 MB | 400         |
| premium-5  | 200     | 1 GB   | 1000        |
| premium-7  | 750     | 7 GB   | 10000       |
| premium-9  | 1450    | 10 GB  | 25000       |
| premium-10 | 3500    | 25 GB  | 40000       |
| premium-12 | 6500    | 50 GB  | 65000       |
| premium-14 | 12500   | 100 GB | 65000       |

### Private (Private Spaces)

| Plan       | $/month | RAM    | Connections |
| ---------- | ------- | ------ | ----------- |
| private-3  | 150     | 500 MB | 400         |
| private-5  | 250     | 750 MB | 700         |
| private-7  | 900     | 7 GB   | 10000       |
| private-9  | 1750    | 10 GB  | 25000       |
| private-10 | 4000    | 25 GB  | 40000       |
| private-12 | 7500    | 50 GB  | 65000       |
| private-14 | 14000   | 100 GB | 65000       |

### Shield (Shield Spaces)

| Plan      | $/month | RAM    | Connections |
| --------- | ------- | ------ | ----------- |
| shield-3  | 210     | 500 MB | 400         |
| shield-5  | 350     | 750 MB | 700         |
| shield-7  | 1100    | 7 GB   | 10000       |
| shield-9  | 2100    | 10 GB  | 25000       |
| shield-10 | 4800    | 25 GB  | 40000       |
| shield-12 | 9000    | 50 GB  | 65000       |
| shield-14 | 19600   | 100 GB | 65000       |

---

## Apache Kafka on Heroku

Source: https://elements.heroku.com/addons/heroku-kafka

### Common Runtime

| Plan       | $/month | Type                  | Capacity |
| ---------- | ------- | --------------------- | -------- |
| basic-0    | 100     | Multi-tenant          | 3.73 GB  |
| basic-1    | 125     | Multi-tenant          | 29.8 GB  |
| basic-2    | 175     | Multi-tenant          | 59.6 GB  |
| standard-0 | 1500    | Dedicated (3 brokers) | 150 GB   |
| standard-1 | 1800    | Dedicated (3 brokers) | 300 GB   |
| standard-2 | 3200    | Dedicated (3 brokers) | 900 GB   |
| extended-0 | 4000    | Dedicated (3 brokers) | 1.5 TB   |
| extended-1 | 5000    | Dedicated (3 brokers) | 3 TB     |
| extended-2 | 8700    | Dedicated (3 brokers) | 6 TB     |

### Private Spaces

| Plan               | $/month | Capacity |
| ------------------ | ------- | -------- |
| private-standard-0 | 1800    | 150 GB   |
| private-standard-1 | 2200    | 300 GB   |
| private-standard-2 | 3600    | 900 GB   |
| private-extended-0 | 5000    | 1.5 TB   |
| private-extended-1 | 6200    | 3 TB     |
| private-extended-2 | 10800   | 6 TB     |

### Shield Spaces

| Plan              | $/month | Capacity |
| ----------------- | ------- | -------- |
| shield-standard-0 | 2200    | 150 GB   |
| shield-standard-1 | 2700    | 300 GB   |
| shield-standard-2 | 4400    | 900 GB   |
| shield-extended-0 | 6000    | 1.5 TB   |
| shield-extended-1 | 7500    | 3 TB     |
| shield-extended-2 | 13000   | 6 TB     |

---

## Private Space Base Fee

| Plan          | $/month |
| ------------- | ------- |
| Private Space | 1000    |
| Shield Space  | 3000    |

---

## Common Add-ons (Fast-Path)

These are estimates for popular fast-path add-ons. When billing data is available, prefer it over these values.

| Add-on               | Typical Plan | $/month  |
| -------------------- | ------------ | -------- |
| Heroku Scheduler     | standard     | 0 (free) |
| Papertrail           | firehose     | 230      |
| SendGrid             | starter      | 0 (free) |
| Mailgun              | starter      | 0 (free) |
| Bonsai Elasticsearch | sandbox      | 0 (free) |
| CloudAMQP            | little-lemur | 0 (free) |
| Memcachier           | dev          | 0 (free) |

> Add-on pricing varies widely by plan. For non-free plans, defer to billing data or user input rather than guessing. Only use $0 for confirmed free-tier plans.

---

## Usage Rules

1. **Lookup by plan name** (case-insensitive exact match from `heroku-resource-inventory.json`)
2. **Multiply by quantity** (from `formation.quantity` for dynos) — **EXCEPT Eco dynos** (always $5 flat)
3. **Sum all resources** to get `heroku_monthly_estimated`
4. **Add Private Space / Shield Space base fee** if `heroku_space` resources exist in inventory
5. **Set `heroku_cost_source: "pricing_cache"`** in `estimation-infra.json`
6. **Accuracy band:** ±5% for dynos, ±10% for data services
7. **Not found:** If a plan is not in this cache, mark as `"unpriced_heroku"` and exclude from Heroku total. Add to warnings.
8. **Deprecated plans:** Map `hobby-dev` → essential-0, `hobby-basic` → essential-1 for pricing lookup.
9. **Heroku Postgres Advanced (compute-month formula, not a flat lookup):** For a `heroku-postgresql` addon whose plan/level string matches one of the Advanced Tier's `*-Performance` level names (rather than a Classic plan name), compute cost as `rate[level] × 1` (one instance at the discovered level — Discover's `addon` resource has no field for instance pool count or leader/follower role, so this cache can only price the single instance it captures; see the Advanced Tier section's "Known limitation" note), assuming it runs a full compute-month (Discover does not capture partial-month usage, so this cache does not attempt to prorate). Add storage overage: `max(0, data_size_gb - 100) × 0.20` using the addon's live-enrichment `data_size_gb` field (`schema-discover-heroku.md`); if `data_size_gb` is absent, price compute only and add a warning that storage overage was not estimated. Attach this caveat to `baseline_note`: "Heroku Postgres Advanced is billed by the compute-month and prorated to the second; this estimate assumes one instance runs the full month. If this database uses high availability or follower pools, actual Heroku billing will be higher than shown — Discover does not currently capture per-pool instance counts. Actual billing will also differ if an instance pool is created, resized, or destroyed partway through a billing period." If the level matches an `unverified` row, treat it as a cache miss (`"unpriced_heroku"`, rung 4 fallback) per rule 7.
