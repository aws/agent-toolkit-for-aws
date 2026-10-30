"""Shared canonicalization examples for the client and reporting verifier."""

import hashlib
import hmac
import importlib.util
import json
import sys
from datetime import datetime
from pathlib import Path

import pytest
from conftest import TELEMETRY

rfc8785 = pytest.importorskip("rfc8785")
pytest.importorskip("botocore")
from botocore.session import Session

VECTORS = json.loads(
    (Path(__file__).parent / "fixtures/account-reporting-v1.json").read_text()
)["vectors"]
SIGNED_VECTORS = json.loads(
    (Path(__file__).parent / "fixtures/account-reporting-signed-v1.json").read_text()
)["vectors"]


def load_reporter_module():
    spec = importlib.util.spec_from_file_location(
        "account_reporting_shared_vector", TELEMETRY / "auth/aws_account.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("vector", VECTORS, ids=lambda vector: vector["name"])
def test_account_reporting_shared_canonical_vectors(vector):
    unsigned = {
        key: value
        for key, value in vector["request"].items()
        if key != "awsIdentityProof"
    }
    encoded = rfc8785.dumps(unsigned)
    assert encoded == vector["canonicalWithoutProof"].encode("utf-8")
    assert hashlib.sha256(encoded).hexdigest() == vector["sha256"]


def test_account_reporting_signer_matches_shared_full_request_vector():
    module = load_reporter_module()
    session = Session()
    # Explicit synthetic credentials avoid every external credential provider.
    session.set_credentials("shared-fixture-access", "shared-fixture-secret")
    reporter = module.AwsAccountReporter(
        "startup-advisor:fixture:report:v1", session=session
    )
    vector = next(item for item in VECTORS if item["name"] == "request-with-proof-excluded")
    unsigned = {
        key: value
        for key, value in vector["request"].items()
        if key != "awsIdentityProof"
    }
    prepared = reporter.prepare_report(
        unsigned, module.AccountIdentity(unsigned["expectedAwsAccountId"])
    )
    assert prepared.payload == vector["canonicalWithoutProof"].encode("utf-8")
    assert prepared.headers[module.PAYLOAD_HASH_HEADER] == vector["sha256"]
    decoded = json.loads(prepared.request_body())
    decoded.pop("awsIdentityProof")
    assert decoded == unsigned


@pytest.mark.parametrize("vector", SIGNED_VECTORS, ids=lambda vector: vector["name"])
def test_account_reporting_reproduces_complete_fixed_signature(vector, monkeypatch):
    module = load_reporter_module()
    session = Session()
    keys = vector["credentials"]
    session.set_credentials(
        keys["accessKeyId"], keys["secretAccessKey"], keys["sessionToken"]
    )
    # A supplied synthetic credential snapshot resolves no outside provider.
    monkeypatch.setattr(
        session, "create_client",
        lambda *args, **kwargs: pytest.fail("a signing fixture contacted STS"),
    )
    monkeypatch.setattr(
        "botocore.auth.get_current_datetime",
        lambda: datetime.fromisoformat(vector["signingTime"]),
    )
    reporter = module.AwsAccountReporter(vector["audience"], session=session)
    unsigned = {
        key: value for key, value in vector["request"].items()
        if key != "awsIdentityProof"
    }
    prepared = reporter.prepare_report(
        unsigned, module.AccountIdentity(unsigned["expectedAwsAccountId"])
    )
    assert prepared.payload.decode() == vector["canonicalWithoutProof"]
    assert json.loads(prepared.request_body()) == vector["request"]


@pytest.mark.parametrize("vector", SIGNED_VECTORS, ids=lambda vector: vector["name"])
def test_account_reporting_fixture_signature_verifies_without_sdk_signer(vector):
    headers = vector["request"]["awsIdentityProof"]["headers"]
    authorization = headers["authorization"]
    credential = authorization.split("Credential=", 1)[1].split(", ", 1)[0]
    access_key, scope = credential.split("/", 1)
    assert access_key == vector["credentials"]["accessKeyId"]
    signed_headers = authorization.split("SignedHeaders=", 1)[1].split(", ", 1)[0]
    canonical_headers = "".join(
        "%s:%s\n" % (name, " ".join(headers[name].split()))
        for name in signed_headers.split(";")
    )
    canonical_sts = "\n".join([
        vector["stsMethod"], "/", "", canonical_headers, signed_headers,
        hashlib.sha256(vector["stsBody"].encode()).hexdigest(),
    ])
    assert canonical_sts == vector["canonicalStsRequest"]
    string_to_sign = "\n".join([
        "AWS4-HMAC-SHA256", headers["x-amz-date"], scope,
        hashlib.sha256(canonical_sts.encode()).hexdigest(),
    ])
    assert string_to_sign == vector["stringToSign"]
    signing_key = ("AWS4" + vector["credentials"]["secretAccessKey"]).encode()
    for part in scope.split("/"):
        signing_key = hmac.new(signing_key, part.encode(), hashlib.sha256).digest()
    signature = hmac.new(signing_key, string_to_sign.encode(), hashlib.sha256).hexdigest()
    assert signature == vector["signature"]
    assert authorization.endswith("Signature=" + signature)


@pytest.mark.parametrize("field,replacement", [
    ("expectedAwsAccountId", "210987654321"),
    ("noticeVersion", 4),
    ("reportingMode", "ANONYMOUS"),
])
def test_account_reporting_fixture_digest_detects_selection_tampering(field, replacement):
    vector = SIGNED_VECTORS[0]
    unsigned = {
        key: value for key, value in vector["request"].items()
        if key != "awsIdentityProof"
    }
    unsigned[field] = replacement
    assert hashlib.sha256(rfc8785.dumps(unsigned)).hexdigest() != vector["payloadSha256"]
