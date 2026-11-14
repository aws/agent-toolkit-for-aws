#!/usr/bin/env bash
# test_connection_jdbc.sh — Test JDBC thin-mode connection to ODB@AWS via JShell
# Usage: bash test_connection_jdbc.sh <scan-host> <port> <service-name> <user> [wallet-dir]

set -euo pipefail

SCAN_HOST="${1:?Usage: test_connection_jdbc.sh <scan-host> <port> <service-name> <user> [wallet-dir]}"
PORT="${2:?Port required}"
SERVICE="${3:?Service name required}"
USER="${4:?Username required}"
WALLET_DIR="${5:-}"

echo "=== ODB@AWS JDBC Connection Test ==="
echo "Host: ${SCAN_HOST}:${PORT}/${SERVICE}"
echo "User: ${USER}"
echo "Wallet: ${WALLET_DIR:-None (TCP mode)}"
echo ""

# Check for Java
if ! command -v jshell &>/dev/null; then
    echo "❌ jshell not found. Install JDK 11+ to run this test."
    exit 1
fi

# Check for ojdbc
OJDBC_JAR=$(find /usr/lib /opt /usr/local -name "ojdbc11.jar" -o -name "ojdbc8.jar" 2>/dev/null | head -1 || true)
if [ -z "$OJDBC_JAR" ]; then
    echo "❌ ojdbc11.jar not found. Download from Oracle or add via Maven."
    exit 1
fi
echo "Using JDBC driver: $OJDBC_JAR"

# Prompt for password
read -sp "Database password: " DB_PASSWORD
echo ""

# Build JDBC URL
if [ -n "$WALLET_DIR" ]; then
    JDBC_URL="jdbc:oracle:thin:@(DESCRIPTION=(ADDRESS=(PROTOCOL=TCPS)(HOST=${SCAN_HOST})(PORT=${PORT}))(CONNECT_DATA=(SERVICE_NAME=${SERVICE}))(SECURITY=(SSL_SERVER_DN_MATCH=TRUE)))"
    EXTRA_PROPS="-J-Doracle.net.tns_admin=${WALLET_DIR}"
    if [ -f "${WALLET_DIR}/truststore.jks" ]; then
        read -sp "Truststore password: " TS_PASSWORD
        echo ""
        export TS_PASSWORD
        EXTRA_PROPS="${EXTRA_PROPS} -J-Djavax.net.ssl.trustStore=${WALLET_DIR}/truststore.jks"
    fi
else
    JDBC_URL="jdbc:oracle:thin:@//${SCAN_HOST}:${PORT}/${SERVICE}"
    EXTRA_PROPS=""
fi

# Run JShell test
echo ""
echo "--- Connecting ---"
export DB_PASSWORD
jshell --class-path "$OJDBC_JAR" $EXTRA_PROPS <<EOF
import java.sql.*;
try {
    String password = System.getenv("DB_PASSWORD");
    String tsPass = System.getenv("TS_PASSWORD");
    if (tsPass != null) System.setProperty("javax.net.ssl.trustStorePassword", tsPass);
    Connection conn = DriverManager.getConnection("${JDBC_URL}", "${USER}", password);
    System.out.println("✅ Connected");

    Statement stmt = conn.createStatement();
    ResultSet rs = stmt.executeQuery("SELECT banner FROM v\$version WHERE ROWNUM = 1");
    if (rs.next()) System.out.println("✅ Database: " + rs.getString(1));

    rs = stmt.executeQuery("SELECT instance_name, host_name FROM v\$instance");
    if (rs.next()) System.out.println("✅ Instance: " + rs.getString(1) + " on " + rs.getString(2));

    rs = stmt.executeQuery("SELECT USER FROM DUAL");
    if (rs.next()) System.out.println("✅ User: " + rs.getString(1));

    conn.close();
    System.out.println("\n=== JDBC connection test passed ✅ ===");
} catch (SQLException e) {
    System.out.println("❌ Connection failed: " + e.getMessage());
    System.exit(1);
}
/exit
EOF
