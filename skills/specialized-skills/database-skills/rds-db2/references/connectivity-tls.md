# RDS for Db2 — TLS/SSL Connectivity Reference

Configuring and troubleshooting encrypted (SSL/TLS) connections to RDS for Db2: the `<region>-bundle.pem` truststore certificate, IBM GSKit, and the `RDSAS` DSN. The `db2client-configure.sh` script wires this up automatically; this reference covers the detail and manual recovery. For the base client install, DSN/CLP/Python usage, and the airgap flow, see `connectivity.md`.

Source blog: <https://aws.amazon.com/blogs/database/connect-to-amazon-rds-for-db2-using-aws-cloudshell/>

## Prerequisites

- SSL enabled on the parameter group (`ssl_svcename` set) — SSL listens on port **50443**.
- Security group inbound rule allowing TCP **50443** from the client.
- Region certificate present at `~/<region>-bundle.pem` (downloaded from the RDS truststore).

## Automatic SSL setup

`db2client-configure.sh` handles SSL with no extra flags:

- Downloads `<region>-bundle.pem` from the RDS truststore.
- Reorders the bundle so the RSA2048 certificate is **first** — required by the Db2 CLP.
- Registers the `RDSAS` DSN with `SSLServerCertificate` and `SecurityTransportMode=SSL`.

It writes one SSL DSN per database: `RDSAS` for the RDSADMIN system database and `<DB>S` for each user database. The certificate lands at `~/<region>-bundle.pem`.

Verify the SSL path end to end:

```bash
db2_test_connection RDSAS
```

## Connect over SSL

```bash
# Helper (preferred — pulls credentials from ~/.db2env / Secrets Manager)
db2_connect RDSAS
# Direct CLP
db2 "connect to RDSAS user admin using '<password>'"
```

SSL connections use port **50443**; plaintext TCP uses 50000. Single quotes around the password protect special characters (`!`, `>`, `<`, `$`).

## Download / re-download the certificate

```bash
# Online — from the RDS truststore
curl -sL https://truststore.pki.rds.amazonaws.com/us-east-1/us-east-1-bundle.pem -o ~/us-east-1-bundle.pem
# Airgap — from the staged S3 bucket
aws s3 cp s3://<bucket>/ssl/us-east-1-bundle.pem ~/us-east-1-bundle.pem
```

After re-downloading, re-run `db2client-configure.sh` to re-register the SSL DSN against the refreshed (RSA-first) certificate.

## Manual SSL catalog (without the helper)

```bash
db2cli writecfg add -dsn RDSAS -database RDSADMIN -host <endpoint> -port 50443 \
  -parameter "SSLServerCertificate=~/<region>-bundle.pem;SecurityTransportMode=SSL;TLSVersion=TLSV12"
```

`TLSVersion=TLSV12` enforces TLS 1.2. Point `SSLServerCertificate` at the reordered region PEM at `~/<region>-bundle.pem`.

## Troubleshooting (GSKit / SSL)

| Problem | Fix |
|---|---|
| GSKit / SSL error on connect | Re-download the cert, re-run `db2client-configure.sh` |
| `db2_test_connection RDSAS` reports a certificate problem | Cert missing, wrong region, or RSA cert not first — re-download and re-run configure |
| SSL / TLS handshake failure | Confirm `ssl_svcename` is set on the parameter group and SG inbound 50443 is open |
| Wrong PEM path | `SSLServerCertificate` must point to `~/<region>-bundle.pem` |
| Plaintext works, SSL fails | Use port **50443** (not 50000) and the `RDSAS` DSN |

Full SSL diagnostics: `db2_test_connection RDSAS`.
