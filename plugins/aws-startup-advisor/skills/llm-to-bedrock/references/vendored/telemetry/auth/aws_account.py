"""Resolve an AWS account and prepare event-bound STS proofs.

This module does not send telemetry, start login, save credentials or change
consent. Callers must select account-linked reporting before invoking it.
SDK imports and credential resolution happen only on an explicit method call.
The wire adapter remains separate until the reporting API contract is agreed.
"""

import hashlib
import json
import logging
import re
import sys
from contextvars import ContextVar
from dataclasses import dataclass, field
from functools import wraps
from types import MappingProxyType
from typing import Mapping


STS_REGION = "us-east-1"
STS_HOST = "sts.us-east-1.amazonaws.com"
STS_ENDPOINT = "https://" + STS_HOST + "/"
STS_BODY = b"Action=GetCallerIdentity&Version=2011-06-15"
CONTENT_TYPE = "application/x-www-form-urlencoded; charset=utf-8"
AUDIENCE_HEADER = "x-startup-advisor-audience"
PAYLOAD_HASH_HEADER = "x-startup-advisor-event-sha256"
MAX_PAYLOAD_BYTES = 65_536

_ACCOUNT_ID = re.compile(r"[0-9]{12}\Z")
_IAM_ARN = re.compile(r"arn:aws:(?:iam|sts)::([0-9]{12}):[^\r\n]+\Z")
_AUDIENCE = re.compile(r"startup-advisor:[A-Za-z0-9][A-Za-z0-9._-]{0,127}:report:v1\Z")
_REQUIRED_SIGNED_HEADERS = frozenset(
    ("host", "content-type", "x-amz-date", AUDIENCE_HEADER, PAYLOAD_HASH_HEADER)
)
_ALLOWED_HEADERS = _REQUIRED_SIGNED_HEADERS | {"authorization", "x-amz-security-token"}
_IN_SDK_OPERATION = ContextVar("startup_advisor_account_operation", default=False)
_ERROR_STATUS = {
    "ACCOUNT_CHANGED": "SETUP_REQUIRED",
    "ACCOUNT_REPORTING_REQUIRED": "SETUP_REQUIRED",
    "ACCOUNT_SELECTION_REQUIRED": "SETUP_REQUIRED",
    "INVALID_ACCOUNT": "SETUP_REQUIRED",
    "INVALID_PROFILE": "SETUP_REQUIRED",
    "NOTICE_VERSION_REQUIRED": "SETUP_REQUIRED",
    "CREDENTIALS_UNAVAILABLE": "SIGN_IN_REQUIRED",
    "SIGN_IN_REQUIRED": "SIGN_IN_REQUIRED",
    "AMBIGUOUS_PROFILE": "ERROR",
    "IDENTITY_RESPONSE_INVALID": "ERROR",
    "IDENTITY_UNAVAILABLE": "ERROR",
    "INTERNAL_ERROR": "ERROR",
    "INVALID_AUDIENCE": "ERROR",
    "PAYLOAD_ALREADY_SIGNED": "ERROR",
    "PAYLOAD_INVALID": "ERROR",
    "PAYLOAD_TOO_LARGE": "ERROR",
    "PROOF_INVALID": "ERROR",
    "PROOF_UNAVAILABLE": "ERROR",
    "PYTHON_VERSION_UNSUPPORTED": "ERROR",
    "SDK_UNAVAILABLE": "ERROR",
    "UNSUPPORTED_PARTITION": "ERROR",
}


class _SensitiveSdkLogFilter(logging.Filter):
    def filter(self, record):
        return not _IN_SDK_OPERATION.get()


_SDK_LOG_FILTER = _SensitiveSdkLogFilter()


def _install_sdk_log_filter():
    # Botocore DEBUG includes request headers, session tokens and response
    # bodies. Filter only this operation's execution context, without changing
    # global log levels or silencing unrelated callers/threads.
    names = {
        "botocore.auth", "botocore.endpoint", "botocore.parsers",
        "botocore.credentials", "botocore.utils", "urllib3.connectionpool",
    }
    names.update(
        name for name in list(logging.Logger.manager.loggerDict)
        if name.startswith(("botocore.", "urllib3."))
    )
    for name in names:
        logger = logging.getLogger(name)
        if _SDK_LOG_FILTER not in logger.filters:
            logger.addFilter(_SDK_LOG_FILTER)


def _sdk_operation(function):
    @wraps(function)
    def wrapped(*args, **kwargs):
        token = _IN_SDK_OPERATION.set(True)
        try:
            return function(*args, **kwargs)
        finally:
            _IN_SDK_OPERATION.reset(token)
    return wrapped


class AccountReportingError(Exception):
    """A bounded error code safe for a UI or log, without raw SDK details."""

    def __init__(self, code):
        self.code = code if isinstance(code, str) and code in _ERROR_STATUS else "INTERNAL_ERROR"
        super().__init__(self.code)

    def as_result(self):
        """A stable, identity-free result for the sharing/CLI adapters."""
        return {"status": _ERROR_STATUS[self.code], "reasonCode": self.code}


@dataclass(frozen=True)
class AccountIdentity:
    """Account selected during setup; this is not a person or consent record."""

    account_id: str
    partition: str = "aws"

    def __post_init__(self):
        if not isinstance(self.account_id, str) or not _ACCOUNT_ID.fullmatch(self.account_id):
            raise AccountReportingError("INVALID_ACCOUNT")
        # This draft implements the commercial STS target only. Other
        # partitions require matching backend targets before being supported.
        if self.partition != "aws":
            raise AccountReportingError("UNSUPPORTED_PARTITION")


@dataclass(frozen=True)
class PreparedReport:
    """Transport-only values. repr deliberately excludes payload and proof."""

    account: AccountIdentity
    payload: bytes = field(repr=False)
    headers: Mapping[str, str] = field(repr=False)

    def __post_init__(self):
        # Prevent a caller changing the signed headers after construction.
        object.__setattr__(self, "headers", MappingProxyType(dict(self.headers)))

    def __repr__(self):
        return "PreparedReport(<redacted>)"

    def request_body(self):
        """Return transport bytes, including sensitive proof headers.

        These bytes must go directly to the reporting transport, never stdout,
        a log, a file, or model-visible tool output.
        """
        body = json.loads(self.payload)
        body["awsIdentityProof"] = {"version": 1, "headers": dict(self.headers)}
        encoded = json.dumps(
            body, ensure_ascii=False, allow_nan=False, separators=(",", ":")
        ).encode("utf-8")
        if len(encoded) > MAX_PAYLOAD_BYTES:
            raise AccountReportingError("PAYLOAD_TOO_LARGE")
        return encoded


def _load_sdk():
    if sys.version_info < (3, 10):
        raise AccountReportingError("PYTHON_VERSION_UNSUPPORTED")
    try:
        import rfc8785
        from botocore.auth import SigV4Auth
        from botocore.awsrequest import AWSRequest
        from botocore.config import Config
        from botocore.session import Session
    except ImportError:
        raise AccountReportingError("SDK_UNAVAILABLE") from None
    _install_sdk_log_filter()
    return rfc8785, SigV4Auth, AWSRequest, Config, Session


def _valid_secret(value):
    return (
        isinstance(value, str)
        and bool(value)
        and not any(ord(char) < 32 or ord(char) == 127 for char in value)
    )


def _sign_in_required(prompt):
    # The caller owns interactive sign-in. Never let an SDK MFA prompt consume
    # a hook's stdin or block waiting for a person.
    raise AccountReportingError("SIGN_IN_REQUIRED")


class AwsAccountReporter:
    """Use the SDK provider chain without creating a credential store.

    audience is explicit: there is no default production reporting audience.
    setup() performs one STS identity lookup. prepare_report() freezes fresh
    credentials for each proof without an identity lookup or telemetry request.
    An SDK provider may contact AWS or run credential_process while refreshing.
    """

    def __init__(self, audience, profile_name=None, session=None):
        if not isinstance(audience, str) or not _AUDIENCE.fullmatch(audience):
            raise AccountReportingError("INVALID_AUDIENCE")
        if profile_name is not None and (
            not isinstance(profile_name, str) or not profile_name.strip()
        ):
            raise AccountReportingError("INVALID_PROFILE")
        if session is not None and profile_name is not None:
            raise AccountReportingError("AMBIGUOUS_PROFILE")
        self._audience = audience
        self._profile_name = profile_name
        self._session = session
        self._sdk = None
        self._setup_identity = None

    def __repr__(self):
        return "AwsAccountReporter(<redacted>)"

    def _runtime(self):
        if self._sdk is None:
            self._sdk = _load_sdk()
        if self._session is None:
            try:
                self._session = self._sdk[4](profile=self._profile_name)
                assume_role = self._session.get_component(
                    "credential_provider"
                ).get_provider("assume-role")
                if assume_role is not None:
                    # Botocore constructs this provider with getpass.getpass.
                    # Preserve its chain/cache/refresh logic, replacing only
                    # the interactive callback. Covered against the pinned SDK.
                    assume_role._prompter = _sign_in_required
            except Exception:
                raise AccountReportingError("CREDENTIALS_UNAVAILABLE") from None
        return self._sdk

    def _credentials(self):
        self._runtime()
        try:
            provider_credentials = self._session.get_credentials()
            if provider_credentials is None:
                raise AccountReportingError("CREDENTIALS_UNAVAILABLE")
            # Resolve access key, secret and token together after any refresh.
            credentials = provider_credentials.get_frozen_credentials()
            if not _valid_secret(credentials.access_key) or not _valid_secret(credentials.secret_key):
                raise AccountReportingError("CREDENTIALS_UNAVAILABLE")
            if credentials.token is not None and not _valid_secret(credentials.token):
                raise AccountReportingError("CREDENTIALS_UNAVAILABLE")
            return credentials
        except AccountReportingError:
            raise
        except Exception:
            raise AccountReportingError("CREDENTIALS_UNAVAILABLE") from None

    @_sdk_operation
    def setup(self):
        """Query STS for the selected profile's account, returning no secrets.

        Explicit endpoint/region/TLS override ambient STS endpoint settings.
        The STS call uses exactly the credential snapshot resolved for setup.
        SDK-managed providers may themselves contact their credential source.
        """
        # A failed repeat setup must not leave an earlier identity as current.
        self._setup_identity = None
        credentials = self._credentials()
        config_type = self._runtime()[3]
        client = None
        try:
            client = self._session.create_client(
                "sts",
                region_name=STS_REGION,
                endpoint_url=STS_ENDPOINT,
                verify=True,
                aws_access_key_id=credentials.access_key,
                aws_secret_access_key=credentials.secret_key,
                aws_session_token=credentials.token,
                config=config_type(
                    connect_timeout=3,
                    read_timeout=3,
                    retries={"total_max_attempts": 1},
                    signature_version="v4",
                ),
            )
            response = client.get_caller_identity()
            account_id = response.get("Account")
            arn = response.get("Arn")
            match = _IAM_ARN.fullmatch(arn) if isinstance(arn, str) else None
            if not match or match.group(1) != account_id:
                raise AccountReportingError("IDENTITY_RESPONSE_INVALID")
            identity = AccountIdentity(account_id)
        except AccountReportingError:
            raise
        except Exception:
            raise AccountReportingError("IDENTITY_UNAVAILABLE") from None
        finally:
            if client is not None:
                try:
                    client.close()
                except Exception:
                    pass
        self._setup_identity = identity
        return identity

    @_sdk_operation
    def prepare_report(self, payload, selected_account):
        """Canonicalize one payload and sign its hash for the selected account.

        selected_account must come from the caller's account-choice state, not
        a fresh implicit account lookup. It remains unchanged when credentials
        refresh; the reporting API must compare it with the STS-verified account.
        This allows separate hook processes to reuse T02's saved selection.
        """
        if not isinstance(selected_account, AccountIdentity):
            raise AccountReportingError("ACCOUNT_SELECTION_REQUIRED")
        if self._setup_identity is not None and selected_account != self._setup_identity:
            raise AccountReportingError("ACCOUNT_CHANGED")
        if not isinstance(payload, dict):
            raise AccountReportingError("PAYLOAD_INVALID")
        if "awsIdentityProof" in payload:
            raise AccountReportingError("PAYLOAD_ALREADY_SIGNED")
        if {"identity", "eventId", "receivedAt", "awsProfile"} & payload.keys():
            raise AccountReportingError("PAYLOAD_INVALID")
        if payload.get("reportingMode") != "AWS_ACCOUNT":
            raise AccountReportingError("ACCOUNT_REPORTING_REQUIRED")
        if payload.get("expectedAwsAccountId") != selected_account.account_id:
            raise AccountReportingError("ACCOUNT_CHANGED")
        notice_version = payload.get("noticeVersion")
        if not (
            type(notice_version) is int and notice_version > 0
            or isinstance(notice_version, str) and notice_version.strip()
        ):
            raise AccountReportingError("NOTICE_VERSION_REQUIRED")
        sdk = self._runtime()
        try:
            encoded = sdk[0].dumps(payload)
        except Exception:
            raise AccountReportingError("PAYLOAD_INVALID") from None
        if len(encoded) > MAX_PAYLOAD_BYTES:
            raise AccountReportingError("PAYLOAD_TOO_LARGE")

        credentials = self._credentials()
        try:
            request = sdk[2](
                method="POST",
                url=STS_ENDPOINT,
                data=STS_BODY,
                headers={
                    "Host": STS_HOST,
                    "Content-Type": CONTENT_TYPE,
                    AUDIENCE_HEADER: self._audience,
                    PAYLOAD_HASH_HEADER: hashlib.sha256(encoded).hexdigest(),
                },
            )
            sdk[1](credentials, "sts", STS_REGION).add_auth(request)
            headers = {name.lower(): str(value) for name, value in request.headers.items()}
            if set(headers) - _ALLOWED_HEADERS:
                raise AccountReportingError("PROOF_INVALID")
            signed_headers = (
                headers["authorization"]
                .split("SignedHeaders=", 1)[1]
                .split(",", 1)[0]
                .split(";")
            )
            required = _REQUIRED_SIGNED_HEADERS
            if credentials.token is not None:
                required = required | {"x-amz-security-token"}
            if (
                not required.issubset(signed_headers)
                or signed_headers != sorted(set(signed_headers))
                or set(signed_headers) != set(headers) - {"authorization"}
            ):
                raise AccountReportingError("PROOF_INVALID")
        except AccountReportingError:
            raise
        except Exception:
            raise AccountReportingError("PROOF_UNAVAILABLE") from None
        result = PreparedReport(selected_account, encoded, headers)
        result.request_body()  # Bound the complete request, including its proof.
        return result
