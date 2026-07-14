# Inspecting Encrypted Traffic with TLS Inspection

## Overview

Domain expertise for decrypting, inspecting, and re-encrypting TLS traffic with AWS Network
Firewall so stateful rules can act on the decrypted payload. Covers creating a TLS inspection
configuration, associating AWS Certificate Manager (ACM) certificates, defining the scope of traffic
to decrypt, adding the configuration to a firewall policy, and the difference between inbound and
outbound inspection.

Inbound and outbound inspection take different certificate types and have different preconditions.
Inbound uses a server certificate per domain, which must be within the service's supported set
(consult the current AWS Network Firewall TLS inspection certificate requirements documentation).
Outbound uses a certificate authority (CA) certificate that the firewall uses to generate server
certificates on the fly, which means every client must already trust that CA.

Does not cover firewall deployment, domain filtering, or logging setup. Those are separate
references.

Execute commands using the AWS MCP server when connected (sandboxed execution, audit logging,
observability). Fall back to the AWS CLI otherwise. Pass `--region` matching the firewall's Region
on every command.

## Table of Contents

- Overview
- Workflow
- Inbound and outbound use different certificates
- Deploy the CA to client trust stores before outbound inspection
- Decrypted traffic is HTTP to the stateful engine
- Revocation checks can drop specific servers
- Scope inspection to the CIDRs that need it
- Troubleshooting
- Procedure
- Security Considerations
- Additional Resources

## Workflow

To inspect encrypted traffic end to end, follow the procedure. It confirms the right certificate
type exists in ACM, creates a TLS inspection configuration with that certificate and a scope that
selects which traffic to decrypt, adds the configuration to a firewall policy, and confirms the
decrypted traffic is inspected by rules written against the decrypted protocol.

## Inbound and outbound use different certificates

**Constraints:**

- You MUST state the certificate type before the customer requests or imports it: inbound inspection
  needs an ACM server certificate for each domain, outbound inspection needs an imported CA
  certificate
- You MUST verify the certificate is within Network Firewall's supported set for inbound inspection
  by consulting the current AWS Network Firewall TLS inspection certificate requirements
  documentation before proceeding; using a type outside that set results in client-side errors
- You SHOULD consult that same documentation for any chain-validation limitations before selecting a
  CA for inbound inspection, since an unsupported chain type causes asynchronous client-side
  failures; where a limitation applies, prefer a certificate whose chain the service can validate

## Deploy the CA to client trust stores before outbound inspection

**Constraints:**

- You MUST make deploying the CA to every client trust store a stated step before enabling outbound
  inspection; the firewall generates server certificates from that CA and clients reject the
  connection if they do not already trust it, with nothing on the firewall side reporting the
  missing trust
- You MUST verify the downstream server's certificate is within Network Firewall's supported set for
  outbound inspection before relying on it; a certificate outside that set can fail. Consult the
  current AWS Network Firewall TLS inspection certificate requirements documentation for the
  supported types

## Decrypted traffic is HTTP to the stateful engine

**Constraints:**

- You MUST explain that after the firewall terminates TLS, the decrypted traffic reaches the
  stateful engine as plain HTTP, so rules matching on port 443 or the `tls` keyword stop matching
- You MUST write the inspection rules against the decrypted protocol (for example `http`), not
  against the encrypted port; the original rules stay valid but silently never fire

## Revocation checks can drop specific servers

**Constraints:**

- You SHOULD point the customer at the TLS logs (`revocation_check` status and the SNI) when
  outbound connections to specific servers are dropped after enabling the optional certificate
  revocation check
- You MAY adjust the TLS inspection scope to pass one target's traffic around inspection, rather
  than switching the whole policy to a global pass on revocation failure

## Scope inspection to the CIDRs that need it

**Constraints:**

- You SHOULD scope the TLS inspection source and destination to the specific CIDR ranges requiring
  inspection rather than using `0.0.0.0/0`, to reduce the processing overhead and limit the blast
  radius of misconfigured decryption

## Troubleshooting

### Inbound clients get certificate errors
A certificate type outside the supported set was used for inbound inspection. Use an ACM server
certificate from a supported CA, and consult the current TLS inspection certificate requirements
documentation for supported types (Inbound and outbound use different certificates).

### Outbound clients reject the connection
The client does not trust the firewall's CA. Deploy the CA to every client trust store (Deploy the
CA to client trust stores before outbound inspection).

### Rules stop matching after enabling TLS inspection
The rules match port 443 or `tls`; decrypted traffic is HTTP. Rewrite them against `http` (Decrypted
traffic is HTTP to the stateful engine).

### Specific outbound servers are dropped
The revocation check blocked a revoked or unknown certificate. Confirm from TLS logs and adjust the
scope for that target if needed (Revocation checks can drop specific servers).

## Procedure

### Overview

This procedure confirms the right ACM certificate, creates a TLS inspection configuration with a
scope, adds it to a firewall policy, and confirms decrypted traffic is inspected.

### Parameters

- **tls_config_name** (required): Name for the TLS inspection configuration.
- **direction** (required): `inbound` or `outbound`.
- **certificate_arn** (required): ACM server certificate (inbound) or imported CA certificate (outbound).
- **scope** (required): Sources, destinations, ports, and protocols of traffic to decrypt.
- **kms_key_id** (required): A customer-managed AWS KMS key to encrypt the TLS inspection configuration at rest.
- **firewall_policy_arn** (required): The policy to add the configuration to.
- **firewall_name** (required): The firewall that uses this policy, for the console link in Step 5.
- **revocation_check** (optional): Whether to enable the outbound certificate revocation check.

**Constraints for parameter acquisition:**

- You MUST ask for all required parameters upfront in a single prompt
- You MUST confirm the certificate type matches the direction before continuing
- You MUST confirm, for outbound, that the CA is deployed to client trust stores

### Steps

#### 1. Verify dependencies

**Constraints:**

- You MUST confirm credentials with `aws sts get-caller-identity`, and you MUST use ephemeral, least-privilege credentials (a time-bound assumed-role session) scoped to the specific `network-firewall:` actions and resources this task needs, never long-lived access keys or broad administrative access
- You MUST confirm the ACM certificate exists and matches the direction: a server certificate for
  inbound, an imported CA certificate for outbound
- You MUST confirm, for outbound, that clients already trust the CA

#### 2. Create the TLS inspection configuration

**Constraints:**

- You MUST create the configuration with the certificate and a scope that selects the traffic to
  decrypt, and encrypt the configuration at rest with a customer-managed AWS KMS key via
  `--encryption-configuration`, since it holds certificate references and decryption-scope definitions:

  ```
  aws network-firewall create-tls-inspection-configuration \
    --tls-inspection-configuration-name {tls_config_name} \
    --tls-inspection-configuration '{"ServerCertificateConfigurations":[{"ServerCertificates":[{"ResourceArn":"{certificate_arn}"}],"Scopes":[{scope}]}]}' \
    --encryption-configuration Type=CUSTOMER_KMS,KeyId={kms_key_id} \
    --region {region}
  ```

- You MUST, when `revocation_check` is true, add a `CheckCertificateRevocationStatus` block to that
  `ServerCertificateConfigurations` entry so the firewall acts on revoked or unknown server
  certificates (without it the parameter has no effect):

  ```json
  "CheckCertificateRevocationStatus": {"RevokedStatusAction": "DROP", "UnknownStatusAction": "PASS"}
  ```

#### 3. Add the configuration to the firewall policy

**Constraints:**

- You MUST first retrieve the current policy with `describe-firewall-policy`, then include all
  existing fields (for example `StatefulRuleGroupReferences`, `StatefulDefaultActions`,
  `StatefulEngineOptions`, `StatelessRuleGroupReferences`) in the `--firewall-policy` JSON, adding
  only the `TLSInspectionConfigurationArn` field to it. `update-firewall-policy` replaces the entire
  policy object rather than merging, so omitting a field deletes it and can drop all stateful rules
  and cause an outage:

  ```
  aws network-firewall describe-firewall-policy \
    --firewall-policy-arn {firewall_policy_arn} --region {region}
  ```

- You MUST then set `TLSInspectionConfigurationArn` on that complete policy, carrying every existing
  field through unchanged:

  ```
  aws network-firewall update-firewall-policy \
    --firewall-policy-arn {firewall_policy_arn} \
    --update-token {update_token} \
    --firewall-policy '{"StatelessDefaultActions":["aws:forward_to_sfe"],"StatelessFragmentDefaultActions":["aws:forward_to_sfe"],"StatefulRuleGroupReferences":[<existing references>],"StatefulDefaultActions":[<existing defaults>],"StatefulEngineOptions":<existing options>,"TLSInspectionConfigurationArn":"{tls_inspection_configuration_arn}"}' \
    --region {region}
  ```

- You SHOULD plan the TLS inspection at policy setup, since changing the configuration on a policy
  later is constrained

#### 4. Write rules against the decrypted protocol

**Constraints:**

- You MUST write the stateful inspection rules against the decrypted protocol (`http`), not against
  port 443 or `tls`

#### 5. Confirm and surface the console link

**Constraints:**

- You MUST confirm decrypted traffic is being inspected, using TLS logs to confirm decryption and
  catch revocation drops
- You MUST present the firewall console link, filling `{region}` and `{firewall_name}`:

  ```
  https://{region}.console.aws.amazon.com/vpcconsole/home?region={region}#FirewallDetails:firewallName={firewall_name}
  ```

### Example

#### Example input

```json
{
  "tls_config_name": "egress-tls",
  "direction": "outbound",
  "certificate_arn": "arn:aws:acm:us-east-1:111122223333:certificate/ca-aaaa",
  "scope": {"Sources": [{"AddressDefinition": "10.0.0.0/16"}], "Destinations": [{"AddressDefinition": "10.0.0.0/8"}], "DestinationPorts": [{"FromPort": 443, "ToPort": 443}], "Protocols": [6]},
  "kms_key_id": "arn:aws:kms:us-east-1:111122223333:key/1234abcd-12ab-34cd-56ef-1234567890ab",
  "firewall_policy_arn": "arn:aws:network-firewall:us-east-1:111122223333:firewall-policy/egress-policy",
  "firewall_name": "egress-fw",
  "revocation_check": true
}
```

#### Example output

```
Created TLS inspection config egress-tls (outbound) with the imported CA certificate.
Added it to egress-policy. Inspection rules written against http, not port 443.
Confirmed clients trust the CA. Open the console and confirm the firewall:
https://us-east-1.console.aws.amazon.com/vpcconsole/home?region=us-east-1#FirewallDetails:firewallName=egress-fw
```

### Troubleshooting

#### Inbound certificate errors
Certificate type outside the supported set. Use an ACM server certificate from a supported CA, and
check the current TLS inspection certificate requirements documentation for supported types (Step 1).

#### Outbound clients reject the connection
CA not trusted by clients. Deploy the CA to client trust stores (Step 1).

#### Rules no longer match
Decrypted traffic is HTTP. Rewrite rules against `http` (Step 4).

## Security Considerations

TLS inspection decrypts traffic, so the decrypted payload and the CA private material are sensitive.

- You SHOULD scope the inspection source and destination to the specific CIDR ranges requiring
  inspection rather than `0.0.0.0/0`, to limit the blast radius of misconfigured decryption.
- You MUST protect the outbound CA certificate and its private key, since possession of the CA lets
  an attacker impersonate any server to the clients that trust it: store the private key in AWS
  Secrets Manager encrypted with a customer-managed AWS KMS key (or AWS CloudHSM), never unencrypted
  in AWS Systems Manager Parameter Store or version control.
- You MUST encrypt the TLS inspection configuration resource itself at rest with a customer-managed
  AWS KMS key (via `--encryption-configuration` on `create-tls-inspection-configuration`), since it
  holds the certificate references and decryption-scope definitions that govern what traffic is decrypted.
- You MUST encrypt every destination that receives firewall logs (alert, flow, or TLS), using a
  customer-managed AWS KMS key on Amazon CloudWatch Logs log groups (`aws logs associate-kms-key`)
  and either SSE-S3 or a customer-managed AWS KMS key on Amazon S3 buckets, because these logs expose sensitive network metadata (source and
  destination IPs, domain names, and SNI values).
- You SHOULD scope each log destination's resource policy (the S3 bucket policy, the CloudWatch
  Logs resource policy, and the Amazon Data Firehose delivery-stream policy) with `aws:SourceArn`
  (the firewall's ARN) and `aws:SourceAccount` condition keys, so only this firewall in the
  expected account can write to the destination and another account or service cannot
  (confused-deputy prevention).
- You MUST use ephemeral, least-privilege credentials (a time-bound assumed-role session) scoped to
  the specific `network-firewall:`, `acm:`, `secretsmanager:`, and `kms:` actions and resources this
  task needs, never long-lived access keys or broad administrative access.
- You SHOULD enable AWS CloudTrail on the account so firewall, policy, rule group, and
  logging-configuration API changes are recorded for audit and incident review.
- You SHOULD configure CloudWatch alarms to alert on firewall endpoint failures, TLS handshake or
  certificate-validation error spikes, and ACM certificate expiry, so issues are detected and
  escalated promptly. You MUST encrypt any SNS topic used for these alarm notifications with a
  customer-managed AWS KMS key and restrict alarm notification recipients to authorized operations and
  security personnel, since alarm messages can expose sensitive firewall metadata (endpoint status,
  traffic patterns, and capacity).

## Additional Resources

- [Using SSL/TLS certificates with TLS inspection configurations in AWS Network Firewall (AWS Network Firewall Developer Guide)](https://docs.aws.amazon.com/network-firewall/latest/developerguide/tls-inspection-certificate-requirements.html)
- [TLS inspection configuration settings in AWS Network Firewall (AWS Network Firewall Developer Guide)](https://docs.aws.amazon.com/network-firewall/latest/developerguide/tls-inspection-settings.html)
- [Creating a TLS inspection configuration in Network Firewall (AWS Network Firewall Developer Guide)](https://docs.aws.amazon.com/network-firewall/latest/developerguide/creating-tls-configuration.html)
- [Troubleshooting TLS inspection in AWS Network Firewall (AWS Network Firewall Developer Guide)](https://docs.aws.amazon.com/network-firewall/latest/developerguide/troubleshooting-tls-inspection.html)
- [TLS inspection configuration for encrypted egress traffic and AWS Network Firewall (AWS Security Blog)](https://aws.amazon.com/blogs/security/tls-inspection-configuration-for-encrypted-egress-traffic-and-aws-network-firewall/)
