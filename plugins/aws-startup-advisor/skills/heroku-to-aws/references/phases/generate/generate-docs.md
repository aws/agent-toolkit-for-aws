---
_fragment: docs
_of_phase: generate
_contributes:
  - MIGRATION_GUIDE.md
  - README.md
---

# Generate Phase: Documentation and Script Generation

> Self-contained sub-file for generating migration documentation and database migration scripts.
> Produces `MIGRATION_GUIDE.md`, `README.md`, and database migration scripts in `$MIGRATION_DIR`.
> Only generates procedures for data stores actually present in the design — omits absent types entirely.

**Execute ALL steps in order. Do not skip or optimize.**

---

## Step 0: Detect Data Store Presence

Scan `aws-design.json`.services[] to determine which compute and data store types exist in the design:

| Check                 | Condition                                                                                    | Flag                       |
| --------------------- | -------------------------------------------------------------------------------------------- | -------------------------- |
| Beanstalk present     | Any service with `aws_service == "Elastic Beanstalk"`                                        | `has_beanstalk = true`     |
| Beanstalk web present | Any service with `aws_service == "Elastic Beanstalk"` and `aws_config.process_type == "web"` | `has_beanstalk_web = true` |
| Fargate present       | Any service with `aws_service == "Fargate"` or `aws_service == "ALB"`                        | `has_fargate = true`       |
| Fargate web present   | Any service with `aws_service == "ALB"`, or `aws_service == "Fargate"` and `aws_config.process_type == "web"` (workers alone never count) | `has_fargate_web = true` |
| EKS present           | Any service with `aws_service == "EKS"` (`design-eks.md` "All-or-Nothing Rule": then no EB or Fargate web service exists) | `has_eks = true`           |
| Postgres present      | Any service with `aws_service` containing `"RDS PostgreSQL"` or `"Aurora PostgreSQL"`        | `has_postgres = true`      |
| Redis present         | Any service with `aws_service == "ElastiCache Redis"`                                        | `has_redis = true`         |
| Kafka present         | Any service with `aws_service == "Amazon MSK"`                                               | `has_kafka = true`         |

Also extract:

- `deferred_addons[]` — entries from `aws-design.json`.deferred[]
- `all_services[]` — full list of designed services for README generation
- `target_region` — from `preferences.json`.global.target_region (default: `us-east-1`)
- `heroku_apps[]` — list of unique app names from design services
- `beanstalk_web_apps[]` — unique app names from Elastic Beanstalk web services, plus each name sanitized by replacing `-` with `_`
- `migration_approach` — from `preferences.json`.global.migration_approach (`"full_cutover"` or `"interim_cutover_data_first"`)
- `migration_method` — from `preferences.json`.data.migration_method (`"pg_dump_restore"`, `"dms"`, `"bucardo"`, `"wal_g"`)
- `containerization_status` — from `preferences.json`.operational.containerization_status (`"containerized"`, `"buildpack_only"`, `"partial"`)
- `target_exit_date` — from `preferences.json`.global.target_exit_date (ISO date or null)
- `dns_strategy` — from `preferences.json`.data.dns_strategy (Clarify Q10 writes it inside the `"data"` block — `clarify-assemble.md`; there is no `global.dns_strategy`). `"route53"` or `"external"`; treat any other or missing value (e.g. a legacy `"manual_cutover"`) as `"external"`.
- `custom_domains[]` — every `resource_type == "domain"` resource's `config.hostname` from `heroku-resource-inventory.json` (deduplicated).
- `dns_hostnames[]` — one entry per `custom_domains[]` hostname, preserving the associations the inventory and design already carry: `{ hostname, heroku_app, app_sanitized, target_kind, output_name }`. `heroku_app` is the domain resource's `heroku_app` (the `{app_name}` segment of `domain:{app_name}:{hostname}`); `app_sanitized` replaces `-` with `_`. `target_kind` is resolved from that app's **web** formation in `aws-design.json`.services[] — not from any worker: `alb:{heroku_app}:web` present → `"alb"` (`output_name: "alb_dns_name"`); else `eb:{heroku_app}:web` present → `"eb"` (`output_name: "eb_environment_url"` — the output Step 3 of `generate-terraform.md` actually emits; there is no `eb_environment_cname`); else `eks:{heroku_app}:web` present → `"eks"` (`output_name: null` — the endpoint is the Kubernetes Service's `EXTERNAL-IP`, known only after Phase 3); else `"none"` (worker-only app, or its formations were deferred).
- `eligible_hostnames[]` — the `dns_hostnames[]` entries with `target_kind` `"alb"` or `"eb"`: the only hostnames `dns.tf` can route. `has_route53_dns = true` when `dns_strategy == "route53"` AND `eligible_hostnames` is non-empty — the same condition under which `generate-terraform.md` Step 9.5 emits `dns.tf`. An EKS design therefore always has `has_route53_dns = false`. Entries with `target_kind` `"eks"` or `"none"` are rendered only in the manual DNS branch (and `generate-terraform.md` Step 9.5 records them in `generation-warnings.json`). Whether a hostname is a zone apex is not known at generation time (it depends on the zone the user supplies), so `dns.tf` decides it at plan time and the guide covers the apex unconditionally inside the Route 53 branch.

---

## Step 1: Generate `MIGRATION_GUIDE.md`

Write the migration guide to `$MIGRATION_DIR/MIGRATION_GUIDE.md` using the template below.

**Critical rules:**

- Include a data migration procedure section ONLY for data store types where the corresponding flag is `true`.
- OMIT the entire section (heading and content) for data store types NOT present in the design.
- Include deferred add-ons as manual migration items if any exist.
- Use connection parameter placeholders (never real credentials).

### Template: MIGRATION_GUIDE.md

````markdown
# Migration Guide: Heroku to AWS

This guide provides step-by-step instructions for migrating your Heroku application(s) to AWS.

## Table of Contents

- [Prerequisites](#prerequisites)
- [Phase 1: Infrastructure Provisioning](#phase-1-infrastructure-provisioning)
- [Phase 2: Data Migration](#phase-2-data-migration)
- [Phase 3: Application Deployment](#phase-3-application-deployment)
- [Phase 4: Verification](#phase-4-verification)
- [Phase 5: Cutover](#phase-5-cutover)
- [Phase 6: Rollback](#phase-6-rollback)
- [Decommission Heroku](#decommission-heroku-resources)
  {{IF deferred_addons.length > 0}}
- [Manual Migration Items](#manual-migration-items)
  {{ENDIF}}

---

## Prerequisites

Before beginning the migration, ensure the following are in place:

### AWS Account Setup

- [ ] AWS account with appropriate IAM permissions for resource creation
- [ ] AWS CLI installed and configured (`aws configure`)
- [ ] Terraform >= 1.5.0 installed
- [ ] Target region selected: `{{target_region}}`

### Heroku Access

- [ ] Heroku CLI installed and authenticated (`heroku auth:whoami`)
- [ ] Access to source application(s): {{heroku_apps_comma_separated}}
      {{IF has_postgres}}
- [ ] Database credentials for Heroku Postgres (retrieve via `heroku pg:credentials:url -a <app>`)
      {{ENDIF}}
      {{IF has_redis}}
- [ ] Redis connection URL from Heroku (retrieve via `heroku redis:credentials -a <app>`)
      {{ENDIF}}
      {{IF has_kafka}}
- [ ] Kafka connection details from Heroku (retrieve via `heroku kafka:info -a <app>`)
      {{ENDIF}}

### Network Requirements

- [ ] VPC and subnet configuration confirmed (see `terraform/` directory)
- [ ] Security group rules reviewed for appropriate access
- [ ] DNS records identified for cutover

### Application Preparation

{{IF has_beanstalk}}

- [ ] Source bundle contains a Dockerfile at the repository root for Elastic Beanstalk Docker deployment
      {{ENDIF}}
      {{IF has_beanstalk_web}}
- [ ] Application listen port identified for every Beanstalk web app's `eb_application_port_<app_sanitized>_web` input
- [ ] HTTP health check path identified for every Beanstalk web app's `eb_health_check_path_<app_sanitized>_web` input
      {{ENDIF}}
      {{IF has_fargate}}
- [ ] Application Docker image built and pushed to ECR (or container registry)
      {{ENDIF}}
- [ ] Environment variables documented and mapped to AWS Secrets Manager / Parameter Store
- [ ] Health check endpoints identified for each web service

{{IF containerization_status == "buildpack_only" OR containerization_status == "partial"}}

### Containerization Prerequisites

Your application currently uses Heroku buildpacks and does not have a Dockerfile. You'll need to create one for AWS compute deployment.

**Common Procfile → Dockerfile patterns:**

- **Node.js** (heroku/nodejs buildpack): `FROM node:20-alpine`, `COPY package*.json ./`, `RUN npm ci --omit=dev`, `COPY . .`, `CMD ["node", "server.js"]`
- **Python** (heroku/python buildpack): `FROM python:3.12-slim`, `COPY requirements.txt .`, `RUN pip install --no-cache-dir -r requirements.txt`, `COPY . .`, `CMD ["gunicorn", "app:app", "--bind", "0.0.0.0:$PORT"]`
- **Ruby** (heroku/ruby buildpack): `FROM ruby:3.3-slim`, `COPY Gemfile* ./`, `RUN bundle install --without development test`, `COPY . .`, `CMD ["bundle", "exec", "puma", "-C", "config/puma.rb"]`
- **Go** (heroku/go buildpack): `FROM golang:1.22 AS build`, `COPY . .`, `RUN go build -o app .`, `FROM alpine`, `COPY --from=build /app .`, `CMD ["./app"]`
- **Java** (heroku/java buildpack): `FROM eclipse-temurin:21-jre`, `COPY target/*.jar app.jar`, `CMD ["java", "-jar", "app.jar"]`

**Key differences from Heroku:**

- Heroku injects `PORT` automatically; set it explicitly in your task definition or Dockerfile `ENV`
- Heroku buildpacks handle dependencies; Docker requires explicit `COPY` + install steps
- Heroku's slug size limit (500 MB) does not apply — but keep images small for faster deploys

For detailed guidance, see your Procfile process types and match each to a Dockerfile `CMD`.
{{ENDIF}}

{{IF migration_approach == "interim_cutover_data_first"}}

### ⚠️ Platform Risk Advisory

> **Heroku is in sustaining engineering mode.** Salesforce has moved Heroku to stability-and-support-only — no new feature investment, enterprise contracts no longer sold to new customers.
>
> Your selected migration approach (database first, app stays on Heroku temporarily) is a **bounded interim phase**. Target exit date: **{{target_exit_date}}**.
>
> Hybrid operation should be limited to weeks, not quarters. Plan your compute migration promptly after data migration completes.
> {{ENDIF}}

---

## Phase 1: Infrastructure Provisioning

Apply the generated Terraform configurations to create AWS resources:

The `terraform/` directory includes `baseline.tf`, an account-wide security
baseline (account alternate contacts, IAM password policy, S3 account public
access block, EBS default encryption, IAM Access Analyzer, IMDSv2 account
default, CloudTrail with its log bucket, a monthly AWS Budget with alerts, and
GuardDuty — plus AWS Config and Security Hub when compliance frameworks were
declared).

**Security baseline contacts.** Before `terraform plan` can succeed, set the
three baseline contact variables in `terraform/terraform.tfvars` to real
inboxes:

```hcl
operations_email = "ops@yourcompany.com"
billing_email    = "billing@yourcompany.com"   # also receives budget alerts
security_email   = "security@yourcompany.com"
```

The alternate-contact phone numbers ship as placeholders — update them in
`baseline.tf` (or post-apply) with real numbers.

To skip the security baseline entirely, do BOTH of the following before
`terraform plan` (the contact variables have no defaults, so deleting only the
file still leaves plan failing on three unused required variables):

1. Delete `terraform/baseline.tf`.
2. Remove (or comment out) the `operations_email`, `billing_email`, and
   `security_email` variable blocks in `terraform/variables.tf`, and their
   entries in `terraform.tfvars` / `terraform.tfvars.example`.

To skip only the compliance-conditional section (Config + Security Hub),
delete the block between `########## Compliance-Conditional ##########` and
`########## End Compliance-Conditional ##########` in `baseline.tf`. If your
AWS account already has a CloudTrail trail, a Config recorder, or Security Hub
enabled, review the collision-warning comments in `baseline.tf` before apply.

{{IF has_beanstalk_web}}

Each Elastic Beanstalk web configuration is not ready to plan until you provide
that app's two runtime settings. Add one pair per Beanstalk web app to
`terraform/terraform.tfvars`, replacing `<app_sanitized>` with the app name after
replacing `-` with `_`:

```hcl
eb_application_port_<app_sanitized>_web  = "<the port this application's web process listens on>"
eb_health_check_path_<app_sanitized>_web = "<the HTTP path that returns a successful health response>"
```

These variables have no defaults. If any required assignment is absent,
`terraform plan -input=false` stops with Terraform's "No value for required variable"
diagnostic naming the missing customer input. Do not continue to apply until both
values are set for every Beanstalk web app. Worker-only Beanstalk apps do not need
these web runtime inputs.

{{ENDIF}}

{{IF has_route53_dns}}

### DNS preparation (Route 53) — before the first apply

`terraform/dns.tf` does two things in the Phase 1 apply that only work if Route 53 is already **authoritative** for every zone in `hosted_zone_ids`: it writes ACM validation records and then waits for them to resolve from the public internet (the apply blocks until they do), and it creates a weighted record pair per hostname — which Route 53 refuses to create next to an existing simple record of the same name and type. Finish this subsection for every hostname below before running `terraform apply`, and do not switch any traffic yet: every record you create here still points at Heroku.

| hostname | Heroku app | AWS endpoint after Phase 1 | `terraform output` |
| --- | --- | --- | --- |

<!-- markdownlint-disable MD055 MD056 -->

{{FOR host IN eligible_hostnames}}
| `{{host.hostname}}` | `{{host.heroku_app}}` | {{IF host.target_kind == "alb"}}ALB DNS name{{ELSE}}Elastic Beanstalk environment CNAME{{ENDIF}} | `{{host.output_name}}` |
{{ENDFOR}}

<!-- markdownlint-enable MD055 MD056 -->

**1. Find out who is authoritative for each zone.** For the zone of each hostname (`example.com` for `www.example.com`):

```bash
dig +short NS example.com                                  # what the internet believes
aws route53 get-hosted-zone --id <ZONE_ID> \
  --query DelegationSet.NameServers --output text             # what Route 53 would answer with
```

If the two sets match, Route 53 is authoritative — continue with step 2. If they do not match, the zone is served by another provider: do step 3 first.

**2. Route 53 is authoritative — convert any existing record for the hostname.** `aws route53 list-resource-record-sets --hosted-zone-id <ZONE_ID> --query "ResourceRecordSets[?Name=='www.example.com.']"`:

- No record → nothing to do; `dns.tf` creates both weighted members.
- A simple CNAME to the Heroku DNS target → convert it to the weighted `heroku` member in **one atomic change** (delete + create in the same ChangeBatch, so the hostname never goes unanswered), then import it so Terraform manages it instead of trying to create a duplicate:

  ```bash
  cat > convert-www.json <<'EOF'
  { "Changes": [
    { "Action": "DELETE", "ResourceRecordSet": { "Name": "www.example.com", "Type": "CNAME", "TTL": 300,
        "ResourceRecords": [ { "Value": "whispering-willow-1234.herokudns.com" } ] } },
    { "Action": "CREATE", "ResourceRecordSet": { "Name": "www.example.com", "Type": "CNAME", "TTL": 60,
        "SetIdentifier": "heroku", "Weight": 100,
        "ResourceRecords": [ { "Value": "whispering-willow-1234.herokudns.com" } ] } }
  ] }
  EOF
  aws route53 change-resource-record-sets --hosted-zone-id <ZONE_ID> --change-batch file://convert-www.json
  cd terraform/ && terraform import 'aws_route53_record.heroku["www.example.com"]' <ZONE_ID>_www.example.com_CNAME_heroku
  ```

  Use the record's current TTL and value in the `DELETE` half (they must match exactly). For an apex hostname the existing record is an `A` record: convert it the same way with `"Type": "A"` and the current IP list, and import as `aws_route53_record.apex_heroku["example.com"]` with id `<ZONE_ID>_example.com_A_heroku`.
- Anything else (an ALIAS to another AWS resource, a record pointing somewhere other than Heroku) → stop and decide what that record is for before continuing; `dns.tf` will not overwrite it.

**3. Another provider is authoritative — adopt the zone into Route 53 first.** Certificate validation and the weighted canaries cannot work until Route 53 answers for the zone, so the move happens **before** Phase 1, not after cutover:

1. Create the hosted zone (`aws route53 create-hosted-zone --name example.com --caller-reference $(date +%s)`) and put its id in `hosted_zone_ids` for every hostname under it.
2. Replicate every record from the current provider into the zone (MX, TXT/SPF/DKIM, other CNAMEs — everything), **except** the custom hostnames from the table above: create those directly in weighted `heroku` form (the `CREATE` half of the ChangeBatch in step 2) and import them. Lower the TTL of the hostnames to 60 at the old provider while you do this.
3. Verify the new zone answers correctly before delegating: `dig @<one of the Route 53 name servers> www.example.com` and the same for MX/TXT.
4. Switch the NS records at your registrar to the four Route 53 name servers. Wait for the old NS TTL (often 24–48 hours), then confirm `dig +short NS example.com` returns only Route 53 servers.
5. Only now continue to the `terraform init` block below.

If you cannot move the zone before cutover, do not run `dns.tf` against a non-authoritative zone: re-run Clarify with `dns_strategy: external` and use the manual cutover path instead.

**4. Apex hostnames (a hostname that equals its zone name, e.g. `example.com`).** Route 53 cannot CNAME or ALIAS an apex to Heroku, so `dns.tf` keeps the apex on Heroku with a weighted `A` record holding the addresses Heroku's DNS target resolves to right now, paired with a weighted ALIAS to AWS. Both members exist at every weight, so the apex moves with `cutover_weight` like every other hostname and always has an authoritative answer. Fill `heroku_apex_ips` in `terraform.tfvars`:

```bash
dig +short A <heroku DNS target of the apex>     # e.g. 2 addresses — paste them into heroku_apex_ips["example.com"]
```

Heroku publishes no stable inbound IP addresses, so pinned addresses are a **bounded stopgap**, not a steady state: re-run the `dig` and update `heroku_apex_ips` immediately before every weight change in Phase 5 and before any rollback in Phase 6, keep the cutover window short, and prefer `www.` as the canonical hostname (with the apex redirecting to it) for the duration.

{{ENDIF}}

```bash
cd terraform/
terraform init
terraform plan -out=tfplan
terraform apply tfplan
```
````

Verify all resources are created successfully:

```bash
terraform output
```

Record the output values — they are needed for data migration and application deployment.

---

## Phase 2: Data Migration

{{IF has_postgres}}

### PostgreSQL Migration (Heroku Postgres → RDS/Aurora)

**Strategy:** Use `pg_dump` / `pg_restore` for a full database migration with minimal downtime.

#### Pre-Migration Steps

1. Enable maintenance mode on Heroku to prevent writes during migration:

   ```bash
   heroku maintenance:on -a {{app_name}}
   ```

2. Verify source database size and estimate transfer time:

   ```bash
   heroku pg:info -a {{app_name}}
   ```

#### Execute Migration

Run the database migration script:

```bash
./scripts/migrate-postgres.sh
```

Or execute manually:

```bash
# Export from Heroku Postgres
PGPASSWORD="{{SOURCE_DB_PASSWORD}}" pg_dump \
  -h {{SOURCE_DB_HOST}} \
  -p {{SOURCE_DB_PORT}} \
  -U {{SOURCE_DB_USER}} \
  -d {{SOURCE_DB_NAME}} \
  -Fc \
  --no-owner \
  --no-acl \
  --verbose \
  > heroku_backup.dump

# Import to AWS RDS/Aurora
PGPASSWORD="{{TARGET_DB_PASSWORD}}" pg_restore \
  -h {{TARGET_DB_HOST}} \
  -p {{TARGET_DB_PORT}} \
  -U {{TARGET_DB_USER}} \
  -d {{TARGET_DB_NAME}} \
  --no-owner \
  --no-acl \
  --verbose \
  heroku_backup.dump
```

#### Post-Migration Verification

```bash
# Connect to target and verify row counts
PGPASSWORD="{{TARGET_DB_PASSWORD}}" psql \
  -h {{TARGET_DB_HOST}} \
  -p {{TARGET_DB_PORT}} \
  -U {{TARGET_DB_USER}} \
  -d {{TARGET_DB_NAME}} \
  -c "SELECT schemaname, relname, n_live_tup FROM pg_stat_user_tables ORDER BY n_live_tup DESC;"
```

Compare row counts between source and target to confirm data integrity.

{{IF migration_approach == "interim_cutover_data_first"}}

#### Interim Database Exposure (TLS Prerequisite, Then a Scoped Allowlist)

During the interim period your Heroku app connects to the AWS database. Work through the steps below **in the order given** — Step 1 is a prerequisite gate that must pass before any network path is opened in Step 2. The database stays private by default; Step 2 is about picking the narrowest path that works for your Heroku runtime.

> **⚠️ Never open port 5432 to `0.0.0.0/0`.** TLS protects the traffic, not the listener — a world-reachable database port is still exposed to internet-wide port scanning, credential stuffing, and protocol-level exploitation, and Heroku's "dynamic dyno IPs" are not a reason to accept it. Every path below ends in a **bounded, enumerated allowlist**.

##### Step 1 (prerequisite) — Enforce TLS and prove it is in effect

Complete every part of Step 1 and pass its verification gate before touching Step 2.

1. **Require TLS on the database.** The generated Terraform already sets `rds.force_ssl = 1` for this database, so `terraform apply` puts it in place — there is no console step and no way to skip it. Where the parameter lives, and whether it needs a reboot, depends on the engine:

   - **RDS for PostgreSQL** — set in the instance-level `aws_db_parameter_group`. The parameter is **static**, so reboot the instance once so it takes effect:

     ```bash
     aws rds reboot-db-instance --db-instance-identifier <db_identifier>
     ```

   - **Aurora PostgreSQL** — set in the cluster-level `aws_rds_cluster_parameter_group` (a cluster parameter, so an instance-level group cannot carry it). The parameter is **dynamic** here, so no reboot is needed and `reboot-db-instance` does not apply to a cluster. `terraform apply` is sufficient.

   > Defaults differ by engine, which is why the generated Terraform always sets this explicitly rather than relying on them. **RDS for PostgreSQL:** `rds.force_ssl` defaults to `1` (on) on major version 15 and later; on 14 and earlier the default is `0` (off). **Aurora PostgreSQL:** the default is `0` (**off**) on version 16 and older, and `1` (on) only from version 17 — so on the Aurora version this guide pins, TLS is _not_ enforced by default.

   Either way, do not treat this as done because the code exists — step 4 below is the gate that proves it.

2. **Ship the RDS CA bundle with your Heroku app** so the client can verify the server certificate:

   ```bash
   curl -o config/rds-ca-bundle.pem https://truststore.pki.rds.amazonaws.com/global/global-bundle.pem
   git add config/rds-ca-bundle.pem && git commit -m "Add RDS CA bundle" && git push heroku main
   ```

3. **Point `DATABASE_URL` at AWS with full certificate verification** (`verify-full`, not `require` — `require` encrypts but does not authenticate the server):

   ```bash
   heroku config:set DATABASE_URL="postgres://{{TARGET_DB_USER}}:{{TARGET_DB_PASSWORD}}@{{TARGET_DB_HOST}}:{{TARGET_DB_PORT}}/{{TARGET_DB_NAME}}?sslmode=verify-full&sslrootcert=config/rds-ca-bundle.pem" -a {{app_name}}
   ```

4. **Verification gate.** From a host that can already reach the database (for example the workstation or bastion you ran `pg_restore` from), confirm enforcement is real rather than assumed:

   ```bash
   # (a) pg_hba rules must be hostssl, not host
   psql "$ADMIN_DATABASE_URL" -c "SELECT type, database, auth_method FROM pg_hba_file_rules;"

   # (b) a plaintext connection must be REJECTED
   psql "postgres://{{TARGET_DB_USER}}@{{TARGET_DB_HOST}}:{{TARGET_DB_PORT}}/{{TARGET_DB_NAME}}?sslmode=disable"
   # Expected: FATAL: no pg_hba.conf entry for host "...", user "...", database "...", SSL off
   ```

   If (a) shows `host` instead of `hostssl`, or (b) succeeds, **stop here** — `rds.force_ssl` is not in effect (most often a missed reboot or a parameter group that was never attached). Do not open any network path until both checks pass.

##### Step 2 — Choose the narrowest connectivity path

Determine your runtime first: `heroku spaces:info --space <space_name>` succeeds only if the app runs in a Private Space; otherwise the app is on the Common Runtime. Then take the **first** path that applies.

**Path A — Private Space peered to your AWS VPC (preferred: no public exposure at all).**
Available on **Cedar**-generation Private Spaces. Private Space Peering establishes a private network connection between your dynos and an AWS VPC you control that does not traverse the public internet, so the database stays `Not publicly accessible` in private subnets.

```bash
heroku spaces:peering:info <space_name>          # Heroku-side account/VPC/CIDRs
# then request peering FROM your AWS account, and accept it on the Heroku side:
aws ec2 create-vpc-peering-connection --vpc-id <your_vpc_id> \
  --peer-vpc-id <heroku_vpc_id> --peer-owner-id <heroku_account_id>
heroku spaces:peerings:accept <pcx_id> --space <space_name>
```

Requirements and consequences:

- Your VPC must use an RFC 1918 CIDR that does not overlap the Private Space CIDRs (default `10.0.0.0/16`, `10.1.0.0/16`, `172.17.0.0/16`); check with `heroku spaces:peering:info` before requesting.
- Add a route for the Space CIDR to the route tables of the subnets holding the database.
- **Allowlist:** the Space's dyno CIDRs from `heroku spaces:peering:info` (e.g. `10.0.128.0/20`, `10.0.144.0/20`) — private ranges, a handful of entries.
- VPC peering is **not** available for **Fir**-generation Private Spaces. If your space is Fir, use Path B.

**Path B — Private Space stable outbound IPs (no peering available).**
Every Private Space, Cedar or Fir, egresses through a NAT gateway from "a small, stable list of IP addresses dedicated to the space." List them and allowlist those `/32`s:

```bash
heroku spaces:info --space <space_name>   # read the "Outbound IPs" line
```

**Allowlist:** each outbound IP as a `/32` (typically 4 addresses).

**Path C — Common Runtime plus a static-egress add-on.**
Common Runtime dynos have no controllable egress address — Heroku states you cannot control the originating IP address of outbound dyno requests, so there is no set of dyno IPs to allowlist. Do **not** compensate by widening the allowlist. Instead route the database connection through a SOCKS5 proxy add-on that owns static IPs, then allowlist the proxy:

- **QuotaGuard Static** — `heroku addons:create quotaguardstatic`. Provides a load-balanced pair of static IPs and a SOCKS5 tunnel (QGTunnel) that carries arbitrary TCP, PostgreSQL included, without application code changes.
- **Fixie Socks** — `heroku addons:create fixie-socks`. A standard SOCKS V5 proxy giving static outbound IPs for database and other TCP traffic; `fixie-wrench` forwards a local port for runtimes with no native SOCKS5 support.

Read the add-on's own dashboard for its current IP list — the addresses are per-plan and can change when you change plans.

**Allowlist:** the proxy's static IPs as `/32`s (typically 2).

Paths B and C send traffic over the public internet, so they additionally require the database to be publicly accessible **and** its DB subnet group to sit in subnets with an internet gateway route. The generated Terraform places the database in private subnets, so a Path B/C interim period means moving the DB subnet group as well — one more reason to prefer Path A and to keep the interim period short.

**There is no fourth path.** If you cannot enumerate a bounded allowlist by any of the routes above, the data-first interim approach is not viable for your setup: switch to `full_cutover` and migrate the database and application in one window instead.

##### Step 3 — Apply the allowlist in Terraform, never by hand in the console

Make every interim change in the generated Terraform and commit it, not through the RDS or EC2 console:

- A console edit is invisible to code review, so nobody sees that a database port was opened.
- A console edit is silently reverted by the next `terraform apply`, so the exposure exists only in the running account and never in Git — you cannot audit when it opened or whether it closed.

In `terraform/terraform.tfvars`, set the interim variables the generator emits, then plan and apply:

```hcl
interim_heroku_ingress_cidrs = ["203.0.113.10/32", "203.0.113.11/32"] # from Step 2
interim_db_public_access     = false                                  # true only on Path B or C
```

```bash
terraform plan -out=tfplan   # review the single added ingress rule before applying
terraform apply tfplan
```

Both variables default to closed (`[]` and `false`). `interim_heroku_ingress_cidrs = []` emits no ingress rule at all, and the variable rejects `0.0.0.0/0`.

##### Step 4 — Close the interim path at cutover

Once the application runs on AWS and no longer connects from Heroku:

1. Reset both variables to their defaults (`interim_heroku_ingress_cidrs = []`, `interim_db_public_access = false`), then `terraform apply`. Confirm the plan removes the ingress rule.
2. Delete the interim variables and the gated ingress block from the Terraform, and remove the static-egress add-on if you provisioned one for Path C.
3. Tear down the peering connection if you used Path A: `heroku spaces:peerings:destroy <pcx_id> --space <space_name>`.
4. Confirm the application reaches the database over private VPC networking only, and that the database reports `Not publicly accessible`.
   {{ENDIF}}

{{IF migration_method == "dms"}}

#### Alternative: AWS DMS Bulk Migration

For databases over ~10GB, AWS DMS can provide a faster migration with less downtime:

⚠️ **Important limitation:** AWS DMS **cannot** perform continuous replication (CDC) with Heroku Postgres. Heroku does not grant the `REPLICATION` role required for logical replication slots. DMS is for **one-time bulk data migration** with a final cutover window only.

**DMS Setup Steps:**

1. Create a DMS replication instance (publicly accessible, same VPC as target RDS)
2. Create source endpoint pointing to Heroku Postgres (SSL mode: require)
3. Create target endpoint pointing to your AWS RDS/Aurora instance
4. Copy schema first: `pg_dump --schema-only` from Heroku → `pg_restore` to target
5. Create migration task with:
   - Migration type: "Migrate existing data" (NOT "Replicate data changes")
   - Target table prep mode: "Do nothing" (schema already copied)
   - LOB mode: "Full LOB mode"
6. Enable pre-migration assessment and review results
7. Start the migration task
8. After completion, perform final cutover using the Heroku CLI sequence below
   {{ENDIF}}

{{IF migration_method == "bucardo"}}

#### Alternative: Bucardo (Near-Zero Downtime)

For near-zero downtime migration using trigger-based replication:

**Requirements:**

- Dedicated EC2 instance (Ubuntu 20.04+) to run Bucardo
- PostgreSQL client matching source version
- Ability to create triggers on Heroku database
- Primary keys on all source tables

**Setup overview:** Bucardo performs an initial full copy, then switches to delta-push mode for continuous replication until cutover. See the detailed Bucardo setup procedure in your migration reference documentation.

**Note:** Bucardo does not support LOB migration. Stored functions/procedures must be migrated separately via `pg_dump --schema-only`.
{{ENDIF}}

{{IF migration_method == "wal_g"}}

#### Alternative: WAL-G (Minimal Downtime for Large Databases)

For large databases requiring minimal downtime via WAL-based replication:

**Requirements:**

- Dedicated EC2 instance for WAL-G processing
- S3 bucket for WAL archive storage
- Network access between Heroku Postgres and your AWS infrastructure

**Setup overview:** WAL-G captures write-ahead logs from the source database and replays them on the target, allowing continuous catch-up with minimal final cutover window. See the detailed WAL-G setup procedure in your migration reference documentation.
{{ENDIF}}

#### Heroku CLI Cutover Sequence

Regardless of migration method, the final cutover follows this sequence:

```bash
# 1. Enable maintenance mode (prevents new writes)
heroku maintenance:on -a {{app_name}}

# 2. Final backup (safety net)
heroku pg:backups:capture -a {{app_name}}

# 3. If using pg_dump: run final migration now
# If using DMS/Bucardo/WAL-G: wait for final sync, then stop replication

# 4. Verify data in target database

# 5. Detach Heroku database (or point to new URL)
heroku config:set DATABASE_URL="postgres://{{TARGET_DB_USER}}:{{TARGET_DB_PASSWORD}}@{{TARGET_DB_HOST}}:{{TARGET_DB_PORT}}/{{TARGET_DB_NAME}}?sslmode=verify-full&sslrootcert=config/rds-ca-bundle.pem" -a {{app_name}}

# 6. Disable maintenance mode
heroku maintenance:off -a {{app_name}}

# 7. Verify application is working with new database
```

**After full application migration to AWS (no longer on Heroku):**

```bash
# Detach and optionally destroy Heroku Postgres
heroku addons:detach DATABASE -a {{app_name}}
# WARNING: Only destroy after confirming all data is accessible in AWS
# heroku addons:destroy heroku-postgresql -a {{app_name}}
```

{{ENDIF}}
{{IF has_redis}}

### Redis Migration (Heroku Redis → ElastiCache)

**Strategy:** Export Redis data using `DUMP`/`RESTORE` or `redis-cli --rdb` depending on dataset size.

#### Pre-Migration Steps

1. Check current Redis memory usage and key count:

   ```bash
   heroku redis:info -a {{app_name}}
   ```

2. Determine migration approach:
   - **Small dataset (< 1 GB):** Use key-by-key `DUMP`/`RESTORE`
   - **Large dataset (≥ 1 GB):** Use RDB snapshot transfer

#### Execute Migration (Small Dataset)

```bash
./scripts/migrate-redis.sh
```

Or execute manually using `redis-cli`:

```bash
# Connect to source and dump keys
redis-cli -h {{SOURCE_REDIS_HOST}} -p {{SOURCE_REDIS_PORT}} \
  -a "{{SOURCE_REDIS_PASSWORD}}" --tls \
  --scan --pattern '*' | while read key; do
    redis-cli -h {{SOURCE_REDIS_HOST}} -p {{SOURCE_REDIS_PORT}} \
      -a "{{SOURCE_REDIS_PASSWORD}}" --tls \
      DUMP "$key" | redis-cli -h {{TARGET_REDIS_HOST}} -p {{TARGET_REDIS_PORT}} \
      -a "{{TARGET_REDIS_PASSWORD}}" --tls \
      RESTORE "$key" 0 -
done
```

#### Execute Migration (Large Dataset)

```bash
# Generate RDB snapshot from source
redis-cli -h {{SOURCE_REDIS_HOST}} -p {{SOURCE_REDIS_PORT}} \
  -a "{{SOURCE_REDIS_PASSWORD}}" --tls \
  --rdb heroku_redis.rdb

# Import to ElastiCache (use S3 as intermediary)
aws s3 cp heroku_redis.rdb s3://{{MIGRATION_BUCKET}}/redis/heroku_redis.rdb
# Then use ElastiCache seed-from-S3 or restore from backup
```

#### Post-Migration Verification

```bash
# Compare key counts
echo "Source keys:" && redis-cli -h {{SOURCE_REDIS_HOST}} -p {{SOURCE_REDIS_PORT}} \
  -a "{{SOURCE_REDIS_PASSWORD}}" --tls DBSIZE
echo "Target keys:" && redis-cli -h {{TARGET_REDIS_HOST}} -p {{TARGET_REDIS_PORT}} \
  -a "{{TARGET_REDIS_PASSWORD}}" --tls DBSIZE
```

{{ENDIF}}
{{IF has_kafka}}

### Kafka Migration (Heroku Kafka → Amazon MSK)

**Strategy:** Use MirrorMaker 2 or topic recreation with producer replay for migration.

#### Pre-Migration Steps

1. Document current topic configuration:

   ```bash
   heroku kafka:topics -a {{app_name}}
   ```

2. Record consumer group offsets for replay:

   ```bash
   heroku kafka:consumer-groups -a {{app_name}}
   ```

#### Execute Migration

##### Option A: Topic Recreation (recommended for most cases)

1. Create topics on MSK matching source configuration:

   ```bash
   # For each topic, create with matching partitions and replication
   aws kafka create-topic \
     --cluster-arn {{MSK_CLUSTER_ARN}} \
     --topic-name {{TOPIC_NAME}} \
     --partitions {{PARTITION_COUNT}} \
     --replication-factor {{REPLICATION_FACTOR}}
   ```

2. Configure producers to write to MSK endpoint.

3. Replay historical data if needed using consumer offset reset.

##### Option B: MirrorMaker 2 (for zero-downtime with large backlogs)

```bash
# Configure MirrorMaker 2 to replicate from Heroku Kafka to MSK
# mm2.properties template:
clusters = source, target
source.bootstrap.servers = {{SOURCE_KAFKA_BROKERS}}
target.bootstrap.servers = {{TARGET_MSK_BROKERS}}
source->target.enabled = true
source->target.topics = .*
```

#### Post-Migration Verification

```bash
# Verify topic list on MSK
aws kafka list-topics --cluster-arn {{MSK_CLUSTER_ARN}}

# Verify message counts per topic/partition
kafka-consumer-groups.sh --bootstrap-server {{TARGET_MSK_BROKERS}} \
  --describe --all-groups
```

{{ENDIF}}

---

## Phase 3: Application Deployment

{{IF has_beanstalk}}

### Deploy to Elastic Beanstalk

The generated EB path deploys a source bundle containing your Dockerfile. GitHub Actions is the default deploy mechanism; CodePipeline is available only when selected during Clarify.

{{IF eb_deploy_method == "github_actions"}}

### GitHub Actions Deploy (Default)

The generated `.github/workflows/deploy-eb.yml` workflow uses GitHub OIDC role assumption, packages the source bundle, creates an Elastic Beanstalk application version, and updates each generated EB environment.

Before first run, create or provide a GitHub OIDC IAM role with permissions to call `elasticbeanstalk create-storage-location`, `elasticbeanstalk create-application-version`, `elasticbeanstalk update-environment`, and upload the source bundle to the EB storage bucket. Store the role ARN as the repository secret `AWS_ROLE_ARN`.

{{ENDIF}}
{{IF eb_deploy_method == "codepipeline"}}

### CodePipeline Deploy

The generated `terraform/pipeline.tf` creates an AWS-managed CodePipeline path from GitHub to Elastic Beanstalk. Complete the one-time GitHub connection authorization in the AWS console before expecting push-triggered deployments to run.

{{ENDIF}}
{{IF eb_deploy_method == "manual"}}

### Manual EB CLI Deploy

No automated deploy artifact was generated. Package and deploy manually:

```bash
VERSION_LABEL="v$(date +%Y%m%d%H%M%S)"
BUCKET="$(aws elasticbeanstalk create-storage-location --query S3Bucket --output text --region {{target_region}})"
zip -r app.zip . -x '.git/*' 'node_modules/*'
aws s3 cp app.zip "s3://${BUCKET}/{{app_name}}/${VERSION_LABEL}.zip" --region {{target_region}}
aws elasticbeanstalk create-application-version \
  --application-name {{app_name}} \
  --version-label "${VERSION_LABEL}" \
  --source-bundle "S3Bucket=${BUCKET},S3Key={{app_name}}/${VERSION_LABEL}.zip" \
  --region {{target_region}}
for ENVIRONMENT in {{EB_ENVIRONMENT_NAMES}}; do
  aws elasticbeanstalk update-environment \
    --environment-name "${ENVIRONMENT}" \
    --version-label "${VERSION_LABEL}" \
    --region {{target_region}}
done
```

{{ENDIF}}

### EB Config Var Migration

Export all Heroku config vars and import sensitive values to AWS Secrets Manager or SSM Parameter Store. Reference secrets in EB via the `environmentsecrets` namespace configured in `beanstalk.tf`; set non-sensitive config directly as EB environment properties.

{{ENDIF}}
{{IF has_fargate}}

### Build and Push Container Image

```bash
# Build Docker image
docker build -t {{app_name}}:latest .

# Tag for ECR
docker tag {{app_name}}:latest {{AWS_ACCOUNT_ID}}.dkr.ecr.{{target_region}}.amazonaws.com/{{app_name}}:latest

# Push to ECR
aws ecr get-login-password --region {{target_region}} | docker login --username AWS --password-stdin {{AWS_ACCOUNT_ID}}.dkr.ecr.{{target_region}}.amazonaws.com
docker push {{AWS_ACCOUNT_ID}}.dkr.ecr.{{target_region}}.amazonaws.com/{{app_name}}:latest
```

### Deploy to Fargate

The Terraform configuration creates ECS services automatically. After pushing the image, force a new deployment:

```bash
aws ecs update-service \
  --cluster {{app_name}}-cluster \
  --service {{app_name}}-web \
  --force-new-deployment \
  --region {{target_region}}
```

### Fargate Config Var Migration

Export all Heroku config vars and import to AWS Secrets Manager / Parameter Store, then reference them in your ECS task definition.

### ECS Express Mode (Forward-Look)

This generated path uses standard ECS/Fargate Terraform. If an ECS Express Mode path becomes available in this skill, treat it as an optional simplification for the Fargate override path, not as a replacement for the Elastic Beanstalk default without explicit user choice.

{{ENDIF}}

## Phase 4: Verification

### Health Checks

{{IF has_beanstalk}}

- [ ] Application responds on EB environment URL: `http://{{EB_ENVIRONMENT_URL}}/`
      {{IF has_beanstalk_web}}
- [ ] Each customer-supplied `eb_health_check_path_<app_sanitized>_web` returns a successful response on its app's EB environment URL
      {{ENDIF}}
      {{ENDIF}}
      {{IF has_fargate}}
- [ ] Application responds on ALB endpoint: `https://{{ALB_DNS_NAME}}/`
- [ ] Health check endpoint returns 200: `https://{{ALB_DNS_NAME}}/health`
      {{ENDIF}}
      {{IF has_postgres}}
- [ ] Database connectivity confirmed (application can read/write)
- [ ] Row counts match source database
      {{ENDIF}}
      {{IF has_redis}}
- [ ] Redis connectivity confirmed (application can read/write cache)
- [ ] Key counts match source Redis
      {{ENDIF}}
      {{IF has_kafka}}
- [ ] Kafka producers sending to MSK successfully
- [ ] Kafka consumers receiving from MSK successfully
- [ ] Topic/partition configuration matches source
      {{ENDIF}}

### Functional Tests

- [ ] Run application test suite against AWS deployment
- [ ] Verify critical user flows end-to-end
- [ ] Check log output in CloudWatch Logs

### Performance Baseline

- [ ] Response time within acceptable range (compare to Heroku baseline)
- [ ] No error rate increase in CloudWatch metrics
- [ ] Resource utilization (CPU/memory) within expected bounds

---

## Phase 5: Cutover

**Do not start this phase until every Phase 4 check passes.** Cutover is the only step that touches customer traffic; everything before it is reversible by deleting AWS resources, and everything after it is reversible by the steps in Phase 6.

### Before you move any traffic

- [ ] Phase 4 checklist green on the AWS deployment at its direct endpoint — for every hostname in the table below, the endpoint of **its own** app
- [ ] TTL on every custom-domain record at your **current** DNS provider lowered to 60 seconds **at least 24 hours ago** (resolvers cache the old TTL until it expires)
- [ ] You know your Heroku DNS targets: `heroku domains -a <app>` → "DNS Target" column, for every app in the table
{{IF has_route53_dns}}
- [ ] Phase 1 § "DNS preparation (Route 53)" is complete: `dig +short NS <zone>` returns Route 53 name servers for every zone in `hosted_zone_ids`, and `terraform plan` shows no changes to `aws_route53_record.heroku` / `aws_route53_record.apex_heroku`
{{ENDIF}}
{{IF migration_approach == "full_cutover"}}
- [ ] A fresh pre-cutover database export exists (Phase 2 procedure) — it is your rollback point for data
{{ENDIF}}

Each hostname has its own target; a hostname is never pointed at another app's endpoint:

| hostname | Heroku app | AWS endpoint | `terraform output` |
| --- | --- | --- | --- |

<!-- markdownlint-disable MD055 MD056 -->

{{FOR host IN dns_hostnames}}
| `{{host.hostname}}` | `{{host.heroku_app}}` | {{IF host.target_kind == "alb"}}ALB DNS name{{ENDIF}}{{IF host.target_kind == "eb"}}Elastic Beanstalk environment CNAME{{ENDIF}}{{IF host.target_kind == "eks"}}Service `EXTERNAL-IP` hostname from `kubectl get svc -n {{host.heroku_app}} web` (exists only after Phase 3){{ENDIF}}{{IF host.target_kind == "none"}}none — `{{host.heroku_app}}` has no web process; this hostname is not routed{{ENDIF}} | {{IF host.output_name}}`{{host.output_name}}`{{ELSE}}—{{ENDIF}} |
{{ENDFOR}}

<!-- markdownlint-enable MD055 MD056 -->

{{IF has_route53_dns}}

### DNS Cutover (Route 53, weighted)

`terraform/dns.tf` created, for each hostname in the table, two weighted records with the same name: one to Heroku, one to that hostname's own AWS endpoint (`terraform output dns_cutover` lists hostname → `heroku_app` → `aws_target` → `zone_id`). `cutover_weight` is the share of traffic AWS receives. Cutover is three applies; rollback is one.

Every step below is the same two actions: edit the `cutover_weight` line in `terraform/terraform.tfvars`, then run a plain apply. Never pass `-var cutover_weight=…` instead — Terraform re-reads `terraform.tfvars` on every apply, so a one-command override is silently undone by the next ordinary apply (for example the one that fixes an AWS-side bug after a rollback).

1. **Canary — 10 %:**

   ```bash
   cd terraform/
   sed -i.bak 's/^cutover_weight *=.*/cutover_weight = 10/' terraform.tfvars
   terraform apply -input=false
   ```

   Watch for 15–30 minutes: CloudWatch 5xx rate on the ALB/EB target group, application error tracker, `heroku logs --tail -a {{app_name}}` for the 90 % still on Heroku. Confirm sessions, logins, and any webhook callbacks work for the AWS share.
2. **Half — 50 %:** set `cutover_weight = 50` in `terraform.tfvars`, `terraform apply -input=false`. Watch for at least one full business cycle (an hour of peak traffic, or a batch window if you have one).
3. **All — 100 %:** set `cutover_weight = 100` in `terraform.tfvars`, `terraform apply -input=false`. Because the value is in the file, any later apply keeps 100.
{{IF migration_approach == "full_cutover"}}
4. **Freeze Heroku writes** once at 100 %: `heroku maintenance:on -a {{app_name}}`. Until this moment the Heroku share could still write to Heroku Postgres; after it, the AWS database is the only writer.
{{ENDIF}}

**Apex hostnames** (a hostname that equals its zone name) move with the same `cutover_weight` as everything else: `dns.tf` holds a weighted `A` record with Heroku's current addresses and a weighted ALIAS to AWS, so there is nothing to delegate or copy at 100 % and nothing to re-create on rollback (`terraform output dns_cutover` shows `apex = true` for them). Before **each** step above, re-resolve the apex's Heroku addresses (`dig +short A <heroku DNS target>`) and update `heroku_apex_ips` in `terraform.tfvars` if they changed — Heroku's inbound addresses are not stable (Phase 1 § DNS preparation, step 4). Test weighted cutover on `www.` first.

**Verify each step:** `dig +short <hostname>` from two networks, for every hostname in the table, should return that hostname's own AWS target in roughly the weighted proportion; `terraform output dns_cutover` shows the live weights and targets.

{{ELSE}}

### DNS Cutover (your current DNS provider)

No `dns.tf` was generated ({{IF custom_domains is empty}}no custom domain was discovered{{ELSE}}{{IF has_eks}}the design runs on EKS, whose web endpoint exists only after the Phase 3 deploy{{ELSE}}{{IF dns_strategy == "route53"}}no custom hostname maps to an Elastic Beanstalk or Fargate web service{{ELSE}}you chose to keep your DNS provider{{ENDIF}}{{ENDIF}}{{ENDIF}}). Cut over by editing records at your provider:

1. For each hostname, change the record from its Heroku DNS target to **its own app's** AWS endpoint from the table above — one line per hostname, never the same target for two apps:

   ```text
   {{FOR host IN dns_hostnames}}
   {{IF host.target_kind == "alb"}}{{host.hostname}}  CNAME  <terraform output alb_dns_name for {{host.heroku_app}}>          (was: <heroku DNS target>){{ENDIF}}
   {{IF host.target_kind == "eb"}}{{host.hostname}}  CNAME  <terraform output eb_environment_url for {{host.heroku_app}}>    (was: <heroku DNS target>){{ENDIF}}
   {{IF host.target_kind == "eks"}}{{host.hostname}}  CNAME  <EXTERNAL-IP hostname of Service web in namespace {{host.heroku_app}}>  (was: <heroku DNS target>){{ENDIF}}
   {{IF host.target_kind == "none"}}{{host.hostname}}  — not routed: {{host.heroku_app}} has no web process on AWS; decide what should answer for it before cutover{{ENDIF}}
   {{ENDFOR}}
   ```

   {{IF has_eks}}
   The EKS Service address is known only after Phase 3 (`kubectl get svc -n <app> web -o jsonpath='{.status.loadBalancer.ingress[0].hostname}'`), so this step cannot run before the deploy. TLS termination for the EKS web Service is **not** generated: request an ACM certificate for these hostnames, validate it at your DNS provider, and set `service.beta.kubernetes.io/aws-load-balancer-ssl-cert: <certificate ARN>` on the Service in `kubernetes/<app>-web-service.yaml` before moving traffic.
   {{ENDIF}}
   Apex hostnames cannot be CNAMEs: use your provider's ALIAS/ANAME record type, or move the zone to Route 53 (re-run Clarify with `dns_strategy: route53` to get `dns.tf`{{IF has_eks}} — not available for an EKS design{{ENDIF}}).
2. If your provider supports weighted or percentage routing, use it the same way as the Route 53 path above (10 % → 50 % → 100 %). If not, this is an all-at-once switch: do it at your lowest-traffic hour and keep the Heroku record value written down.
{{IF migration_approach == "full_cutover"}}
3. Once resolvers have moved (watch `dig` from two networks; TTL 60 means ~2 minutes after propagation), freeze Heroku writes: `heroku maintenance:on -a {{app_name}}`.
{{ENDIF}}
4. Restore TTLs to your normal value after the Phase 6 rollback window closes.

{{ENDIF}}

### After cutover

- [ ] Phase 4 checklist green again, now at the custom domain over HTTPS
- [ ] Heroku dyno load approaches zero (`heroku ps -a {{app_name}}`, request logs)
- [ ] Leave Heroku **running** for the rollback window below — do not scale to zero yet

---

## Phase 6: Rollback

Rollback is cheap only while Heroku is still running. This section is the reason Decommission comes last.

### Rollback window

Keep every Heroku dyno, add-on, and the pre-cutover database export for **at least 72 hours** after reaching 100 % on AWS. Nothing in Phase 7 (decommission) is reversible.

### Triggers — roll back when any of these holds after cutover

| Signal | Threshold | Where to look |
| --- | --- | --- |
| `{{health_check_path}}` on the custom domain | non-200 for > 2 minutes | ALB/EB target health, `curl -I https://{{app_domain}}{{health_check_path}}` |
| 5xx rate | > 2× the Heroku baseline for 10 minutes | CloudWatch `HTTPCode_Target_5XX_Count` vs Heroku's last week of `heroku logs` |
| p95 latency | > 1.5× Heroku baseline for 15 minutes | CloudWatch `TargetResponseTime` |
| A Phase 4 functional check fails on the custom domain | any | your test suite |
<!-- markdownlint-disable MD055 MD056 -->
{{IF has_postgres}}
| Row counts diverge from the Phase 2 reconciliation | any table | `scripts/migrate-postgres.sh --verify` |
{{ENDIF}}
<!-- markdownlint-enable MD055 MD056 -->

### Rollback by phase — what it costs and how long it takes

| You are in… | Rollback action | Data at risk | RTO |
| --- | --- | --- | --- |
| Phase 1 (provisioned, nothing deployed) | `terraform destroy` | none — Heroku untouched | minutes |
| Phase 2 (data copied) | Drop/ignore the AWS copy; Heroku Postgres is still primary | none | minutes |
| Phase 3 (deployed, no traffic) | Scale AWS services to 0 or leave idle | none | none |
| Phase 5 at 10 % / 50 % | **DNS back to Heroku** (below) | {{IF migration_approach == "full_cutover"}}writes made by the AWS share during the window — see "Writes after cutover"{{ELSE}}none — the database already lives on AWS and Heroku keeps using it through the interim path{{ENDIF}} | TTL (60 s) + resolver drain ≈ 5 min |
| Phase 5 at 100 % | DNS back to Heroku, then `heroku maintenance:off -a {{app_name}}` | {{IF migration_approach == "full_cutover"}}every write since 100 % — reverse-sync required{{ELSE}}none{{ENDIF}} | 5 min + reverse-sync time |
| After decommission | **No rollback** — rebuild Heroku from scratch | all Heroku-side state | hours–days |

### DNS back to Heroku

{{IF has_route53_dns}}

```bash
cd terraform/
sed -i.bak 's/^cutover_weight *=.*/cutover_weight = 0/' terraform.tfvars   # persist first — see below
grep '^cutover_weight' terraform.tfvars                                      # expect: cutover_weight = 0
terraform apply -input=false
```

Edit the file, do not pass `-var cutover_weight=0`: Phase 5 wrote `cutover_weight = 100` into `terraform.tfvars`, and Terraform re-reads that file on every apply. A `-var` override rolls traffic back for exactly one apply; the next ordinary `terraform apply` — typically the one you run minutes later to fix the AWS-side cause — would read 100 from the file and send all traffic back to AWS, skipping the 10 % restart below. With the value persisted, every later apply keeps traffic on Heroku until you deliberately raise it again.

That single apply returns every hostname — apex included — to Heroku: both weighted members stay in the zone (the AWS record at weight 0), so nothing is deleted, Route 53 keeps answering authoritatively for the apex, and rolling forward later is the same edit with a higher number. Before the apply, re-resolve the apex's Heroku addresses (`dig +short A <heroku DNS target>`) and update `heroku_apex_ips` in `terraform.tfvars` if they moved; the `heroku` apex member is only as good as those addresses.

{{ELSE}}

At your DNS provider, set each hostname back to its Heroku DNS target (the value you wrote down before cutover; `heroku domains -a {{app_name}}` shows it). With TTL 60 the change takes effect within about two minutes.

{{ENDIF}}

Then, if you had frozen Heroku: `heroku maintenance:off -a {{app_name}}`.

### Writes after cutover

{{IF migration_approach == "full_cutover"}}

Once traffic reached AWS, the AWS database received writes that Heroku Postgres never saw. Rolling DNS back without handling them silently loses data. Before `heroku maintenance:off`:

1. Decide: **accept the gap** (acceptable for a short canary with low write volume — say so explicitly in your incident notes), or **reverse-sync**.
2. Reverse-sync: `pg_dump` the AWS database (`--data-only` for the tables with new rows, or the whole database if the window was long) and `pg_restore` into Heroku Postgres — the Phase 2 script in reverse. Reconcile row counts before reopening Heroku.
3. Only then `heroku maintenance:off`.

The smaller the step that failed, the smaller this problem — which is why the canary is 10 %, not 50 %.

{{ELSE}}

Your database already lives on AWS (data-first migration) and Heroku reaches it through the interim access path. Rolling compute back to Heroku does not move or lose data; the database stays where it is. Do **not** close the interim path (`interim_heroku_ingress_cidrs`, `interim_db_public_access`) until compute has cut over for good.

{{ENDIF}}

### After a rollback

- Keep AWS resources provisioned; fix the cause (its `terraform apply` is safe: `terraform.tfvars` still says `cutover_weight = 0`); re-run Phase 4 at the direct endpoint; restart Phase 5 from 10 % by editing `terraform.tfvars` again.
- Record what tripped and what you changed in `ROLLBACK-NOTES.md` next to this guide — the next cutover attempt should start from that.

---

## Phase 7: Decommission Heroku

### Post-Migration Lockdown

Once your application is fully running on AWS (no longer connecting from Heroku):

- [ ] **Disable public access on RDS/Aurora:** Confirm the database reports "Not publicly accessible"
- [ ] **Restrict security groups:** Ensure no `0.0.0.0/0` inbound rules remain; allow only VPC-internal traffic on database ports
- [ ] **Verify backups:** Confirm automated backups are enabled with appropriate retention
- [ ] **Confirm private connectivity:** Application connects to the database via private VPC networking (not public endpoint)

{{IF migration_approach == "interim_cutover_data_first"}}

- [ ] **Close the interim access path in Terraform:** reset `interim_heroku_ingress_cidrs = []` and `interim_db_public_access = false`, `terraform apply`, then delete the interim ingress block — full procedure in "Interim Database Exposure" Step 4 above

{{ENDIF}}

### Decommission Heroku Resources

Only after the Phase 6 rollback window (72 hours at 100 % on AWS with no trigger fired):

1. Scale Heroku dynos to 0:

   ```bash
   heroku ps:scale web=0 worker=0 -a {{app_name}}
   ```

2. Disable Heroku maintenance mode (if still on):

   ```bash
   heroku maintenance:off -a {{app_name}}
   ```

3. Remove add-ons and delete app when confident:

   ```bash
   heroku addons:destroy --confirm {{app_name}} <addon_name>
   heroku apps:destroy --confirm {{app_name}}
   ```

{{IF deferred_addons.length > 0}}

---

## Manual Migration Items

The following add-ons could not be automatically mapped to AWS equivalents and require manual migration:

| Add-On | Plan | Provider | Reason | Recommendation |
| ------ | ---- | -------- | ------ | -------------- |

<!-- markdownlint-disable MD055 MD056 -->

{{FOR addon IN deferred_addons}}
| {{addon.addon_name}} | {{addon.addon_plan}} | {{addon.provider}} | {{addon.reason}} | {{addon.recommendation}} |
{{ENDFOR}}

<!-- markdownlint-enable MD055 MD056 -->

### Action Required

For each deferred add-on above:

1. Identify the equivalent AWS service or third-party replacement
2. Provision the replacement service manually
3. Migrate data/configuration from the Heroku add-on
4. Update application configuration to use the new service endpoint
5. Verify functionality before decommissioning the Heroku add-on

{{ENDIF}}

````
### Template Variable Resolution

Replace template variables using these sources:

| Variable | Source |
|----------|--------|
| `{{target_region}}` | `preferences.json` → `global.target_region` |
| `{{app_name}}` | First app from `heroku-resource-inventory.json`.apps[] (repeat per-app for multi-app) |
| `{{heroku_apps_comma_separated}}` | All app names from design services, comma-separated |
| `{{migration_approach}}` | `preferences.json` → `global.migration_approach` |
| `{{migration_method}}` | `preferences.json` → `data.migration_method` |
| `{{containerization_status}}` | `preferences.json` → `operational.containerization_status` |
| `{{target_exit_date}}` | `preferences.json` → `global.target_exit_date` (or "not set") |
| `{{SOURCE_DB_*}}` | Placeholder — user fills from `heroku pg:credentials:url` output |
| `{{TARGET_DB_*}}` | Placeholder — user fills from Terraform output |
| `{{SOURCE_REDIS_*}}` | Placeholder — user fills from `heroku redis:credentials` output |
| `{{TARGET_REDIS_*}}` | Placeholder — user fills from Terraform output |
| `{{SOURCE_KAFKA_*}}` | Placeholder — user fills from `heroku kafka:info` output |
| `{{TARGET_MSK_*}}` | Placeholder — user fills from Terraform output |
| `{{AWS_ACCOUNT_ID}}` | Placeholder — user fills with their AWS account ID |
| `{{ALB_DNS_NAME}}` | Placeholder — user fills from Terraform output |
| `{{EB_ENVIRONMENT_URL}}` | Elastic Beanstalk web environment CNAME output |
| `{{EB_ENVIRONMENT_NAMES}}` | Space-separated generated Elastic Beanstalk environment names for all EB process types |
| `{{MSK_CLUSTER_ARN}}` | Placeholder — user fills from Terraform output |
| `{{MIGRATION_BUCKET}}` | Placeholder — user creates an S3 bucket for migration artifacts |
| `{{app_domain}}` | First hostname in `custom_domains[]` when the inventory has `domain` resources; otherwise a placeholder the user fills |
| `{{custom_domains}}` | Comma-separated `custom_domains[]` (inventory `domain` resources' `config.hostname`) |
| `{{FOR host IN dns_hostnames}}` / `{{FOR host IN eligible_hostnames}}` | Step 0 `dns_hostnames[]` / `eligible_hostnames[]`; `host.hostname`, `host.heroku_app`, `host.target_kind` (`alb` / `eb` / `eks` / `none`), `host.output_name` (`alb_dns_name` / `eb_environment_url` / null) — one table row or record line per hostname, each with its own app's endpoint |
| `{{health_check_path}}` | `eb_health_check_path_<app_sanitized>_web` for the first Beanstalk web app; `/` for a Fargate web service (the ALB target group default) — the same path Phase 4 checks |

### Conditional Section Rules

**Strict enforcement — no empty sections:**

- Phase 1 renders "DNS preparation (Route 53) — before the first apply" exactly when `has_route53_dns`, placed before the `terraform init` block; it lists every `eligible_hostnames[]` entry and always includes the authority check, the existing-record conversion/import, the zone-adoption path, and the apex `heroku_apex_ips` paragraph.
- Phase 5 renders exactly ONE of its two DNS subsections: "DNS Cutover (Route 53, weighted)" when `has_route53_dns`, else "DNS Cutover (your current DNS provider)". Never both, never neither. The per-hostname table under "Before you move any traffic" always renders one row per `dns_hostnames[]` entry with that hostname's own app and endpoint; the manual branch renders one record line per entry (EKS and `none` entries get their own wording), and the EKS TLS note renders only when `has_eks`.
- Phase 6 Rollback is ALWAYS rendered. Its "Writes after cutover" subsection renders the `full_cutover` text or the data-first text per `migration_approach`, never both. The row-count trigger row renders only when `has_postgres`.

- If `has_postgres == false`: Omit the entire "PostgreSQL Migration" subsection under Phase 2 (heading + content)
- If `has_redis == false`: Omit the entire "Redis Migration" subsection under Phase 2 (heading + content)
- If `has_kafka == false`: Omit the entire "Kafka Migration" subsection under Phase 2 (heading + content)
- If ALL data store flags are false: Omit the entire "Phase 2: Data Migration" section and its Table of Contents entry
- If `deferred_addons.length == 0`: Omit the entire "Manual Migration Items" section and its Table of Contents entry
- Verification section (Phase 4) checkboxes: Only include data-store-specific checks for present data stores

---

## Step 2: Generate `README.md`

Write the README to `$MIGRATION_DIR/README.md` listing all generated artifacts.

### Template: README.md

```markdown
# Heroku-to-AWS Migration Artifacts

Generated by the heroku-to-aws migration skill on {{generation_timestamp}}.

## Overview

This directory contains all artifacts needed to migrate your Heroku application(s) to AWS.

**Source:** {{heroku_apps_comma_separated}} (Heroku)
**Target:** AWS ({{target_region}})
**Estimated Monthly Cost:** ${{estimated_monthly_total}} USD

---

## Artifact Files

| File | Purpose |
|------|---------|
| `terraform/` | Terraform configurations for all AWS infrastructure |
| `terraform/main.tf` | Provider configuration and module declarations |
| `terraform/baseline.tf` | Account-wide security baseline (contacts, CloudTrail, GuardDuty, budget alerts; Config + Security Hub when compliance declared). Opt-out steps in MIGRATION_GUIDE.md Phase 1 |
| `terraform/variables.tf` | Input variables (region, VPC, naming, baseline contact emails) |
| `terraform/outputs.tf` | Output values (endpoints, ARNs, DNS names) |
{{IF has_beanstalk}}
| `terraform/beanstalk.tf` | Elastic Beanstalk applications and environments |
{{IF eb_deploy_method == "github_actions"}}
| `.github/workflows/deploy-eb.yml` | GitHub Actions source-to-EB deploy workflow |
{{ENDIF}}
{{IF eb_deploy_method == "codepipeline"}}
| `terraform/pipeline.tf` | Optional CodePipeline source-to-EB deploy path |
{{ENDIF}}
{{ENDIF}}
{{IF has_fargate}}
| `terraform/ecs.tf` | ECS/Fargate task definitions and services |
| `terraform/alb.tf` | Application Load Balancer configuration |
{{ENDIF}}
{{IF has_postgres}}
| `terraform/rds.tf` | RDS/Aurora PostgreSQL database configuration |
{{ENDIF}}
{{IF has_redis}}
| `terraform/elasticache.tf` | ElastiCache Redis cluster configuration |
{{ENDIF}}
{{IF has_kafka}}
| `terraform/msk.tf` | Amazon MSK Kafka cluster configuration |
{{ENDIF}}
| `terraform/vpc.tf` | VPC, subnets, and networking configuration |
| `terraform/security-groups.tf` | Security group rules |
| `MIGRATION_GUIDE.md` | Step-by-step migration procedure |
| `README.md` | This file — artifact listing and quick start |
| `migration-report.html` | Stakeholder summary (costs + optional what-if scenarios); draft for review |
| `validation-report.json` | Terraform validation + policy-gate verdict (`status`, `policy_status`); reviewed at the completion gate |
{{IF has_postgres}}
| `scripts/migrate-postgres.sh` | PostgreSQL data migration script |
{{ENDIF}}
{{IF has_redis}}
| `scripts/migrate-redis.sh` | Redis data migration script |
{{ENDIF}}
{{IF generation_warnings_exist}}
| `generation-warnings.json` | Resources that could not be generated |
{{ENDIF}}
| `.phase-status.json` | Migration phase tracking (internal) |
| `heroku-resource-inventory.json` | Discovered Heroku resources (input) |
| `preferences.json` | Migration preferences (input) |
| `aws-design.json` | Designed AWS architecture (input) |
| `estimation-infra.json` | Cost estimates (input) |
| `scenarios/` | Optional what-if workshop snapshots (baseline + priced variants; see skill workshop docs) |

> **SA tip:** After Estimate (before or instead of regenerating), you can re-enter
> what-if workshop mode to change region, HA, compute target, or Graviton
> preference and compare up to 5 scenarios without re-discovery. Generated
> `migration-report.html` includes the scenario comparison when variants exist.

---

## Quick Start

### 1. Review the Migration Guide

Read `MIGRATION_GUIDE.md` for the complete migration procedure including prerequisites, data migration steps, and verification.

### 2. Configure Variables

Edit `terraform/variables.tf` or create a `terraform.tfvars` file:

```hcl
aws_region     = "{{target_region}}"
environment    = "{{environment_name}}"
# Add VPC, subnet, and other variables as needed
{{IF has_beanstalk_web}}
# Required customer inputs; repeat once per Beanstalk web app.
eb_application_port_<app_sanitized>_web  = "<application listen port>"
eb_health_check_path_<app_sanitized>_web = "<HTTP health check path>"
{{ENDIF}}
````

{{IF has_beanstalk_web}}

The generated per-app Elastic Beanstalk web variables have no defaults. A
non-interactive plan fails and identifies any missing or invalid value.

{{ENDIF}}

### 3. Apply Terraform

```bash
cd terraform/

# Initialize providers and modules
terraform init

# Preview changes
terraform plan -out=tfplan

# Apply infrastructure
terraform apply tfplan

# Record outputs for data migration
terraform output > ../terraform-outputs.txt
```

### 4. Migrate Data

{{IF has_postgres}}

```bash
# Migrate PostgreSQL database
./scripts/migrate-postgres.sh
```

{{ENDIF}}
{{IF has_redis}}

```bash
# Migrate Redis data
./scripts/migrate-redis.sh
```

{{ENDIF}}

### 5. Deploy Application

{{IF has_beanstalk}}
Deploy through the selected Elastic Beanstalk deploy method from `MIGRATION_GUIDE.md` Phase 3. The default is the generated GitHub Actions workflow.
{{ENDIF}}
{{IF has_fargate}}
Build and push your container image, then update ECS services. See `MIGRATION_GUIDE.md` Phase 3 for details.
{{ENDIF}}

### 6. Verify and Cutover

Follow the verification checklist in `MIGRATION_GUIDE.md` Phase 4, then perform DNS cutover per Phase 5.

---

## Important Notes

- **Placeholders:** Connection strings and credentials use `{{PLACEHOLDER}}` format. Replace with actual values from Heroku credentials and Terraform outputs.
- **Order matters:** Apply Terraform BEFORE running data migration scripts. The target infrastructure must exist first.
- **Backup:** Always verify backups exist before performing destructive operations on Heroku.
- **Parallel run:** Recommended 48–72 hours of parallel running before decommissioning Heroku.
  {{IF deferred_addons.length > 0}}
- **Manual items:** {{deferred_addons.length}} add-on(s) require manual migration. See "Manual Migration Items" in `MIGRATION_GUIDE.md`.
  {{ENDIF}}

````
### Template Variable Resolution

| Variable | Source |
|----------|--------|
| `{{generation_timestamp}}` | Current ISO 8601 timestamp |
| `{{heroku_apps_comma_separated}}` | All app names from design services |
| `{{target_region}}` | `preferences.json` → `global.target_region` |
| `{{estimated_monthly_total}}` | `estimation-infra.json` → total projected monthly cost |
| `{{environment_name}}` | `preferences.json` → `global.environment_naming` |
| `{{deferred_addons.length}}` | Count of entries in `aws-design.json`.deferred[] |

### Conditional Section Rules

- `has_beanstalk`: True if any service in design has `aws_service == "Elastic Beanstalk"`
- `eb_deploy_method`: `preferences.design_constraints.eb_deploy_method.value`; default to `"github_actions"` when absent and `has_beanstalk` is true
- `has_fargate`: True if any service in design has `aws_service == "Fargate"`
- `has_postgres`: True if any service has `aws_service` containing `"RDS PostgreSQL"` or `"Aurora PostgreSQL"`
- `has_redis`: True if any service has `aws_service == "ElastiCache Redis"`
- `has_kafka`: True if any service has `aws_service == "Amazon MSK"`
- `generation_warnings_exist`: True if `generation-warnings.json` has a NON-EMPTY `warnings` array (the file is always written, so test its contents, not its existence)

---

## Step 3: Generate Database Migration Scripts

Generate migration scripts ONLY for data stores present in the design. Place scripts in `$MIGRATION_DIR/scripts/`.

### 3A: PostgreSQL Migration Script

**Trigger:** `has_postgres == true`

Write to `$MIGRATION_DIR/scripts/migrate-postgres.sh`:

```bash
#!/usr/bin/env bash
set -euo pipefail

###############################################################################
# PostgreSQL Migration Script
# Migrates data from Heroku Postgres to AWS RDS/Aurora PostgreSQL
#
# Prerequisites:
#   - pg_dump and pg_restore installed (PostgreSQL client tools)
#   - Network access to both source and target databases
#   - Source and target credentials configured below
#
# Usage:
#   1. Fill in connection parameters below
#   2. Run: chmod +x migrate-postgres.sh && ./migrate-postgres.sh
###############################################################################

# ─── Source Connection (Heroku Postgres) ─────────────────────────────────────
# Retrieve via: heroku pg:credentials:url -a <app_name>
SOURCE_DB_HOST="{{SOURCE_DB_HOST}}"
SOURCE_DB_PORT="{{SOURCE_DB_PORT}}"
SOURCE_DB_USER="{{SOURCE_DB_USER}}"
SOURCE_DB_PASSWORD="{{SOURCE_DB_PASSWORD}}"
SOURCE_DB_NAME="{{SOURCE_DB_NAME}}"

# ─── Target Connection (AWS RDS/Aurora) ──────────────────────────────────────
# Retrieve via: terraform output (after terraform apply)
TARGET_DB_HOST="{{TARGET_DB_HOST}}"
TARGET_DB_PORT="{{TARGET_DB_PORT}}"
TARGET_DB_USER="{{TARGET_DB_USER}}"
TARGET_DB_PASSWORD="{{TARGET_DB_PASSWORD}}"
TARGET_DB_NAME="{{TARGET_DB_NAME}}"

# ─── Configuration ───────────────────────────────────────────────────────────
BACKUP_FILE="heroku_postgres_backup_$(date +%Y%m%d_%H%M%S).dump"
LOG_FILE="postgres_migration_$(date +%Y%m%d_%H%M%S).log"

# ─── Functions ───────────────────────────────────────────────────────────────
log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOG_FILE"; }

check_prerequisites() {
  log "Checking prerequisites..."
  command -v pg_dump >/dev/null 2>&1 || { log "ERROR: pg_dump not found"; exit 1; }
  command -v pg_restore >/dev/null 2>&1 || { log "ERROR: pg_restore not found"; exit 1; }
  command -v psql >/dev/null 2>&1 || { log "ERROR: psql not found"; exit 1; }
  log "Prerequisites OK"
}

test_source_connection() {
  log "Testing source database connection..."
  PGPASSWORD="$SOURCE_DB_PASSWORD" psql \
    -h "$SOURCE_DB_HOST" -p "$SOURCE_DB_PORT" \
    -U "$SOURCE_DB_USER" -d "$SOURCE_DB_NAME" \
    -c "SELECT 1;" >/dev/null 2>&1 || { log "ERROR: Cannot connect to source database"; exit 1; }
  log "Source connection OK"
}

test_target_connection() {
  log "Testing target database connection..."
  PGPASSWORD="$TARGET_DB_PASSWORD" psql \
    -h "$TARGET_DB_HOST" -p "$TARGET_DB_PORT" \
    -U "$TARGET_DB_USER" -d "$TARGET_DB_NAME" \
    -c "SELECT 1;" >/dev/null 2>&1 || { log "ERROR: Cannot connect to target database"; exit 1; }
  log "Target connection OK"
}

export_source() {
  log "Exporting source database to $BACKUP_FILE..."
  PGPASSWORD="$SOURCE_DB_PASSWORD" pg_dump \
    -h "$SOURCE_DB_HOST" \
    -p "$SOURCE_DB_PORT" \
    -U "$SOURCE_DB_USER" \
    -d "$SOURCE_DB_NAME" \
    -Fc \
    --no-owner \
    --no-acl \
    --verbose \
    -f "$BACKUP_FILE" 2>>"$LOG_FILE"
  log "Export complete: $(du -h "$BACKUP_FILE" | cut -f1)"
}

import_target() {
  log "Importing to target database..."
  PGPASSWORD="$TARGET_DB_PASSWORD" pg_restore \
    -h "$TARGET_DB_HOST" \
    -p "$TARGET_DB_PORT" \
    -U "$TARGET_DB_USER" \
    -d "$TARGET_DB_NAME" \
    --no-owner \
    --no-acl \
    --verbose \
    "$BACKUP_FILE" 2>>"$LOG_FILE"
  log "Import complete"
}

verify_migration() {
  log "Verifying migration..."

  SOURCE_COUNT=$(PGPASSWORD="$SOURCE_DB_PASSWORD" psql \
    -h "$SOURCE_DB_HOST" -p "$SOURCE_DB_PORT" \
    -U "$SOURCE_DB_USER" -d "$SOURCE_DB_NAME" \
    -t -c "SELECT SUM(n_live_tup) FROM pg_stat_user_tables;" | tr -d ' ')

  TARGET_COUNT=$(PGPASSWORD="$TARGET_DB_PASSWORD" psql \
    -h "$TARGET_DB_HOST" -p "$TARGET_DB_PORT" \
    -U "$TARGET_DB_USER" -d "$TARGET_DB_NAME" \
    -t -c "SELECT SUM(n_live_tup) FROM pg_stat_user_tables;" | tr -d ' ')

  log "Source row count: $SOURCE_COUNT"
  log "Target row count: $TARGET_COUNT"

  if [ "$SOURCE_COUNT" == "$TARGET_COUNT" ]; then
    log "✓ Row counts match — migration verified"
  else
    log "⚠ Row count mismatch (source=$SOURCE_COUNT, target=$TARGET_COUNT)"
    log "  This may be expected if the source had writes during migration."
    log "  Review per-table counts to identify discrepancies."
  fi
}

# ─── Main ────────────────────────────────────────────────────────────────────
main() {
  log "=== PostgreSQL Migration Started ==="
  check_prerequisites
  test_source_connection
  test_target_connection
  export_source
  import_target
  verify_migration
  log "=== PostgreSQL Migration Complete ==="
  log "Backup file: $BACKUP_FILE"
  log "Log file: $LOG_FILE"
}

main "$@"
````

### 3B: Redis Migration Script

**Trigger:** `has_redis == true`

Write to `$MIGRATION_DIR/scripts/migrate-redis.sh`:

```bash
#!/usr/bin/env bash
set -euo pipefail

###############################################################################
# Redis Migration Script
# Migrates data from Heroku Redis to AWS ElastiCache Redis
#
# Prerequisites:
#   - redis-cli installed (Redis client tools)
#   - Network access to both source and target Redis instances
#   - TLS support enabled in redis-cli (if source/target use TLS)
#
# Usage:
#   1. Fill in connection parameters below
#   2. Run: chmod +x migrate-redis.sh && ./migrate-redis.sh
###############################################################################

# ─── Source Connection (Heroku Redis) ────────────────────────────────────────
# Retrieve via: heroku redis:credentials -a <app_name>
SOURCE_REDIS_HOST="{{SOURCE_REDIS_HOST}}"
SOURCE_REDIS_PORT="{{SOURCE_REDIS_PORT}}"
SOURCE_REDIS_PASSWORD="{{SOURCE_REDIS_PASSWORD}}"
SOURCE_REDIS_TLS="true"

# ─── Target Connection (AWS ElastiCache) ─────────────────────────────────────
# Retrieve via: terraform output (after terraform apply)
TARGET_REDIS_HOST="{{TARGET_REDIS_HOST}}"
TARGET_REDIS_PORT="{{TARGET_REDIS_PORT}}"
TARGET_REDIS_PASSWORD="{{TARGET_REDIS_PASSWORD}}"
TARGET_REDIS_TLS="true"

# ─── Configuration ───────────────────────────────────────────────────────────
LOG_FILE="redis_migration_$(date +%Y%m%d_%H%M%S).log"
BATCH_SIZE=100

# ─── Functions ───────────────────────────────────────────────────────────────
log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOG_FILE"; }

source_cli() {
  local tls_flag=""
  [ "$SOURCE_REDIS_TLS" == "true" ] && tls_flag="--tls"
  redis-cli -h "$SOURCE_REDIS_HOST" -p "$SOURCE_REDIS_PORT" \
    -a "$SOURCE_REDIS_PASSWORD" $tls_flag "$@"
}

target_cli() {
  local tls_flag=""
  [ "$TARGET_REDIS_TLS" == "true" ] && tls_flag="--tls"
  redis-cli -h "$TARGET_REDIS_HOST" -p "$TARGET_REDIS_PORT" \
    -a "$TARGET_REDIS_PASSWORD" $tls_flag "$@"
}

check_prerequisites() {
  log "Checking prerequisites..."
  command -v redis-cli >/dev/null 2>&1 || { log "ERROR: redis-cli not found"; exit 1; }
  log "Prerequisites OK"
}

test_connections() {
  log "Testing source connection..."
  source_cli PING >/dev/null 2>&1 || { log "ERROR: Cannot connect to source Redis"; exit 1; }
  log "Source connection OK"

  log "Testing target connection..."
  target_cli PING >/dev/null 2>&1 || { log "ERROR: Cannot connect to target Redis"; exit 1; }
  log "Target connection OK"
}

get_source_info() {
  local dbsize
  dbsize=$(source_cli DBSIZE | awk '{print $NF}')
  log "Source database size: $dbsize keys"
  echo "$dbsize"
}

migrate_keys() {
  local total_keys migrated=0 failed=0
  total_keys=$(get_source_info)

  log "Starting key migration ($total_keys keys)..."

  source_cli --scan --pattern '*' | while IFS= read -r key; do
    # Get TTL
    local ttl
    ttl=$(source_cli TTL "$key")
    [ "$ttl" -lt 0 ] && ttl=0

    # Dump and restore
    local dump
    dump=$(source_cli DUMP "$key")

    if [ -n "$dump" ] && [ "$dump" != "" ]; then
      if target_cli RESTORE "$key" "$((ttl * 1000))" "$dump" REPLACE >/dev/null 2>&1; then
        migrated=$((migrated + 1))
      else
        failed=$((failed + 1))
        log "WARN: Failed to restore key: $key"
      fi
    fi

    # Progress report every BATCH_SIZE keys
    if [ $(( (migrated + failed) % BATCH_SIZE )) -eq 0 ]; then
      log "Progress: $((migrated + failed))/$total_keys (migrated=$migrated, failed=$failed)"
    fi
  done

  log "Migration complete: migrated=$migrated, failed=$failed"
}

verify_migration() {
  log "Verifying migration..."

  local source_count target_count
  source_count=$(source_cli DBSIZE | awk '{print $NF}')
  target_count=$(target_cli DBSIZE | awk '{print $NF}')

  log "Source key count: $source_count"
  log "Target key count: $target_count"

  if [ "$source_count" == "$target_count" ]; then
    log "✓ Key counts match — migration verified"
  else
    log "⚠ Key count mismatch (source=$source_count, target=$target_count)"
    log "  Possible causes: expired keys during migration, or failed restores above."
  fi
}

# ─── Main ────────────────────────────────────────────────────────────────────
main() {
  log "=== Redis Migration Started ==="
  check_prerequisites
  test_connections
  migrate_keys
  verify_migration
  log "=== Redis Migration Complete ==="
  log "Log file: $LOG_FILE"
}

main "$@"
```

### 3C: No Kafka Migration Script

Kafka migration does NOT generate a standalone script because MirrorMaker 2 configuration is environment-specific and requires running infrastructure. The `MIGRATION_GUIDE.md` provides the procedure and configuration templates instead.

---

## Step 4: Set Script Permissions

After writing scripts, ensure they are executable:

```bash
chmod +x $MIGRATION_DIR/scripts/migrate-postgres.sh  # (if generated)
chmod +x $MIGRATION_DIR/scripts/migrate-redis.sh     # (if generated)
```

---

## Step 5: Validate Generated Documentation

Verify all generated files:

1. **MIGRATION_GUIDE.md** exists and:
   - Contains "Prerequisites" section
   - Contains "Phase 1: Infrastructure Provisioning" section
   - If `has_postgres`: Contains "PostgreSQL Migration" subsection
   - If `has_redis`: Contains "Redis Migration" subsection
   - If `has_kafka`: Contains "Kafka Migration" subsection
   - If NOT `has_postgres`: Does NOT contain "PostgreSQL Migration" subsection
   - If NOT `has_redis`: Does NOT contain "Redis Migration" subsection
   - If NOT `has_kafka`: Does NOT contain "Kafka Migration" subsection
   - If `has_postgres`: Contains "Heroku CLI Cutover Sequence" subsection
   - If `migration_method == "dms"`: Contains DMS limitation warning about CDC/continuous replication
   - If `migration_approach == "interim_cutover_data_first"`: Contains "Interim Database Exposure" section whose Step 1 is the TLS prerequisite gate and whose Step 2 offers only bounded-allowlist connectivity paths
   - If `migration_approach == "interim_cutover_data_first"`: Contains "Platform Risk Advisory" section
   - Does NOT instruct opening a database port (5432) to `0.0.0.0/0` anywhere — interim access must be a scoped CIDR allowlist applied through Terraform
   - If `containerization_status != "containerized"`: Contains "Containerization Prerequisites" section
   - Contains "Post-Migration Lockdown" section
   - Contains "Config Var Migration" section
   - If `has_beanstalk_web`: Explains that each web app's `eb_application_port_<app>_web` and `eb_health_check_path_<app>_web` are required before planning
   - If `has_beanstalk`: Contains selected EB deploy method instructions and the EB DNS cutover target, and emits no CodePipeline artifact unless `eb_deploy_method` is `"codepipeline"`
   - If `has_route53_dns`: Phase 1 contains "DNS preparation (Route 53)" before the `terraform init` block (authority check, existing-record conversion + `terraform import`, zone adoption, `heroku_apex_ips`), and no Route 53 write is instructed before that authority check
   - Phase 5 lists every `dns_hostnames[]` hostname with its own Heroku app and its own AWS endpoint/output name (`alb_dns_name` or `eb_environment_url`; never `eb_environment_cname`); no two apps share a target. If `has_eks`: the manual branch names the Kubernetes Service `EXTERNAL-IP` as the target and states that EKS web TLS is not generated
   - Every `cutover_weight` change in Phases 5 and 6 edits `terraform.tfvars` and runs a plain `terraform apply`; the guide contains no `-var cutover_weight` command
   - Does NOT hard-code a health check path for Elastic Beanstalk verification; use the applicable per-app `eb_health_check_path_<app>_web` instead
   - Contains "Verification" section with data-store-appropriate checks
   - If `deferred_addons.length > 0`: Contains "Manual Migration Items" section

2. **README.md** exists and:
   - Lists all artifact files present in `$MIGRATION_DIR`
   - Includes terraform apply command sequence
   - References correct target region
   - Includes estimated monthly cost

3. **Scripts** (if generated):
   - `scripts/migrate-postgres.sh` exists if `has_postgres`
   - `scripts/migrate-redis.sh` exists if `has_redis`
   - Scripts contain connection parameter placeholders (not real credentials)
   - Scripts are executable (`chmod +x` applied)

---

## Error Handling

| Error                          | Behavior                                        | Impact                                 |
| ------------------------------ | ----------------------------------------------- | -------------------------------------- |
| Template variable unresolvable | Use placeholder with `{{VARIABLE_NAME}}` format | User fills manually                    |
| No data stores in design       | Omit Phase 2 entirely from guide                | Valid — compute-only migration         |
| No deferred add-ons            | Omit Manual Migration Items section             | Valid — all add-ons mapped             |
| All three data stores absent   | MIGRATION_GUIDE still generated (compute-only)  | Valid migration path                   |
| Script write failure           | Log warning, continue with remaining files      | Parent captures in generation-warnings |
