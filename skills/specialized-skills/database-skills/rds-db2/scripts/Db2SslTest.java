import javax.net.ssl.*;
import java.io.*;
import java.net.*;
import java.security.*;
import java.security.cert.*;
import java.util.*;

/**
 * Db2SslTest.java — Test SSL connection to RDS DB2 bypassing GSKit entirely.
 *
 * Compile:  javac Db2SslTest.java
 * Run:      java Db2SslTest <host> <port> <pemFile>
 * Example:  java Db2SslTest mydb2.abc123def456.us-west-1.rds.amazonaws.com 50443 /tmp/us-west-1-bundle.pem
 *
 * No JDBC driver needed — tests the raw SSL handshake the same way the blog
 * approach works (Java TrustManager loaded from PEM, no keystore/keytool).
 */
public class Db2SslTest {

    public static void main(String[] args) throws Exception {
        if (args.length < 3) {
            System.err.println("Usage: java Db2SslTest <host> <port> <pem-file>");
            System.exit(1);
        }
        String host    = args[0];
        int    port    = Integer.parseInt(args[1]);
        String pemPath = args[2];

        System.out.println("============================================================");
        System.out.println("  RDS DB2 Java SSL Test (no GSKit, no keystore)");
        System.out.printf ("  Host : %s%n", host);
        System.out.printf ("  Port : %d%n", port);
        System.out.printf ("  PEM  : %s%n", pemPath);
        System.out.println("============================================================");
        System.out.println();

        // 1. Load certs from PEM
        List<X509Certificate> certs = loadPem(pemPath);
        System.out.printf("[PEM]  %d certificate(s) loaded from %s%n", certs.size(), pemPath);
        for (int i = 0; i < certs.size(); i++) {
            X509Certificate c = certs.get(i);
            System.out.printf("       [%d] Subject : %s%n", i, c.getSubjectX500Principal().getName());
            System.out.printf("           Issuer  : %s%n",     c.getIssuerX500Principal().getName());
            System.out.printf("           Expires : %s%n",     c.getNotAfter());
        }
        System.out.println();

        // 2. TCP
        System.out.print("[TCP]  Connecting... ");
        try (Socket s = new Socket()) {
            s.connect(new InetSocketAddress(host, port), 5000);
            System.out.println("OK");
        } catch (Exception e) {
            System.out.println("FAIL: " + e.getMessage());
            System.exit(1);
        }

        // 3. TLS with PEM-based TrustManager (blog approach)
        System.out.println();
        testTls("TLS with PEM TrustManager (blog approach)", host, port,
                buildSslContext(certs, false), false);

        // 4. TLS with PEM TrustManager, TLSv1.2 only
        testTls("TLS with PEM TrustManager, TLSv1.2 only", host, port,
                buildSslContext(certs, true), true);

        // 5. TLS trust-all (no cert check)
        testTls("TLS trust-all (no cert verification)", host, port,
                buildTrustAllContext(), false);

        System.out.println();
        System.out.println("============================================================");
    }

    // -------------------------------------------------------------------------

    static void testTls(String label, String host, int port,
                        SSLContext ctx, boolean tlsv12Only) {
        System.out.printf("[TLS]  %s%n", label);
        try {
            SSLSocketFactory factory = ctx.getSocketFactory();
            try (SSLSocket ssl = (SSLSocket) factory.createSocket()) {
                if (tlsv12Only) {
                    ssl.setEnabledProtocols(new String[]{"TLSv1.2"});
                }
                ssl.connect(new InetSocketAddress(host, port), 5000);
                ssl.startHandshake();
                SSLSession session = ssl.getSession();
                System.out.printf("       Status   : OK%n");
                System.out.printf("       Protocol : %s%n", session.getProtocol());
                System.out.printf("       Cipher   : %s%n", session.getCipherSuite());
                X509Certificate peer = (X509Certificate) session.getPeerCertificates()[0];
                System.out.printf("       Subject  : %s%n", peer.getSubjectX500Principal().getName());
                System.out.printf("       Expires  : %s%n", peer.getNotAfter());
            }
        } catch (Exception e) {
            System.out.printf("       Status   : FAIL%n");
            System.out.printf("       Error    : %s%n", e.getMessage());
        }
        System.out.println();
    }

    // Build SSLContext from PEM certs — same approach as the blog (no keystore/keytool)
    static SSLContext buildSslContext(List<X509Certificate> certs, boolean tlsv12Only)
            throws Exception {
        KeyStore ks = KeyStore.getInstance(KeyStore.getDefaultType());
        ks.load(null, null);
        for (int i = 0; i < certs.size(); i++) {
            ks.setCertificateEntry("rds-ca-" + i, certs.get(i));
        }
        TrustManagerFactory tmf = TrustManagerFactory.getInstance(
                TrustManagerFactory.getDefaultAlgorithm());
        tmf.init(ks);
        SSLContext ctx = SSLContext.getInstance(tlsv12Only ? "TLSv1.2" : "TLS");
        ctx.init(null, tmf.getTrustManagers(), null);
        return ctx;
    }

    // Trust-all context for baseline check
    static SSLContext buildTrustAllContext() throws Exception {
        TrustManager[] trustAll = new TrustManager[]{
            new X509TrustManager() {
                public X509Certificate[] getAcceptedIssuers() { return new X509Certificate[0]; }
                public void checkClientTrusted(X509Certificate[] c, String a) {}
                public void checkServerTrusted(X509Certificate[] c, String a) {}
            }
        };
        SSLContext ctx = SSLContext.getInstance("TLS");
        ctx.init(null, trustAll, null);
        return ctx;
    }

    // Load all certs from a PEM bundle (handles multi-cert bundles)
    static List<X509Certificate> loadPem(String path) throws Exception {
        CertificateFactory cf = CertificateFactory.getInstance("X.509");
        List<X509Certificate> certs = new ArrayList<>();
        try (InputStream in = new FileInputStream(path)) {
            Collection<? extends java.security.cert.Certificate> c = cf.generateCertificates(in);
            for (java.security.cert.Certificate cert : c) {
                certs.add((X509Certificate) cert);
            }
        }
        if (certs.isEmpty()) throw new Exception("No certificates found in " + path);
        return certs;
    }
}
