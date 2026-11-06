# Networking — Route 53 Resolver DNS Forwarding

After ODB peering, SCAN hostnames like `cluster-abc-scan.sub1.vcn1.oraclevcn.com` live in OCI's private DNS zone. AmazonProvidedDNS cannot resolve them — every client fails with `TNS:could not resolve` or ORA-12154 until a Route 53 Resolver outbound endpoint + forwarding rule is created. This is the #1 missed step.

## Prerequisites

- ODB peering in `AVAILABLE` state
- Route in app VPC route table to ODB client subnet CIDR
- ODB network's DNS listener IPs from `aws odb get-odb-network`

## Step-by-Step

### 1. Get DNS listener IPs

```bash
aws odb get-odb-network \
  --odb-network-id odbnet-abc12def \
  --region us-east-1 \
  --query 'dnsListenerIps'
```

These are dedicated DNS listener IPs. They MUST NOT be confused with the SCAN IPs — SCAN addresses are not DNS servers.

### 2. Create a security group for the outbound endpoint

```bash
aws ec2 create-security-group \
  --group-name odb-resolver-sg \
  --description "Route 53 Resolver outbound to ODB DNS" \
  --vpc-id vpc-0a1b2c3d4e5f6g7h \
  --region us-east-1

aws ec2 authorize-security-group-egress \
  --group-id sg-0123456789abcdef0 \
  --protocol udp --port 53 --cidr 10.20.0.0/24 \
  --region us-east-1

aws ec2 authorize-security-group-egress \
  --group-id sg-0123456789abcdef0 \
  --protocol tcp --port 53 --cidr 10.20.0.0/24 \
  --region us-east-1
```

### 3. Create the outbound endpoint

```bash
aws route53resolver create-resolver-endpoint \
  --name odb-outbound \
  --direction OUTBOUND \
  --security-group-ids sg-0123456789abcdef0 \
  --ip-addresses SubnetId=subnet-aaa SubnetId=subnet-bbb \
  --region us-east-1
```

Use 2+ subnets in different AZs for HA.

### 4. Create the forwarding rule

```bash
aws route53resolver create-resolver-rule \
  --name odb-forward-oraclevcn \
  --rule-type FORWARD \
  --domain-name oraclevcn.com \
  --resolver-endpoint-id rslvr-out-abc123 \
  --target-ips Ip=10.20.0.10,Port=53 Ip=10.20.0.11,Port=53 \
  --region us-east-1
```

If the ODB network uses a custom domain, substitute that domain name. You MUST NOT point the rule at SCAN IPs because SCAN is not a DNS server.

### 5. Associate the rule with the app VPC

```bash
aws route53resolver associate-resolver-rule \
  --resolver-rule-id rslvr-rr-abc123 \
  --vpc-id vpc-0a1b2c3d4e5f6g7h \
  --region us-east-1
```

### 6. Verify

```bash
# From an EC2 in the app VPC:
dig cluster-abc-scan.sub1.vcn1.oraclevcn.com +short

# Or use the script:
python3 scripts/resolve_scan.py cluster-abc-scan.sub1.vcn1.oraclevcn.com
```

Expected: 3 SCAN IPs for a 3-node RAC cluster; 1 IP for Autonomous DB.

## Multi-VPC — Share the Rule via RAM

Do NOT create duplicate outbound endpoints per VPC because each endpoint carries a standing cost. Share the rule instead.

```bash
aws ram create-resource-share \
  --name odb-resolver-rule-share \
  --resource-arns arn:aws:route53resolver:us-east-1:123456789012:resolver-rule/rslvr-rr-abc123 \
  --principals 234567890123

aws route53resolver associate-resolver-rule \
  --resolver-rule-id rslvr-rr-abc123 \
  --vpc-id vpc-other-vpc-id
```

## Common Mistakes

| Mistake | Symptom | Fix |
|---|---|---|
| Rule points at SCAN IPs | NXDOMAIN | Use DNS listener IPs from ODB network details |
| Rule not associated with VPC | DNS fails in that VPC | `associate-resolver-rule` |
| SG blocks DNS | DNS fails | Allow UDP/TCP 53 outbound to ODB client CIDR |
| No route to ODB CIDR | DNS times out | Add route before DNS setup |
| Used `oracle.com` instead of `oraclevcn.com` | NXDOMAIN | Use `oraclevcn.com` or the configured custom domain |
| One endpoint per VPC | Works but wasteful | Share rule via RAM |
