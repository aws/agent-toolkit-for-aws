"""Account-reporting component tests using synthetic credentials and no AWS I/O."""

import builtins
import getpass
import hashlib
import hmac
import importlib.util
import json
import logging
import sys
import threading
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock

import pytest
from conftest import TELEMETRY

pytest.importorskip("botocore")
pytest.importorskip("rfc8785")

from botocore.credentials import Credentials, RefreshableCredentials
from botocore.httpsession import URLLib3Session
from botocore.session import Session
from botocore.stub import Stubber

_SPEC = importlib.util.spec_from_file_location(
    "telemetry_account_reporting", TELEMETRY / "auth/aws_account.py"
)
reporting = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = reporting
_SPEC.loader.exec_module(reporting)

ACCOUNT = "123456789012"
OTHER_ACCOUNT = "210987654321"
ACCESS_KEY = "synthetic-access-key"
SECRET_KEY = "synthetic-secret-never-log"
SESSION_TOKEN = "synthetic-session-token-never-log"
AUDIENCE = "startup-advisor:test:report:v1"


@pytest.fixture(autouse=True)
def isolated_aws_environment(home, monkeypatch):
    """Neither a developer's credential provider nor AWS may be reached."""
    import os

    for name in tuple(os.environ):
        if name.startswith("AWS_"):
            monkeypatch.delenv(name)
    monkeypatch.setenv("AWS_CONFIG_FILE", str(home / "aws-config"))
    monkeypatch.setenv("AWS_SHARED_CREDENTIALS_FILE", str(home / "aws-credentials"))
    monkeypatch.setenv("AWS_EC2_METADATA_DISABLED", "true")

    def reject_network(*args, **kwargs):
        pytest.fail("an account-reporting unit test attempted an AWS HTTP request")

    monkeypatch.setattr(URLLib3Session, "send", reject_network)


@pytest.fixture
def sdk_session():
    session = Session()
    session.set_credentials(ACCESS_KEY, SECRET_KEY, SESSION_TOKEN)
    return session


@pytest.fixture
def selected_account():
    return reporting.AccountIdentity(ACCOUNT)


def report_payload(values=None):
    return {
        "reportingMode": "AWS_ACCOUNT",
        "expectedAwsAccountId": ACCOUNT,
        "noticeVersion": "test-notice-v1",
        **(values or {}),
    }


def reporter_for(session):
    return reporting.AwsAccountReporter(AUDIENCE, session=session)


def synthetic_sts_client(session):
    return session.create_client(
        "sts",
        region_name="us-east-1",
        endpoint_url="https://sts.us-east-1.amazonaws.com/",
        aws_access_key_id=ACCESS_KEY,
        aws_secret_access_key=SECRET_KEY,
        aws_session_token=SESSION_TOKEN,
    )


def identity_response(account=ACCOUNT, arn_account=None):
    return {
        "Account": account,
        "Arn": "arn:aws:sts::%s:assumed-role/test-role/test-session"
        % (arn_account or account),
        "UserId": "synthetic-principal:test-session",
    }


def independent_signature(headers, secret_key=SECRET_KEY):
    """Recompute SigV4 with hashlib/hmac, independently of Botocore's signer."""
    authorization = headers["authorization"]
    credential, signed, _ = authorization.removeprefix(
        "AWS4-HMAC-SHA256 "
    ).split(", ")
    _, scope = credential.removeprefix("Credential=").split("/", 1)
    date, region, service, terminator = scope.split("/")
    assert terminator == "aws4_request"
    signed_headers = signed.removeprefix("SignedHeaders=")
    names = signed_headers.split(";")
    canonical_headers = "".join(
        "%s:%s\n" % (name, " ".join(headers[name].split())) for name in names
    )
    canonical_request = "\n".join(
        (
            "POST",
            "/",
            "",
            canonical_headers,
            signed_headers,
            hashlib.sha256(
                b"Action=GetCallerIdentity&Version=2011-06-15"
            ).hexdigest(),
        )
    )
    string_to_sign = "\n".join(
        (
            "AWS4-HMAC-SHA256",
            headers["x-amz-date"],
            scope,
            hashlib.sha256(canonical_request.encode()).hexdigest(),
        )
    )
    key = ("AWS4" + secret_key).encode()
    for component in (date, region, service, terminator):
        key = hmac.new(key, component.encode(), hashlib.sha256).digest()
    return hmac.new(key, string_to_sign.encode(), hashlib.sha256).hexdigest()


def signature_from(headers):
    return headers["authorization"].split("Signature=", 1)[1]


def test_environment_provider_is_used_without_sts_or_state_writes(
    home, monkeypatch, selected_account
):
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", ACCESS_KEY)
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", SECRET_KEY)
    monkeypatch.setenv("AWS_SESSION_TOKEN", SESSION_TOKEN)
    reporter = reporting.AwsAccountReporter(AUDIENCE)

    prepared = reporter.prepare_report(report_payload({"event": "test"}), selected_account)

    assert reporter._session.get_credentials().method == "env"
    assert "Credential=%s/" % ACCESS_KEY in prepared.headers["authorization"]
    assert prepared.headers["x-amz-security-token"] == SESSION_TOKEN
    assert not (home / ".aws-startup-advisor").exists()
    assert not (home / "aws-credentials").exists()


def test_explicit_profile_uses_shared_credentials_instead_of_environment(
    home, monkeypatch, selected_account
):
    credentials_file = home / "aws-credentials"
    original = (
        "[selected]\n"
        "aws_access_key_id = profile-access-key\n"
        "aws_secret_access_key = profile-secret\n"
        "aws_session_token = profile-token\n"
    )
    credentials_file.write_text(original)
    (home / "aws-config").write_text(
        "[profile selected]\nregion = eu-west-1\n"
    )
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "other-environment-access")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "other-environment-secret")
    reporter = reporting.AwsAccountReporter(AUDIENCE, profile_name="selected")

    prepared = reporter.prepare_report(report_payload({"event": "test"}), selected_account)

    assert reporter._session.get_credentials().method == "shared-credentials-file"
    assert "Credential=profile-access-key/" in prepared.headers["authorization"]
    assert prepared.headers["x-amz-security-token"] == "profile-token"
    assert "/us-east-1/sts/aws4_request" in prepared.headers["authorization"]
    assert credentials_file.read_text() == original


def test_profile_with_blank_session_token_can_sign_and_resolve_identity(
    home, monkeypatch, sdk_session, selected_account
):
    (home / "aws-config").write_text("[profile selected]\nregion = eu-west-1\n")
    credentials_file = home / "aws-credentials"
    original = (
        "[selected]\n"
        "aws_access_key_id = %s\n"
        "aws_secret_access_key = %s\n"
        "aws_session_token = \n" % (ACCESS_KEY, SECRET_KEY)
    )
    credentials_file.write_text(original)
    reporter = reporting.AwsAccountReporter(AUDIENCE, profile_name="selected")

    prepared = reporter.prepare_report(
        report_payload({"event": "test"}), selected_account
    )

    assert reporter._session.get_credentials().method == "shared-credentials-file"
    assert reporter._session.get_credentials().get_frozen_credentials().token == ""
    assert "x-amz-security-token" not in prepared.headers
    signed_headers = prepared.headers["authorization"].split(
        "SignedHeaders=", 1
    )[1].split(",", 1)[0].split(";")
    assert "x-amz-security-token" not in signed_headers
    assert independent_signature(prepared.headers) == signature_from(prepared.headers)

    client = synthetic_sts_client(sdk_session)
    create_client = Mock(return_value=client)
    monkeypatch.setattr(reporter._session, "create_client", create_client)
    with Stubber(client) as stubber:
        stubber.add_response("get_caller_identity", identity_response(), {})
        assert reporter.setup() == selected_account
        stubber.assert_no_pending_responses()

    create_client.assert_called_once()
    args, kwargs = create_client.call_args
    assert args == ("sts",)
    assert kwargs["endpoint_url"] == "https://sts.us-east-1.amazonaws.com/"
    assert kwargs["region_name"] == "us-east-1"
    assert kwargs["verify"] is True
    assert kwargs["aws_access_key_id"] == ACCESS_KEY
    assert kwargs["aws_secret_access_key"] == SECRET_KEY
    assert kwargs["aws_session_token"] is None
    assert credentials_file.read_text() == original


def test_missing_credentials_fail_without_creating_state(home, selected_account):
    reporter = reporting.AwsAccountReporter(AUDIENCE)

    with pytest.raises(reporting.AccountReportingError) as error:
        reporter.prepare_report(report_payload({"event": "test"}), selected_account)

    assert error.value.code == "CREDENTIALS_UNAVAILABLE"
    assert not (home / ".aws-startup-advisor").exists()


def test_setup_uses_one_frozen_snapshot_and_fixed_tls_sts_target(
    sdk_session, monkeypatch
):
    client = synthetic_sts_client(sdk_session)
    create_client = Mock(return_value=client)
    monkeypatch.setattr(sdk_session, "create_client", create_client)
    close = Mock(wraps=client.close)
    monkeypatch.setattr(client, "close", close)
    reporter = reporter_for(sdk_session)

    with Stubber(client) as stubber:
        stubber.add_response("get_caller_identity", identity_response(), {})
        identity = reporter.setup()
        stubber.assert_no_pending_responses()

    assert identity == reporting.AccountIdentity(ACCOUNT)
    assert vars(identity) == {"account_id": ACCOUNT, "partition": "aws"}
    create_client.assert_called_once()
    args, kwargs = create_client.call_args
    assert args == ("sts",)
    assert kwargs["endpoint_url"] == "https://sts.us-east-1.amazonaws.com/"
    assert kwargs["region_name"] == "us-east-1"
    assert kwargs["verify"] is True
    assert kwargs["aws_access_key_id"] == ACCESS_KEY
    assert kwargs["aws_secret_access_key"] == SECRET_KEY
    assert kwargs["aws_session_token"] == SESSION_TOKEN
    assert kwargs["config"].connect_timeout == 3
    assert kwargs["config"].read_timeout == 3
    assert kwargs["config"].retries == {"total_max_attempts": 1}
    close.assert_called_once()


def test_setup_rejects_an_arn_from_another_account(sdk_session, monkeypatch):
    client = synthetic_sts_client(sdk_session)
    monkeypatch.setattr(sdk_session, "create_client", Mock(return_value=client))
    reporter = reporter_for(sdk_session)

    with Stubber(client) as stubber:
        stubber.add_response(
            "get_caller_identity", identity_response(arn_account=OTHER_ACCOUNT), {}
        )
        with pytest.raises(reporting.AccountReportingError) as error:
            reporter.setup()

    assert error.value.code == "IDENTITY_RESPONSE_INVALID"
    assert reporter._setup_identity is None


@pytest.mark.parametrize(
    "service_code,expected_code,expected_status",
    [
        ("ExpiredToken", "SIGN_IN_REQUIRED", "SIGN_IN_REQUIRED"),
        ("ExpiredTokenException", "SIGN_IN_REQUIRED", "SIGN_IN_REQUIRED"),
        ("AccessDenied", "IDENTITY_UNAVAILABLE", "ERROR"),
        ("InternalFailure", "IDENTITY_UNAVAILABLE", "ERROR"),
    ],
)
def test_setup_failure_exposes_only_bounded_error_code(
    sdk_session, monkeypatch, service_code, expected_code, expected_status
):
    client = synthetic_sts_client(sdk_session)
    monkeypatch.setattr(sdk_session, "create_client", Mock(return_value=client))

    with Stubber(client) as stubber:
        stubber.add_client_error(
            "get_caller_identity",
            service_error_code=service_code,
            service_message=SECRET_KEY + SESSION_TOKEN,
        )
        with pytest.raises(reporting.AccountReportingError) as error:
            reporter_for(sdk_session).setup()

    assert str(error.value) == expected_code
    assert error.value.as_result() == {
        "status": expected_status, "reasonCode": expected_code
    }
    assert SECRET_KEY not in repr(error.value)
    assert SESSION_TOKEN not in repr(error.value)
    assert error.value.__suppress_context__


def test_setup_network_failure_is_not_misreported_as_expired_login(
    sdk_session, monkeypatch
):
    client = synthetic_sts_client(sdk_session)
    monkeypatch.setattr(sdk_session, "create_client", Mock(return_value=client))
    monkeypatch.setattr(
        client, "get_caller_identity", Mock(side_effect=TimeoutError(SESSION_TOKEN))
    )
    reporter = reporter_for(sdk_session)

    with pytest.raises(reporting.AccountReportingError) as error:
        reporter.setup()

    assert error.value.as_result() == {
        "status": "ERROR", "reasonCode": "IDENTITY_UNAVAILABLE"
    }
    assert SESSION_TOKEN not in repr(error.value)
    assert reporter._setup_identity is None


def test_debug_sdk_request_and_response_logs_do_not_expose_secrets(
    sdk_session, monkeypatch, selected_account, caplog, capsys
):
    from botocore.parsers import QueryParser

    client = synthetic_sts_client(sdk_session)
    shape = client.meta.service_model.operation_model("GetCallerIdentity").output_shape
    response_xml = (
        "<GetCallerIdentityResponse>"
        "<GetCallerIdentityResult>"
        "<Arn>arn:aws:iam::%s:user/test</Arn>"
        "<UserId>%s</UserId>"
        "<Account>%s</Account>"
        "</GetCallerIdentityResult>"
        "</GetCallerIdentityResponse>"
    ) % (ACCOUNT, SESSION_TOKEN, ACCOUNT)

    def parse_sensitive_response():
        # QueryParser logs the raw response body at DEBUG level.
        return QueryParser().parse(
            {"body": response_xml.encode(), "status_code": 200, "headers": {}},
            shape,
        )

    monkeypatch.setattr(client, "get_caller_identity", parse_sensitive_response)
    monkeypatch.setattr(sdk_session, "create_client", Mock(return_value=client))
    reporter = reporter_for(sdk_session)

    with caplog.at_level(logging.DEBUG):
        assert reporter.setup() == selected_account
        prepared = reporter.prepare_report(
            report_payload({"private": "sensitive-report-value"}), selected_account
        )
        assert prepared.headers["x-amz-security-token"] == SESSION_TOKEN
        assert caplog.records == []
        logging.getLogger("botocore.auth").debug("outside-auth-operation")
        logging.getLogger("botocore.parsers").debug("outside-parser-operation")

    assert "outside-auth-operation" in caplog.text
    assert "outside-parser-operation" in caplog.text
    output = capsys.readouterr()
    for secret in (SECRET_KEY, SESSION_TOKEN, "sensitive-report-value"):
        assert secret not in caplog.text + output.out + output.err


def test_provider_warning_and_exception_are_redacted_without_silencing_other_callers(
    sdk_session, monkeypatch, selected_account, caplog, capsys
):
    provider_logger = logging.getLogger("botocore.credentials")

    def failing_provider():
        # The separate caller is in another execution context while the helper
        # is active; it must retain its ordinary logging behavior.
        other_caller = threading.Thread(
            target=lambda: provider_logger.warning("concurrent-sdk-caller")
        )
        other_caller.start()
        other_caller.join(timeout=2)
        assert not other_caller.is_alive()
        try:
            raise RuntimeError(SECRET_KEY)
        except RuntimeError:
            provider_logger.warning(
                "provider could not refresh %s", SESSION_TOKEN, exc_info=True
            )
            raise

    monkeypatch.setattr(sdk_session, "get_credentials", failing_provider)
    with caplog.at_level(logging.DEBUG, logger="botocore.credentials"):
        with pytest.raises(reporting.AccountReportingError) as error:
            reporter_for(sdk_session).prepare_report(
                report_payload({"event": "test"}), selected_account
            )
        provider_logger.warning("outside-provider-operation")
        assert provider_logger.level == logging.DEBUG

    assert str(error.value) == "CREDENTIALS_UNAVAILABLE"
    assert "concurrent-sdk-caller" in caplog.text
    assert "outside-provider-operation" in caplog.text
    output = capsys.readouterr()
    for secret in (SECRET_KEY, SESSION_TOKEN):
        assert secret not in caplog.text + output.out + output.err


def test_mfa_profile_requires_explicit_sign_in_without_prompt_or_network(
    home, monkeypatch, selected_account
):
    (home / "aws-config").write_text(
        "[profile requires-mfa]\n"
        "role_arn = arn:aws:iam::123456789012:role/test-role\n"
        "source_profile = source\n"
        "mfa_serial = arn:aws:iam::123456789012:mfa/test-user\n"
        "region = us-east-1\n"
    )
    (home / "aws-credentials").write_text(
        "[source]\n"
        "aws_access_key_id = %s\n"
        "aws_secret_access_key = %s\n"
        "aws_session_token = %s\n" % (ACCESS_KEY, SECRET_KEY, SESSION_TOKEN)
    )
    prompt = Mock(side_effect=AssertionError("MFA attempted to consume stdin"))
    monkeypatch.setattr(getpass, "getpass", prompt)
    reporter = reporting.AwsAccountReporter(AUDIENCE, profile_name="requires-mfa")

    with pytest.raises(reporting.AccountReportingError) as error:
        reporter.prepare_report(report_payload({"event": "test"}), selected_account)

    assert error.value.code == "SIGN_IN_REQUIRED"
    prompt.assert_not_called()
    assert not (home / ".aws-startup-advisor").exists()


def test_repaired_config_retry_still_blocks_mfa_prompt(
    home, monkeypatch, selected_account
):
    from botocore.credentials import AssumeRoleProvider

    config_file = home / "aws-config"
    config_file.write_text("[profile requires-mfa\n")
    (home / "aws-credentials").write_text(
        "[source]\n"
        "aws_access_key_id = %s\n"
        "aws_secret_access_key = %s\n"
        "aws_session_token = %s\n" % (ACCESS_KEY, SECRET_KEY, SESSION_TOKEN)
    )
    prompt = Mock(side_effect=AssertionError("MFA attempted to consume stdin"))
    monkeypatch.setattr(getpass, "getpass", prompt)
    original_provider_init = AssumeRoleProvider.__init__

    def tracked_provider_init(self, *args, **kwargs):
        # Botocore captures getpass in its constructor's default arguments at
        # import time. Replace that callback as well so a regression cannot
        # actually read stdin, and the test can observe an attempted prompt.
        kwargs["prompter"] = prompt
        original_provider_init(self, *args, **kwargs)

    monkeypatch.setattr(AssumeRoleProvider, "__init__", tracked_provider_init)
    reporter = reporting.AwsAccountReporter(AUDIENCE, profile_name="requires-mfa")

    with pytest.raises(reporting.AccountReportingError) as error:
        reporter.prepare_report(report_payload({"event": "test"}), selected_account)

    assert error.value.code == "CREDENTIALS_UNAVAILABLE"
    failed_session = reporter._session
    prompt.assert_not_called()
    config_file.write_text(
        "[profile requires-mfa]\n"
        "role_arn = arn:aws:iam::123456789012:role/test-role\n"
        "source_profile = source\n"
        "mfa_serial = arn:aws:iam::123456789012:mfa/test-user\n"
        "region = us-east-1\n"
    )

    with pytest.raises(reporting.AccountReportingError) as error:
        reporter.prepare_report(report_payload({"event": "test"}), selected_account)

    prompt.assert_not_called()
    assert error.value.code == "SIGN_IN_REQUIRED"
    assert failed_session is None
    assert reporter._session is not None


def test_failed_repeat_setup_clears_previous_identity(sdk_session, monkeypatch):
    client = synthetic_sts_client(sdk_session)
    monkeypatch.setattr(sdk_session, "create_client", Mock(return_value=client))
    reporter = reporter_for(sdk_session)
    with Stubber(client) as stubber:
        stubber.add_response("get_caller_identity", identity_response(), {})
        reporter.setup()
    monkeypatch.setattr(
        sdk_session, "get_credentials", Mock(side_effect=RuntimeError(SECRET_KEY))
    )

    with pytest.raises(reporting.AccountReportingError) as error:
        reporter.setup()

    assert error.value.code == "CREDENTIALS_UNAVAILABLE"
    assert reporter._setup_identity is None


def test_setup_account_mismatch_blocks_report_before_credentials(
    sdk_session, monkeypatch
):
    client = synthetic_sts_client(sdk_session)
    monkeypatch.setattr(sdk_session, "create_client", Mock(return_value=client))
    reporter = reporter_for(sdk_session)
    with Stubber(client) as stubber:
        stubber.add_response("get_caller_identity", identity_response(), {})
        reporter.setup()
    get_credentials = Mock(side_effect=AssertionError("credentials were read"))
    monkeypatch.setattr(sdk_session, "get_credentials", get_credentials)

    with pytest.raises(reporting.AccountReportingError) as error:
        reporter.prepare_report(
            report_payload({"event": "test"}), reporting.AccountIdentity(OTHER_ACCOUNT)
        )

    assert error.value.code == "ACCOUNT_CHANGED"
    get_credentials.assert_not_called()


def test_each_report_freezes_refreshed_credentials_without_an_sts_call(
    sdk_session, monkeypatch, selected_account
):
    clock = [datetime(2026, 10, 28, tzinfo=timezone.utc)]
    refresh = Mock(
        return_value={
            "access_key": "refreshed-access-key",
            "secret_key": "refreshed-secret",
            "token": "refreshed-token",
            "expiry_time": (clock[0] + timedelta(hours=3)).isoformat(),
        }
    )
    credentials = RefreshableCredentials(
        access_key=ACCESS_KEY,
        secret_key=SECRET_KEY,
        token=SESSION_TOKEN,
        expiry_time=clock[0] + timedelta(hours=1),
        refresh_using=refresh,
        method="synthetic-refresh-provider",
        time_fetcher=lambda: clock[0],
    )
    snapshots = Mock(wraps=credentials.get_frozen_credentials)
    monkeypatch.setattr(credentials, "get_frozen_credentials", snapshots)
    monkeypatch.setattr(sdk_session, "get_credentials", lambda: credentials)
    create_client = Mock(side_effect=AssertionError("per-report STS request"))
    monkeypatch.setattr(sdk_session, "create_client", create_client)
    reporter = reporter_for(sdk_session)

    first = reporter.prepare_report(report_payload({"event": "first"}), selected_account)
    clock[0] += timedelta(hours=2)
    second = reporter.prepare_report(report_payload({"event": "second"}), selected_account)

    assert "Credential=%s/" % ACCESS_KEY in first.headers["authorization"]
    assert first.headers["x-amz-security-token"] == SESSION_TOKEN
    assert "Credential=refreshed-access-key/" in second.headers["authorization"]
    assert second.headers["x-amz-security-token"] == "refreshed-token"
    assert first.account == second.account == selected_account
    assert independent_signature(first.headers) == signature_from(first.headers)
    assert independent_signature(second.headers, "refreshed-secret") == (
        signature_from(second.headers)
    )
    assert snapshots.call_count == 2
    refresh.assert_called_once()
    create_client.assert_not_called()


def test_rfc8785_float_encoding_matches_fixed_expected_bytes(
    sdk_session, selected_account
):
    prepared = reporter_for(sdk_session).prepare_report(
        report_payload({
            "tiny": 1e-27,
            "negativeZero": -0.0,
            "fraction": 4.5,
            "exponent": 1e30,
            "decimal": 1.0,
        }),
        selected_account,
    )

    assert prepared.payload == (
        b'{"decimal":1,"expectedAwsAccountId":"123456789012",'
        b'"exponent":1e+30,"fraction":4.5,"negativeZero":0,'
        b'"noticeVersion":"test-notice-v1","reportingMode":"AWS_ACCOUNT",'
        b'"tiny":1e-27}'
    )


def test_rfc8785_sorts_keys_by_utf16_not_python_codepoint(
    sdk_session, selected_account
):
    prepared = reporter_for(sdk_session).prepare_report(
        report_payload({"\ufffd": 4, "\U0001f600": 3, "\u20ac": 2, "a": 1}),
        selected_account,
    )

    assert prepared.payload == (
        '{"a":1,"expectedAwsAccountId":"123456789012",'
        '"noticeVersion":"test-notice-v1","reportingMode":"AWS_ACCOUNT",'
        '"€":2,"😀":3,"�":4}'
    ).encode("utf-8")


@pytest.mark.parametrize(
    "payload",
    [
        [],
        {"number": float("nan")},
        {"number": float("inf")},
        {"number": -float("inf")},
        {"number": 2**53},
        {"number": -(2**53)},
        {"text": "\ud800"},
        {1: "non-string key"},
        {"value": b"not-json"},
    ],
)
def test_invalid_json_is_rejected_before_credentials(
    sdk_session, monkeypatch, selected_account, payload
):
    get_credentials = Mock(side_effect=AssertionError("credentials were read"))
    monkeypatch.setattr(sdk_session, "get_credentials", get_credentials)

    with pytest.raises(reporting.AccountReportingError) as error:
        reporter_for(sdk_session).prepare_report(
            report_payload(payload) if isinstance(payload, dict) else payload,
            selected_account,
        )

    assert error.value.code == "PAYLOAD_INVALID"
    get_credentials.assert_not_called()


def test_payload_limit_is_on_canonical_utf8_bytes(sdk_session, selected_account):
    reporter = reporter_for(sdk_session)
    empty = reporter.prepare_report(report_payload({"data": ""}), selected_account)
    payload = report_payload({"data": "a" * (65_536 - len(empty.request_body()))})
    prepared = reporter.prepare_report(payload, selected_account)
    assert len(prepared.request_body()) == 65_536

    payload["data"] += "é"
    with pytest.raises(reporting.AccountReportingError) as error:
        reporter.prepare_report(payload, selected_account)

    assert error.value.code == "PAYLOAD_TOO_LARGE"


def test_request_body_adds_only_top_level_proof_and_hashes_every_other_field(
    sdk_session, selected_account
):
    payload = report_payload(
        {
            "event": {"amount": 4.5, "awsIdentityProof": "ordinary nested field"},
            "extra": "also-bound-to-proof",
        }
    )
    prepared = reporter_for(sdk_session).prepare_report(payload, selected_account)
    body = json.loads(prepared.request_body())

    proof = body.pop("awsIdentityProof")
    assert body == payload
    assert proof == {"version": 1, "headers": dict(prepared.headers)}
    # This payload has ASCII keys and a simple float, so ordinary JSON encoding
    # gives an independent expected canonical byte sequence.
    independently_encoded = json.dumps(
        body, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    assert prepared.payload == independently_encoded
    assert proof["headers"]["x-startup-advisor-event-sha256"] == (
        hashlib.sha256(independently_encoded).hexdigest()
    )
    assert prepared.request_body() == prepared.request_body()


@pytest.mark.parametrize(
    "change,code",
    [
        ({"reportingMode": "ANONYMOUS"}, "ACCOUNT_REPORTING_REQUIRED"),
        ({"expectedAwsAccountId": OTHER_ACCOUNT}, "ACCOUNT_CHANGED"),
        ({"noticeVersion": None}, "NOTICE_VERSION_REQUIRED"),
        ({"noticeVersion": ""}, "NOTICE_VERSION_REQUIRED"),
        ({"noticeVersion": "  "}, "NOTICE_VERSION_REQUIRED"),
        ({"noticeVersion": 0}, "NOTICE_VERSION_REQUIRED"),
        ({"noticeVersion": True}, "NOTICE_VERSION_REQUIRED"),
        ({"awsIdentityProof": {}}, "PAYLOAD_ALREADY_SIGNED"),
        ({"identity": {"accountId": ACCOUNT}}, "PAYLOAD_INVALID"),
        ({"eventId": "untrusted-client-event-id"}, "PAYLOAD_INVALID"),
        ({"receivedAt": 0}, "PAYLOAD_INVALID"),
        ({"awsProfile": "local-profile-name"}, "PAYLOAD_INVALID"),
    ],
)
def test_invalid_account_envelope_never_resolves_credentials(
    sdk_session, monkeypatch, selected_account, change, code
):
    get_credentials = Mock(side_effect=AssertionError("credentials were read"))
    monkeypatch.setattr(sdk_session, "get_credentials", get_credentials)
    payload = report_payload(change)

    with pytest.raises(reporting.AccountReportingError) as error:
        reporter_for(sdk_session).prepare_report(payload, selected_account)

    assert error.value.code == code
    get_credentials.assert_not_called()


def test_proof_binds_canonical_payload_audience_and_session_token(
    sdk_session, selected_account
):
    original = report_payload({"z": [2, 1], "a": {"value": "sensitive-report-value"}})
    prepared = reporter_for(sdk_session).prepare_report(original, selected_account)

    assert prepared.account == selected_account
    assert prepared.headers["host"] == "sts.us-east-1.amazonaws.com"
    assert prepared.headers["x-startup-advisor-audience"] == AUDIENCE
    assert prepared.headers["x-startup-advisor-event-sha256"] == (
        hashlib.sha256(prepared.payload).hexdigest()
    )
    assert prepared.headers["x-amz-security-token"] == SESSION_TOKEN
    assert independent_signature(prepared.headers) == signature_from(prepared.headers)
    signed_headers = prepared.headers["authorization"].split(
        "SignedHeaders=", 1
    )[1].split(",", 1)[0].split(";")
    assert {
        "content-type",
        "host",
        "x-amz-date",
        "x-amz-security-token",
        "x-startup-advisor-audience",
        "x-startup-advisor-event-sha256",
    } <= set(signed_headers)
    original["a"]["value"] = "modified-after-preparation"
    assert json.loads(prepared.payload)["a"]["value"] == "sensitive-report-value"

    for header in (
        "x-startup-advisor-audience",
        "x-startup-advisor-event-sha256",
        "x-amz-security-token",
    ):
        changed_headers = dict(prepared.headers)
        changed_headers[header] += "-modified"
        assert independent_signature(changed_headers) != signature_from(
            prepared.headers
        )


def test_long_term_credentials_do_not_add_an_empty_session_token(
    sdk_session, selected_account
):
    sdk_session.set_credentials(ACCESS_KEY, SECRET_KEY)
    prepared = reporter_for(sdk_session).prepare_report(
        report_payload({"event": "test"}), selected_account
    )

    assert "x-amz-security-token" not in prepared.headers
    assert independent_signature(prepared.headers) == signature_from(prepared.headers)


def test_prepared_values_are_immutable_and_repr_is_redacted(
    sdk_session, selected_account
):
    reporter = reporter_for(sdk_session)
    prepared = reporter.prepare_report(
        report_payload({"private": "sensitive-report-value"}), selected_account
    )

    with pytest.raises(TypeError):
        prepared.headers["authorization"] = "modified"
    assert repr(prepared) == "PreparedReport(<redacted>)"
    assert repr(reporter) == "AwsAccountReporter(<redacted>)"
    for value in (SECRET_KEY, SESSION_TOKEN, "sensitive-report-value", AUDIENCE):
        assert value not in repr(prepared) + repr(reporter)


@pytest.mark.parametrize(
    "credentials",
    [
        Credentials("", SECRET_KEY, SESSION_TOKEN),
        Credentials(ACCESS_KEY, "", SESSION_TOKEN),
        Credentials(ACCESS_KEY, "unsafe\nsecret", SESSION_TOKEN),
        Credentials(ACCESS_KEY, SECRET_KEY, "unsafe\r\ntoken"),
    ],
)
def test_invalid_credential_values_have_safe_failures(
    sdk_session, monkeypatch, selected_account, credentials
):
    monkeypatch.setattr(sdk_session, "get_credentials", lambda: credentials)

    with pytest.raises(reporting.AccountReportingError) as error:
        reporter_for(sdk_session).prepare_report(report_payload({"event": "test"}), selected_account)

    assert str(error.value) == "CREDENTIALS_UNAVAILABLE"
    assert SECRET_KEY not in repr(error.value)
    assert SESSION_TOKEN not in repr(error.value)


def test_missing_optional_sdk_is_a_controlled_failure(
    sdk_session, monkeypatch, selected_account
):
    original_import = builtins.__import__

    def reject_sdk(name, *args, **kwargs):
        if name == "rfc8785" or name.startswith("botocore"):
            raise ImportError("simulated missing optional dependency")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", reject_sdk)
    reporter = reporter_for(sdk_session)

    with pytest.raises(reporting.AccountReportingError) as error:
        reporter.prepare_report(report_payload({"event": "test"}), selected_account)

    assert str(error.value) == "SDK_UNAVAILABLE"


def test_construction_does_not_load_sdk_or_resolve_credentials(monkeypatch):
    load_sdk = Mock(side_effect=AssertionError("SDK loaded by construction"))
    monkeypatch.setattr(reporting, "_load_sdk", load_sdk)

    reporter = reporting.AwsAccountReporter(AUDIENCE, profile_name="selected")

    assert repr(reporter) == "AwsAccountReporter(<redacted>)"
    load_sdk.assert_not_called()


@pytest.mark.parametrize("account", ["", "123", "١٢٣٤٥٦٧٨٩٠١٢", ACCOUNT + "\n"])
def test_invalid_account_selection_is_rejected(account):
    with pytest.raises(reporting.AccountReportingError) as error:
        reporting.AccountIdentity(account)

    assert error.value.code == "INVALID_ACCOUNT"


def test_noncommercial_partition_is_explicitly_unsupported():
    with pytest.raises(reporting.AccountReportingError) as error:
        reporting.AccountIdentity(ACCOUNT, "aws-cn")

    assert error.value.code == "UNSUPPORTED_PARTITION"


@pytest.mark.parametrize(
    "code,status",
    [
        ("ACCOUNT_CHANGED", "SETUP_REQUIRED"),
        ("ACCOUNT_SELECTION_REQUIRED", "SETUP_REQUIRED"),
        ("NOTICE_VERSION_REQUIRED", "SETUP_REQUIRED"),
        ("CREDENTIALS_UNAVAILABLE", "SIGN_IN_REQUIRED"),
        ("SIGN_IN_REQUIRED", "SIGN_IN_REQUIRED"),
        ("IDENTITY_UNAVAILABLE", "ERROR"),
        ("SDK_UNAVAILABLE", "ERROR"),
        ("PAYLOAD_INVALID", "ERROR"),
    ],
)
def test_error_result_is_a_stable_identity_free_adapter_contract(code, status):
    error = reporting.AccountReportingError(code)
    assert error.as_result() == {"status": status, "reasonCode": code}
    assert str(error) == code


def test_unknown_error_detail_cannot_become_model_visible_output():
    error = reporting.AccountReportingError(SECRET_KEY + SESSION_TOKEN)
    assert error.as_result() == {"status": "ERROR", "reasonCode": "INTERNAL_ERROR"}
    assert str(error) == "INTERNAL_ERROR"
    assert SECRET_KEY not in repr(error)
    assert SESSION_TOKEN not in repr(error)
