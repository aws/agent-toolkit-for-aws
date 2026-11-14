# Networking — ODB Peering (Single VPC)

ODB peering connects an AWS VPC to an ODB network (an OCI VCN hosted in an AWS AZ). It is **not** VPC peering — use `aws odb`, not `aws ec2 create-vpc-peering-connection`.

## Prerequisites

- ODB network already created (AWS console or `aws odb create-odb-network`)
- App VPC in the same AWS region
- Non-overlapping CIDRs between the VPC and ODB client/backup subnets
- Reserved CIDRs that MUST NOT appear in ODB client/backup subnets: `169.254.0.0/16`, `224.0.0.0/4`, `240.0.0.0/4`, `100.105.0.0/16`

## Step-by-Step

### 1. Get ODB network details

```bash
aws odb get-odb-network \
  --odb-network-id odbnet-abc12def \
  --region us-east-1
```

Record: `clientSubnetCidr`, `backupSubnetCidr`, `dnsListenerIps`, `availabilityZone`, `availabilityZoneId`.

### 2. Verify CIDR non-overlap

The app VPC CIDR MUST NOT overlap with ODB client/backup subnet CIDRs or any other peered VPC CIDR. If they overlap, re-plan before creating the peering because overlapping CIDRs cause peering creation to fail with an opaque error.

### 3. Create the ODB peering

```bash
aws odb create-odb-peering-connection \
  --odb-network-id odbnet-abc12def \
  --peer-network-id vpc-0a1b2c3d4e5f6g7h \
  --region us-east-1
```

Wait for status `AVAILABLE`:

```bash
aws odb get-odb-peering-connection \
  --odb-peering-connection-id odbpcx-11223344 \
  --region us-east-1
```

### 4. Add route in app VPC route table (most commonly missed)

```bash
aws ec2 create-route \
  --route-table-id rtb-0123456789abcdef0 \
  --destination-cidr-block 10.20.0.0/24 \
  --odb-network-arn arn:aws:odb:us-east-1:123456789012:odb-network/odbnet-abc12def
```

Add this route for **every** route table associated with subnets where the application runs. Without it, connections hang with ORA-12170.

### 5. Update security groups

App VPC security group — outbound:
- TCP 1521 (Oracle TCP) to ODB client subnet CIDR
- TCP 2484 (Oracle TCPS) to ODB client subnet CIDR
- UDP/TCP 53 to ODB DNS listener IPs (if resolver outbound endpoint shares the SG)

### 6. Proceed to DNS (mandatory next step)

Load **networking-dns-resolver.md** (loaded reference). Without DNS forwarding, the SCAN hostname will not resolve.

## Cross-Account Peering

If the ODB network and app VPC are in different AWS accounts:

1. ODB network owner shares the ODB network via AWS RAM:

   ```bash
   aws ram create-resource-share \
     --name odb-network-share \
     --resource-arns arn:aws:odb:us-east-1:123456789012:odb-network/odbnet-abc12def \
     --principals 234567890123
   ```

2. Peer account accepts the RAM invitation.

3. Peer account creates the peering from step 3 above.

## Limits

- Up to **45 ODB peering connections** per ODB network
- One ODB peering per VPC-to-ODB-network pair

## Common Mistakes

| Mistake | Symptom | Fix |
|---|---|---|
| No route in app VPC route table | ORA-12170 timeout | Add route to ODB client subnet CIDR via `--odb-network-arn` |
| Used `aws ec2 create-vpc-peering-connection` | Peering creation fails / attaches nowhere | Use `aws odb create-odb-peering-connection` |
| Overlapping CIDRs | Peering create fails | Re-plan CIDR allocation |
| Forgot DNS setup | `TNS:could not resolve` | Follow **networking-dns-resolver.md** (loaded reference) |
| App subnet in wrong AZ | High latency, intermittent timeout | Move workloads to the AZ ID matching `availabilityZoneId` |
