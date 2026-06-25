# RDS for Db2 — Bring Your Own Key (BYOK) Reference

> **Source:** `04-db2-client/bring-your-own-key/bring-your-own-kms-key-for-rds-for-db2.md`
> (blog DBBLOG-5188). Commands and option names are reproduced from that source; no secret
> values, credentials, or customer IDs are included — replace every `<placeholder>`.

---

## Why BYOK

RDS for Db2 encrypts at rest with AWS KMS. BYOK lets you import your own key material into a
customer-managed KMS key so you control the key, meet key-management compliance, keep a CloudTrail
audit trail, and reuse the same key material across Regions for disaster recovery. Always create
the instance encrypted (encryption at rest cannot be added in place — see migration below).

Prerequisites: AWS CLI, OpenSSL, `jq`, and a valid IBM Customer ID + Site ID for BYOL.

## Environment

```bash
export HOME_REGION=<region>
export DR_REGION=<dr-region>
export KEY_ALIAS=alias/byok-db2
export DB_INSTANCE_ID=<db-instance-id>
export SUBNET_GROUP=<subnet-group>
export SG_ID=<sg-id>
export IBM_CUSTOMER_ID=<IBM_CUSTOMER_ID>   # rds.ibm_customer_id
export IBM_SITE_ID=<IBM_SITE_ID>           # rds.ibm_site_id
```

## 1. Create a multi-region external-origin key

A multi-region key (MRK) keeps the same key ID/material when replicated to a DR Region.

```bash
aws kms create-key --region $HOME_REGION \
  --origin EXTERNAL --key-usage ENCRYPT_DECRYPT --key-spec SYMMETRIC_DEFAULT \
  --multi-region --description "BYOK for RDS Db2" \
  --query KeyMetadata.KeyId --output text | tee KEY_ID.txt
export KEY_ID=$(cat KEY_ID.txt)

aws kms create-alias --region $HOME_REGION \
  --alias-name $KEY_ALIAS --target-key-id $KEY_ID
```

## 2. Get import parameters

```bash
aws kms get-parameters-for-import --region $HOME_REGION --key-id $KEY_ID \
  --wrapping-algorithm RSAES_OAEP_SHA_256 --wrapping-key-spec RSA_2048 \
  --query '{PublicKey:PublicKey,ImportToken:ImportToken}' --output json > import-params.json

jq -r .PublicKey  import-params.json | base64 --decode > wrappingKey.der
jq -r .ImportToken import-params.json | base64 --decode > importToken.bin
openssl pkey -inform DER -pubin -in wrappingKey.der -out wrappingKey.pem
```

## 3. Wrap key material with OpenSSL and import

```bash
openssl rand -out keyMaterial.bin 32          # your own 256-bit key material

openssl pkeyutl -encrypt -inkey wrappingKey.pem -pubin \
  -in keyMaterial.bin -out encryptedKeyMaterial.bin \
  -pkeyopt rsa_padding_mode:oaep -pkeyopt rsa_oaep_md:sha256 -pkeyopt rsa_mgf1_md:sha256

aws kms import-key-material --region $HOME_REGION --key-id $KEY_ID \
  --encrypted-key-material fileb://encryptedKeyMaterial.bin \
  --import-token fileb://importToken.bin \
  --expiration-model KEY_MATERIAL_DOES_NOT_EXPIRE
```

> Import tokens expire after **24 hours**. If import fails, re-run `get-parameters-for-import`.

## 4. Replicate the key to DR

```bash
aws kms replicate-key --region $HOME_REGION --key-id $KEY_ID \
  --replica-region $DR_REGION \
  --query ReplicaKeyMetadata.Arn --output text | tee REPLICA_ARN.txt
export REPLICA_ARN=$(cat REPLICA_ARN.txt)

aws kms create-alias --region $DR_REGION \
  --alias-name $KEY_ALIAS --target-key-id $REPLICA_ARN
```

## 5. KMS permissions

The principal creating the instance needs, on the key:

- `kms:CreateGrant` — lets RDS create a grant to use the key
- `kms:DescribeKey` — lets RDS read key metadata

Use a least-privilege IAM policy (no `*FullAccess`); trust the account root in the key policy and
let RDS use the grant created at instance creation. Inspect grants with
`aws kms list-grants --key-id $KEY_ID --region $HOME_REGION`.

## 6. BYOL parameter group with IBM IDs

```bash
export PG_FAMILY=<db2-se-x.y|db2-ae-x.y>
export PG_NAME=db2-se-byol-params

aws rds create-db-parameter-group --region $HOME_REGION \
  --db-parameter-group-name $PG_NAME --db-parameter-group-family $PG_FAMILY \
  --description "BYOL: IBM IDs for RDS Db2"

aws rds modify-db-parameter-group --region $HOME_REGION \
  --db-parameter-group-name $PG_NAME --parameters \
    "ParameterName=rds.ibm_customer_id,ParameterValue=$IBM_CUSTOMER_ID,ApplyMethod=pending-reboot" \
    "ParameterName=rds.ibm_site_id,ParameterValue=$IBM_SITE_ID,ApplyMethod=pending-reboot"
```

## 7. Create the encrypted instance

Encryption at rest is set **at creation** with the customer-managed KMS key. Use
`--manage-master-user-password` (RDS stores and rotates the credential in Secrets Manager)
rather than an inline plaintext password.

```bash
aws rds create-db-instance --region $HOME_REGION \
  --db-instance-identifier $DB_INSTANCE_ID \
  --engine db2-se --engine-version <engine-version> \
  --db-instance-class db.r7i.xlarge --allocated-storage 100 --storage-type gp3 \
  --master-username db2inst1 --manage-master-user-password \
  --vpc-security-group-ids $SG_ID --db-subnet-group-name $SUBNET_GROUP \
  --storage-encrypted --kms-key-id $KEY_ALIAS \
  --license-model bring-your-own-license \
  --db-parameter-group-name $PG_NAME
```

`--storage-encrypted --kms-key-id` binds the instance to your KMS key. BYOL requires the parameter
group with IBM IDs.

## 8. Encrypt an existing (unencrypted) instance

Encryption cannot be toggled in place — re-encrypt through a snapshot:

```bash
# 1) snapshot the unencrypted DB
aws rds create-db-snapshot --region $HOME_REGION \
  --db-instance-identifier $DB_INSTANCE_ID \
  --db-snapshot-identifier ${DB_INSTANCE_ID}-plain-snap

# 2) copy the snapshot, encrypting with your key
aws rds copy-db-snapshot --region $HOME_REGION \
  --source-db-snapshot-identifier ${DB_INSTANCE_ID}-plain-snap \
  --target-db-snapshot-identifier ${DB_INSTANCE_ID}-enc-snap \
  --kms-key-id $KEY_ALIAS

# 3) restore a new encrypted DB
aws rds restore-db-instance-from-db-snapshot --region $HOME_REGION \
  --db-instance-identifier ${DB_INSTANCE_ID}-enc \
  --db-snapshot-identifier ${DB_INSTANCE_ID}-enc-snap \
  --db-subnet-group-name $SUBNET_GROUP --vpc-security-group-ids $SG_ID
```

## 9. Cross-region encrypted snapshot copy (DR)

Use the DR replica key as the target `--kms-key-id`:

```bash
aws rds copy-db-snapshot \
  --source-region $HOME_REGION --region $DR_REGION \
  --source-db-snapshot-identifier \
    arn:aws:rds:$HOME_REGION:<account-id>:snapshot:${DB_INSTANCE_ID}-enc-snap \
  --target-db-snapshot-identifier ${DB_INSTANCE_ID}-enc-snap-dr \
  --kms-key-id <alias|arn>
```

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `import-key-material` fails | Import token expired (24h). Re-run `get-parameters-for-import` and re-wrap. |
| Permission errors at create | Role lacks `kms:CreateGrant` / `kms:DescribeKey`, or key policy blocks the action. |
| Cross-region copy fails | Replica key missing in target Region, or wrong `--kms-key-id` alias/ARN. |

**Considerations:** multi-region keys bill per Region; enable CloudTrail on KMS operations; store
your original key material securely for recovery.
