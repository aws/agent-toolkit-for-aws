# RDS for Db2 — Connectivity Reference

Installing the IBM Db2 client and connecting to RDS for Db2 from CloudShell, EC2, or laptop. The `db2-driver.sh` / `db2client-configure.sh` scripts automate install and DSN setup for online and airgap (private-subnet) deployments.

Source blog: <https://aws.amazon.com/blogs/database/connect-to-amazon-rds-for-db2-using-aws-cloudshell/>

## VPC requirements

- RDS for Db2 lives in a VPC (not publicly accessible by default).
- Security group inbound: TCP **50000** (plain), **50443** (SSL, controlled by `ssl_svcename`).
- CloudShell MUST use a **VPC environment** (Actions → Create VPC Environment) in the same subnet/AZ as the RDS instance.
- EC2 clients: same VPC or peered VPC, with routing and SG rules.
- Private subnet: use airgap flow + VPC endpoints for S3, SSM, Secrets Manager.

## Install — online mode

Works from EC2 or CloudShell with internet.

**Step 1 — Download the installer scripts:**

```bash
curl -sL https://bit.ly/getdb2driver | bash
```

Writes `db2-driver.sh` (RT client installer) and `db2client-airgap.sh` (airgap bundler) to the current directory.

**Step 2 — Install the RT client** (run as root or ec2-user):

```bash
REGION=us-east-1 ./db2-driver.sh                     # Db2 11.5 (default)
DB2_VER=12.1 REGION=us-east-1 ./db2-driver.sh        # Db2 12.1
```

`DB2_VER` defaults to `11.5`. On completion the script prints the next command.

**Step 3 — Configure DSN entries** (as `db2inst1`):

```bash
sudo su - db2inst1
REGION=us-east-1 source db2client-configure.sh
# Or target a specific instance:
DB_INSTANCE_ID=my-db2-instance REGION=us-east-1 source db2client-configure.sh
```

**Step 4 — Activate helper functions:**

```bash
source ~/.bashrc
db2_help
```

`source ~/functions.sh` is added to `~/.bashrc` automatically during configure.

## Install — airgap mode

Private subnet with no internet. Artifacts staged in S3.

**Step 1 — On internet-connected machine, download:**

```bash
curl -sL https://bit.ly/getdb2driver | bash
./db2client-airgap.sh --mode download --region <region>
# Or for Db2 12.1:
DB2_VER=12.1 ./db2client-airgap.sh --mode download --region <region>
```

Produces `./db2client-artifacts/{scripts,drivers,ssl}/`.

**Step 2 — On AWS-configured machine, upload to S3:**

```bash
./db2client-airgap.sh --mode upload --region <region>
```

Creates `db2client-artifacts-<account-id>-<region>`, uploads all artifacts, verifies every file, prints target-machine commands.

**Step 3 — On target (private subnet, AWS configured):**

```bash
aws s3 cp s3://db2client-artifacts-<account>-<region>/db2-driver.sh . && chmod +x db2-driver.sh
export BUCKET=db2client-artifacts-<account>-<region> REGION=<region>
./db2-driver.sh                      # Db2 11.5
# DB2_VER=12.1 ./db2-driver.sh       # Db2 12.1
```

**Step 4 — Configure DSNs** (as `db2inst1`):

```bash
sudo su - db2inst1
BUCKET=db2client-artifacts-<account>-<region> REGION=<region> source db2client-configure.sh
source ~/.bashrc
```

Reach EC2 via SSM: `aws ssm start-session --target <ec2-instance-id> --region <region>`.

## What `db2client-configure.sh` creates

DSN entries in `db2dsdriver.cfg`:

| DSN | Purpose |
|---|---|
| `RDSAT` | TCP to RDSADMIN system database (local auth) |
| `RDSAS` | SSL to RDSADMIN system database (local auth) |
| `RDSAKS` | SSL + Kerberos to RDSADMIN (domain-joined hosts only) |
| `<DB>T` | TCP to each user database (local auth) |
| `<DB>S` | SSL to each user database (local auth) |
| `<DB>SK` | SSL + Kerberos to each user database (domain-joined hosts only) |

Files written:

| File | Purpose | Perms |
|---|---|---|
| `~/sqllib/cfg/db2dsdriver.cfg` | DSN configuration | — |
| `~/.db2env` | Active instance credentials | `chmod 600` |
| `~/.db2instances` | Instance registry (no passwords) | `chmod 600` |
| `~/CONN_HELP_README.txt` | Ready-to-run connect commands | — |
| `~/<region>-bundle.pem` | RDS SSL certificate | — |

## Connecting

```bash
db2 terminate
cat ~/CONN_HELP_README.txt
db2 "connect to RDSAT user admin using '$MASTER_USER_PASSWORD'"
db2 "connect to RDSAS user admin using '$MASTER_USER_PASSWORD'"
db2 connect reset && db2 terminate
```

Single quotes around `$MASTER_USER_PASSWORD` protect special characters (`!`, `>`, `<`, `$`).

## Security considerations

- **Passwords in shell history.** `db2 connect ... using '<password>'` writes the password into shell
  history and the process list. Prefer `db2_connect` / `db2_use`, which read the password from `~/.db2env`
  (env var, not a literal argument). If you must type a literal password, clear it from history afterward
  (`history -d <n>` or unset `HISTFILE` for the session).
- **Prefer Secrets Manager.** Provision with `--manage-master-user-password` so RDS stores and rotates the
  master password in Secrets Manager; `db2_use` fetches the current value automatically after each rotation.
- **`~/.need_password` is dev/test only.** A plaintext password file is **never acceptable for production**.
  When used for local dev/test it must be `chmod 600` and must never be committed to source control or shared.
- **Use SSL DSNs (`50443`).** Prefer the `*S` / `*SK` (SSL) DSNs over plain TCP (`50000`) so credentials and
  data are encrypted in transit. See `connectivity-tls.md` for certificate setup.
- **Never log credentials.** Do not log full connection strings, DSN parameters, or password values in
  application or diagnostic logs. Use structured logging and mask password fields before writing to
  CloudWatch Logs or any log sink.

## Helper functions (`source ~/functions.sh`)

| Function | Purpose |
|---|---|
| `db2_help` | Print function summary |
| `db2_use [instance-id]` | Switch active instance — reads `~/.db2instances`, fetches fresh password from Secrets Manager, rewrites `~/.db2env`. No arg shows a menu. Password priority: Secrets Manager → `~/.need_password` → interactive prompt. |
| `db2_connect [DSN]` | Connect with creds in `~/.db2env`. DSN fallback: argument → `DB_DSN` (TCP) → `DB_SSL_DSN` (SSL) → `RDSAT`. |
| `db2_disconnect` | Reset connection + terminate agent |
| `db2_test_connection [DSN]` | Diagnose step by step: DSN exists, TCP reaches host:port, attempts `db2 connect` and decodes error |
| `db2_list_dsns` | List DSNs in `db2dsdriver.cfg` |
| `db2_show_env` | Print active instance, DSN, user, password presence (value never printed) |
| `db2_load_env` / `db2_save_env` | Load/save `~/.db2env` from/to the current shell |
| `get_task_status` | All RDS background tasks via `rdsadmin.get_task_status()` |
| `get_task_elapsed` | Elapsed seconds per task |
| `get_task_output` | Most recent task: input params + output |
| `monitor_db_instance_creation` | Poll RDS instance status every 30s until `available` |

`db2_test_connection` decodes these:

| Error | Meaning |
|---|---|
| `SQL30082N` | Wrong username or password |
| `SQL08001N` | Database not found |
| `SQL01013N` | Network / TCP error |
| GSKit / SSL | Certificate problem |

For SSL/TLS, GSKit, and certificate setup, see `connectivity-tls.md`.

## Manual password file (`~/.need_password`)

> **Warning — dev/test only.** A plaintext password file is **NEVER acceptable for production**.
> For any production or shared instance use `--manage-master-user-password` so RDS stores and rotates
> the master password in Secrets Manager; `db2_use` then fetches it automatically. The `~/.need_password`
> fallback exists solely for local dev/test instances that are not integrated with Secrets Manager, and
> must be `chmod 600` and never committed to source control or shared.

If not using Secrets Manager:

```bash
vi ~/.need_password && chmod 600 ~/.need_password
# Format — one line per instance:
# end-to-end-trust  MyP@ssw0rd!
# trp-test-by-ibm   An0therP@ss#
```

## Troubleshooting

| Problem | Fix |
|---|---|
| "No instance registry found" | Re-run `db2client-configure.sh` — writes `~/.db2instances` |
| `SQL30082N` after rotation | Run `db2_use <instance>` — re-fetches current password from Secrets Manager |
| `SQL1531N` | `db2 terminate` clears cache; re-run `db2client-configure.sh` if still failing |
| TCP timeout | SG inbound rule for 50000 (TCP) or 50443 (SSL) missing |
| `db2icrt` failed | Re-run `db2-driver.sh` as root (uses `env -i` to avoid symbol conflicts) |
| Wrong Db2 version | `DB2_VER=12.1 REGION=us-east-1 ./db2-driver.sh` — valid: `11.5`, `12.1` |

Full diagnostics: `db2_test_connection` / `db2_test_connection RDSAS`.

Find Db2 version:

```bash
aws rds describe-db-instances --db-instance-identifier <id> \
  --query 'DBInstances[0].EngineVersion' --output text
```

```sql
SELECT SERVICE_LEVEL FROM TABLE(SYSPROC.ENV_GET_INST_INFO()) AS T
```

For Python/Java drivers, Kerberos/AD, MacBook laptop, and multi-instance workflow, see `connection-drivers.md`.
