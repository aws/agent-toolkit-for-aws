#!/usr/bin/env bash
# =============================================================================
# db2-kerberos-test.sh
#
# Driver script for Db2KerberosConnection.java
#
# Compiles the Java source (if needed), collects all parameters interactively
# or via flags, then runs the TCPIP and/or SSL connection path(s).
#
# SSL uses a region-specific PEM certificate from AWS — no KeyStore or keytool.
# Reference:
#   https://aws.amazon.com/blogs/database/
#   create-an-ssl-connection-to-amazon-rds-for-db2-in-java-without-keystore-or-keytool/
#
# Usage:
#   ./run_db2_kerberos.sh [OPTIONS]
#
# Options:
#   -h HOST          Db2 server hostname or IP
#   -d DATABASE      Db2 database name
#   -p PORT          Port (used for both TCPIP and SSL when set; overrides defaults)
#   -P TCPIP_PORT    TCPIP-specific port (default: 50000)
#   -S SSL_PORT      SSL-specific port   (default: 50001)
#   -m MODE          TCPIP | SSL | BOTH  (default: BOTH)
#   -c CERT_PEM      Path to region-specific PEM file (e.g. us-east-1-bundle.pem)
#                    If not provided, the script downloads it automatically.
#   -r REGION        AWS region for cert download (default: us-east-1)
#   -j DB2_JAR       Path to db2jcc4.jar (default: ~/sqllib/java/db2jcc4.jar)
#   --no-compile     Skip recompilation
#   --help           Show this help
#
# Examples:
#   # Interactive — prompts for everything missing:
#   ./run_db2_kerberos.sh
#
#   # TCPIP only:
#   ./run_db2_kerberos.sh -h mydb2.abc123.us-east-1.rds.amazonaws.com \
#       -d MYDB -p 50000 -m TCPIP
#
#   # SSL only (auto-downloads cert for us-east-1):
#   ./run_db2_kerberos.sh -h mydb2.abc123.us-east-1.rds.amazonaws.com \
#       -d MYDB -S 50001 -m SSL -r us-east-1
#
#   # SSL with an existing PEM file:
#   ./run_db2_kerberos.sh -h mydb2.abc123.us-east-1.rds.amazonaws.com \
#       -d MYDB -S 50001 -m SSL -c /home/db2inst1/us-east-1-bundle.pem
#
#   # Both paths:
#   ./run_db2_kerberos.sh -h mydb2.abc123.us-east-1.rds.amazonaws.com \
#       -d MYDB -P 50000 -S 50001 -m BOTH -r us-east-1
# =============================================================================

set -euo pipefail

# ---------------------------------------------------------------------------
# User-configurable variables — edit these before running, or override via
# command-line flags.
# ---------------------------------------------------------------------------
PORT_TCPIP="50000"   # Plain TCPIP port          (-P flag)
PORT_SSL="50001"     # SSL/TLS port               (-S flag)
REGION="us-east-1"  # AWS region for cert download (-r flag)

# ---------------------------------------------------------------------------
# Defaults (not normally edited)
# ---------------------------------------------------------------------------
HOST=""
DATABASE=""
MODE=""
CERT_PEM=""
DB2_JAR="${HOME}/sqllib/java/db2jcc4.jar"
SKIP_COMPILE=false
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
JAVA_SRC="${SCRIPT_DIR}/Db2KerberosConnection.java"
JAVA_CLASS="Db2KerberosConnection"

# ---------------------------------------------------------------------------
# Colour helpers
# ---------------------------------------------------------------------------
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
info()    { echo -e "${GREEN}[INFO]${NC}  $*"; }
warn()    { echo -e "${YELLOW}[WARN]${NC}  $*"; }
error()   { echo -e "${RED}[ERROR]${NC} $*" >&2; }
section() { echo -e "\n${YELLOW}=== $* ===${NC}"; }

# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------
usage() {
    sed -n '/^# Usage:/,/^# =====/p' "$0" | sed 's/^# \?//'
    exit 0
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        -h) HOST="$2";       shift 2 ;;
        -d) DATABASE="$2";   shift 2 ;;
        -p) PORT_TCPIP="$2"; PORT_SSL="$2"; shift 2 ;;
        -P) PORT_TCPIP="$2"; shift 2 ;;
        -S) PORT_SSL="$2";   shift 2 ;;
        -m) MODE="${2^^}";   shift 2 ;;
        -c) CERT_PEM="$2";   shift 2 ;;
        -r) REGION="$2";     shift 2 ;;
        -j) DB2_JAR="$2";    shift 2 ;;
        --no-compile) SKIP_COMPILE=true; shift ;;
        --help) usage ;;
        *) error "Unknown option: $1"; usage ;;
    esac
done

# ---------------------------------------------------------------------------
# Interactive prompts for missing required values
# ---------------------------------------------------------------------------
prompt() {
    local var_name="$1" prompt_text="$2" default="$3"
    local current
    current=$(eval echo "\$$var_name")
    if [[ -z "$current" ]]; then
        read -rp "${prompt_text} [${default}]: " input
        eval "$var_name=\"${input:-$default}\""
    fi
}

prompt_required() {
    # Always prompts. Shows current/default value in brackets.
    # Accepts Enter to keep the existing value; rejects empty when no default.
    local var_name="$1" prompt_text="$2"
    local current
    current=$(eval echo "\$$var_name")
    if [[ -n "$current" ]]; then
        read -rp "${prompt_text} [${current}]: " input
        eval "$var_name=\"${input:-$current}\""
    else
        read -rp "${prompt_text}: " input
        if [[ -z "$input" ]]; then
            error "${var_name} is required."
            exit 1
        fi
        eval "$var_name=\"$input\""
    fi
}

section "Db2 Kerberos Connection — Parameter Collection"

prompt_required HOST     "Db2 server hostname or IP"
prompt_required DATABASE "Db2 database name"

if [[ -z "$MODE" ]]; then
    echo "Connection mode options:"
    echo "  1) TCPIP  — plain TCP (no encryption)"
    echo "  2) SSL    — TLS encrypted, PEM certificate (no KeyStore/keytool)"
    echo "  3) BOTH   — run TCPIP first, then SSL"
    read -rp "Choose mode [1/2/3, default=3]: " mode_choice
    case "${mode_choice:-3}" in
        1) MODE="TCPIP" ;;
        2) MODE="SSL"   ;;
        3) MODE="BOTH"  ;;
        *) error "Invalid choice"; exit 1 ;;
    esac
fi

if [[ "$MODE" == "TCPIP" || "$MODE" == "BOTH" ]]; then
    prompt_required PORT_TCPIP "TCPIP port"
fi

if [[ "$MODE" == "SSL" || "$MODE" == "BOTH" ]]; then
    prompt_required PORT_SSL "SSL port"
    prompt_required REGION   "AWS region (for cert download)"
fi

prompt DB2_JAR "Path to db2jcc4.jar" "${HOME}/sqllib/java/db2jcc4.jar"

# ---------------------------------------------------------------------------
# Validate prerequisites
# ---------------------------------------------------------------------------
section "Validating Prerequisites"

if [[ ! -f "$DB2_JAR" ]]; then
    error "db2jcc4.jar not found at: $DB2_JAR"
    error "Copy it from your Db2 client: ~/sqllib/java/db2jcc4.jar"
    exit 1
fi
info "DB2 JAR : $DB2_JAR"

if ! command -v javac &>/dev/null; then
    error "javac not found. Install a JDK (Java 8+)."
    exit 1
fi
if ! command -v java &>/dev/null; then
    error "java not found. Install a JRE/JDK (Java 8+)."
    exit 1
fi
info "Java    : $(java -version 2>&1 | head -1)"

# Check Kerberos ticket
if command -v klist &>/dev/null; then
    if klist -s 2>/dev/null; then
        info "Kerberos ticket cache is valid."
    else
        warn "No valid Kerberos ticket found. Run 'kinit' before connecting."
    fi
else
    warn "klist not found — cannot verify Kerberos ticket."
fi

# ---------------------------------------------------------------------------
# Download PEM certificate (SSL paths only)
# ---------------------------------------------------------------------------
if [[ "$MODE" == "SSL" || "$MODE" == "BOTH" ]]; then
    section "SSL Certificate (PEM)"

    # Default cert path if not supplied
    if [[ -z "$CERT_PEM" ]]; then
        CERT_PEM="${SCRIPT_DIR}/${REGION}-bundle.pem"
    fi

    if [[ -f "$CERT_PEM" ]]; then
        info "Certificate already exists: $CERT_PEM"
    else
        CERT_URL="https://truststore.pki.rds.amazonaws.com/${REGION}/${REGION}-bundle.pem"
        info "Downloading certificate from: $CERT_URL"
        if ! curl -fsSL "$CERT_URL" -o "$CERT_PEM"; then
            error "Failed to download certificate. Check region name and network access."
            exit 1
        fi
        info "Certificate saved to: $CERT_PEM"
    fi

    # Remind about the global-bundle limitation
    if [[ "$CERT_PEM" == *"global-bundle"* ]]; then
        warn "global-bundle.pem is NOT supported by the IBM JDBC driver's sslCertLocation."
        warn "Use a region-specific bundle, e.g. ${REGION}-bundle.pem"
        exit 1
    fi
fi

# ---------------------------------------------------------------------------
# Compile
# ---------------------------------------------------------------------------
section "Compiling ${JAVA_CLASS}.java"

CLASS_FILE="${SCRIPT_DIR}/${JAVA_CLASS}.class"

if [[ "$SKIP_COMPILE" == false ]]; then
    javac -cp "${DB2_JAR}" "${JAVA_SRC}" -d "${SCRIPT_DIR}"
    info "Compilation successful."
else
    if [[ ! -f "$CLASS_FILE" ]]; then
        error "Class file not found and --no-compile was set. Run without --no-compile first."
        exit 1
    fi
    info "Skipping compilation (--no-compile)."
fi

# ---------------------------------------------------------------------------
# Run helper
# ---------------------------------------------------------------------------
run_connection() {
    local label="$1"; shift
    section "Running $label Connection"
    info "java -cp \"${SCRIPT_DIR}:${DB2_JAR}\" ${JAVA_CLASS} $*"
    echo "---"
    # Uncomment the line below to enable SSL handshake debug output:
    # export JAVA_OPTS="-Djavax.net.debug=ssl:handshake:verbose"
    if java ${JAVA_OPTS:-} -cp "${SCRIPT_DIR}:${DB2_JAR}" "${JAVA_CLASS}" "$@"; then
        info "$label connection: SUCCESS"
        return 0
    else
        error "$label connection: FAILED (exit code $?)"
        return 1
    fi
}

# ---------------------------------------------------------------------------
# Execute connection path(s)
# ---------------------------------------------------------------------------
TCPIP_OK=true
SSL_OK=true

if [[ "$MODE" == "TCPIP" || "$MODE" == "BOTH" ]]; then
    run_connection "TCPIP" "$HOST" "$DATABASE" "$PORT_TCPIP" "TCPIP" || TCPIP_OK=false
fi

if [[ "$MODE" == "SSL" || "$MODE" == "BOTH" ]]; then
    run_connection "SSL" "$HOST" "$DATABASE" "$PORT_SSL" "SSL" "$CERT_PEM" || SSL_OK=false
fi

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
section "Summary"
[[ "$MODE" == "TCPIP" || "$MODE" == "BOTH" ]] && {
    $TCPIP_OK && info "TCPIP : PASSED" || error "TCPIP : FAILED"
}
[[ "$MODE" == "SSL"   || "$MODE" == "BOTH" ]] && {
    $SSL_OK  && info "SSL   : PASSED" || error "SSL   : FAILED"
}

# Exit non-zero if either selected path failed
$TCPIP_OK && $SSL_OK
