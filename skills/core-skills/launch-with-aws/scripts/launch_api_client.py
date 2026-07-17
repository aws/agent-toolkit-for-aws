# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""Backend API client.

Bearer-authenticated wrapper over the backend HTTP API. Includes the custom
boto3 service model registration for the Launch with AWS service.
"""

import json
import os
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, Optional

import boto3
import botocore.loaders
import botocore.session
import botocore.tokens
from auth import get_access_token
from botocore.config import Config as BotoConfig
from botocore.exceptions import ClientError
from launch_config import (
    DEFAULT_BASE_URL,
    REQUEST_TIMEOUT_SECS,
    UPLOAD_TIMEOUT_SECS,
    load_config,
)

# ── Boto3 custom service client ──────────────────────────────────────────

_SERVICE_MODEL_PATH = Path(__file__).parent.parent / "references" / "launchwithaws-2026-06-15.json"

SERVICE_NAME = "launchwithaws"
API_VERSION = "2026-06-15"


def _load_service_model() -> dict:
    with open(_SERVICE_MODEL_PATH, "r") as f:
        return json.load(f)


def _register_service(session: botocore.session.Session) -> None:
    model = _load_service_model()
    original_load_service_model = session.get_component("data_loader").load_service_model

    def patched_load_service_model(service_name, type_name, api_version=None):
        if service_name == SERVICE_NAME and type_name == "service-2":
            return model
        return original_load_service_model(service_name, type_name, api_version)

    session.get_component("data_loader").load_service_model = patched_load_service_model

    original_list = session.get_component("data_loader").list_available_services

    def patched_list(type_name="service-2"):
        services = original_list(type_name)
        if type_name == "service-2" and SERVICE_NAME not in services:
            services.append(SERVICE_NAME)
        return services

    session.get_component("data_loader").list_available_services = patched_list


class _StaticTokenProvider:
    METHOD = "static"

    def __init__(self, token: str) -> None:
        self._token = botocore.tokens.FrozenAuthToken(token=token, expiration=None)

    def load_token(self, **kwargs) -> botocore.tokens.FrozenAuthToken:
        return self._token


def create_client(
    endpoint_url: Optional[str] = None,
    bearer_token: Optional[str] = None,
    region_name: str = "us-east-1",
    config: Optional[BotoConfig] = None,
):
    """Create a boto3 client for the Launch with AWS service."""
    if endpoint_url is None:
        endpoint_url = os.environ.get("LAUNCH_WITH_AWS_BASE_URL", DEFAULT_BASE_URL)

    botocore_session = botocore.session.get_session()
    _register_service(botocore_session)

    if bearer_token:
        static_provider = _StaticTokenProvider(bearer_token)
        token_chain = botocore.tokens.TokenProviderChain(providers=[static_provider])
        botocore_session.register_component("token_provider", token_chain)

    boto3_session = boto3.Session(botocore_session=botocore_session, region_name=region_name)

    client_config = config or BotoConfig(
        retries={"max_attempts": 3, "mode": "adaptive"},
    )

    return boto3_session.client(
        SERVICE_NAME,
        endpoint_url=endpoint_url,
        config=client_config,
        aws_access_key_id="unused",
        aws_secret_access_key="unused",
    )


# ── API client ───────────────────────────────────────────────────────────


class ApiError(Exception):
    """Raised when a backend API request returns a non-success status."""

    def __init__(self, status: int, method: str, path: str, body: str) -> None:
        super().__init__(f"{method} {path} failed ({status}): {body}")
        self.status = status
        self.method = method
        self.path = path
        self.body = body


def _client_error_to_api_error(err: ClientError, method: str, path: str) -> ApiError:
    status = err.response.get("ResponseMetadata", {}).get("HTTPStatusCode", 500)
    message = err.response.get("Error", {}).get("Message", str(err))
    return ApiError(status, method, path, message)


def _get_base_url() -> str:
    return load_config().base_url


def _get_boto3_client() -> Any:
    """Create a boto3 client with the current Bearer token."""
    token = get_access_token()
    return create_client(
        endpoint_url=_get_base_url(),
        bearer_token=token,
        config=BotoConfig(
            retries={"max_attempts": 3, "mode": "adaptive"},
            connect_timeout=REQUEST_TIMEOUT_SECS,
            read_timeout=REQUEST_TIMEOUT_SECS,
        ),
    )


# ── Public API functions ─────────────────────────────────────────────────


def create_upload_url() -> Any:
    """POST /api/uploads -> presigned S3 PUT location."""
    client = _get_boto3_client()
    try:
        return client.create_upload_url()
    except ClientError as err:
        raise _client_error_to_api_error(err, "POST", "/api/uploads") from err


def put_archive(upload_url: str, archive: bytes) -> None:
    """Upload zip bytes to a presigned S3 PUT URL."""
    req = urllib.request.Request(
        upload_url,
        data=archive,
        headers={"Content-Type": "application/zip"},
        method="PUT",
    )
    try:
        with urllib.request.urlopen(req, timeout=UPLOAD_TIMEOUT_SECS):
            pass
    except urllib.error.HTTPError as err:
        raise ApiError(err.code, "PUT", "(presigned S3 upload)", err.read().decode()) from err


# ── Launch resource API ──────────────────────────────────────────────────


def create_launch(
    name: str,
    source: Dict[str, Any],
    client_token: Optional[str] = None,
) -> Any:
    """POST /api/launches — create a new launch from an upload or GitHub repo."""
    client = _get_boto3_client()
    kwargs: Dict[str, Any] = {"name": name, "source": source}
    if client_token:
        kwargs["clientToken"] = client_token
    try:
        return client.create_launch(**kwargs)
    except ClientError as err:
        raise _client_error_to_api_error(err, "POST", "/api/launches") from err


def get_launch(launch_id: str, include: Optional[str] = None) -> Any:
    """GET /api/launches/:launchId — get launch details with optional sections."""
    client = _get_boto3_client()
    kwargs: Dict[str, Any] = {"launchIdentifier": launch_id}
    if include:
        # The API accepts a list of section enum values.
        kwargs["include"] = [s.strip() for s in include.split(",")]
    try:
        return client.get_launch(**kwargs)
    except ClientError as err:
        raise _client_error_to_api_error(err, "GET", f"/api/launches/{launch_id}") from err


def list_launches(max_results: Optional[int] = None) -> Any:
    """GET /api/launches — list all launches for the current user."""
    client = _get_boto3_client()
    kwargs: Dict[str, Any] = {}
    if max_results is not None:
        kwargs["maxResults"] = max_results
    try:
        return client.list_launches(**kwargs)
    except ClientError as err:
        raise _client_error_to_api_error(err, "GET", "/api/launches") from err


def delete_launch(launch_id: str) -> None:
    """DELETE /api/launches/:launchId — delete a launch (returns 204 No Content)."""
    client = _get_boto3_client()
    try:
        client.delete_launch(launchIdentifier=launch_id)
    except ClientError as err:
        raise _client_error_to_api_error(err, "DELETE", f"/api/launches/{launch_id}") from err


def refine_plan(
    launch_id: str,
    context_answers: Optional[Dict[str, str]] = None,
    prompt: Optional[str] = None,
    client_token: Optional[str] = None,
) -> Any:
    """POST /api/launches/:launchId/refine — provide context answers to refine the plan."""
    client = _get_boto3_client()
    kwargs: Dict[str, Any] = {"launchIdentifier": launch_id}
    if context_answers:
        kwargs["contextAnswers"] = context_answers
    if prompt:
        kwargs["prompt"] = prompt
    if client_token:
        kwargs["clientToken"] = client_token
    try:
        return client.refine_plan(**kwargs)
    except ClientError as err:
        raise _client_error_to_api_error(err, "POST", f"/api/launches/{launch_id}/refine") from err


def start_launch_execution(launch_id: str, client_token: Optional[str] = None) -> Any:
    """POST /api/launches/:launchId/start — start execution of the deployment plan."""
    client = _get_boto3_client()
    kwargs: Dict[str, Any] = {"launchIdentifier": launch_id}
    if client_token:
        kwargs["clientToken"] = client_token
    try:
        return client.start_launch_execution(**kwargs)
    except ClientError as err:
        raise _client_error_to_api_error(err, "POST", f"/api/launches/{launch_id}/start") from err
