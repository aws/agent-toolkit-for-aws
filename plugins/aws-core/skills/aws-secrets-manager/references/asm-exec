#!/usr/bin/env python3
"""asm-exec: Resolve {{resolve:secretsmanager:...}} references and run the command.

Usage: asm-exec <command> [args...]

Resolves dynamic references in arguments and exported environment variables,
then runs the command. Secret values never return to the calling agent.

Resolution order:
  1. AWS Secrets Manager Agent (SMA) on localhost:2773 (zero-latency, cached)
  2. Streamable HTTP MCP endpoint (requires AWS credentials)

Security: Uses re.sub with callable for single-pass substitution (resolved
values are never re-scanned). SecretBinary is not supported.
"""

import datetime
import hashlib
import hmac
import json
import os
import re
import shlex
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request


def _shell_quote(value):
    """Quote a value for safe inclusion in the cli_command string."""
    return shlex.quote(value)

PATTERN = re.compile(r'\{\{resolve:secretsmanager:([^}]+)\}\}')
SMA_ENDPOINT = os.environ.get('AWS_SECRETS_MANAGER_AGENT_ENDPOINT', 'http://localhost:2773')
SSRF_TOKEN = os.environ.get('AWS_SESSION_TOKEN', os.environ.get('AWS_TOKEN', ''))
MCP_ENDPOINT = os.environ.get('ASM_EXEC_MCP_ENDPOINT', 'https://aws-mcp.us-east-1.api.aws/mcp')

_sma_available = None


def _check_sma():
    global _sma_available
    if _sma_available is None:
        try:
            req = urllib.request.Request(f'{SMA_ENDPOINT}/ping', method='GET')
            urllib.request.urlopen(req, timeout=1)
            _sma_available = True
        except (urllib.error.URLError, OSError):
            _sma_available = False
    return _sma_available


def _get_aws_credentials():
    """Resolve AWS credentials for SigV4 signing.

    Order: environment variables, then `aws configure export-credentials`
    (AWS CLI v2), then `aws configure get` (AWS CLI v1, which lacks
    export-credentials). Returns a dict with access_key/secret_key/token or None.
    """
    if os.environ.get('AWS_ACCESS_KEY_ID'):
        return {
            'access_key': os.environ['AWS_ACCESS_KEY_ID'],
            'secret_key': os.environ.get('AWS_SECRET_ACCESS_KEY', ''),
            'token': os.environ.get('AWS_SESSION_TOKEN', ''),
        }
    # AWS CLI v2: export-credentials emits resolved (possibly assumed-role) creds.
    try:
        result = subprocess.run(
            ['aws', 'configure', 'export-credentials', '--format', 'env'],
            capture_output=True, text=True, check=True, timeout=5
        )
        creds = {}
        for line in result.stdout.splitlines():
            if '=' in line:
                line = line.removeprefix('export ')
                k, v = line.split('=', 1)
                if k == 'AWS_ACCESS_KEY_ID':
                    creds['access_key'] = v
                elif k == 'AWS_SECRET_ACCESS_KEY':
                    creds['secret_key'] = v
                elif k == 'AWS_SESSION_TOKEN':
                    creds['token'] = v
        if creds.get('access_key'):
            return creds
    except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
        pass
    # AWS CLI v1 fallback: read static creds from the configured profile.
    try:
        def _cfg(key):
            r = subprocess.run(['aws', 'configure', 'get', key],
                               capture_output=True, text=True, timeout=5)
            return r.stdout.strip() if r.returncode == 0 else ''
        access_key = _cfg('aws_access_key_id')
        if access_key:
            return {
                'access_key': access_key,
                'secret_key': _cfg('aws_secret_access_key'),
                'token': _cfg('aws_session_token'),
            }
    except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
        pass
    return None


def _signing_service_region(endpoint):
    """Derive (service, region) for SigV4 from an AWS MCP endpoint hostname.

    Mirrors mcp-proxy-for-aws: 'service.region.api.aws' -> (service, region);
    'bedrock-agentcore' style is handled as a special case. The signing region
    is the endpoint's own region, independent of any secret's region.
    """
    host = urllib.parse.urlparse(endpoint).hostname or ''
    parts = host.split('.')
    if len(parts) >= 5 and parts[-4] == 'bedrock-agentcore' and parts[-2:] == ['amazonaws', 'com']:
        return 'bedrock-agentcore', parts[-3]
    if len(parts) == 4 and parts[2:] == ['api', 'aws']:
        return parts[0], parts[1]
    # Fallback: first segment as service, region from environment.
    region = os.environ.get('AWS_REGION') or os.environ.get('AWS_DEFAULT_REGION') or 'us-east-1'
    return (parts[0] if parts else 'aws-mcp'), region


def _sign_v4(method, path, body, creds, service, region, now):
    """Compute SigV4 headers (stdlib only) for a request. Returns a header dict.

    botocore is not available in asm-exec's runtime, so signing is implemented
    directly with hashlib/hmac following the AWS SigV4 spec.
    """
    host = urllib.parse.urlparse(MCP_ENDPOINT).hostname or ''
    amzdate = now.strftime('%Y%m%dT%H%M%SZ')
    datestamp = now.strftime('%Y%m%d')
    payload_hash = hashlib.sha256(body).hexdigest()

    headers = {
        'host': host,
        'x-amz-date': amzdate,
        'x-amz-content-sha256': payload_hash,
    }
    if creds.get('token'):
        headers['x-amz-security-token'] = creds['token']

    signed_keys = sorted(headers)
    canonical_headers = ''.join(f'{k}:{headers[k].strip()}\n' for k in signed_keys)
    signed_headers_str = ';'.join(signed_keys)
    canonical_request = (f'{method}\n{path}\n\n{canonical_headers}\n'
                         f'{signed_headers_str}\n{payload_hash}')

    scope = f'{datestamp}/{region}/{service}/aws4_request'
    string_to_sign = (f'AWS4-HMAC-SHA256\n{amzdate}\n{scope}\n'
                      f'{hashlib.sha256(canonical_request.encode()).hexdigest()}')

    def _hmac(key, msg):
        return hmac.new(key, msg.encode('utf-8'), hashlib.sha256).digest()

    k_date = _hmac(('AWS4' + creds['secret_key']).encode('utf-8'), datestamp)
    k_region = _hmac(k_date, region)
    k_service = _hmac(k_region, service)
    k_signing = _hmac(k_service, 'aws4_request')
    signature = hmac.new(k_signing, string_to_sign.encode('utf-8'),
                         hashlib.sha256).hexdigest()

    headers['Authorization'] = (
        f'AWS4-HMAC-SHA256 Credential={creds["access_key"]}/{scope}, '
        f'SignedHeaders={signed_headers_str}, Signature={signature}'
    )
    return headers


def _mcp_post(payload, session_id=None):
    """POST a SigV4-signed JSON-RPC request to the AWS MCP endpoint.

    Returns (parsed_response, session_id_from_response). The caller passes the
    session id returned by 'initialize' back into subsequent calls.
    """
    creds = _get_aws_credentials()
    if not creds or not creds.get('access_key'):
        raise RuntimeError('no AWS credentials available for MCP signing')

    body = json.dumps(payload).encode()
    service, region = _signing_service_region(MCP_ENDPOINT)
    path = urllib.parse.urlparse(MCP_ENDPOINT).path or '/'
    now = datetime.datetime.utcnow()

    sig_headers = _sign_v4('POST', path, body, creds, service, region, now)
    req = urllib.request.Request(MCP_ENDPOINT, data=body, method='POST')
    req.add_header('Content-Type', 'application/json')
    req.add_header('Accept', 'application/json, text/event-stream')
    req.add_header('User-Agent', 'ASMExecWrapper/1.0.0')
    if session_id:
        req.add_header('Mcp-Session-Id', session_id)
    for k, v in sig_headers.items():
        req.add_header(k, v)

    resp = urllib.request.urlopen(req, timeout=10)
    session_out = resp.headers.get('Mcp-Session-Id')
    raw = resp.read()
    parsed = json.loads(raw) if raw else {}
    return parsed, session_out


def _extract_secret_string(payload):
    """Pull SecretString out of a parsed get-secret-value response dict."""
    if isinstance(payload, dict):
        if "SecretString" in payload:
            return payload["SecretString"]
        # call_aws may nest the CLI output under a results/output key
        for key in ("result", "results", "output", "stdout"):
            if key in payload:
                nested = payload[key]
                if isinstance(nested, str):
                    try:
                        nested = json.loads(nested)
                    except json.JSONDecodeError:
                        continue
                found = _extract_secret_string(nested)
                if found:
                    return found
    return None


def _resolve_via_mcp(secret_name, label, region):
    """Resolve a secret via the SigV4-authenticated AWS MCP endpoint.

    The server exposes 'aws___call_aws', which runs a full AWS CLI command
    (passed as the 'cli_command' string) server-side and returns its output.
    The SecretString returns into this process and never reaches the agent.
    Returns the value or None.
    """
    try:
        # Initialize and capture the session id for subsequent calls.
        _, session_id = _mcp_post(
            {"jsonrpc": "2.0", "id": 1, "method": "initialize",
             "params": {"protocolVersion": "2024-11-05",
                        "clientInfo": {"name": "asm-exec", "version": "1.0.0"},
                        "capabilities": {}}})
        # Notify initialized
        _mcp_post({"jsonrpc": "2.0", "method": "notifications/initialized"},
                  session_id)
        # Build the CLI command string the MCP server will execute. Include
        # --region so cross-region secrets resolve regardless of the endpoint's
        # home region. The secret id is quoted to tolerate ARNs and shell metachars.
        cmd_parts = ["aws", "secretsmanager", "get-secret-value",
                     "--secret-id", _shell_quote(secret_name),
                     "--version-stage", _shell_quote(label),
                     "--output", "json"]
        if region:
            cmd_parts += ["--region", region]
        cli_command = " ".join(cmd_parts)
        # Call tool
        resp, _ = _mcp_post(
            {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
             "params": {"name": "aws___call_aws",
                        "arguments": {"cli_command": cli_command}}},
            session_id)
        result = resp.get("result", {})
        # tools/call returns a content array of text items
        if isinstance(result, dict) and "content" in result:
            for item in result["content"]:
                if item.get("type") == "text":
                    try:
                        data = json.loads(item["text"])
                    except (json.JSONDecodeError, TypeError):
                        continue
                    found = _extract_secret_string(data)
                    if found:
                        return found
        if isinstance(result, dict):
            return _extract_secret_string(result)
    except (urllib.error.URLError, OSError, json.JSONDecodeError,
            KeyError, TypeError, RuntimeError):
        pass
    return None


def resolve_one(ref):
    """Resolve secret-id[:field-type[:json-key[:version-stage]]].

    Secret-id may be an ARN (contains colons) or a plain name.
    ARN format: arn:aws:secretsmanager:<Region>:<AccountId>:secret:<SecretName>-<6RandomChars>
    """
    # ARN-aware split: if ref starts with 'arn:', treat everything up to
    # the 7th colon as the secret-id (6 colons in a standard ARN)
    if ref.startswith('arn:'):
        arn_parts = ref.split(':')
        # Standard ARN has 7 segments (indices 0-6): arn:partition:service:region:account:resource-type:resource-id
        if len(arn_parts) >= 7:
            secret_name = ':'.join(arn_parts[:7])
            remainder = arn_parts[7:]
        else:
            secret_name = ref
            remainder = []
        field_type = remainder[0] if len(remainder) > 0 else 'SecretString'
        json_key = remainder[1] if len(remainder) > 1 else None
        label = remainder[2] if len(remainder) > 2 else 'AWSCURRENT'
    else:
        parts = ref.split(':', 3)
        secret_name = parts[0]
        field_type = parts[1] if len(parts) > 1 else 'SecretString'
        json_key = parts[2] if len(parts) > 2 else None
        label = parts[3] if len(parts) > 3 else 'AWSCURRENT'

    if field_type != 'SecretString':
        print(f'asm-exec: ERROR: Only SecretString is supported, got: {field_type}', file=sys.stderr)
        sys.exit(1)

    value = None

    # Region for cross-region secrets: honor an ARN's region segment first,
    # then fall back to the ambient AWS_REGION / AWS_DEFAULT_REGION.
    region = None
    if secret_name.startswith('arn:'):
        arn_segments = secret_name.split(':')
        if len(arn_segments) >= 4 and arn_segments[3]:
            region = arn_segments[3]
    if not region:
        region = os.environ.get('AWS_REGION') or os.environ.get('AWS_DEFAULT_REGION')

    # 1. Try SMA daemon
    if _check_sma():
        url = f'{SMA_ENDPOINT}/secretsmanager/get?secretId={urllib.parse.quote(secret_name, safe="")}&versionStage={label}'
        req = urllib.request.Request(url, method='GET')
        if SSRF_TOKEN:
            req.add_header('X-Aws-Parameters-Secrets-Token', SSRF_TOKEN)
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read())
                value = data.get('SecretString')
        except (urllib.error.URLError, OSError, json.JSONDecodeError):
            pass

    # 2. Resolve via Streamable HTTP MCP
    if not value:
        value = _resolve_via_mcp(secret_name, label, region)

    if not value:
        print(f'asm-exec: ERROR: Failed to resolve: {ref}', file=sys.stderr)
        sys.exit(1)

    if json_key:
        try:
            obj = json.loads(value)
            value = obj[json_key]
        except (json.JSONDecodeError, KeyError, TypeError):
            print(f"asm-exec: ERROR: JSON key '{json_key}' not found in: {secret_name}", file=sys.stderr)
            sys.exit(1)
        if not isinstance(value, str):
            value = json.dumps(value)

    return value


def resolve_string(s):
    """Single-pass substitution — resolved values are never re-scanned."""
    return PATTERN.sub(lambda m: resolve_one(m.group(1)), s)


def main():
    if len(sys.argv) < 2:
        print('Usage: asm-exec <command> [args...]', file=sys.stderr)
        sys.exit(1)

    cmd_args = sys.argv[1:]
    # Strip optional -- separator (convention: asm-exec -- command)
    if cmd_args and cmd_args[0] == '--':
        cmd_args = cmd_args[1:]
    if not cmd_args:
        print('Usage: asm-exec <command> [args...]', file=sys.stderr)
        sys.exit(1)

    args = [resolve_string(a) if PATTERN.search(a) else a for a in cmd_args]

    result = subprocess.run(args)
    sys.exit(result.returncode)


if __name__ == '__main__':
    main()
