"""lambda_handler_example.py — Lambda handler for ODB@AWS with python-oracledb thin mode.

Demonstrates:
  - Wallet download from Secrets Manager (binary secret) on cold start
  - Credential retrieval from Secrets Manager
  - Connection reuse across warm invocations
  - Error handling with retry for transient ORA- errors

Environment variables:
  DB_SECRET: Secrets Manager secret ID for credentials (JSON)
  WALLET_SECRET: Secrets Manager secret ID for wallet (binary ZIP)
"""

import base64
import io
import json
import logging
import os
import time
import zipfile

import boto3
import oracledb

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Global state for connection reuse across warm invocations
_conn = None
_wallet_dir = None
_secrets_client = None

# Transient ORA- errors that warrant retry
TRANSIENT_ERRORS = {12170, 12541, 3113, 3114, 3135, 25408}


def get_secrets_client():
    global _secrets_client
    if _secrets_client is None:
        _secrets_client = boto3.client("secretsmanager")
    return _secrets_client


def setup_wallet() -> str:
    """Download wallet from Secrets Manager to /tmp on cold start."""
    global _wallet_dir
    wallet_path = "/tmp/wallet"

    if _wallet_dir and os.path.exists(f"{wallet_path}/cwallet.sso"):
        return _wallet_dir

    logger.info("Downloading wallet from Secrets Manager")
    client = get_secrets_client()
    response = client.get_secret_value(SecretId=os.environ["WALLET_SECRET"])
    wallet_zip = base64.b64decode(response["SecretBinary"])

    os.makedirs(wallet_path, exist_ok=True)
    with zipfile.ZipFile(io.BytesIO(wallet_zip)) as zf:
        zf.extractall(wallet_path)

    _wallet_dir = wallet_path
    logger.info(f"Wallet extracted to {wallet_path}")
    return _wallet_dir


def get_credentials() -> dict:
    """Retrieve database credentials from Secrets Manager."""
    client = get_secrets_client()
    response = client.get_secret_value(SecretId=os.environ["DB_SECRET"])
    return json.loads(response["SecretString"])


def get_connection() -> oracledb.Connection:
    """Get or create a database connection with retry logic."""
    global _conn

    # Reuse existing connection if healthy
    if _conn is not None:
        try:
            _conn.ping()
            return _conn
        except Exception:
            logger.warning("Existing connection is stale, reconnecting")
            try:
                _conn.close()
            except oracledb.DatabaseError as close_err:
                logger.warning(f"Stale-connection close failed: {close_err}")
            _conn = None

    wallet_dir = setup_wallet()
    secret = get_credentials()

    dsn = f"{secret['host']}:{secret['port']}/{secret['service_name']}"

    for attempt in range(3):
        try:
            _conn = oracledb.connect(
                user=secret["username"],
                password=secret["password"],
                dsn=dsn,
                config_dir=wallet_dir,
                wallet_location=wallet_dir,
                wallet_password=secret.get("wallet_password"),
                tcp_connect_timeout=10,
                retry_count=1,
                retry_delay=1,
            )
            logger.info(f"Connected to {dsn} (attempt {attempt + 1})")
            return _conn
        except oracledb.DatabaseError as e:
            error = e.args[0]
            if error.code in TRANSIENT_ERRORS and attempt < 2:
                wait = (attempt + 1) * 2
                logger.warning(f"Transient error ORA-{error.code}, retrying in {wait}s")
                time.sleep(wait)
            else:
                raise

    raise RuntimeError("Failed to connect after 3 attempts")


def handler(event, context):
    """Lambda handler — connects to ODB@AWS and runs a test query."""
    try:
        conn = get_connection()
        with conn.cursor() as cursor:
            cursor.execute("SELECT USER, SYS_CONTEXT('USERENV', 'SERVICE_NAME') FROM DUAL")
            row = cursor.fetchone()
            return {
                "statusCode": 200,
                "body": json.dumps(
                    {"user": row[0], "service": row[1], "message": "Connected to ODB@AWS"}
                ),
            }
    except oracledb.DatabaseError as e:
        error = e.args[0]
        logger.error(f"Database error: ORA-{error.code} {error.message}")
        return {
            "statusCode": 500,
            "body": json.dumps(
                {
                    "error": f"ORA-{error.code}",
                    "message": error.message,
                }
            ),
        }
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        return {
            "statusCode": 500,
            "body": json.dumps({"error": str(e)}),
        }
