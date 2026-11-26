"""Shared settings and AWS Context API access for the AWS Context hooks.

One file holds the settings: ~/.aws-context/config.json. Only the /context-hooks command
writes it. A missing, unreadable or malformed file means both hooks are off.

Example:
{
  "graphArn": "arn:aws:context:us-east-1:111122223333:agent-context/ac-0123456789abcdef0123456789abcdef",
  "profile": "context-saml",
  "steering": "off",       # off | hint | search
  "feedback": "off",       # off | on
  "readers": [{"access": "ALLOW", "principalId": "*"}]
}

The Region comes from the graph ARN. "endpoint", or the AWS_CONTEXT_ENDPOINT environment variable,
overrides the API endpoint, for testing.

Hooks cannot use the agent's OAuth token, so "search" and "feedback" call the AWS Context
HTTPS API with SigV4, signing with credentials the AWS CLI exports for "profile". Signing
uses only the Python standard library, so the hooks need no AWS SDK and no `aws context`
CLI commands.
"""

import configparser
import datetime
import hashlib
import hmac
import http.client
import json
import os
import re
import shutil
import threading
import time
import subprocess
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

CONFIG_DIR = Path.home() / ".aws-context"
CONFIG_FILE = CONFIG_DIR / "config.json"
DEFAULTS = {"steering": "off", "feedback": "off"}
SIGNING_SERVICE = "context"
SEARCH_PATH = "/api/v1/agent-contexts/{agentContextId}/search"
PLUGIN_VERSION = "0.1.0"
PUT_TRACE_PATH = "/api/v1/traces"


def debug(message):
    """Append one line to ~/.aws-context/debug.log when AWS_CONTEXT_HOOKS_DEBUG is set, for
    troubleshooting. Never raises."""
    if not os.environ.get("AWS_CONTEXT_HOOKS_DEBUG"):
        return
    try:
        with open(str(CONFIG_DIR / "debug.log"), "a") as handle:
            handle.write("%s %s\n" % (time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), message))
    except OSError:
        pass


def load():
    """The settings, with defaults for any missing key. Never raises."""
    cfg = dict(DEFAULTS)
    try:
        data = json.loads(CONFIG_FILE.read_text())
    except (OSError, ValueError):
        return cfg
    if isinstance(data, dict):
        cfg.update(data)
    return cfg


def parse_arn(arn):
    """(region, account, agent context id) from an agent context ARN, or None."""
    parts = str(arn or "").split(":")
    if len(parts) != 6 or parts[:3] != ["arn", "aws", "context"] or not parts[5].startswith("agent-context/"):
        return None
    graph_id = parts[5][len("agent-context/"):]
    if not parts[3] or not parts[4] or not graph_id:
        return None
    return parts[3], parts[4], graph_id


def endpoint(cfg):
    override = os.environ.get("AWS_CONTEXT_ENDPOINT") or cfg.get("endpoint")
    if override:
        return str(override).rstrip("/")
    parsed = parse_arn(cfg.get("graphArn"))
    return "https://context.%s.api.aws" % parsed[0] if parsed else None


class Result:
    """The outcome of one API call. status is the HTTP status, or None when no answer came."""

    def __init__(self, status=None, error_type="", message="", body=None, timed_out=False):
        self.status = status
        self.error_type = error_type
        self.message = message
        self.body = body
        self.timed_out = timed_out

    @property
    def ok(self):
        return self.status is not None and 200 <= self.status < 300

    @property
    def answered(self):
        return self.status is not None

    @property
    def trace_analysis_disabled(self):
        return self.status == 400 and "trace analysis is disabled" in self.message.lower()

    @property
    def rejected(self):
        """The service judged this request itself, so a resend gets the same answer."""
        # An unknown operation means the route is gone, not that this request is wrong: keep it.
        return (self.status is not None and 400 <= self.status < 500 and self.status not in (401, 403, 408, 429)
                and self.error_type != "UnknownOperationException")


# Config keys that make the AWS CLI get credentials some other way than the credentials file.
INDIRECT_KEYS = ("role_arn", "source_profile", "credential_source", "credential_process", "web_identity_token_file",
                 "sso_session", "sso_start_url", "sso_account_id", "login_session")


def _aws_file(env_name, default):
    return Path(os.environ.get(env_name) or str(Path.home() / ".aws" / default)).expanduser()


def _static_credentials(profile):
    """Keys stored for the profile in the shared credentials file, when nothing in the config file
    sends the CLI elsewhere for that profile. Reading them avoids starting the AWS CLI, which can
    take seconds while a session starts."""
    config = configparser.RawConfigParser()
    try:
        config.read(str(_aws_file("AWS_CONFIG_FILE", "config")))
    except configparser.Error:
        return None
    section = "default" if profile == "default" else "profile " + profile
    if config.has_section(section) and any(config.has_option(section, k) for k in INDIRECT_KEYS):
        return None
    stored = configparser.RawConfigParser()
    try:
        stored.read(str(_aws_file("AWS_SHARED_CREDENTIALS_FILE", "credentials")))
    except configparser.Error:
        return None
    if not stored.has_section(profile) or any(stored.has_option(profile, k) for k in INDIRECT_KEYS):
        return None
    key, secret = stored.get(profile, "aws_access_key_id", fallback=""), stored.get(profile, "aws_secret_access_key", fallback="")
    if not key or not secret:
        return None
    creds = {"AccessKeyId": key, "SecretAccessKey": secret}
    token = stored.get(profile, "aws_session_token", fallback="")
    if token:
        creds["SessionToken"] = token
    return creds


def credentials(profile, timeout):
    """Credentials for the profile, or None. Keys stored in the shared credentials file are read
    directly; anything else (SSO, assume-role, credential-process) is exported by the AWS CLI,
    which resolves it the same way the user's other tools do."""
    if not profile:
        return None
    try:
        static = _static_credentials(str(profile))
    except (OSError, ValueError):
        static = None
    if static:
        return static
    aws = shutil.which("aws")
    if not aws:
        return None
    try:
        out = subprocess.run([aws, "configure", "export-credentials", "--profile", str(profile), "--format", "process"],
                             capture_output=True, text=True, timeout=timeout, check=False)
    except (OSError, subprocess.SubprocessError):
        return None
    if out.returncode != 0:
        return None
    try:
        data = json.loads(out.stdout)
    except ValueError:
        return None
    if not data.get("AccessKeyId") or not data.get("SecretAccessKey"):
        return None
    return data


def _hmac(key, text):
    return hmac.new(key, text.encode("utf-8"), hashlib.sha256).digest()


def sign(method, url, body, creds, region, now=None):
    """SigV4 headers for a request with a JSON body (AWS Signature Version 4)."""
    now = now or datetime.datetime.now(datetime.timezone.utc)
    amz_date = now.strftime("%Y%m%dT%H%M%SZ")
    day = now.strftime("%Y%m%d")
    parts = urllib.parse.urlsplit(url)
    payload_hash = hashlib.sha256(body).hexdigest()
    headers = {"content-type": "application/json", "host": parts.netloc, "x-amz-date": amz_date}
    if creds.get("SessionToken"):
        headers["x-amz-security-token"] = creds["SessionToken"]
    names = sorted(headers)
    canonical = "\n".join([
        method,
        urllib.parse.quote(parts.path or "/", safe="/-_.~"),
        parts.query,
        "".join("%s:%s\n" % (n, headers[n].strip()) for n in names),
        ";".join(names),
        payload_hash,
    ])
    scope = "%s/%s/%s/aws4_request" % (day, region, SIGNING_SERVICE)
    to_sign = "\n".join(["AWS4-HMAC-SHA256", amz_date, scope, hashlib.sha256(canonical.encode("utf-8")).hexdigest()])
    key = _hmac(_hmac(_hmac(_hmac(("AWS4" + creds["SecretAccessKey"]).encode("utf-8"), day), region), SIGNING_SERVICE),
                "aws4_request")
    signature = hmac.new(key, to_sign.encode("utf-8"), hashlib.sha256).hexdigest()
    headers["authorization"] = "AWS4-HMAC-SHA256 Credential=%s/%s, SignedHeaders=%s, Signature=%s" % (
        creds["AccessKeyId"], scope, ";".join(names), signature)
    headers["x-amz-content-sha256"] = payload_hash
    return headers


def user_agent(hook, session_id=None):
    """The User-Agent the hooks send, which CloudTrail records as `userAgent`: the plugin, the
    client, the hook and the Claude Code session."""
    agent = "aws-context-plugin/%s (claude-code; hook/%s" % (PLUGIN_VERSION, hook)
    if isinstance(session_id, str) and re.fullmatch(r"[A-Za-z0-9_-]{1,128}", session_id):
        agent += "; session/" + session_id
    return agent + ")"


def call(cfg, path, payload, timeout, creds=None, agent=None):
    """POST a JSON payload to the AWS Context API and return within `timeout` seconds, however
    slowly the server answers. `{agentContextId}` in `path` becomes the graph's ID. Never raises."""
    deadline = time.monotonic() + timeout
    base = endpoint(cfg)
    parsed = parse_arn(cfg.get("graphArn"))
    if not base or not parsed:
        return Result(message="no graph ARN configured")
    path = path.replace("{agentContextId}", urllib.parse.quote(parsed[2], safe=""))
    creds = creds or credentials(cfg.get("profile"), timeout)
    if not creds:
        return Result(message="no credentials for profile %r" % cfg.get("profile"))
    outcome = []
    worker = threading.Thread(target=lambda: outcome.append(_post(base + path, payload, creds, parsed[0], timeout,
                                                                  agent or user_agent("unknown"))),
                              daemon=True)
    worker.start()
    worker.join(max(0.0, deadline - time.monotonic()))
    return outcome[0] if outcome else Result(message="timed out", timed_out=True)


def _post(url, payload, creds, region, timeout, agent):
    try:
        body = json.dumps(payload).encode("utf-8")
        headers = sign("POST", url, body, creds, region)
        headers["user-agent"] = agent
        request = urllib.request.Request(url, data=body, headers=headers, method="POST")
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read()
            status = response.status
    except urllib.error.HTTPError as err:
        try:
            raw = err.read()
        except (OSError, http.client.HTTPException):
            raw = b""
        error_type = (err.headers.get("x-amzn-ErrorType") or "").split(":")[0]
        if not error_type:
            try:
                envelope = json.loads(raw or b"{}").get("Output") or {}
                error_type = str(envelope.get("__type") or "").split("#")[-1]
            except (ValueError, AttributeError):
                pass
        try:
            message = str(json.loads(raw or b"{}").get("message") or json.loads(raw or b"{}").get("Message") or "")
        except (ValueError, AttributeError):
            message = raw[:500].decode("utf-8", "replace")
        return Result(err.code, error_type, message)
    except (OSError, http.client.HTTPException, ValueError) as err:
        return Result(message=str(err), timed_out="timed out" in str(err).lower())
    try:
        parsed_body = json.loads(raw or b"{}")
    except ValueError:
        return Result(status, body={})
    # A route the service no longer serves can answer 200 with a Coral error envelope, such as
    # {"Output": {"__type": "com.amazon.coral.service#UnknownOperationException"}}.
    envelope = parsed_body.get("Output") if isinstance(parsed_body, dict) else None
    if isinstance(envelope, dict) and envelope.get("__type"):
        error_type = str(envelope["__type"]).split("#")[-1]
        return Result(_envelope_status(error_type), error_type,
                      str(envelope.get("message") or envelope.get("Message") or error_type))
    return Result(status, body=parsed_body)


# Coral error types a 200 envelope can carry that mean the request itself is invalid; any other
# type is treated as a server-side failure, so a trace batch is kept and sent again later.
INVALID_REQUEST_TYPES = ("ValidationException", "SerializationException")
CREDENTIAL_TYPES = ("ExpiredTokenException", "ExpiredToken", "InvalidSignatureException", "UnrecognizedClientException",
                    "InvalidClientTokenId", "IncompleteSignatureException", "AccessDeniedException")


def _envelope_status(error_type):
    if error_type == "UnknownOperationException":
        return 404
    if error_type in CREDENTIAL_TYPES:
        return 403
    if error_type in INVALID_REQUEST_TYPES:
        return 400
    return 502
