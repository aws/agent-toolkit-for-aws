# Networking

## VPC Egress (Network Connectors)

A Web Function runs on Lambda-managed infrastructure, not in your VPC. By default, a revision
reaches public destinations directly over IPv4 and cannot reach anything private to your VPC. To
reach private resources (Amazon RDS, ElastiCache, internal APIs, VPC endpoints, on-premises networks
over Direct Connect or VPN), reference an **egress network connector** from a revision.

The connector changes outbound traffic only. The endpoint stays a public HTTPS URL, so it is not
access control; for who can call the endpoint, see [iam-and-security.md](iam-and-security.md).

### How It Fits Together

- A connector is a Lambda resource managed with `aws lambda-core`. Web Function calls use
  `aws lambda-web`. Both are authorized with `lambda:` IAM actions.
- The reference lives on the **revision**, in `serviceConfig.egressNetworkConnectorArn`. On the CLI,
  only `create-web-function` (in `--revision-config`) and `create-web-function-revision` (in
  `--service-config`) accept it; in CloudFormation and CDK it is
  `ServiceConfig.EgressNetworkConnectorArn` on `AWS::Lambda::WebFunctionRevision` (see
  [infrastructure-as-code.md](infrastructure-as-code.md)). A revision is immutable, so
  adding, changing or removing a connector always means a new revision plus a traffic shift.
- The ARN must be **version-qualified** (`...:network-connector:nc-...:2`). Updating a connector
  publishes a new version; revisions keep the version they name.
- One connector per revision, in the same account and Region as the function.
- Serve a revision that references a connector from a `HomeRegion` endpoint. A connector is
  Regional, so the API rejects a `MultiRegion` or `PerRegion` endpoint that would serve a revision
  referencing one.
- A connector serves exactly one compute type, set at creation to `WebFunction`, and it cannot be
  changed later.
- `aws lambda-web deploy` has no connector option, so it cannot give a function VPC egress in the
  first place. Establish it with `create-web-function-revision`. Once a revision carries a
  connector, a later `deploy` builds the new revision from the previous one and carries the
  reference forward, so shipping a code change does not drop VPC egress. What it carries forward is
  the version-qualified ARN it found, so a `deploy` after a connector update keeps the old version
  (see Change or Remove a Connector). Declaring the connector in a CloudFormation or CDK template
  covers both: every revision the stack creates carries it, and an `update-stack` moves to the new
  version (see [infrastructure-as-code.md](infrastructure-as-code.md)).

### Egress Paths

| Revision has | Outbound traffic | Reaches |
|---|---|---|
| No connector (the default) | Leaves from a Lambda-managed address, IPv4 only | Public internet; nothing private |
| A VPC egress connector | Leaves through the connector's subnets and security groups | Your VPC; public destinations only through your NAT gateway (IPv4) or egress-only internet gateway (IPv6) |

A connector **replaces** the default path. In private subnets without a NAT route, public names
still resolve but connections time out, so every third-party API call fails as soon as traffic
shifts to the new revision. The source address is not fixed on either path: allow-list the
connector's security groups or subnet CIDRs, never a single IP.

### Set Up VPC Egress

**1. VPC prerequisites.** Subnets in one VPC, one per Availability Zone, in at least three
Availability Zones where the Region has them, so egress keeps working during a zone outage (a
single subnet is accepted but ties egress to one zone), with free IP addresses (the connector holds addresses in every subnet). For private DNS names (an
RDS endpoint, a Route 53 private hosted zone, an interface VPC endpoint), enable DNS support and DNS
hostnames on the VPC and associate any private hosted zone with it.

**2. Security groups, least privilege.** Give the connector its own security group. Allow its
egress only to the destination's ports, and allow the destination's ingress only from the
connector's security group:

```bash
aws ec2 authorize-security-group-ingress --group-id {destination-sg} \
  --ip-permissions 'IpProtocol=tcp,FromPort=5432,ToPort=5432,UserIdGroupPairs=[{GroupId={connector-sg}}]'
```

Private networking is not encryption. Connect to data stores over TLS: for example
`sslmode=verify-full` with the RDS certificate bundle for PostgreSQL, and in-transit encryption
enabled on ElastiCache with a TLS client. Enable encryption at rest on the destination too, with a
customer-managed KMS key where you want the key policy to govern access: storage encryption on
RDS and Aurora, and encryption at rest on ElastiCache.

**3. Operator role.** Lambda assumes this role to manage network interfaces in your subnets. It
is separate from the revision's execution role, which needs no VPC permissions. Trust
`lambda.amazonaws.com` (`sts:AssumeRole`) and allow `ec2:CreateNetworkInterface` and
`ec2:CreateTags`. Condition the trust policy on `aws:SourceAccount` set to your account, so the
role cannot be assumed on another account's behalf; add `aws:SourceArn` for the connector ARN once
the connector exists, which narrows it to that one connector. The role needs no delete permission:
Lambda deletes the connector's network
interfaces through the service-linked role `AWSServiceRoleForLambda`
([`AWSLambdaServiceRolePolicy`](https://docs.aws.amazon.com/lambda/latest/dg/security-iam-awsmanpol.html#lambda-security-iam-awsmanpol-AWSLambdaServiceRolePolicy)),
which Lambda sets up in your account.

**4. Create the connector and wait for `ACTIVE`** (a few minutes; up to about 10):

```bash
aws lambda-core create-network-connector \
  --name {connector-name} \
  --configuration '{"VpcEgressConfiguration":{
    "SubnetIds":["{subnet-a}","{subnet-b}"],
    "SecurityGroupIds":["{connector-sg}"],
    "NetworkProtocol":"IPv4",
    "AssociatedComputeResourceTypes":["WebFunction"]}}' \
  --operator-role arn:aws:iam::{account}:role/{operator-role} \
  --region {region}

aws lambda-core get-network-connector --identifier {connector-name} --region {region} \
  --query '[State,StateReason,LatestVersionArn]'
```

Repeat the `get-network-connector` call until `State` is `ACTIVE`; a revision that names a connector
that is not `ACTIVE` is rejected. `LatestVersionArn` is the version-qualified ARN a revision needs.

**5. Create a revision that references it.** Copy `buildConfig` and the rest of `serviceConfig`
from the revision that is serving now (`get-web-function-revision`), so only the connector
changes; a `serviceConfig` you leave out is not inherited:

```bash
aws lambda-web create-web-function-revision \
  --function-name {name} \
  --build-config '{"codeConfig":{"s3Object":{"bucket":"{bucket}","key":"{key}"}},"runtimeConfig":{"runtime":"{runtime}"}}' \
  --service-config '{"executionRoleArn":"arn:aws:iam::{account}:role/{execution-role}",
    "egressNetworkConnectorArn":"arn:aws:lambda:{region}:{account}:network-connector:{connector-id}:{version}"}' \
  --region {region}
```

For a new function, put the same `serviceConfig` inside `--revision-config` on `create-web-function`.

**6. Read the reference back.** A revision without the field still reaches `Active` and serves
traffic on the public path, so a missing reference looks exactly like a broken VPC route:

```bash
aws lambda-web get-web-function-revision --function-name {name} --revision-id {revision-id} \
  --region {region} --query '{State:state,Connector:serviceConfig.egressNetworkConnectorArn}'
```

`Connector: null` means the revision has no VPC egress.

**7. Shift traffic deliberately.** There is no health gate on `LatestRevision`, so for a revision
that changes the egress path, set the endpoint to `Disabled` and move `revisionWeights` yourself,
keeping the previous revision as the rollback target (see [deployment.md](deployment.md)). During a
split, each request takes the egress path of the revision that serves it.

**8. Verify from application code.** There is no shell access to an execution environment. Deploy
a route that resolves and connects to a private destination and to a public control, and logs the
DNS result and the connection result separately. Confirm with VPC flow logs on the connector's
subnets: no records at all means traffic never entered the VPC (check the revision's reference
first); `REJECT` records mean a security group or network ACL blocked it.

### Change or Remove a Connector

- **Change:** `aws lambda-core update-network-connector --identifier {connector-id} --configuration '...'`
  with the unqualified identifier. Poll until `LastUpdateStatus` is `Successful`, read the new
  `LatestVersionArn`, create a revision that names it, and shift traffic. Existing revisions keep
  their old version until you do.
- **Remove:** create a revision whose `serviceConfig` omits `egressNetworkConnectorArn`, then shift
  traffic. Omitting the field is the only way to express "no VPC egress".
- **Delete a connector** only after no endpoint routes traffic to a revision that references it,
  and delete those revisions first. Deletion is not blocked, and the revision keeps reporting
  `Active`: environments already running lose all outbound network access (DNS lookups and
  connections fail, so requests that call out can time out with HTTP 504), and new environments
  fail requests with HTTP 502 `Lambda-Web-Error-Type: Platform.InvalidNetworkConfiguration`.
  Recover by shifting weights back to a revision with a live connector or none.

### IPv6

`NetworkProtocol: DualStack` enables IPv6 egress; it requires an IPv6 CIDR on every connector
subnet and IPv6 rules in the security groups. Without a connector, or with an `IPv4` connector,
egress is IPv4 only: names can still return AAAA records, but IPv6 connections fail immediately, so
use clients that fall back to IPv4. Public IPv6 destinations through a `DualStack` connector need
a `::/0` route to an egress-only internet gateway.

### IAM for the Deploying Identity

In addition to the Web Function actions in [iam-and-security.md](iam-and-security.md):

- `lambda:PassNetworkConnector` whenever a create request names a connector. Scope it to the
  connectors the deployer may use. Lambda checks the version-qualified ARN, so end the resource
  with `:*` (every version) or `:{version}`; the unqualified connector ARN does not match:

  ```json
  {
    "Effect": "Allow",
    "Action": "lambda:PassNetworkConnector",
    "Resource": "arn:aws:lambda:{region}:{account}:network-connector:{connector-id}:*"
  }
  ```

- `lambda:GetNetworkConnector` to read the version ARN.
- Restrict `lambda:CreateNetworkConnector` and `lambda:UpdateNetworkConnector` to identities you
  trust with your VPC configuration; that is where the network path is governed.

### Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `InvalidParameterValueException` ... "Subnets and Security Groups must belong to the same VPC" | Security group from another VPC | Use a security group in the subnets' VPC |
| `InvalidParameterValueException` ... "SecurityGroupIds cannot be null or empty" | No security group given | Pass at least one security group |
| `InvalidParameterValueException` ... "invalid ConnectorOperatorRole permissions" | Operator role lacks the EC2 permissions in step 3 | Grant them on the operator role |
| `ValidationException` ... "A version qualifier is required" | Unqualified connector ARN | Use `LatestVersionArn` from `get-network-connector` |
| `ValidationException` ... "ARNs must start with 'arn:'" | Connector name or ID passed | Pass the version-qualified ARN |
| `ValidationException` ... "is not active" | Connector still `PENDING` | Wait for `ACTIVE`, then create the revision |
| `ValidationException` ... "not configured with a valid compute type" | Connector created for another compute type | Create a connector with `AssociatedComputeResourceTypes: ["WebFunction"]` |
| `ResourceNotFoundException` ... "does not exist" | Wrong version number, or deleted connector | Re-read `LatestVersionArn` |
| `AccessDeniedException` ... "Cross-account" | Connector in another account | Create the connector in the function's account |
| `InvalidParameterValueException` ... "not compatible with the provided network protocol" | `DualStack` on subnets without IPv6 CIDRs | Add IPv6 CIDRs to every subnet, or use `IPv4` |
| Revision is `Active` but private resources are unreachable | Reference missing from the serving revision, or the endpoint serves another revision | Read the revision back, then `revisionWeights` on the endpoint |
| Endpoint creation or update rejected for a revision that carries a connector | The endpoint is `MultiRegion` or `PerRegion`, and a connector is Regional | Serve connector revisions from a `HomeRegion` endpoint |
| Public API calls time out after moving to the connector | No NAT route in the connector's subnets | Add a `0.0.0.0/0` route to a NAT gateway, or keep that traffic on a revision without a connector |
| Private name returns `ENOTFOUND` | Revision has no connector, VPC DNS attributes off, or private zone not associated | Check in that order |
| VPC access works for some requests only | Endpoint split across a VPC and a non-VPC revision | Finish the shift to one revision |
| Connector update had no effect | Revisions name the old version, including one a `deploy` carried forward | Create a revision with the new `LatestVersionArn` |
| HTTP 502 `Platform.InvalidNetworkConfiguration`, or outbound calls failing with DNS errors and 504s | Serving revision references a deleted connector | Shift traffic to a working revision |
