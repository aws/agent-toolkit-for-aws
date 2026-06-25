import java.sql.Connection;
import java.sql.PreparedStatement;
import java.sql.ResultSet;
import java.sql.SQLException;

import javax.sql.DataSource;

import com.ibm.db2.jcc.DB2SimpleDataSource;

/**
 * Db2KerberosConnection
 *
 * Connects to a Db2 database using Kerberos authentication over either
 * plain TCPIP or SSL (TLS). SSL mode uses a PEM certificate file directly
 * via the IBM JDBC driver's sslCertLocation property — no KeyStore or
 * keytool required.
 *
 * Reference:
 *   https://aws.amazon.com/blogs/database/
 *   create-an-ssl-connection-to-amazon-rds-for-db2-in-java-without-keystore-or-keytool/
 *
 * Usage (TCPIP):
 *   java Db2KerberosConnection <HOST> <DATABASE> <PORT> TCPIP
 *
 * Usage (SSL):
 *   java Db2KerberosConnection <HOST> <DATABASE> <PORT> SSL <CERT_PEM_PATH>
 *
 *   CERT_PEM_PATH — region-specific PEM bundle from AWS, e.g.
 *                   us-east-1-bundle.pem  (do NOT use global-bundle.pem;
 *                   the IBM JDBC driver only supports single-region bundles)
 */
public class Db2KerberosConnection {

    // Db2 JDBC security mechanism: 11 = Kerberos
    private static final String KERBEROS_SECURITY_MECHANISM = "11";

    public static void main(String[] args) {
        ConnectionConfig config = parseArgs(args);
        if (config == null) {
            printUsage();
            System.exit(1);
        }

        Connection connection = loadDriverAndConnect(config);
        if (connection != null) {
            verifyConnection(connection);
            closeQuietly(connection);
        } else {
            System.exit(2);
        }
    }

    // -------------------------------------------------------------------------
    // Argument parsing
    // -------------------------------------------------------------------------

    private static ConnectionConfig parseArgs(String[] args) {
        if (args.length < 4) return null;

        String host     = args[0];
        String database = args[1];
        String port     = args[2];
        String mode     = args[3].toUpperCase();

        if (mode.equals("TCPIP")) {
            return new ConnectionConfig(host, database, port, false, null);
        }

        if (mode.equals("SSL")) {
            if (args.length < 5) {
                System.err.println("ERROR: SSL mode requires <CERT_PEM_PATH>");
                return null;
            }
            String certPath = args[4];
            java.io.File certFile = new java.io.File(certPath);
            if (!certFile.exists()) {
                System.err.println("ERROR: Certificate file not found: " + certPath);
                System.err.println("       Download it with:");
                System.err.println("       curl -sL https://truststore.pki.rds.amazonaws.com/"
                        + "<region>/<region>-bundle.pem -o <region>-bundle.pem");
                return null;
            }
            return new ConnectionConfig(host, database, port, true, certPath);
        }

        System.err.println("ERROR: Unknown mode '" + args[3] + "'. Use TCPIP or SSL.");
        return null;
    }

    private static void printUsage() {
        System.err.println();
        System.err.println("Usage (TCPIP):");
        System.err.println("  java Db2KerberosConnection <HOST> <DATABASE> <PORT> TCPIP");
        System.err.println();
        System.err.println("Usage (SSL):");
        System.err.println("  java Db2KerberosConnection <HOST> <DATABASE> <PORT> SSL <CERT_PEM_PATH>");
        System.err.println();
        System.err.println("  CERT_PEM_PATH — region-specific PEM bundle, e.g. <region>-bundle.pem");
        System.err.println("                  Download: curl -sL https://truststore.pki.rds.amazonaws.com/");
        System.err.println("                            <region>/<region>-bundle.pem -o <region>-bundle.pem");
        System.err.println();
    }

    // -------------------------------------------------------------------------
    // Driver loading and connection
    // -------------------------------------------------------------------------

    private static Connection loadDriverAndConnect(ConnectionConfig config) {
        try {
            Class.forName("com.ibm.db2.jcc.DB2Driver");
        } catch (ClassNotFoundException e) {
            System.err.println("ERROR: DB2 JDBC driver not found. "
                    + "Ensure db2jcc4.jar (v4.33+) is on the classpath.");
            e.printStackTrace(System.err);
            return null;
        }
        System.out.println("DB2 driver loaded successfully.");

        System.out.println("Connecting to : " + config.host + ":" + config.port + "/" + config.database);
        System.out.println("Mode          : " + (config.useSsl ? "SSL (PEM)" : "TCPIP"));
        if (config.useSsl) {
            System.out.println("Certificate   : " + config.certPath);
        }

        try {
            // Use a javax.sql.DataSource with dedicated setter methods rather than
            // concatenating host/port/database into a JDBC URL string. Passing the
            // connection parameters as typed properties avoids JDBC connection-string
            // injection (nothing is parsed back out of a URL).
            DataSource ds = buildDataSource(config);
            Connection conn = ds.getConnection();
            System.out.println("Connected to Db2 successfully using Kerberos"
                    + (config.useSsl ? " over SSL!" : "!"));
            return conn;
        } catch (SQLException e) {
            System.err.println("ERROR: Failed to connect to Db2.");
            e.printStackTrace(System.err);
            return null;
        }
    }

    // -------------------------------------------------------------------------
    // DataSource builder — sets connection parameters via dedicated setters
    // (no JDBC URL string concatenation, so no connection-string injection)
    // -------------------------------------------------------------------------

    private static DataSource buildDataSource(ConnectionConfig config) {
        DB2SimpleDataSource ds = new DB2SimpleDataSource();
        ds.setDriverType(4);
        ds.setServerName(config.host);
        ds.setPortNumber(Integer.parseInt(config.port));
        ds.setDatabaseName(config.database);

        // Kerberos — no user/password needed (security mechanism 11 = Kerberos)
        ds.setSecurityMechanism(Integer.parseInt(KERBEROS_SECURITY_MECHANISM));

        if (config.useSsl) {
            // PEM-based SSL: no KeyStore, no keytool. Requires db2jcc4.jar v4.33+
            ds.setSslConnection(true);
            // Enforce TLS 1.2 so the driver cannot negotiate down to TLS 1.0/1.1
            ds.setSslVersion("TLSv1.2");
            ds.setSslCertLocation(config.certPath);
        }
        return ds;
    }

    // -------------------------------------------------------------------------
    // Post-connect verification
    // -------------------------------------------------------------------------

    private static void verifyConnection(Connection conn) {
        String sql = "SELECT CURRENT SERVER, CURRENT TIMESTAMP FROM SYSIBM.SYSDUMMY1";
        try (PreparedStatement pstmt = conn.prepareStatement(sql);
             ResultSet rs           = pstmt.executeQuery()) {
            if (rs.next()) {
                System.out.println("Server    : " + rs.getString(1));
                System.out.println("Timestamp : " + rs.getTimestamp(2));
            }
        } catch (SQLException e) {
            System.err.println("WARNING: Connected but verification query failed.");
            e.printStackTrace(System.err);
        }
    }

    // -------------------------------------------------------------------------
    // Helpers
    // -------------------------------------------------------------------------

    private static void closeQuietly(Connection conn) {
        try {
            conn.close();
            System.out.println("Connection closed.");
        } catch (SQLException e) {
            e.printStackTrace(System.err);
        }
    }

    // -------------------------------------------------------------------------
    // Inner config class
    // -------------------------------------------------------------------------

    private static class ConnectionConfig {
        final String  host;
        final String  database;
        final String  port;
        final boolean useSsl;
        final String  certPath;   // path to region-specific .pem file (SSL only)

        ConnectionConfig(String host, String database, String port,
                         boolean useSsl, String certPath) {
            this.host     = host;
            this.database = database;
            this.port     = port;
            this.useSsl   = useSsl;
            this.certPath = certPath;
        }
    }
}
