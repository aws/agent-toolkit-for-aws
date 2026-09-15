# Configure MSK Brokers and Clusters

Broker-level and cluster-level configuration for Amazon MSK Provisioned clusters: creating and applying MSK **configurations** (`server.properties`), and setting custom domain names on the brokers with `custom.advertised.listeners`.

For the client-side layer that fronts a custom domain (NLB, ACM certificate, Route 53, TLS handshake, mTLS), see [configure-clients.md](configure-clients.md). For per-instance-size thread tuning and durability defaults, see [size-and-choose-cluster.md](size-and-choose-cluster.md).

> **Note:** The AWS MCP server is the recommended way to run the AWS API interactions in this reference (`kafka` describe/update calls, `kafka-configs.sh`, etc.) — it provides sandboxed execution, audit logging, and observability. It is not a hard requirement; when the MCP server is unavailable, fall back to the AWS CLI or shell.

## Custom Domain Names (custom.advertised.listeners)

Use a custom domain name (e.g., `b-1.example.com`) when clients need a static, customer-controlled endpoint that survives cluster recreation, migration, or DR failover, or must align with organizational DNS/naming. MSK brokers otherwise advertise AWS-generated addresses (`b-1.<cluster>.<id>.kafka.<region>.amazonaws.com`) that change when a cluster is recreated. This section covers the **cluster configuration** that sets the advertised address; the NLB / certificate / DNS layer that must exist first is in [configure-clients.md](configure-clients.md).

### Set it with the `custom.advertised.listeners` configuration property

Recommended approach: a single, validated, cluster-wide MSK **configuration property**. Set it once and MSK resolves it per broker and reapplies it automatically as the cluster scales. This **replaces** the per-broker `kafka-configs.sh --alter --add-config advertised.listeners=...` override.

- **Works in both ZooKeeper and KRaft mode.** The per-broker `advertised.listeners` override could not be applied on KRaft clusters; `custom.advertised.listeners` works on both. If asked whether custom domains are possible on a KRaft cluster, the answer is yes — via this property. Do NOT recommend the per-broker `kafka-configs.sh` override or self-managed Kafka as the current solution, and do NOT claim custom domains are impossible on KRaft.
- **Provisioned only (Standard and Express brokers).** NOT supported on MSK Serverless (Serverless does not support custom broker configurations). If a custom domain is required on Serverless, use a Provisioned cluster.
- **Reversible and IaC-friendly.** Flows through CloudFormation, CDK, Terraform, and the CLI.

**Value format:**

```
custom.advertised.listeners=<LISTENER>://<hostname>:<port>
```

Example (three-broker IAM cluster fronted by an NLB on ports 9001-9003):

```
custom.advertised.listeners=CLIENT_IAM://b-{broker_id}.example.com:9000+{broker_id}
```

### Rules that MSK validates (synchronously, before any change)

1. **Client listeners only.** Valid values are the client-facing listeners: `CLIENT`, `CLIENT_SECURE`, `CLIENT_SECURE_PUBLIC`, `CLIENT_SASL_SCRAM`, `CLIENT_SASL_SCRAM_PUBLIC`, `CLIENT_IAM`, `CLIENT_IAM_PUBLIC`. Internal listeners `REPLICATION` and `CONTROLLER` are **rejected** — this protects the listeners MSK manages. A rejected `REPLICATION://...` config is not a syntax problem with the `+` separator or offset; it is rejected because internal listeners are not allowed.
2. **Listener must be bound (active) on the cluster.** Name the client listener that matches the cluster's authentication type (e.g., `CLIENT_IAM` on an IAM cluster). Specifying an unbound listener (e.g., `CLIENT_SECURE` on an IAM-only cluster) is rejected, and the error lists the valid client listeners for your cluster.
3. **`{broker_id}` template + uniqueness.** `{broker_id}` is replaced with each broker's numeric ID at apply time. In a port expression like `9000+{broker_id}`, the broker ID is added to the base port, so broker 1 -> 9001, broker 2 -> 9002, broker 10 -> 9010 (9000 is just an example base). Each broker's **resolved `host:port` must be unique**. `{broker_id}` may appear in the hostname, the port, or both — so a shared hostname with a per-broker port (`CLIENT_IAM://example.com:9000+{broker_id}`) is valid, but a shared hostname AND shared port for every broker fails validation. The resulting ports must match the TLS listeners provisioned on your NLB.

### Apply workflow

1. Put the property in a file (leave `{broker_id}` **literal** — MSK resolves it per broker; do not substitute IDs yourself). It can live alongside other broker properties in a single configuration revision.
2. Create/update the configuration, passing the file with **`fileb://`** (not `file://`) so the CLI reads it as bytes and base64-encodes it — passing inline or with `file://` is fragile because of the `{broker_id}` braces:

   ```
   aws kafka create-configuration --name custom-domain-iam \
     --server-properties fileb://custom-domain-config.txt
   ```

   (For an existing configuration, add the property and create a new revision with `update-configuration`.)
3. Apply the returned configuration ARN and revision to the cluster:

   ```
   aws kafka update-cluster-configuration \
     --cluster-arn <arn> \
     --configuration-info arn=<config-arn>,revision=<revision> \
     --current-version <current-cluster-version>
   ```

   MSK validates, resolves the pattern per broker, and applies it via a **rolling restart**.
4. Track the rollout with `describe-cluster-operation-v2` (or the `DescribeOperation` API): states go `UPDATE_IN_PROGRESS` -> `UPDATE_COMPLETE`/`SUCCESS` or `UPDATE_FAILED`/`FAILED`.

> **Auditability:** Ensure CloudTrail is logging MSK API calls (`kafka:UpdateClusterConfiguration`, `kafka:UpdateConfiguration`) so configuration changes are auditable.

**Rollout failure recovery.** If a broker fails to start, the rollout **halts at that broker** and the remaining brokers keep their previous configuration — the cluster is not left half-configured, and no recreation is needed. Fix the property (common cause: the resolved `host:port` isn't resolvable/reachable/trusted via your NLB+DNS+cert) and re-apply.

**Reverting.** Fully reversible: remove `custom.advertised.listeners` from the configuration (new revision without it) and re-apply. MSK reverts the listener to its original AWS-generated advertised address via a rolling restart. Only the advertised address of the **named** listener is affected — `REPLICATION`, authentication, multi-VPC (`CLIENT_IAM_VPCE`), and PrivateLink connectivity are unaffected.

### Migrate from the dynamic per-broker override to the static property

Existing custom-domain setups configured the advertised address **dynamically, per broker**, with `kafka-configs.sh --alter --add-config advertised.listeners=[...]` — repeated on every broker and re-run whenever a broker was added, hand-preserving the `REPLICATION`/`REPLICATION_SECURE` (and any multi-VPC) entries each time. Migrating to the static `custom.advertised.listeners` property removes that per-broker toil, adds up-front validation, works on KRaft, and flows through IaC. The networking layer you already built (NLB, DNS, certificate) stays exactly as is — only *how* the advertised address is configured changes.

1. **Capture the current pattern.** On each broker, read the existing dynamic value so you can reproduce it exactly:

   ```
   kafka-configs.sh --bootstrap-server $BS --entity-type brokers --entity-name <broker-id> \
     --command-config client.properties --all --describe | grep advertised.listeners
   ```

   Note the client listener name and the `host:port` each broker advertises (e.g., `CLIENT_SASL_SCRAM://b-1.example.com:9001`) and confirm it fits a `{broker_id}` template such as `b-{broker_id}.example.com:9000+{broker_id}`.
2. **Include only the client listener in the property.** Unlike the dynamic override — where you had to include and preserve `REPLICATION`/`REPLICATION_SECURE` (and multi-VPC) entries yourself — `custom.advertised.listeners` manages only the named client listener, and MSK preserves the internal, multi-VPC (`CLIENT_IAM_VPCE`), and PrivateLink listeners for you. Do NOT put `REPLICATION`/`CONTROLLER` in the property (they are rejected).
3. **Match the existing address for a zero-cutover migration.** Choose the template so each broker's resolved `host:port` equals what it already advertises. Then the advertised address does not change and clients keep connecting with no cutover. If you deliberately change the pattern, clients cut over on their next metadata refresh — build and verify the new NLB listeners, target groups, and DNS records first (see [configure-clients.md](configure-clients.md)).
4. **Apply via the configuration, not `kafka-configs.sh`.** Add `custom.advertised.listeners` to a new MSK configuration or, if you already manage one for the cluster, add it and create a new revision with `update-configuration`; then apply with `update-cluster-configuration` (see Apply workflow above). From now on, manage the advertised address only through the MSK configuration, not with per-broker dynamic overrides.
5. **Clear any stale dynamic override and verify the effective value.** A per-broker dynamic config can take precedence over broker configuration in Kafka, so after applying, confirm the effective `advertised.listeners` with the `--describe` command from step 1. If a leftover dynamic override remains, delete it with `kafka-configs.sh --alter --entity-type brokers --entity-name <broker-id> --delete-config advertised.listeners` — do this only after step 3 guarantees the resolved address is identical, so removal changes nothing for clients.
6. **Confirm and finish.** Ensure the operation reaches `SUCCESS` (`describe-cluster-operation-v2`) and clients still connect (`kafka-topics.sh --list --bootstrap-server <custom-bootstrap>`). Going forward MSK reapplies the property to new/replaced brokers automatically, so you no longer re-run the per-broker override (you still add NLB/DNS entries for new brokers).

KRaft note: if the dynamic override was never an option because the cluster is in KRaft mode, the static property is the supported path and works on KRaft. The migration is reversible — remove the property and re-apply to return to the AWS-generated address.

### Scaling and broker replacement (cluster side)

When you add brokers (or a broker is replaced during automated healing), MSK automatically applies the configuration to the new broker, resolving `{broker_id}` for its ID — nothing to do on the cluster side. The **networking layer does NOT auto-scale**, however: you must add the corresponding NLB listener, target group, and DNS record for each new broker. See [configure-clients.md](configure-clients.md).

### Prerequisite: the networking/trust layer must exist first

Applying this property changes what the brokers advertise, so clients cut over to the custom domain on their next metadata refresh. If the NLB, DNS, and trusted certificate are not already in place, connected clients cannot reconnect. Build that layer first and follow the safe two-phase cutover documented in [configure-clients.md](configure-clients.md).

## References

- [Amazon MSK simplifies configuring custom domain names](https://aws.amazon.com/blogs/big-data/amazon-msk-simplifies-configuring-custom-domain-names/) — the `custom.advertised.listeners` property
- [MSK Configuration](https://docs.aws.amazon.com/msk/latest/developerguide/msk-configuration.html)
