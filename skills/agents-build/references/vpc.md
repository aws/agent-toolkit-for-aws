# vpc

Configure your AgentCore agent to connect to private AWS resources inside a VPC.

## When to use

- Your agent needs to connect to an RDS database
- Your agent needs to call internal APIs not exposed to the internet
- You want to keep your agent's network traffic private
- VPC connectivity is configured but connections are timing out

## Input

`$ARGUMENTS` is optional:

```
/vpc                        # interactive — asks what you're connecting to
/vpc rds                    # RDS database connectivity
/vpc debug                  # diagnose VPC connectivity issues
```

## How AgentCore VPC connectivity works

When you configure VPC mode, AgentCore creates **Elastic Network Interfaces (ENIs)** in your VPC subnets. These ENIs give your agent a private IP address in your VPC, enabling it to reach private resources.

**Key facts:**

- VPC connectivity directly affects **outbound traffic** — ENIs route your agent's outbound calls through your VPC. For **inbound traffic**, you can optionally add an AgentCore VPC endpoint to keep API calls private via PrivateLink (this is separate from the `networkMode` setting).
- AgentCore creates ENIs via the service-linked role `AWSServiceRoleForBedrockAgentCoreNetwork` (auto-created on first VPC deployment)
- Subnets must be in **supported Availability Zones** — not all AZs are supported. The supported AZ list changes as AgentCore expands to new regions.

---

## Step 0: Verify CLI version

Run `agentcore --version`. This skill requires v0.9.0 or later. If the version is older, tell the developer to run `agentcore update` before proceeding.

---

## Step 1: Verify your subnets are in supported AZs

AgentCore only supports specific Availability Zone IDs per region. The supported AZ list changes as AgentCore expands — **always check the current docs** for the latest table.

Check your subnet's AZ ID:

```bash
# Check the AZ ID of your subnet
aws ec2 describe-subnets \
  --subnet-ids subnet-12345678 \
  --query 'Subnets[0].{AZ:AvailabilityZone,AZId:AvailabilityZoneId,SubnetId:SubnetId}'
```

**To find the current supported AZ IDs:** See the AgentCore VPC configuration guide: https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-vpc.html — look for the "Supported Availability Zones" section. The table lists AZ IDs (e.g., `use1-az1`, `usw2-az2`) per region — use AZ IDs, not AZ names, because AZ name-to-ID mappings differ across AWS accounts.

If your subnet is in an unsupported AZ, the deployment will fail. Use subnets in supported AZs.

**Best practice:** Use at least two subnets in different supported AZs for high availability.

---

## Step 2: Configure security groups

Security groups control what your agent can connect to. Configure them based on what you're connecting to.

### Connecting to RDS PostgreSQL

**AgentCore agent security group** (outbound rule):

```
Type: Custom TCP
Port: 5432
Destination: RDS security group ID (not CIDR)
```

**RDS security group** (inbound rule):

```
Type: PostgreSQL
Port: 5432
Source: AgentCore agent security group ID
```

```bash
# Create a security group for the agent
aws ec2 create-security-group \
  --group-name agentcore-agent-sg \
  --description "AgentCore agent security group" \
  --vpc-id vpc-12345678

# Add outbound rule to reach RDS
aws ec2 authorize-security-group-egress \
  --group-id sg-agent123 \
  --protocol tcp \
  --port 5432 \
  --source-group sg-rds456

# Add inbound rule to RDS security group
aws ec2 authorize-security-group-ingress \
  --group-id sg-rds456 \
  --protocol tcp \
  --port 5432 \
  --source-group sg-agent123
```

### Connecting to internal APIs (HTTP/HTTPS)

**AgentCore agent security group** (outbound rules):

```
Type: HTTPS, Port: 443, Destination: API security group or CIDR
Type: HTTP, Port: 80, Destination: API security group or CIDR (if needed)
```

---

## Step 3: Configure the agent for VPC

### New project

```bash
agentcore create \
  --name MyAgent \
  --defaults \
  --network-mode VPC \
  --subnets subnet-abc123,subnet-def456 \
  --security-groups sg-agent123
```

### Existing project

```bash
agentcore add agent \
  --name MyAgent \
  --network-mode VPC \
  --subnets subnet-abc123,subnet-def456 \
  --security-groups sg-agent123
```

Or edit `agentcore/agentcore.json` directly — add the `networkMode` and `networkConfig` fields to the runtime's entry:

```json
{
  "runtimes": [
    {
      "name": "MyAgent",
      "networkMode": "VPC",
      "networkConfig": {
        "subnets": ["subnet-abc123", "subnet-def456"],
        "securityGroups": ["sg-agent123"]
      }
    }
  ]
}
```

The `$schema` URL at the top of `agentcore.json` (`https://schema.agentcore.aws.dev/v1/agentcore.json`) gives IDE autocomplete and validation for every field — including the subnet/security-group ID patterns.

### Deploy

```bash
agentcore deploy -y
```

---

## Internet access from VPC

> [!WARNING]
> Connecting AgentCore to a VPC does NOT provide internet access by default.
> Public subnets do NOT provide internet access for AgentCore ENIs.
> To reach the internet from VPC mode, you MUST use private subnets with a NAT gateway.

**Architecture for internet + VPC access:**

```
AgentCore agent (private subnet)
    ↓ outbound traffic
NAT Gateway (public subnet)
    ↓
Internet Gateway
    ↓
Internet
```

```bash
# Create NAT gateway in a public subnet
aws ec2 create-nat-gateway \
  --subnet-id subnet-public123 \
  --allocation-id eipalloc-12345678

# Update private subnet route table to use NAT gateway
aws ec2 create-route \
  --route-table-id rtb-private123 \
  --destination-cidr-block 0.0.0.0/0 \
  --nat-gateway-id nat-12345678
```

---

## Fully private VPC (no internet)

If your VPC has no internet access, you need VPC endpoints for AWS services. These endpoints are **required** without internet access and **strongly recommended** even with a NAT gateway to avoid NAT gateway data processing charges:

```bash
# ECR Docker endpoint (required for container image pulls)
aws ec2 create-vpc-endpoint \
  --vpc-id vpc-12345678 \
  --service-name com.amazonaws.REGION.ecr.dkr \
  --vpc-endpoint-type Interface \
  --subnet-ids subnet-abc123 \
  --security-group-ids sg-agent123

# ECR API endpoint (required for container image pulls)
aws ec2 create-vpc-endpoint \
  --vpc-id vpc-12345678 \
  --service-name com.amazonaws.REGION.ecr.api \
  --vpc-endpoint-type Interface \
  --subnet-ids subnet-abc123 \
  --security-group-ids sg-agent123

# S3 Gateway endpoint (required — ECR stores image layers in S3)
# This is a free Gateway endpoint. Without it, ECR image refreshes
# route through NAT and incur data processing charges.
aws ec2 create-vpc-endpoint \
  --vpc-id vpc-12345678 \
  --service-name com.amazonaws.REGION.s3 \
  --vpc-endpoint-type Gateway \
  --route-table-ids rtb-private123

# CloudWatch Logs (required for agent logging)
aws ec2 create-vpc-endpoint \
  --vpc-id vpc-12345678 \
  --service-name com.amazonaws.REGION.logs \
  --vpc-endpoint-type Interface \
  --subnet-ids subnet-abc123 \
  --security-group-ids sg-agent123
```

---

## Cold-start connectivity checklist

A common pattern: `UpdateAgentRuntime` returns READY, the network configuration looks right, but invocations return 502 or hang. Requests never reach your container. This almost always means a new VM can start but can't complete the work needed to be ready for traffic.

Cold-start VMs need outbound HTTPS (port 443) to these AWS service endpoints. In public or NAT-routed VPCs, a correctly configured NAT gateway covers all of them. In fully private VPCs, every one of these needs an interface VPC endpoint or gateway endpoint:

- `com.amazonaws.<region>.ecr.api` — pull image metadata
- `com.amazonaws.<region>.ecr.dkr` — pull container layers
- `com.amazonaws.<region>.s3` (Gateway endpoint) — ECR layers live in S3
- `com.amazonaws.<region>.logs` — emit CloudWatch logs
- `com.amazonaws.<region>.monitoring` — emit CloudWatch metrics
- `com.amazonaws.<region>.sts` — assume the execution role

Plus whichever endpoints your agent's tools and dependencies need (Bedrock, DynamoDB, Secrets Manager, etc.).

### Security group outbound rule

The agent's security group needs an outbound rule to reach 443 on each VPC endpoint's prefix list, or `0.0.0.0/0` if the endpoints are reachable directly:

```bash
aws ec2 authorize-security-group-egress \
  --group-id sg-agent123 \
  --protocol tcp \
  --port 443 \
  --cidr 0.0.0.0/0
```

If you scope egress more tightly (to specific endpoint prefix lists or CIDR blocks), double-check that every endpoint above is covered.

### NACLs — the gotcha

Network ACLs are **stateless**. A security group allowing outbound 443 implicitly allows the response traffic. A NACL does not.

If your subnet uses a restrictive NACL, you need both directions explicitly:

- **Outbound:** allow TCP 443 to the destination
- **Inbound:** allow **ephemeral ports 1024–65535** (TCP) from the destination — these are the return-traffic ports

Forgetting the inbound ephemeral-port rule produces the exact symptom of "connection works sometimes, hangs other times" because TCP handshakes succeed (SYN goes out, SYN-ACK comes back on low port ranges) but the actual data response on an ephemeral port gets dropped.

### Transit Gateway and custom egress

If your subnet routes outbound through a Transit Gateway to a central firewall, NAT, or network virtualization layer, the TGW attachment and downstream must have a working route to the internet (or to each VPC endpoint individually).

Symptoms of a missing TGW route:

- Invocations hang for the full client-side timeout (~300 seconds for default Lambda clients)
- No 502, no `ConnectionClosedError` — the request just doesn't come back
- `ping` from a test EC2 in the same subnet/SG works, but actual invocations don't
- Warm environments (already initialized, so already have all their egress done) succeed, new cold starts fail

The test-from-an-EC2 pattern is useful here: launch a t3.micro in the same subnet with the same security group, and try `curl https://s3.<region>.amazonaws.com`, `curl https://ecr.<region>.amazonaws.com`, etc. If any of those hang or fail, the agent will fail to cold-start too.

### Expect higher cold-start time in VPC mode

VPC mode adds ENI attachment and setup time to cold start on top of container image pull and application startup. First invocations in a freshly-configured VPC are noticeably slower than in public mode.

Mitigation is the same as for all cold-start latency: reuse sessions, keep the image lean, defer heavy initialization. See `agents-harden` Initialization time section.

---

## Troubleshooting

**Connection timeouts to RDS or internal APIs:**

1. Verify security group rules — outbound from agent SG, inbound on target SG
2. Check route tables — private subnet must route to NAT gateway (for internet) or have direct routes to targets
3. Verify DNS resolution is enabled in the VPC: `aws ec2 describe-vpc-attribute --vpc-id vpc-12345678 --attribute enableDnsSupport`

**"Unsupported Availability Zone" error during deploy:**
Your subnet is in an AZ that AgentCore doesn't support. Check the AZ ID (not the AZ name) and use a subnet in a supported AZ.

**Agent can't reach internet after VPC configuration:**
You're using a public subnet or missing a NAT gateway. AgentCore ENIs in public subnets don't get internet access. Use private subnets with a NAT gateway.

**"AccessDenied" when using VPC endpoints:**
The execution role is missing permissions for the service behind the VPC endpoint. Check the endpoint's resource policy and the execution role's IAM policy.

**Code Interpreter timeouts calling public endpoints:**
Code Interpreter also needs VPC configuration if your agent is in a VPC. Configure it with the same subnets and a NAT gateway for internet access.

**DNS resolution failures:**
Enable DNS resolution and DNS hostnames in your VPC:

```bash
aws ec2 modify-vpc-attribute --vpc-id vpc-12345678 --enable-dns-support
aws ec2 modify-vpc-attribute --vpc-id vpc-12345678 --enable-dns-hostnames
```

## Output

- Subnet AZ validation results
- Security group rules for the specific target (RDS, internal API, etc.)
- CLI commands to configure VPC mode
- NAT gateway setup if internet access is needed
- VPC endpoint list for fully private deployments

## Quality criteria

- Subnet AZ IDs are validated against supported AZs (not AZ names — names vary by account)
- Security group rules cover both directions (agent outbound + target inbound)
- NAT gateway is recommended for internet access (not public subnets — AgentCore ENIs don't get public IPs)
- VPC endpoint list is complete for fully private deployments
- The developer understands that `networkMode: VPC` primarily affects outbound traffic
