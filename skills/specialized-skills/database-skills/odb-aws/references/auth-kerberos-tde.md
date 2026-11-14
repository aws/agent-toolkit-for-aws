# Auth — Kerberos and AWS KMS for TDE

Two OCI-Exadata-specific auth / encryption features that depend on AWS integration.

## Kerberos on Exadata Database Service

Supported on **Exadata Database Service only** (not Autonomous DB). Uses AWS Managed Microsoft AD or self-managed AD reachable over the ODB peering.

### Prerequisites

- ExaDB-D (Kerberos is NOT supported on Autonomous DB).
- AWS Managed Microsoft AD or self-managed AD reachable from the ODB network.
- `krb5.conf` configured on client machines.
- python-oracledb **thick mode** (thin mode does NOT support Kerberos).

### Setup

1. Ensure the ODB network can reach the AD domain controllers:
   - ODB peering into a VPC with AD (or reachable via TGW).
   - DNS forwarding for the AD domain.

2. Register the Oracle SPN in AD:
   ```cmd
   setspn -A oracle/cluster-abc-scan.sub1.vcn1.oraclevcn.com <service-account>
   ```

3. Generate a keytab:
   ```bash
   ktutil
   addent -password -p oracle/cluster-abc-scan.sub1.vcn1.oraclevcn.com@EXAMPLE.COM -k 1 -e aes256-cts-hmac-sha1-96
   wkt /opt/oracle/oracle.keytab
   ```

4. Client `/etc/krb5.conf`:
   ```ini
   [libdefaults]
       default_realm = EXAMPLE.COM
       dns_lookup_realm = false
       dns_lookup_kdc = true

   [realms]
       EXAMPLE.COM = {
           kdc = dc1.example.com
           admin_server = dc1.example.com
       }

   [domain_realm]
       .example.com = EXAMPLE.COM
       example.com = EXAMPLE.COM
   ```

### Connect

Python (thick mode):

```python
import oracledb
oracledb.init_oracle_client(lib_dir="/opt/oracle/instantclient_21_13")

conn = oracledb.connect(
    externalauth=True,
    dsn="cluster-abc-scan.sub1.vcn1.oraclevcn.com:1521/orclpdb1.sub1.vcn1.oraclevcn.com",
)
```

Java:

```java
String url = "jdbc:oracle:thin:@//cluster-abc-scan.sub1.vcn1.oraclevcn.com:1521/orclpdb1";
Properties props = new Properties();
props.setProperty("oracle.net.authentication_services", "(KERBEROS5)");
props.setProperty("oracle.net.kerberos5_cc_name", "/tmp/krb5cc_1000");
Connection conn = DriverManager.getConnection(url, props);
```

### Rules

- Kerberos REQUIRES python-oracledb thick mode (Oracle Instant Client installed).
- Kerberos is NOT supported on Autonomous Database.
- AD must be reachable from the ODB network.
- For Lambda / Fargate, Kerberos is impractical; use password auth + Secrets Manager (**auth-wallet-tcps.md** (loaded reference)) or OCI IAM SSO token (**auth-oci-iam.md** (loaded reference)).

## AWS KMS as TDE Key Store

ODB@AWS supports AWS KMS as the encryption key store for TDE via an OIDC-federated IAM role.

### Prerequisites

- ODB network created with **STS + KMS** integration enabled.
- OIDC provider for OCI tenancy in AWS IAM (created via CloudFormation).
- IAM role federated with the OIDC provider; policy grants `kms:Encrypt`, `kms:Decrypt`, `kms:GenerateDataKey`, `kms:DescribeKey` on the target KMS key.
- Registration step in OCI that binds the KMS key ARN + IAM role ARN.

### Example CloudFormation snippet

```yaml
Resources:
  ODBOIDCProvider:
    Type: AWS::IAM::OIDCProvider
    Properties:
      Url: !Sub "https://identity.oraclecloud.com/${OciTenancyOcid}"
      ClientIdList: [!Ref OciClientId]
      ThumbprintList: [!Ref OciThumbprint]

  ODBKMSRole:
    Type: AWS::IAM::Role
    Properties:
      AssumeRolePolicyDocument:
        Version: "2012-10-17"
        Statement:
          - Effect: Allow
            Principal: { Federated: !Ref ODBOIDCProvider }
            Action: sts:AssumeRoleWithWebIdentity
            Condition:
              StringEquals:
                !Sub "identity.oraclecloud.com/${OciTenancyOcid}:aud": !Ref OciClientId
      Policies:
        - PolicyName: ODBKMSAccess
          PolicyDocument:
            Version: "2012-10-17"
            Statement:
              - Effect: Allow
                Action:
                  - kms:Encrypt
                  - kms:Decrypt
                  - kms:GenerateDataKey
                  - kms:DescribeKey
                Resource: !GetAtt KMSKey.Arn
```

### Create KMS key and enable rotation

```bash
aws kms create-key \
  --description "ODB TDE encryption key" \
  --key-usage ENCRYPT_DECRYPT \
  --key-spec SYMMETRIC_DEFAULT \
  --region us-east-1

aws kms enable-key-rotation --key-id <key-id> --region us-east-1
```

### Register in OCI

In the OCI console, bind the AWS KMS key ARN and the IAM role ARN to the database.

### Rules

- AWS KMS integration requires OIDC federation — a plain IAM role is not sufficient.
- The KMS key MUST be in the same region as the ODB network.
- Enable key rotation (annual) for compliance.
- Validate after setup: `SELECT * FROM V$ENCRYPTION_WALLET;`.
- MUST back up the KMS key policy — losing access to the key means losing access to encrypted data.
- MUST NOT disable the key or delete it without confirming all encrypted data has been re-keyed because TDE decryption will permanently fail.
