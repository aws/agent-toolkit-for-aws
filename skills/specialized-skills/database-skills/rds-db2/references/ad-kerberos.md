# RDS for Db2 — Self-Managed Active Directory + Kerberos

Join an RDS for Db2 instance directly to a customer-managed Active Directory domain for Kerberos single sign-on — no Amazon Managed Microsoft AD and no directory trust in the path.

## Source

- Workspace: `04-db2-client/self-managed-ad-for-rds-db2/` (`README.md`, `README-UI.md`, `README-PowerShell.md`, `README-KMS-Secret.md`, `README-RDS-Db2.md`, `README-Networking.md`, `README-Db2-Client.md`, `README-Blog.md`)
- Bundled scripts: `scripts/Db2KerberosConnection.java`, `scripts/db2-kerberos-test.sh`
- Blog: <https://aws.amazon.com/blogs/database/> self-managed AD Kerberos for RDS for Db2 (`aws-samples/sample-rds-db2-tools`)
- AWS doc: <https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/db2-kerberos-setting-up.html>

## Architecture

RDS for Db2 joins your AD directly. A dedicated service account, scoped to one OU, is stored in Secrets Manager and encrypted with a customer-managed KMS key. During join, RDS reads the secret to register the instance. A domain-joined client gets a Kerberos ticket (TGT) from the AD KDC and connects with no password exchanged.

## 1. Delegate the nine AD permissions

Create a dedicated OU and service account, then grant the exact permissions on **descendant User objects** (RDS provisions principals as User objects):

- Create / Delete User and Computer objects in the OU
- Reset Password (extended right)
- Read + Write `msDS-SupportedEncryptionTypes`
- Read + Write `servicePrincipalName`

**Gotcha:** the ADUC Delegation of Control Wizard filters `servicePrincipalName` (and `msDS-SupportedEncryptionTypes`) out of the User-object attribute list. Grant those with **ADSI Edit** (`adsiedit.msc`), not ADUC — the most common failure, producing an ACL that looks correct but fails the join at runtime. Scope to User objects, not Computer objects. The PowerShell helper `Grant-ADDomainJoinPrivileges.ps1` applies all permissions in one idempotent pass; verify with `Show-OUDelegation.ps1`.

## 2. KMS key + Secrets Manager secret

Create a dedicated symmetric KMS key (not the AWS default) in the same account/Region. Store two keys in the secret:

- `SELF_MANAGED_ACTIVE_DIRECTORY_USERNAME` — sAMAccountName **only** (e.g. `rdsdb2svc`); a `DOMAIN\` prefix fails instance creation
- `SELF_MANAGED_ACTIVE_DIRECTORY_PASSWORD`

Attach a resource policy trusting `rds.amazonaws.com`, guarded against the confused-deputy problem with `aws:SourceArn` / `aws:SourceAccount`:

```json
{
  "Effect": "Allow",
  "Principal": { "Service": "rds.amazonaws.com" },
  "Action": "secretsmanager:GetSecretValue",
  "Resource": "*",
  "Condition": {
    "StringEquals": { "aws:SourceAccount": "<account-id>" },
    "ArnLike": { "aws:SourceArn": "arn:aws:rds:<region>:<account-id>:db:*" }
  }
}
```

## 3. Join the instance

```bash
aws rds modify-db-instance \
  --db-instance-identifier "<instance-id>" \
  --domain-fqdn "<your-domain-fqdn>" \
  --domain-ou "OU=RDSDb2,DC=company,DC=com" \
  --domain-auth-secret-arn "<your-secret-arn>" \
  --domain-dns-ips "<dc-ip-1>" "<dc-ip-2>" \
  --apply-immediately
```

Then reboot for the join to take effect. Supply at least two `--domain-dns-ips` for redundancy. New instances take the same four flags plus `--storage-encrypted --kms-key-id`. **Verify:**

```bash
aws rds describe-db-instances --db-instance-identifier "<instance-id>" \
  --query 'DBInstances[0].{Status:DBInstanceStatus,Domain:DomainMemberships}'
```

A successful join shows `DomainMemberships` with `Status: joined`.

## 4. Networking (port matrix)

Open between RDS and the domain controllers (and from the client):

| Protocol | Port(s) | Service |
|---|---|---|
| TCP+UDP | 53 | DNS |
| TCP+UDP | 88 | Kerberos |
| TCP+UDP | 389 / TCP 3268 | LDAP / Global Catalog |
| TCP+UDP | 464 | Kerberos password change |
| TCP+UDP | 49152–65535 | RPC dynamic ports |

Missing the RPC range is the top cause of intermittent failures after a working initial join. Keep clock skew **under 5 minutes** (shared NTP) and ensure VPC DNS resolves the AD domain. Topologies: same VPC (reference by SG ID), cross-account (VPC Peering / Transit Gateway + CIDR rules + Route 53 Resolver), or Azure-hosted DCs (Site-to-Site VPN / Direct Connect + ExpressRoute).

## 5. Domain-join the client + connect

On an AL2023 EC2 client in the same VPC, install `realmd`/`sssd`/`adcli`/`krb5-workstation`, join the realm, then install the Db2 Runtime Client (`db2-driver.sh`) and configure DSNs (`db2client-configure.sh` auto-detects the realm and writes both local-auth and Kerberos DSNs):

```bash
kinit your.username@COMPANY.COM   # obtain a TGT
klist                              # confirm ticket present
db2 "connect to RDSAKS"            # SSL + Kerberos DSN, no password
```

The RDS admin account (created with `--master-username admin`, preferably with `--manage-master-user-password`) is a **local** account — it cannot get a Kerberos ticket and is used only for local-auth DSNs. AD users need a ticket plus `GRANT CONNECT ON DATABASE TO USER domain\user`.

DSN matrix written by the configure script: `RDSAT` (TCP/local), `RDSAS` (SSL/local), `RDSAKS` (SSL/Kerberos), and per-database `<DB>T` / `<DB>S` / `<DB>SK`. Which are written depends on the `db2comm` parameter (`TCPIP`, `SSL`, or both).

## 6. JDBC Kerberos

The bundled `scripts/Db2KerberosConnection.java` (driven by `scripts/db2-kerberos-test.sh`) connects with the IBM JDBC driver (`db2jcc4.jar` v4.33+) using:

```java
props.setProperty("securityMechanism", "11");   // 11 = Kerberos
props.setProperty("sslConnection", "true");
props.setProperty("sslVersion", "TLSv1.2");
props.setProperty("sslCertLocation", "/path/to/<region>-bundle.pem");
```

`securityMechanism=11` selects Kerberos (no user/password). For SSL use the **region-specific** PEM via `sslCertLocation` — never `global-bundle.pem`, which the IBM driver does not support. Download it:

```bash
curl -sL https://truststore.pki.rds.amazonaws.com/<region>/<region>-bundle.pem \
  -o <region>-bundle.pem
```

## Must-surface facts

- Self-managed AD path uses `--domain-fqdn`, `--domain-ou`, `--domain-auth-secret-arn`, `--domain-dns-ips` — no Managed AD or trust required.
- Secret keys are `SELF_MANAGED_ACTIVE_DIRECTORY_USERNAME` (sAMAccountName only) and `_PASSWORD`; resource policy carries `aws:SourceArn` / `aws:SourceAccount`.
- Grant `servicePrincipalName` via ADSI Edit, not ADUC.
- Open RPC 49152–65535; keep clock skew under 5 minutes.
- Verify with `DomainMemberships: joined`; JDBC uses `securityMechanism=11` + region PEM via `sslCertLocation`.
