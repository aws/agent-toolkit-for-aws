# Connecting to an Express Cluster (IAM authentication)

Express clusters use IAM-only authentication via the Internet Access Gateway. There is no master password. When the user asks how to connect or run SQL, walk them through the IAM auth token flow — do NOT offer to run SQL yourself, do NOT suggest enabling the Data API as a workaround, and do NOT try to set a master password.

**Data API cannot be enabled at create time on express clusters.** The create-time `--enable-http-endpoint` flag is incompatible with `--with-express-configuration` (express forces IAM-only authentication at creation). However, Data API CAN be enabled AFTER creation via `ModifyDBCluster` (`aws rds modify-db-cluster --enable-http-endpoint`). Note it does not support master username/password authentication; you must create separate database user credentials to use Data API. The recommended/primary connection method for express is a direct connection with a short-lived IAM auth token.

1. **Wait for the cluster to be available.** The `Endpoint` field is populated only when status is `available`:

   ```bash
   aws rds describe-db-clusters --db-cluster-identifier <cluster-id> --region <region> \
     --query "DBClusters[0].{Status:Status,Endpoint:Endpoint}"
   ```

   Poll until `Status` is `"available"` and `Endpoint` is non-null.

2. **Connect with an IAM auth token (recommended/primary method).** The master user is `postgres` (configured for IAM auth automatically):

   ```bash
   RDSHOST="<endpoint from describe-db-clusters>"
   TOKEN=$(aws rds generate-db-auth-token --hostname $RDSHOST --port 5432 --region <region> --username postgres)
   PGPASSWORD=$TOKEN psql "host=$RDSHOST port=5432 dbname=postgres user=postgres sslmode=require" -c "SELECT 1;"
   ```

   Or in Python:

   ```python
   import boto3, psycopg2
   rds = boto3.client("rds", region_name="<region>")
   token = rds.generate_db_auth_token(DBHostname=endpoint, Port=5432, DBUsername="postgres")
   conn = psycopg2.connect(host=endpoint, port=5432, database="postgres", user="postgres", password=token, sslmode="require")
   ```

3. **Tokens expire in 15 minutes** — the user generates a fresh token before each session or query batch. `generate-db-auth-token` produces a short-lived IAM token; it is not a stored credential but the secure, approved connection method. The call is the user's responsibility, not the skill's.

4. **Adding additional database users**: the user creates them in the database directly and configures each for IAM auth. Source: [IAM database authentication for Aurora](https://docs.aws.amazon.com/AmazonRDS/latest/AuroraUserGuide/UsingWithRDS.IAMDBAuth.html).

The skill creates the cluster and provides the connection workflow above. The skill does NOT execute SQL against the cluster — the user runs queries themselves via psql, the RDS Data API (with separately created credentials), or their application.
