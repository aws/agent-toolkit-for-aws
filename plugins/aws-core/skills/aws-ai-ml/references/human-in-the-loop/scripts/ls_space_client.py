# mypy: disable-error-code="arg-type,assignment,attr-defined,misc,operator,return-value,type-var,union-attr,var-annotated"
"""
Client for the Label Studio app running in a SageMaker Studio shared space.

The Label Studio app runs in a shared JupyterLab space on the first-party
``label-studio-jupyterlab`` image: the user launches it from the Label Studio icon
in SageMaker Studio, or, when the user chooses so, the skill creates the space
(``create``) or starts its app (``start``). The space is found by its image, never
by its name. Label Studio listens on 127.0.0.1 only and is reached through the
Studio proxy at:

    https://<space-host>/jupyterlab/default/label-studio/<path>

The app signs each Studio user in automatically from the proxy's
StudioAuthToken cookie, creating the Label Studio user
``<profile>@studio.local`` on first visit.

This module runs OUTSIDE the space (wherever the agent runs) with the caller's
AWS credentials. Most SageMaker describe, create and delete calls go through the SageMaker
Python SDK (sagemaker>=3.30.0); the list calls, CreateApp, CreatePresignedDomainUrl and S3 use
boto3 (see _SageMaker). It never installs or patches Label Studio, never deletes a space
and never stops a running app; the one thing it deletes is a Failed app, and only
with --replace-failed-app. It:

    find_label_studio_space()   locate the Label Studio space and check its app is running
    create_label_studio_space() create the space (if the domain has none) and start its app
    start_label_studio_app()    start the app in an existing space (a Failed app is recreated)
    list_annotator_profiles()   SageMaker user profiles in the space's domain
    check_admin_profile()       can these credentials open the space as a given profile
    setup_projects()            split records, one project per annotator, return links
    get_progress()              per-annotator completion status
    export_annotations()        completed annotations for the post-annotation steps

How it talks to Label Studio: it mints a 5-second presigned domain URL for the
admin profile, the user's own (--admin-profile; required, no default), redeems it in an in-memory cookie jar,
and calls Label Studio's REST API through the Studio proxy. Label Studio's
autologin authenticates those calls as the admin profile, so no Label Studio
API token is needed. The presigned URL and cookies are never printed or stored.

IAM the caller needs: sagemaker:ListDomains, sagemaker:DescribeDomain,
sagemaker:ListSpaces, sagemaker:DescribeSpace, sagemaker:ListApps,
sagemaker:ListUserProfiles, and sagemaker:CreatePresignedDomainUrl on the admin
profile (sts:GetCallerIdentity, which needs no IAM permission, gives caller_arn in
discover/profiles and the caller's account for the image check). create/start also need sagemaker:CreateSpace,
sagemaker:CreateApp, sagemaker:DescribeApp and sagemaker:DeleteApp (used only on a
Failed app). The full list: references/label-studio-space.md, IAM. Optional S3 copy of the
export: s3:ListBucket (HeadBucket), s3:PutObject and s3:DeleteObject (write
check) on the destination, sts:GetCallerIdentity (bucket-owner check; no IAM permission needed), and
read-only S3 permissions to report the bucket's settings (the full list:
references/label-studio-space.md, S3 copy of the export).

Errors from Label Studio carry the HTTP status and, for a validation error, the
names of the fields it rejected, never Label Studio's own text: that text is
data written by others.

CLI (prints JSON on stdout; errors as {"error", "message"} JSON on stderr, which
create/start precede with {"progress"} lines while they wait).
Exit codes: 0 ok; 2 no running Label Studio space (or unknown domain; discover
still prints not_running and domains on stdout);
3 Label Studio unreachable, Studio rejected the session URL twice, a Label
Studio call failed, setup created the
projects but could not save --out, s3-check could not record its result in
the HIL log (OutputWriteError; stdout has the result), or export could not write
--out / --discarded-out (OutputWriteError; any earlier file is unchanged, nothing uploaded); 4 missing/invalid
arguments, no AWS region, the SageMaker Python SDK not importable (SdkUnavailableError), unreadable input file, fewer records than annotators,
a record with no --id-field value or one another record shares,
export --s3-uri without a passed s3-check of that upload URI, or an --approval-id /
--relabel-of the HIL log doesn't hold as an approval entry with discarded_unique_ids
(nothing was changed);
5 an AWS call failed (no credentials, AccessDenied, throttling; for export --s3-uri the
local export is still written and printed, with s3_error), the SageMaker Python SDK failed to
read an AWS response (the call may have gone through), or create/start could
not bring the space or app up (LaunchError); 6 create: the domain has no default
space execution role. When searching all domains, AccessDenied while searching one
means that domain was not fully checked (named in skipped_domains or the exit-2
message), and other per-domain errors are listed as "(error)"; exit 5 only if no
running space was found. With --domain-id, an unknown domain exits 2 (4 for create
and start) and any other AWS error exits 5.
profiles --admin-profile reports a denied CreatePresignedDomainUrl, or a profile not
in the domain, in admin_profile_check (exit 0).


    python ls_space_client.py discover [--domain-id d-xxx] [--space-name <name>]
    python ls_space_client.py estimate-storage --records data.jsonl     # local: storage estimate for create
    python ls_space_client.py create --domain-id d-xxx --admin-profile <p> [--ebs-gb 5] [--no-wait]
    python ls_space_client.py start --domain-id d-xxx --space-name label-studio-20260101000000 [--replace-failed-app] [--no-wait]
    python ls_space_client.py profiles --domain-id d-xxx [--space-name <name>] [--admin-profile <p>]
    python ls_space_client.py setup --domain-id d-xxx --space-name label-studio-20260101000000 \\
        --admin-profile <p> --annotators a,b --project-name fix-responses \\
        --label-config config.xml --records data.jsonl [--data-fields text] \\
        [--hide-fields split] [--id-field id]
    python ls_space_client.py status --domain-id d-xxx --space-name label-studio-20260101000000 \\
        --admin-profile <p> --assignments assignments.json
    python ls_space_client.py s3-inspect --s3-uri s3://bucket/prefix/ \\
        --assignments ls_setup.json --out export.jsonl          # read-only: key and bucket settings
    python ls_space_client.py s3-check --s3-uri s3://bucket/prefix/ \\
        --assignments ls_setup.json --project-dir <dir>         # can we write there? recorded in the HIL log
    python ls_space_client.py export ... --assignments ls_setup.json --out export.jsonl \\
        [--s3-uri s3://bucket/prefix/ --project-dir <dir>]      # uploads only where s3-check passed
    python ls_space_client.py setup ... --relabel-of <approval-id> --project-dir <dir>  # a relabel project
    python ls_space_client.py export ... --approval-id <approval-id> --project-dir <dir> \\
        [--relabel-setup ls_setup_relabel.json ...]             # leaves out the rows discarded at Step 7
    python ls_space_client.py record-relabel-round --assignments ls_setup_relabel.json --project-dir <dir>
                                                                # records a saved round setup could not record

``--s3-uri`` is the destination the user chose (a bucket, a prefix, or a full
object key). The script derives the upload URI from it (``export_upload_uri``),
so s3-inspect, s3-check and export always use the same key.
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import http.cookiejar
import json
import os
import re
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Optional

_HERE = os.path.dirname(os.path.abspath(__file__))  # record_ids sits beside this file
if _HERE not in sys.path:
    sys.path.append(_HERE)  # appended, so no file here can shadow a standard-library module
from record_ids import record_id_problems  # noqa: E402

# A Label Studio space is a shared JupyterLab space on this first-party image: exact name, in an
# account other than the customer's own, and on prod in one of the regions label-studio-images.json
# lists, with that region's image account (is_label_studio_image_arn). The space name is never
# trusted, because any user can give a space on another image a similar name.
LS_IMAGE_NAME = "label-studio-jupyterlab"
# Spaces the skill (and the Studio Label Studio page) create: <prefix><UTC YYYYMMDDHHMMSS>.
LS_SPACE_NAME_PREFIX = "label-studio-"
LS_SPACE_DISPLAY_NAME = "Label Studio"
LS_APP_NAME = "default"
DEFAULT_INSTANCE_TYPE = "ml.t3.medium"
DEFAULT_EBS_GB = 5
# Per-region first-party image account and alias; no public API serves them.
IMAGE_CONFIG_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "label-studio-images.json"
)
DESCRIBE_CONCURRENCY = 5  # DescribeSpace calls in flight at once while finding the space
POLL_INTERVAL_S = 5
MAX_POLLS = 60  # 5 minutes for the space, and again for the app
BUSY_RETRIES = 5  # CreateSpace/CreateApp return ResourceInUse while the domain or storage settles
BUSY_RETRY_BASE_S = 3
LS_SUBPATH = "/jupyterlab/default/label-studio"
MAX_RECORDS_BYTES = (
    50 * 1024 * 1024
)  # the most setup reads client-side (as data_helpers.read_records)
READY_TIMEOUT_S = 180
URL_EXPIRES_S = 5  # the skill's own session URL: opened at once, so it never needs to live longer
TITLE_MAX_LEN = 50  # Label Studio Project.title max_length


class SpaceNotFoundError(RuntimeError):
    """No shared Label Studio space (a shared JupyterLab space on the Label Studio image) was found."""


class AppNotRunningError(RuntimeError):
    """A Label Studio space exists but its JupyterLab app (which hosts Label Studio) is not InService."""


class DomainNotReadyError(RuntimeError):
    """The domain has no default space execution role, which a shared space needs (exit code 6)."""


class LaunchError(RuntimeError):
    """create/start: the space or app failed, was stopped while starting, or did not start in time."""


class LabelStudioError(RuntimeError):
    """Label Studio returned an error or never became reachable."""


class SdkUnavailableError(RuntimeError):
    """The SageMaker Python SDK can't be imported here: the environment, not AWS."""


class AwsCallError(RuntimeError):
    """A SageMaker API call failed (credentials, AccessDenied, throttling): exit code 5."""


class UsageError(ValueError):
    """Missing or invalid CLI arguments (exit code 4); nothing was changed."""


class FailedAppError(UsageError):
    """start without --replace-failed-app found a Failed app (exit code 4); nothing was changed."""

    def __init__(self, message: str, space: Optional[dict] = None):
        super().__init__(message)
        self.space = space


class SetupPartialError(LabelStudioError):
    """setup_projects failed partway; ``result`` holds the projects already created."""

    def __init__(self, result, failed_profile: str, cause: Exception):
        self.result = result
        self.failed_profile = failed_profile
        created = ", ".join(f"{a.profile} -> {a.project_id}" for a in result.annotator_links)
        super().__init__(
            f"Project for '{failed_profile}' failed: {cause}. Already created: {created}."
        )


LAUNCH_INSTRUCTIONS = (
    "Either open SageMaker Studio, click the Label Studio app icon and wait until Label Studio "
    "opens in the browser, or have the skill create or start it ('create' or 'start')."
)
MISSING_SPACE_ROLE = (
    "This domain has no default space execution role. Ask a domain administrator to set one before "
    "launching Label Studio."
)


@dataclass
class SpaceInfo:
    region: str
    domain_id: str
    domain_name: str
    space_name: str
    owner_profile: Optional[str]
    space_url: str  # origin, e.g. https://abc.studio.us-west-2.sagemaker.aws

    @property
    def ls_base_url(self) -> str:
        return f"{self.space_url}{LS_SUBPATH}"

    def project_url(self, project_id: int) -> str:
        return f"{self.ls_base_url}/projects/{project_id}/data"


@dataclass
class AnnotatorLink:
    profile: str
    project_id: int
    title: str
    url: str
    task_count: int


@dataclass
class SetupResult:
    space: SpaceInfo
    admin_profile: str
    run_id: str
    annotator_links: list = field(default_factory=list)
    project_name: str = ""
    created_at: str = ""  # when setup ran, ISO 8601 UTC (the HIL log's form); run_id is local time
    relabel_of: Optional[str] = (
        None  # the approval entry whose discarded rows this project relabels
    )

    @property
    def assignments(self) -> dict:
        return {
            a.profile: {
                "project_id": a.project_id,
                "title": a.title,
                "url": a.url,
                "task_count": a.task_count,
            }
            for a in self.annotator_links
        }

    def to_dict(self) -> dict:
        return {
            "space": asdict(self.space),
            "admin_profile": self.admin_profile,
            "project_name": self.project_name,
            "run_id": self.run_id,
            **({"created_at": self.created_at} if self.created_at else {}),
            "admin_url": f"{self.space.ls_base_url}/projects/",
            "assignments": self.assignments,
            **({"relabel_of": self.relabel_of} if self.relabel_of else {}),
        }

    def to_markdown(self) -> str:
        lines = [
            f"**Label Studio projects are ready** in shared space `{self.space.space_name}` "
            f"(domain `{self.space.domain_name}`).",
            "",
            f"- **You ({self.admin_profile}):** {self.space.ls_base_url}/projects/",
            "",
            "| Annotator profile | Project | Tasks | Link |",
            "|---|---|---|---|",
        ]
        for a in self.annotator_links:
            lines.append(f"| `{a.profile}` | {a.title} | {a.task_count} | {a.url} |")
        lines += [
            "",
            "Each annotator: sign in to SageMaker Studio as your own user profile, open the "
            f"`{self.space.space_name}` space (or click the Label Studio icon), then open your link. "
            "Label Studio signs you in automatically.",
        ]
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# AWS side: discovery
# ---------------------------------------------------------------------------


_ATTRIBUTED = []


def _pysdk():
    """Import-time setup for the SageMaker Python SDK, once: the agent-plugin attribution
    data_helpers.py also sets. Some sagemaker-core versions log to stdout; the CLI keeps its
    stdout for the JSON result (see __main__)."""
    if not _ATTRIBUTED:
        try:
            import sagemaker.core.resources  # noqa: F401  (fail here, not inside a call)
            from sagemaker.core import Attribution, set_attribution
        except (
            Exception
        ) as e:  # a missing or broken install: ImportError, or what its import raises
            raise SdkUnavailableError(
                f"The SageMaker Python SDK can't be imported ({type(e).__name__}: {e}). This script needs "
                "boto3 and sagemaker>=3.30.0, as in the sdk-getting-started environment; install them "
                "in this Python, then run the command again."
            ) from None
        set_attribution(Attribution.SAGEMAKER_AGENT_PLUGIN)
        _ATTRIBUTED.append(True)


def _snake_keys(value):
    """A boto3-style (PascalCase) request value with snake_case keys, as PySDK's resources take."""
    from sagemaker.core.utils.utils import pascal_to_snake

    if isinstance(value, dict):
        return {pascal_to_snake(k): _snake_keys(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_snake_keys(v) for v in value]
    return value


class _SageMaker:
    """The SageMaker calls this script makes, with boto3's method names, arguments and dict results.

    DescribeDomain, DescribeSpace, DescribeApp, CreateSpace and DeleteApp go through the SageMaker
    Python SDK (PySDK) resources (``sagemaker.core.resources``), whose objects are serialized back
    to the API's PascalCase dicts the rest of the script reads. The rest stay on the session's
    boto3 client, where PySDK (sagemaker-core 2.29) can't do the job:
    - the four list calls: PySDK's ``get_all`` describes every item it lists, one at a time, so
      finding the space would describe every space and app in the domain and fail on any one of
      them, while this script reads only the spaces it needs (find_space_in_domain);
    - CreateApp: ``App.create`` describes the new app without its SpaceName, which the service
      rejects (ValidationException), so it raises after a CreateApp that succeeded;
    - CreatePresignedDomainUrl: see create_presigned_domain_url.
    """

    def __init__(self, region: Optional[str] = None):
        _pysdk()  # an unusable SDK fails here, once, before any AWS call
        self.session = _session(region)
        self._boto3 = self.session.client("sagemaker")
        self.meta = self._boto3.meta  # .region_name, as on a boto3 client

    @property
    def _where(self) -> dict:
        return {"session": self.session, "region": self.meta.region_name}

    # boto3 (see the class docstring)
    def list_domains(self, **kwargs):
        return self._boto3.list_domains(**kwargs)

    def list_spaces(self, **kwargs):
        return self._boto3.list_spaces(**kwargs)

    def list_apps(self, **kwargs):
        return self._boto3.list_apps(**kwargs)

    def list_user_profiles(self, **kwargs):
        return self._boto3.list_user_profiles(**kwargs)

    # PySDK
    def describe_domain(self, DomainId):
        _pysdk()
        from sagemaker.core.resources import Domain
        from sagemaker.core.utils.utils import serialize

        return serialize(Domain.get(domain_id=DomainId, **self._where))

    def describe_space(self, DomainId, SpaceName):
        _pysdk()
        from sagemaker.core.resources import Space
        from sagemaker.core.utils.utils import serialize

        return serialize(Space.get(domain_id=DomainId, space_name=SpaceName, **self._where))

    def describe_app(self, DomainId, SpaceName, AppType, AppName):
        _pysdk()
        from sagemaker.core.resources import App
        from sagemaker.core.utils.utils import serialize

        return serialize(
            App.get(
                domain_id=DomainId,
                space_name=SpaceName,
                app_type=AppType,
                app_name=AppName,
                **self._where,
            )
        )

    def create_space(self, DomainId, SpaceName, **kwargs):
        _pysdk()
        from sagemaker.core.resources import Space

        try:
            Space.create(
                domain_id=DomainId, space_name=SpaceName, **_snake_keys(kwargs), **self._where
            )
        except Exception as e:
            # PySDK describes the new space right after CreateSpace; a space that describe can't
            # see yet was still created, and the caller reads it again (find_space_in_domain).
            # A not-found from CreateSpace itself is a real failure.
            if not (_is_not_found(e) and getattr(e, "operation_name", "") == "DescribeSpace"):
                raise
        return {}

    def create_app(self, **kwargs):
        # boto3: see the class docstring
        return self._boto3.create_app(**kwargs)

    def delete_app(self, DomainId, SpaceName, AppType, AppName):
        _pysdk()
        from sagemaker.core.resources import App

        App.get(
            domain_id=DomainId,
            space_name=SpaceName,
            app_type=AppType,
            app_name=AppName,
            **self._where,
        ).delete()
        return {}

    def create_presigned_domain_url(self, **kwargs):
        # boto3: PySDK's PresignedDomainUrl.create (sagemaker-core 2.29) mints the URL, then builds
        # its result from the PascalCase request and always fails validation, with the URL in the
        # error text. That error must never be what a presigned URL travels in.
        return self._boto3.create_presigned_domain_url(**kwargs)


def _sm_client(region: Optional[str] = None):
    return _SageMaker(region)


def _origin(url: str) -> str:
    if not url.startswith("http"):
        url = f"https://{url}"
    parsed = urllib.parse.urlparse(url)
    return f"https://{parsed.netloc}"


def _list_domains(sm) -> list:
    domains, token = [], None
    while True:
        resp = sm.list_domains(**({"NextToken": token} if token else {}))
        domains.extend(resp.get("Domains", []))
        token = resp.get("NextToken")
        if not token:
            return domains


def _paged(call, key: str, **kwargs) -> list:
    items, token = [], None
    while True:
        resp = call(**kwargs, **({"NextToken": token} if token else {}))
        items.extend(resp.get(key, []))
        token = resp.get("NextToken")
        if not token:
            return items


def _app_status(sm, domain_id: str, space_name: str) -> Optional[str]:
    resp = sm.list_apps(DomainIdEquals=domain_id, SpaceNameEquals=space_name)
    for app in resp.get("Apps", []):
        if app.get("AppType") == "JupyterLab" and app.get("Status") != "Deleted":
            return app.get("Status")
    return None


_ACCESS_DENIED = ("AccessDenied", "AccessDeniedException", "UnauthorizedOperation")
_FAILED_SPACE_STATUSES = ("Failed", "Update_Failed", "Delete_Failed")
_IMAGE_ARN = re.compile(r"^arn:[^:]+:sagemaker:([^:]*):(\d{12}):image(?:-version)?/([^/]+)")


def image_arn_of(resource_spec: Optional[dict]) -> Optional[str]:
    """The image ARN, or the image-version ARN when a space was created with only that."""
    spec = resource_spec or {}
    return spec.get("SageMakerImageArn") or spec.get("SageMakerImageVersionArn")


def _is_non_prod_stage() -> bool:
    """SageMaker calls go to a non-prod stage: AWS_ENDPOINT_URL_SAGEMAKER (or AWS_ENDPOINT_URL)
    names a host outside amazonaws.com. Unset, ignored by AWS_IGNORE_CONFIGURED_ENDPOINT_URLS, or an
    amazonaws.com host is prod. An endpoint set only in the AWS config file isn't read here, so it
    gets prod's stricter image check."""
    if os.environ.get("AWS_IGNORE_CONFIGURED_ENDPOINT_URLS", "").lower() == "true":
        return False
    url = os.environ.get("AWS_ENDPOINT_URL_SAGEMAKER") or os.environ.get("AWS_ENDPOINT_URL")
    if not url:
        return False
    host = urllib.parse.urlparse(url if "//" in url else f"//{url}").hostname or ""
    return not (host.endswith(".amazonaws.com") or host.endswith(".amazonaws.com.cn"))


_IMAGE_KEYS = ("account", "imageName", "alias")


def _image_table(path: Optional[str] = None) -> Optional[dict]:
    """label-studio-images.json as {region: {account, imageName, alias}}, or None when the file
    can't be read, is empty, or any entry is damaged (not an object, or missing one of those strings): a
    partly damaged table isn't trusted for any region."""
    try:
        with open(path or IMAGE_CONFIG_PATH, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or not data:  # an empty table lists no image anywhere: damaged
        return None
    table = {}
    for region, entry in data.items():
        block = entry.get("firstParty") if isinstance(entry, dict) else None
        if not (
            isinstance(block, dict)
            and all(isinstance(block.get(k), str) and block.get(k) for k in _IMAGE_KEYS)
        ):
            return None
        table[region] = block
    return table


def _prod_image_account(region: str) -> Optional[str]:
    """The region's image account; None for a region the table doesn't list, and "" when the
    table can't be read or is damaged (_image_table). Neither matches an account, so the check
    fails closed."""
    table = _image_table()
    if table is None:
        return ""
    return (table.get(region) or {}).get("account")


IMAGE_TABLE_UNREADABLE = (
    "scripts/label-studio-images.json can't be read or is incomplete, so no Label "
    "Studio space can be recognized or created. Restore that file from the skill, then run "
    "the command again."
)


def _no_label_studio_here(region: str) -> Optional[str]:
    """Why no Label Studio space can be found in ``region`` on prod, or None when one can."""
    if _is_non_prod_stage():
        return None
    account = _prod_image_account(region)
    if account == "":
        return IMAGE_TABLE_UNREADABLE
    if account is None:
        return (
            f"Label Studio isn't available in {region}; its image ships in "
            f"{', '.join(_image_regions())}. Use one of those regions, or local review."
        )
    return None


def _image_regions() -> list:
    """The regions label-studio-images.json lists, sorted ([] when it can't be read or is damaged)."""
    return sorted(_image_table() or {})


def is_label_studio_image_arn(arn: Optional[str], own_account: str) -> bool:
    """The first-party Label Studio image: exact name, in the image owner's account.

    At CreateApp, Studio resolves an image of this name to the stage's registered first-party image,
    so a running app's resource spec shows the owner account. An image of this name in the
    customer's own account is their custom image and never counts. On prod the image ships only
    in the regions label-studio-images.json lists, so the region must be listed and the account
    must be that region's account. Other stages' accounts aren't shipped with the skill, so there
    any account other than the caller's own counts. The region is looked up exactly, so on prod a
    region spelled otherwise (``US-WEST-2``, ``us-west-2x``) is not listed and never counts.
    """
    match = _IMAGE_ARN.match(arn or "")
    if not match or match.group(3) != LS_IMAGE_NAME or match.group(2) == own_account:
        return False
    if _is_non_prod_stage():
        return True
    listed = _prod_image_account(match.group(1))  # None: no Label Studio image in that region
    return bool(listed) and match.group(2) == listed


def _space_image_arn(space: dict) -> Optional[str]:
    return image_arn_of(
        ((space.get("SpaceSettings") or {}).get("JupyterLabAppSettings") or {}).get(
            "DefaultResourceSpec"
        )
    )


def is_label_studio_space(space: dict, own_account: str) -> bool:
    """A DescribeSpace output is a Label Studio space: shared, on the Label Studio image.

    A private space on the image belongs to one user and is an ordinary space.
    """
    return (space.get("SpaceSharingSettings") or {}).get(
        "SharingType"
    ) == "Shared" and is_label_studio_image_arn(_space_image_arn(space), own_account)


def _running_app_image_arn(sm, domain_id: str, space_name: str) -> Optional[str]:
    """The image Studio resolved for the space's running or starting JupyterLab app, if any."""
    resp = sm.list_apps(DomainIdEquals=domain_id, SpaceNameEquals=space_name)
    for app in resp.get("Apps", []):
        if app.get("AppType") == "JupyterLab" and app.get("Status") in ("InService", "Pending"):
            return image_arn_of(app.get("ResourceSpec"))
    return None


def is_label_studio_space_named(sm, domain_id: str, space: dict, own_account: str) -> bool:
    """The same rule as find_space_in_domain for one named space: shared, and its running app's
    resolved image or else its own record's image is the first-party Label Studio image."""
    if (space.get("SpaceSharingSettings") or {}).get("SharingType") != "Shared":
        return False
    running = _running_app_image_arn(sm, domain_id, space["SpaceName"])
    return is_label_studio_image_arn(running or _space_image_arn(space), own_account)


def _is_not_found(e: Exception) -> bool:
    return _error_code(e) in ("ResourceNotFound", "ResourceNotFoundException")


def _describe_space_or_none(sm, domain_id: str, space_name: str) -> Optional[dict]:
    try:
        return sm.describe_space(DomainId=domain_id, SpaceName=space_name)
    except Exception as e:
        # Deleted since ListSpaces: no longer a candidate. Any other error is raised: swallowed
        # on the real space, it would read as "none found" and a create would make a duplicate.
        if _is_not_found(e):
            return None
        raise


def _creation_time(summary: dict) -> float:
    created = summary.get("CreationTime")
    return created.timestamp() if hasattr(created, "timestamp") else float("inf")


def find_space_in_domain(
    sm, domain_id: str, own_account: str, read_all: bool = False
) -> Optional[dict]:
    """The domain's Label Studio space as DescribeSpace output, or None.

    Lists the domain's shared JupyterLab spaces (not Deleting or failed), reads each one's image
    from its running app or else from DescribeSpace (DESCRIBE_CONCURRENCY at a time), and
    returns the oldest match that can still be described. The same rule as the Label Studio page
    in Studio, so both pick the same space. Spaces newer than the oldest match confirmed by a
    running app are not read. Errors on the spaces that are read, other than a vanished space, are raised.
    """
    spaces = [
        sp
        for sp in _paged(sm.list_spaces, "Spaces", DomainIdEquals=domain_id, MaxResults=100)
        if sp.get("SpaceName")
        and (sp.get("SpaceSettingsSummary") or {}).get("AppType") == "JupyterLab"
        and (sp.get("SpaceSharingSettingsSummary") or {}).get("SharingType") == "Shared"
        and sp.get("Status") not in ("Deleting", *_FAILED_SPACE_STATUSES)
    ]
    running = {}
    for app in _paged(sm.list_apps, "Apps", DomainIdEquals=domain_id, MaxResults=100):
        if (
            app.get("SpaceName")
            and app.get("AppType") == "JupyterLab"
            and app.get("Status") in ("InService", "Pending")
        ):
            running[app["SpaceName"]] = app  # SpaceName is case-sensitive: never fold it
    matches, to_describe = [], []
    for sp in spaces:
        arn = image_arn_of(running.get(sp["SpaceName"], {}).get("ResourceSpec"))
        if not arn:
            to_describe.append(sp)
        elif is_label_studio_image_arn(arn, own_account):
            matches.append((sp, None))
    skipped = []
    if matches and not read_all:
        # A space created after the oldest confirmed running match can't be the oldest, so it isn't
        # read: an error on it can't fail the domain. An older one is read, and its errors still raise.
        cutoff = min(_creation_time(sp) for sp, _ in matches)
        skipped = [sp for sp in to_describe if _creation_time(sp) >= cutoff]
        to_describe = [sp for sp in to_describe if _creation_time(sp) < cutoff]
    if to_describe:
        with ThreadPoolExecutor(max_workers=DESCRIBE_CONCURRENCY) as pool:
            described = list(
                pool.map(
                    lambda sp: _describe_space_or_none(sm, domain_id, sp["SpaceName"]), to_describe
                )
            )
        matches += [
            (sp, d)
            for sp, d in zip(to_describe, described)
            if d and is_label_studio_space(d, own_account)
        ]
    matches.sort(key=lambda m: _creation_time(m[0]))
    for summary, described in matches:
        space = described or _describe_space_or_none(sm, domain_id, summary["SpaceName"])
        if space:
            return space
    if skipped:  # every match vanished meanwhile: the skipped spaces are candidates again
        return find_space_in_domain(sm, domain_id, own_account, read_all=True)
    return None


def _space_info(region: str, domain_id: str, domain_name: str, space: dict) -> SpaceInfo:
    return SpaceInfo(
        region=region,
        domain_id=domain_id,
        domain_name=domain_name,
        space_name=space["SpaceName"],
        owner_profile=(space.get("OwnershipSettings") or {}).get("OwnerUserProfileName"),
        space_url=_origin(space["Url"]) if space.get("Url") else "",
    )


def _domain_settings(domain: dict) -> dict:
    dss = domain.get("DefaultSpaceSettings") or {}
    ebs = (dss.get("SpaceStorageSettings") or {}).get("DefaultEbsStorageSettings") or {}
    return {
        "default_space_role": bool(dss.get("ExecutionRole")),
        "max_ebs_gb": ebs.get("MaximumEbsVolumeSizeInGb"),
    }


def _is_sdk_model_error(e: Exception) -> bool:
    """A SageMaker Python SDK modeling (pydantic) error: main() reports it without its text."""
    return type(e).__module__.startswith("pydantic")


def _domain_candidates(sm, domains: list) -> list:
    """Where a Label Studio space could be created: each fully searched domain and its settings."""
    out = []
    for d in domains:
        did = d["DomainId"]
        row = {"domain_id": did, "domain_name": d.get("DomainName", did)}
        try:
            full = d if "DefaultSpaceSettings" in d else sm.describe_domain(DomainId=did)
            row.update(_domain_settings(full))
        except Exception as e:
            if _is_sdk_model_error(e):
                raise
            row["error"] = _error_code(e)
        out.append(row)
    return out


def find_label_studio_space(
    space_name: Optional[str] = None,
    domain_id: Optional[str] = None,
    region: Optional[str] = None,
    skipped: Optional[list] = None,
) -> list:
    """Return every running Label Studio space, one per domain at most.

    In each domain the Label Studio space is the one ``find_space_in_domain`` picks. With
    ``space_name``, only that space is checked, and it must be a Label Studio space. A domain
    that could not be searched is listed in ``skipped``: "<name> (<id>)" for AccessDenied,
    "<name> (<id>): <code> (error)" for any other error (or any error with ``domain_id``).

    Raises SpaceNotFoundError if none exists and AppNotRunningError if one exists but its app is
    not InService. Both carry ``not_running`` (the spaces found, with ``space_status``,
    ``app_status`` and ``instance_type``) and ``domains`` (the fully searched domains, with ``default_space_role`` and
    ``max_ebs_gb``) for the create-or-start choice. Raises AwsCallError if nothing was found and
    some domain failed for a reason other than AccessDenied, or for any reason with ``domain_id``.
    When more than one space is returned (in different domains), the caller asks the user which
    space to use.
    """
    sm = _sm_client(region)
    region = sm.meta.region_name
    own_account = _own_account(region)  # fails closed: no account, no match
    if domain_id:
        try:
            domains = [sm.describe_domain(DomainId=domain_id)]
        except Exception as e:
            if isinstance(e, SdkUnavailableError) or _is_sdk_model_error(e):
                raise  # neither is this domain's: main() reports them
            if _is_not_found(e) or _error_code(e) == "ValidationException":
                err = SpaceNotFoundError(
                    f"Domain '{domain_id}' was not found in {region} ({type(e).__name__})."
                )
                err.not_running, err.domains = [], []
                raise err from None
            raise AwsCallError(f"DescribeDomain '{domain_id}' failed: {_aws_error(e)}") from None
    else:
        domains = [d for d in _list_domains(sm) if d.get("Status") == "InService"]

    found, not_running, searched = [], [], []
    skipped = [] if skipped is None else skipped  # domains the caller may not read
    errors = (
        []
    )  # domains that failed for another reason (throttling, bad state), or any error with domain_id
    for d in domains:
        did, dname = d["DomainId"], d.get("DomainName", d["DomainId"])
        try:
            if space_name:
                space = _describe_space_or_none(sm, did, space_name)
                if space and not is_label_studio_space_named(sm, did, space, own_account):
                    space = None  # a space of that name, but not on the Label Studio image or not shared
            else:
                space = find_space_in_domain(sm, did, own_account)
            app = _app_status(sm, did, space["SpaceName"]) if space else None
        except SdkUnavailableError:
            raise  # the same in every domain: not a per-domain failure
        except ValueError as e:
            if _is_sdk_model_error(e):
                raise  # an SDK modeling error, not this domain's: main() reports it (exit 5)
            errors.append(f"{dname} ({did}): {_error_code(e)}")
            continue
        except Exception as e:  # one domain must not stop the others from being searched
            if domain_id or _error_code(e) not in _ACCESS_DENIED:
                errors.append(f"{dname} ({did}): {_error_code(e)}")
            else:
                skipped.append(f"{dname} ({did})")
            continue
        searched.append(d)
        if not space:
            continue
        info = _space_info(region, did, dname, space)
        if space.get("Status") == "InService" and app == "InService":
            found.append(info)
        else:
            spec = ((space.get("SpaceSettings") or {}).get("JupyterLabAppSettings") or {}).get(
                "DefaultResourceSpec"
            ) or {}
            not_running.append(
                {
                    **asdict(info),
                    "space_status": space.get("Status"),
                    "app_status": app,
                    "instance_type": spec.get("InstanceType"),
                }
            )

    skipped.extend(f"{e} (error)" for e in errors)
    if found:
        return found
    if errors:
        # Nothing found, but some domains could not be searched: retryable, not "launch the app".
        retry = any(not e.endswith(_ACCESS_DENIED) for e in errors)
        hint = (
            "Retry once."
            if retry
            else "Grant ListSpaces/ListApps/DescribeSpace there; retrying won't help."
        )
        raise AwsCallError(
            f"Search for the Label Studio space failed in: {'; '.join(errors)}. {hint}"
        )
    denied = (
        f" These domains could not be fully checked (access denied): {', '.join(skipped)}."
        if skipped
        else ""
    )
    if not_running:
        names = ", ".join(
            f"'{s['space_name']}' in {s['domain_name']} ({s['domain_id']})" for s in not_running
        )
        err = AppNotRunningError(
            f"Label Studio space {names} exists but Label Studio is not running.{denied} "
            + LAUNCH_INSTRUCTIONS
        )
    else:
        wanted = f"named '{space_name}' " if space_name else ""
        # no first-party image here (or no way to tell), so launching from Studio or 'create' can't help
        launch = _no_label_studio_here(region) or LAUNCH_INSTRUCTIONS
        err = SpaceNotFoundError(
            f"No Label Studio space {wanted}(a shared JupyterLab space on the "
            f"{LS_IMAGE_NAME} image) found in {region}.{denied} " + launch
        )
    err.not_running = not_running
    err.domains = _domain_candidates(sm, searched)
    raise err


# ---------------------------------------------------------------------------
# AWS side: create the space, start its app
# ---------------------------------------------------------------------------


def _progress(message: str) -> None:
    """One progress line on stderr while create/start waits; the error JSON stays the last line."""
    print(json.dumps({"progress": message}), file=sys.stderr, flush=True)


def load_image_config(region: str, path: Optional[str] = None) -> dict:
    """The first-party Label Studio image for ``region``: {account, imageName, alias}."""
    table = _image_table(path)
    if table is None:
        raise UsageError(IMAGE_TABLE_UNREADABLE)
    if region not in table:
        raise UsageError(
            f"No Label Studio image is listed for {region}. Regions with one: "
            f"{', '.join(sorted(table))}."
        )
    return table[region]


def _partition(region: str) -> str:
    if region.startswith("cn-"):
        return "aws-cn"
    if region.startswith("us-gov-"):
        return "aws-us-gov"
    return "aws"


def label_studio_image_arn(region: str, image: dict) -> str:
    return (
        f"arn:{_partition(region)}:sagemaker:{region}:{image['account']}:image/{image['imageName']}"
    )


def new_space_name(now: Optional[datetime] = None) -> str:
    """label-studio-<UTC YYYYMMDDHHMMSS>: never a user's own space name, and valid as one."""
    return LS_SPACE_NAME_PREFIX + (now or datetime.now(timezone.utc)).strftime("%Y%m%d%H%M%S")


def _is_in_use(e: Exception) -> bool:
    return _error_code(e) in ("ResourceInUse", "ResourceInUseException")


def _already_exists(e: Exception) -> bool:
    # SageMaker returns ResourceInUse both for an existing resource and a busy one; only the
    # message tells them apart.
    return _is_in_use(e) and bool(re.search(r"already exists|already in use", str(e), re.I))


def _with_busy_retry(call, sleep=time.sleep) -> bool:
    """Run ``call``; retry while SageMaker reports the resource busy. True if it already exists."""
    for attempt in range(BUSY_RETRIES):
        try:
            call()
            return False
        except Exception as e:
            if _already_exists(e):
                return True
            if _is_in_use(e) and attempt < BUSY_RETRIES - 1:
                sleep(BUSY_RETRY_BASE_S * (attempt + 1))
                continue
            raise
    return False


def _wait_space_in_service(sm, domain_id: str, space_name: str, sleep) -> dict:
    for attempt in range(MAX_POLLS):
        try:
            space = sm.describe_space(DomainId=domain_id, SpaceName=space_name)
        except Exception as e:
            if _is_not_found(e):
                raise LaunchError(f"Space '{space_name}' was not found.") from None
            raise
        status = space.get("Status")
        _progress(f"space {space_name}: {status}")
        if status == "InService":
            return space
        if status in (*_FAILED_SPACE_STATUSES, "Deleting"):
            raise LaunchError(
                f"Space '{space_name}' is {status}: {space.get('FailureReason') or 'no reason given'}."
            )
        if attempt < MAX_POLLS - 1:
            sleep(POLL_INTERVAL_S)
    raise LaunchError(
        f"Space '{space_name}' did not reach InService within {MAX_POLLS * POLL_INTERVAL_S} s. "
        "Run discover to check it again."
    )


def _describe_app(sm, domain_id: str, space_name: str) -> dict:
    """DescribeApp for the space's Label Studio app, or {} when there is none."""
    try:
        return sm.describe_app(
            DomainId=domain_id, SpaceName=space_name, AppType="JupyterLab", AppName=LS_APP_NAME
        )
    except Exception as e:
        if _is_not_found(e):
            return {}
        raise


def _wait_app_gone(sm, domain_id: str, space_name: str, sleep) -> None:
    for attempt in range(MAX_POLLS):
        status = _describe_app(sm, domain_id, space_name).get("Status")
        _progress(f"app in {space_name}: {status or 'gone'}")
        if status in (None, "Deleted"):
            return
        if attempt < MAX_POLLS - 1:
            sleep(POLL_INTERVAL_S)
    raise LaunchError(
        f"The failed app in '{space_name}' was not removed within {MAX_POLLS * POLL_INTERVAL_S} s."
    )


def _wait_app_in_service(sm, domain_id: str, space_name: str, sleep) -> str:
    for attempt in range(MAX_POLLS):
        app = _describe_app(
            sm, domain_id, space_name
        )  # right after CreateApp it can be not found yet
        status = app.get("Status")
        _progress(f"app in {space_name}: {status or 'not created yet'}")
        if status == "InService":
            return status
        if status == "Failed":
            raise LaunchError(
                f"Label Studio failed to start in '{space_name}': "
                f"{app.get('FailureReason') or 'no reason given'}."
            )
        if status in ("Deleting", "Deleted"):  # the space is shared: another user can stop it
            raise LaunchError(f"The app in '{space_name}' was stopped while it was starting.")
        if attempt < MAX_POLLS - 1:
            sleep(POLL_INTERVAL_S)
    raise LaunchError(
        f"Label Studio did not start in '{space_name}' within {MAX_POLLS * POLL_INTERVAL_S} s. "
        "Run discover to check it again."
    )


def _describe_domain(sm, domain_id: str) -> dict:
    try:
        return sm.describe_domain(DomainId=domain_id)
    except Exception as e:
        if _is_not_found(e) or _error_code(e) == "ValidationException":
            raise UsageError(
                f"Domain '{domain_id}' was not found in {sm.meta.region_name}."
            ) from None
        raise


def start_label_studio_app(
    space_name: str,
    domain_id: str,
    region: Optional[str] = None,
    wait: bool = True,
    sleep=time.sleep,
    sm=None,
    domain: Optional[dict] = None,
    replace_failed_app: bool = False,
) -> dict:
    """Start the Label Studio app in an existing Label Studio space.

    A Failed app never recovers, so it is deleted and created again, but only with
    ``replace_failed_app`` (the user approved it); without it a Failed app is a UsageError and
    nothing changes. The space and its storage are always kept. The app is space-scoped (no user profile), so any domain user can start it. With
    ``wait``, returns once the app is InService; without it, once CreateApp is accepted.
    """
    sm = sm or _sm_client(region)
    domain = domain or _describe_domain(sm, domain_id)
    space = _describe_space_or_none(sm, domain_id, space_name)
    if not space:
        raise UsageError(f"Space '{space_name}' was not found in domain '{domain_id}'.")
    if not is_label_studio_space_named(sm, domain_id, space, _own_account(sm.meta.region_name)):
        why = _no_label_studio_here(sm.meta.region_name)
        if why:
            raise UsageError(why)
        raise UsageError(
            f"'{space_name}' is not a shared space on the {LS_IMAGE_NAME} image; "
            "the skill starts only a Label Studio space."
        )
    space = _wait_space_in_service(sm, domain_id, space_name, sleep)
    status = _describe_app(sm, domain_id, space_name).get("Status")
    replaced_failed_app = False
    if status == "Failed" and not replace_failed_app:
        info = _space_info(
            sm.meta.region_name, domain_id, domain.get("DomainName", domain_id), space
        )
        raise FailedAppError(
            f"The app in '{space_name}' has Failed. Replacing it deletes the failed app (the space "
            "and its projects are kept); run start again with --replace-failed-app once the user "
            "approves.",
            asdict(info),
        )
    if status == "Failed":
        auto_deleted = False
        try:
            sm.delete_app(
                DomainId=domain_id, SpaceName=space_name, AppType="JupyterLab", AppName=LS_APP_NAME
            )
        except Exception as e:
            # DeleteApp rejects a Failed app SageMaker has already removed, though DescribeApp keeps
            # reporting Failed for a day: don't wait for it. CreateApp below still fails loudly.
            if _error_code(e) == "ValidationException":
                auto_deleted = True
            elif not _is_not_found(e):
                raise
        if not auto_deleted:
            _wait_app_gone(sm, domain_id, space_name, sleep)
        status, replaced_failed_app = None, True
    elif status == "Deleting":
        _wait_app_gone(sm, domain_id, space_name, sleep)
        status = None
    if status in (None, "Deleted"):
        _with_busy_retry(
            lambda: sm.create_app(
                DomainId=domain_id, SpaceName=space_name, AppType="JupyterLab", AppName=LS_APP_NAME
            ),
            sleep,
        )
        status = "Pending"
    if wait and status != "InService":
        status = _wait_app_in_service(sm, domain_id, space_name, sleep)
    info = _space_info(sm.meta.region_name, domain_id, domain.get("DomainName", domain_id), space)
    return {"space": asdict(info), "app_status": status, "replaced_failed_app": replaced_failed_app}


def create_label_studio_space(
    domain_id: str,
    admin_profile: str,
    region: Optional[str] = None,
    ebs_gb: int = DEFAULT_EBS_GB,
    wait: bool = True,
    sleep=time.sleep,
    now: Optional[datetime] = None,
) -> dict:
    """Create the domain's Label Studio space (unless one exists) and start its app.

    Looks for the domain's Label Studio space again right before creating, and creates one only
    when there is none: shared, owned by ``admin_profile``, named label-studio-<UTC timestamp>,
    on the first-party image for the region. If an older Label Studio space shows up right after,
    that one is used and the new space is reported in ``unused_space``; nothing is ever deleted.
    If the space it ends up with has a Failed app, the app is left as it is and ``app_status`` is
    "Failed": replacing it is ``start --replace-failed-app``, after the user approves.
    """
    sm = _sm_client(region)
    region = sm.meta.region_name
    domain = _describe_domain(sm, domain_id)
    settings = _domain_settings(domain)
    if not settings["default_space_role"]:
        raise DomainNotReadyError(MISSING_SPACE_ROLE)
    if admin_profile not in list_annotator_profiles(domain_id, region):
        raise UsageError(
            f"'{admin_profile}' is not an InService user profile in domain '{domain_id}'."
        )

    own_account = _own_account(region)
    existing = find_space_in_domain(sm, domain_id, own_account)
    created, unused = None, None
    if existing:
        space_name = existing["SpaceName"]
    else:
        # Only a new space needs the image and a volume size; a reused space keeps its own.
        max_gb = settings["max_ebs_gb"]
        if ebs_gb < DEFAULT_EBS_GB or (max_gb and ebs_gb > max_gb):
            raise UsageError(
                f"--ebs-gb must be at least {DEFAULT_EBS_GB}"
                + (f" and at most {max_gb}, this domain's limit." if max_gb else ".")
            )
        image = load_image_config(region)
        space_name = new_space_name(now)
        _progress(f"creating space {space_name}")
        already = _with_busy_retry(
            lambda: sm.create_space(
                DomainId=domain_id,
                SpaceName=space_name,
                SpaceDisplayName=LS_SPACE_DISPLAY_NAME,
                OwnershipSettings={"OwnerUserProfileName": admin_profile},
                SpaceSharingSettings={"SharingType": "Shared"},
                SpaceSettings={
                    "AppType": "JupyterLab",
                    "JupyterLabAppSettings": {
                        "DefaultResourceSpec": {
                            "SageMakerImageArn": label_studio_image_arn(region, image),
                            "SageMakerImageVersionAlias": image["alias"],
                            "InstanceType": DEFAULT_INSTANCE_TYPE,
                        }
                    },
                    "SpaceStorageSettings": {"EbsStorageSettings": {"EbsVolumeSizeInGb": ebs_gb}},
                },
            ),
            sleep,
        )
        if (
            already
        ):  # created by someone else in the same second: continue only if it is a Label Studio space
            other = _describe_space_or_none(sm, domain_id, space_name)
            if not (other and is_label_studio_space(other, own_account)):
                raise LaunchError(
                    f"A space named '{space_name}' already exists and is not a Label Studio space."
                )
        else:
            created = space_name
            # Two launches can both pass the check above: keep the older space.
            oldest = find_space_in_domain(sm, domain_id, own_account)
            if oldest and oldest["SpaceName"] != space_name:
                unused, space_name = space_name, oldest["SpaceName"]
    try:
        result = start_label_studio_app(
            space_name, domain_id, region, wait, sleep, sm=sm, domain=domain
        )
    except FailedAppError as e:  # an existing space's app failed: report it with what create did
        result = {"space": e.space, "app_status": "Failed", "replaced_failed_app": False}
    return {**result, "created_space": created, "unused_space": unused}


def estimate_storage(records_path: str) -> dict:
    """Expected growth of the Label Studio database for one annotation per record: 2S + N/2 KB."""
    size = os.path.getsize(records_path)
    with open(records_path, encoding="utf-8") as f:
        count = sum(1 for line in f if line.strip())
    estimate = 2 * size + count * 512
    return {
        "records": count,
        "file_bytes": size,
        "estimated_gb": round(estimate / 1024**3, 3),
        "default_gb": DEFAULT_EBS_GB,
    }


def list_annotator_profiles(domain_id: str, region: Optional[str] = None) -> list:
    """SageMaker user profile names in the domain (InService only), sorted."""
    sm = _sm_client(region)
    names, token = [], None
    while True:
        kwargs = {"DomainIdEquals": domain_id}
        if token:
            kwargs["NextToken"] = token
        resp = sm.list_user_profiles(**kwargs)
        names += [
            p["UserProfileName"]
            for p in resp.get("UserProfiles", [])
            if p.get("Status") == "InService"
        ]
        token = resp.get("NextToken")
        if not token:
            return sorted(names)


# ---------------------------------------------------------------------------
# Label Studio side: REST through the Studio proxy
# ---------------------------------------------------------------------------


_FIELD_NAME = re.compile(r"[A-Za-z0-9_]{1,40}")


def _rejected_fields(body: bytes) -> str:
    """' (fields: a, b)' for a Label Studio validation error, else ''.

    Only the names of the rejected fields are kept, never Label Studio's message text:
    an error body can echo project titles, task data or annotations, which others wrote.
    """
    try:
        data = json.loads(body[:20000])
    except ValueError:
        return ""
    errors = data.get("validation_errors") if isinstance(data, dict) else None
    names = (
        [k for k in errors if isinstance(k, str) and _FIELD_NAME.fullmatch(k)][:5]
        if isinstance(errors, dict)
        else []
    )
    return f" (fields: {', '.join(names)})" if names else ""


def _presigned_url(space: SpaceInfo, profile: str) -> str:
    """One presigned URL for ``profile`` in the space, valid URL_EXPIRES_S. Never log or store it."""
    return _sm_client(space.region).create_presigned_domain_url(
        DomainId=space.domain_id,
        UserProfileName=profile,
        SpaceName=space.space_name,
        ExpiresInSeconds=URL_EXPIRES_S,
        SessionExpirationDurationInSeconds=1800,  # the API's minimum session length
    )["AuthorizedUrl"]


def check_admin_profile(space: SpaceInfo, profile: str, profiles: list) -> dict:
    """Can these credentials open the space as ``profile``? AWS only; nothing is opened.

    Mints one presigned URL for ``profile`` (valid URL_EXPIRES_S) and discards it unopened, so
    no Label Studio session starts; the URL is never printed or stored. ``ok`` is False with
    ``error`` when ``profile`` is not one of ``profiles`` or IAM denies CreatePresignedDomainUrl
    on it. Credential, throttling and network failures are raised (AwsCallError, exit 5).
    """
    if profile not in profiles:
        return {"profile": profile, "ok": False, "error": "NotADomainProfile"}
    try:
        _presigned_url(space, profile)
    except Exception as e:  # botocore ClientError / NoCredentialsError
        if _error_code(e) in _ACCESS_DENIED:
            return {"profile": profile, "ok": False, "error": _error_code(e)}
        raise AwsCallError(
            f"CreatePresignedDomainUrl for profile '{profile}' failed: {_aws_error(e)}"
        ) from None
    return {"profile": profile, "ok": True}


class LabelStudioSession:
    """Authenticated HTTP session to Label Studio, acting as ``admin_profile``."""

    def __init__(self, space: SpaceInfo, admin_profile: str):
        self.space = space
        self.admin_profile = admin_profile
        self.jar = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(self.jar),
            urllib.request.HTTPSHandler(context=ssl.create_default_context()),
        )
        self._connected = False

    def _mint_url(self) -> str:
        """A fresh presigned URL for ``admin_profile``, valid for URL_EXPIRES_S. Never logged or stored."""
        try:
            return _presigned_url(self.space, self.admin_profile)
        except Exception as e:  # botocore ClientError / NoCredentialsError
            raise AwsCallError(
                f"CreatePresignedDomainUrl for profile '{self.admin_profile}' failed: {_aws_error(e)}"
            ) from None

    def _redeem(self, authorized_url: str) -> bool:
        """Open the URL once, setting the Studio session cookies. False if Studio says it expired.

        Checked live in a space: a URL opened after its 5 s answers HTTP 403 with
        "Invalid or Expired Auth Token", and a URL opened in time ends on the space's own host.
        The API reference says an expired URL goes to the AWS console sign-in page, so a redirect
        off the space's host also counts as expired.
        """
        try:
            with self.opener.open(authorized_url, timeout=90) as r:
                body = r.read(65536)
                if (
                    urllib.parse.urlparse(r.geturl()).netloc
                    != urllib.parse.urlparse(self.space.space_url).netloc
                ):
                    return False
        except urllib.error.HTTPError as e:
            if e.code in (401, 403):
                return False
            raise LabelStudioError(
                f"Could not open a Studio session for space '{self.space.space_name}': "
                f"HTTP {e.code}"
            ) from None
        except OSError as e:  # URLError, socket timeout
            raise LabelStudioError(
                f"Could not open a Studio session for space '{self.space.space_name}': "
                f"{type(e).__name__}"
            ) from None
        return b"Invalid or Expired" not in body

    def connect(self) -> "LabelStudioSession":
        # A short-lived URL can expire on a slow link before it is opened: mint one fresh URL and try
        # again, once. A URL is never reused.
        if not self._redeem(self._mint_url()) and not self._redeem(self._mint_url()):
            raise LabelStudioError(
                f"Studio rejected the session URL for space '{self.space.space_name}' twice: usually it "
                f"expired ({URL_EXPIRES_S}s) before it was opened on a slow link, or an IAM condition on "
                f"the caller (source IP, VPC endpoint) refused it."
            )
        self._connected = True
        self._wait_until_ready()
        return self

    def _wait_until_ready(self) -> None:
        """GET the project list page until LS answers. Also sets csrftoken."""
        deadline = time.time() + READY_TIMEOUT_S
        last = ""
        while True:
            left = deadline - time.time()
            if left <= 0:
                break
            if last:  # stdout is the command's JSON result, so progress goes to stderr
                print(
                    f"Waiting for Label Studio in space '{self.space.space_name}' to answer ({last}); "
                    f"{int(left)}s left",
                    file=sys.stderr,
                )
            try:
                with self.opener.open(f"{self.space.ls_base_url}/projects/", timeout=30) as r:
                    r.read()
                    if r.status == 200:
                        return
                    last = f"HTTP {r.status}"
            except urllib.error.HTTPError as e:
                last = f"HTTP {e.code}"
            except urllib.error.URLError as e:
                last = str(e.reason)
            except OSError as e:  # socket timeout, connection reset
                last = f"{type(e).__name__}: {e}"
            time.sleep(5)
        raise LabelStudioError(
            f"Label Studio in space '{self.space.space_name}' did not respond within "
            f"{READY_TIMEOUT_S}s ({last}). "
            + LAUNCH_INSTRUCTIONS.format(space_name=self.space.space_name)
        )

    def _csrf(self) -> str:
        for c in self.jar:
            if c.name == "csrftoken":
                return c.value
        return ""

    def request(self, method: str, path: str, body=None):
        if not self._connected:
            self.connect()
        headers = {"Accept": "application/json"}
        data = None
        if body is not None:
            data = json.dumps(body).encode()
            headers["Content-Type"] = "application/json"
        if method != "GET":
            # Django CSRF: token cookie echoed in a header, Origin in CSRF_TRUSTED_ORIGINS.
            headers["X-CSRFToken"] = self._csrf()
            headers["Origin"] = self.space.space_url
            headers["Referer"] = f"{self.space.ls_base_url}/projects/"
        req = urllib.request.Request(
            f"{self.space.ls_base_url}{path}", data=data, headers=headers, method=method
        )
        try:
            with self.opener.open(req, timeout=120) as r:
                raw = r.read()
        except urllib.error.HTTPError as e:
            raise LabelStudioError(
                f"{method} {path} -> HTTP {e.code}{_rejected_fields(e.read())}"
            ) from None
        except OSError as e:  # URLError, socket timeout, connection reset
            raise LabelStudioError(f"{method} {path} failed: {type(e).__name__}: {e}") from None
        if not raw:
            return None
        try:
            return json.loads(raw)
        except ValueError:
            raise LabelStudioError(
                f"{method} {path} returned non-JSON (likely the login page; autologin did not sign in "
                f"'{self.admin_profile}')."
            ) from None

    # -- resources ---------------------------------------------------------

    def list_projects(self) -> list:
        out, page = [], 1
        while True:
            resp = self.request("GET", f"/api/projects/?page={page}&page_size=100")
            if isinstance(resp, list):
                return resp
            out += resp.get("results", [])
            if not resp.get("next"):
                return out
            page += 1

    def get_project(self, project_id: int) -> dict:
        return self.request("GET", f"/api/projects/{project_id}/")

    def create_project(self, title: str, label_config: str, description: str = "") -> dict:
        return self.request(
            "POST",
            "/api/projects/",
            {"title": title, "label_config": label_config, "description": description},
        )

    def import_tasks(self, project_id: int, tasks: list) -> dict:
        return self.request("POST", f"/api/projects/{project_id}/import", tasks)

    def list_users(self) -> list:
        resp = self.request("GET", "/api/users/")
        return resp.get("results", []) if isinstance(resp, dict) else (resp or [])

    def list_task_counters(self, project_id: int) -> list:
        """[(total_annotations, cancelled_annotations)] per task; Label Studio's own per-task counters."""
        out, page = [], 1
        while True:
            try:
                resp = self.request(
                    "GET", f"/api/tasks/?project={project_id}&page={page}&page_size=100"
                )
            except LabelStudioError as e:
                if "HTTP 404" in str(e) and out:  # past the last page
                    return out
                raise
            tasks = (resp or {}).get("tasks", []) if isinstance(resp, dict) else (resp or [])
            out += [
                (t.get("total_annotations") or 0, t.get("cancelled_annotations") or 0)
                for t in tasks
            ]
            total = resp.get("total") if isinstance(resp, dict) else None
            if not tasks or (total is not None and len(out) >= total):
                return out
            page += 1

    def export_project(self, project_id: int) -> list:
        return (
            self.request(
                "GET", f"/api/projects/{project_id}/export?exportType=JSON&download_all_tasks=true"
            )
            or []
        )


# ---------------------------------------------------------------------------
# Workflow helpers the skill calls
# ---------------------------------------------------------------------------


def _split_records(records: list, n_chunks: int) -> list:
    """Contiguous split in file order; sizes differ by at most one (the first chunks take the remainder)."""
    if n_chunks <= 0:
        return []
    base, extra = divmod(len(records), n_chunks)
    chunks, start = [], 0
    for i in range(n_chunks):
        size = base + (1 if i < extra else 0)
        chunks.append(records[start : start + size])
        start += size
    return chunks


def _hidden_by_default(key: str) -> bool:
    """A field the upload drops when no ``data_fields`` are named: a ``_``-prefixed field,
    such as review.jsonl's ``_review_reason`` tag."""
    return key.startswith("_")


def _id_problem_message(report: dict, id_field: str) -> str:
    parts = []
    if report["missing"]:
        rows = ", ".join(str(n) for n in report["missing"][:5])
        parts.append(f"{len(report['missing'])} record(s) have no {id_field} (rows {rows})")
    if report["duplicates"]:
        parts.append(
            f"{len(report['duplicates'])} {id_field} value(s) are shared by several records "
            f"({', '.join(report['duplicates'][:5])})"
        )
    return "; ".join(parts) + ". Nothing was created: the export is joined back on this id."


def _to_task(
    record: dict, data_fields: Optional[list] = None, hide_fields=(), id_field: str = "id"
) -> dict:
    """The task imported for one record: with ``data_fields`` only ``id`` (and ``id_field``),
    ``unique_id`` and those fields; without, every field except a ``_``-prefixed one. A
    ``hide_fields`` name is never imported, such as auto-labeling's ``split`` tag, which has
    no ``_`` prefix.

    Label Studio's Data Manager lists every task-data key as a column, so a field left
    in a record is shown to the annotator. A blind review (auto-labeling's review.jsonl
    or cold-start sample) passes its input fields, so a task carries nothing else of the
    record. Without them the upload still drops every ``_``-prefixed field, such as
    review.jsonl's ``_review_reason`` tag, so a spot-check row looks like every other row
    (route_to_review.py already keeps the model's answer out of the file). ``unique_id``
    is still the hash of the whole record, and the record is not changed, so the caller
    keeps it for the fold, which joins on ``id``.
    """
    hidden = set(hide_fields or ())
    if data_fields is None:
        data = {k: v for k, v in record.items() if not _hidden_by_default(k) and k not in hidden}
    else:
        keep = list(dict.fromkeys(["id", id_field, "unique_id"] + list(data_fields)))
        data = {k: record[k] for k in keep if k in record and k not in hidden}
    if "unique_id" not in data:
        data["unique_id"] = hashlib.sha256(
            json.dumps(record, sort_keys=True).encode()
        ).hexdigest()  # the whole SHA-256 hex digest
    return {"data": data}


def _abbreviate(name: str) -> str:
    """'massive-intent-review' -> 'massive-ir': first word plus initials of the rest."""
    words = [w for w in name.split("-") if w]
    if len(words) < 2:
        return name
    return f"{words[0]}-{''.join(w[0] for w in words[1:])}"


def _shorten_name(name: str, room: int) -> str:
    """Fit ``name`` in ``room`` chars: leading whole words (2+), else abbreviation, else cut."""
    if len(name) <= room:
        return name
    words = [w for w in name.split("-") if w]
    for n in range(len(words) - 1, 1, -1):
        prefix = "-".join(words[:n])
        if len(prefix) <= room:
            return prefix
    abbrev = _abbreviate(name)
    if len(abbrev) <= room:
        return abbrev
    return abbrev[: max(room, 1)].rstrip("-")


def project_title(project_name: str, profile: str, run_id: str, limit: int = TITLE_MAX_LEN) -> str:
    """``<project_name>-<profile>-<run_id>``, shortened to fit Label Studio's title limit.

    The annotator's profile is kept whole whenever possible; the project name is
    shortened first. Steps, stopping at the first that fits:

      1. full title
      2. run id without the year: ``1008-003612``
      3. run id as ``MMDD-HHMM`` plus a 4-char hash of the full title (keeps
         titles unique), project name shortened (leading whole words, else
         ``massive-ir``-style abbreviation, else cut), and
         the profile cut only if it alone would not leave room for the project
         name (it keeps at least its first 28 characters)

    Full names are always in the project description (``assignment_marker``).
    """
    full = f"{project_name}-{profile}-{run_id}"
    if len(full) <= limit:
        return full
    is_std = len(run_id) == 15 and run_id[8] == "-"  # YYYYMMDD-HHMMSS
    no_year = run_id[4:] if is_std else run_id
    if len(f"{project_name}-{profile}-{no_year}") <= limit:
        return f"{project_name}-{profile}-{no_year}"

    run = run_id[4:13] if is_std else run_id[-9:]
    tag = f"~{hashlib.sha256(full.encode()).hexdigest()[:4]}-{run}"
    room = limit - len(tag)  # for "<project>-<profile>"
    abbrev = _abbreviate(project_name)
    prof = profile
    if len(prof) > room - 1 - min(len(abbrev), 6):
        prof = profile[: max(room - 1 - min(len(abbrev), 6), 1)].rstrip("-")
    proj = _shorten_name(project_name, room - 1 - len(prof))
    title = f"{proj}-{prof}{tag}"
    return title[:limit]


def assignment_marker(project_name: str, profile: str, run_id: str) -> str:
    """Machine-readable line in the project description; titles may be shortened."""
    return f"[hil project={project_name} profile={profile} run={run_id}]"


def setup_projects(
    space: SpaceInfo,
    admin_profile: str,
    annotators: list,
    label_config: str,
    data_records: list,
    project_name: str,
    description: str = "",
    session: Optional[LabelStudioSession] = None,
    data_fields: Optional[list] = None,
    relabel_of: Optional[str] = None,
    hide_fields: Optional[list] = None,
    id_field: Optional[str] = None,
) -> SetupResult:
    """Split ``data_records`` evenly and create one project per annotator.

    ``relabel_of`` (an approval entry id) marks the projects as a relabel round: export
    --approval-id puts their tasks in place of the discarded ones (``apply_discards``).

    ``data_fields`` limits each task to ``id``, ``unique_id`` and those fields
    (``_to_task``; a single string is one field); a field no record has is refused
    before anything is created. ``hide_fields`` names fields no task carries; a
    ``data_fields`` name among them is refused. ``id_field`` requires every record to
    carry a non-empty value there that no other record shares (``record_id_problems``),
    and keeps it in each task; otherwise nothing is created.
    """
    if not annotators:
        raise ValueError("At least one annotator profile is required.")
    if isinstance(data_fields, str):
        data_fields = [data_fields]
    if isinstance(hide_fields, str):
        hide_fields = [hide_fields]
    hide_fields = list(hide_fields or [])
    if data_fields is not None:
        if not data_fields:
            raise UsageError("--data-fields names no field; name the record fields annotators see.")
        unknown = [f for f in data_fields if not any(f in r for r in data_records)]
        if unknown:
            raise UsageError(f"--data-fields names fields no record has: {', '.join(unknown)}.")
        shown_hidden = [f for f in data_fields if f in hide_fields]
        if shown_hidden:
            raise UsageError(
                f"--data-fields names fields --hide-fields hides: {', '.join(shown_hidden)}."
            )
    if (id_field or "id") in hide_fields:  # without --id-field the task still keeps `id`
        raise UsageError(
            f"--hide-fields names the id field {id_field or 'id'}; the export must carry it."
        )
    if id_field:
        report = record_id_problems(data_records, id_field)
        if report["missing"] or report["duplicates"]:
            raise UsageError(_id_problem_message(report, id_field))
    if len(data_records) < len(annotators):
        raise UsageError(
            f"{len(data_records)} records can't be split across {len(annotators)} annotators without "
            "leaving some with an empty project; choose fewer annotators."
        )
    session = session or LabelStudioSession(space, admin_profile).connect()
    run_id = datetime.now().strftime("%Y%m%d-%H%M%S")
    created_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    result = SetupResult(
        space=space,
        admin_profile=admin_profile,
        run_id=run_id,
        project_name=project_name,
        created_at=created_at,
        relabel_of=relabel_of,
    )
    for annotator, chunk in zip(annotators, _split_records(data_records, len(annotators))):
        title = project_title(project_name, annotator, run_id)
        desc = (
            (description or f"Assigned to SageMaker profile {annotator}")
            + "\n"
            + assignment_marker(project_name, annotator, run_id)
        )
        try:
            project = session.create_project(title, label_config, desc)
        except LabelStudioError as e:
            if not result.annotator_links:
                raise  # nothing was created: a plain failure, not a partial setup
            raise SetupPartialError(result, annotator, e) from None
        if chunk:
            try:
                session.import_tasks(
                    project["id"],
                    [_to_task(r, data_fields, hide_fields, id_field or "id") for r in chunk],
                )
            except LabelStudioError as e:
                # The project exists but holds no tasks; record it so it isn't left untracked.
                result.annotator_links.append(
                    AnnotatorLink(
                        annotator, project["id"], title, space.project_url(project["id"]), 0
                    )
                )
                raise SetupPartialError(result, annotator, e) from None
        result.annotator_links.append(
            AnnotatorLink(
                annotator, project["id"], title, space.project_url(project["id"]), len(chunk)
            )
        )
    return result


def get_progress(
    space: SpaceInfo,
    admin_profile: str,
    assignments: dict,
    session: Optional[LabelStudioSession] = None,
) -> dict:
    """Per-annotator progress for ``assignments`` ({profile: {"project_id": id, ...}}).

    Each task is counted once, from Label Studio's per-task counters:
    completed = has a non-skipped annotation; skipped = only skipped
    annotations; remaining = no annotation yet. (Project-level
    ``skipped_annotations_number`` counts annotations, so a task skipped and
    later completed — or skipped twice — would be counted more than once.)
    """
    session = session or LabelStudioSession(space, admin_profile).connect()
    rows = []
    for profile, a in assignments.items():
        counters = session.list_task_counters(a["project_id"])
        total = len(counters)
        done = sum(1 for done_n, _ in counters if done_n > 0)
        skipped = sum(1 for done_n, skip_n in counters if done_n == 0 and skip_n > 0)
        rows.append(
            {
                "profile": profile,
                "project_id": a["project_id"],
                "title": a.get("title"),
                "total": total,
                "completed": done,
                "skipped": skipped,
                "remaining": total - done - skipped,
                "pct": round(100.0 * done / total, 1) if total else 0.0,
                "url": space.project_url(a["project_id"]),
            }
        )
        if a.get("task_count") is not None and total != a["task_count"]:
            rows[-1]["task_count_changed"] = {"at_setup": a["task_count"], "now": total}
    totals = {k: sum(r[k] for r in rows) for k in ("total", "completed", "skipped", "remaining")}
    totals["pct"] = (
        round(100.0 * totals["completed"] / totals["total"], 1) if totals["total"] else 0.0
    )
    return {
        "annotators": rows,
        "totals": totals,
        "all_done": bool(rows) and totals["remaining"] == 0,
        "task_count_changed": [r["profile"] for r in rows if "task_count_changed" in r],
    }


def progress_markdown(progress: dict) -> str:
    lines = [
        "| Annotator | Completed | Skipped | Remaining | Progress |",
        "|---|---|---|---|---|",
    ]
    for r in progress["annotators"]:
        lines.append(
            f"| `{r['profile']}` | {r['completed']}/{r['total']} | {r['skipped']} | {r['remaining']} | {r['pct']}% |"
        )
    t = progress["totals"]
    lines.append(
        f"| **Total** | **{t['completed']}/{t['total']}** | {t['skipped']} | {t['remaining']} | **{t['pct']}%** |"
    )
    return "\n".join(lines)


ATTRIBUTION_ROWS_SHOWN = 50  # rows listed in attribution_summary; the counts are always exact


def _user_profile(user, users: dict) -> Optional[str]:
    """Profile name for a Label Studio user (an id or an object): ``<profile>@studio.local`` -> profile."""
    uid = user.get("id") if isinstance(user, dict) else user
    email = users.get(uid) or (user.get("email") if isinstance(user, dict) else None)
    return email.split("@")[0] if email and email.endswith("@studio.local") else None


def attribution_flags(assigned_profile: str, annotations: list) -> list:
    """Why a task's annotations are not simply its assigned annotator's own work.

    ``other_annotator``: an annotation (or skip) was made by another profile. ``unknown_annotator``:
    its user is not a ``<profile>@studio.local`` user. ``edited_by_other``: the last editor
    (Label Studio sets ``updated_by`` itself) differs from the submitter or isn't a studio.local
    user. ``multiple_annotations``:
    more than one annotation that wasn't skipped. Attribution is best-effort; what it can't
    catch: ``references/label-studio-space.md`` → Attribution.
    """
    flags = set()
    for ann in annotations:
        by = ann.get("completed_by_profile")
        if by is None:
            flags.add("unknown_annotator")
        elif by != assigned_profile:
            flags.add("other_annotator")
        if ann.get("updated_by") is not None and (
            ann.get("updated_by_profile") is None or ann.get("updated_by_profile") != by
        ):
            flags.add(
                "edited_by_other"
            )  # includes an editor who isn't a <profile>@studio.local user
    if sum(1 for ann in annotations if not ann.get("was_cancelled")) > 1:
        flags.add("multiple_annotations")
    return sorted(flags)


def _profiles(annotations: list, key: str) -> list:
    """Distinct values of ``key`` across annotations, sorted; an unknown user is ``None``, listed last."""
    values = {a.get(key) for a in annotations if key in a}
    return sorted(v for v in values if v is not None) + ([None] if None in values else [])


def attribution_summary(rows: list) -> dict:
    """Export-level count of flagged tasks, plus the first ATTRIBUTION_ROWS_SHOWN of them."""
    flagged = [r for r in rows if r.get("attribution")]
    by_flag = {}
    for r in flagged:
        for f in r["attribution"]:
            by_flag[f] = by_flag.get(f, 0) + 1
    return {
        "flagged_tasks": len(flagged),
        "by_flag": dict(sorted(by_flag.items())),
        "rows": [
            {
                "task_id": r["task_id"],
                "project_id": r["project_id"],
                "unique_id": (r.get("data") or {}).get("unique_id"),
                "assigned_profile": r["assigned_profile"],
                "completed_by_profiles": _profiles(r["annotations"], "completed_by_profile"),
                "updated_by_profiles": _profiles(r["annotations"], "updated_by_profile"),
                "flags": r["attribution"],
            }
            for r in flagged[:ATTRIBUTION_ROWS_SHOWN]
        ],
    }


def export_annotations(
    space: SpaceInfo,
    admin_profile: str,
    assignments: dict,
    session: Optional[LabelStudioSession] = None,
) -> list:
    """Tasks that have at least one annotation, tagged with the assigned profile and ``attribution`` flags.

    ``completed_by`` / ``updated_by`` are Label Studio user ids: a nested user object is reduced to its id.
    """
    session = session or LabelStudioSession(space, admin_profile).connect()
    users = {u.get("id"): u.get("email") for u in session.list_users()}
    out = []
    for profile, a in assignments.items():
        for task in session.export_project(a["project_id"]):
            anns = task.get("annotations") or []
            if not anns:
                continue
            for ann in anns:
                ann["completed_by_profile"] = _user_profile(ann.get("completed_by"), users)
                if ann.get("updated_by") is not None:
                    ann["updated_by_profile"] = _user_profile(ann.get("updated_by"), users)
                for key in ("completed_by", "updated_by"):  # a nested user object carries an email
                    if isinstance(ann.get(key), dict):
                        ann[key] = ann[key].get("id")
            out.append(
                {
                    "assigned_profile": profile,
                    "project_id": a["project_id"],
                    "task_id": task.get("id"),
                    "data": task.get("data"),
                    "annotations": anns,
                    "attribution": attribution_flags(profile, anns),
                }
            )
    return out


def relabel_records(
    export_rows: list, discarded: set, approval_id: str, path: str = "the export"
) -> list:
    """The task data of the export rows approval ``approval_id`` discarded, one per record, for a relabel round."""
    out, seen = [], set()
    for row in export_rows:
        uid = _unique_id(row) if isinstance(row, dict) else None
        if uid in discarded and uid not in seen:
            seen.add(uid)
            out.append(row["data"])
    if not out:
        raise UsageError(
            f"{path} has no row that approval entry {approval_id} discarded; pass the export "
            "the decision was made on as --records. Nothing was created."
        )
    return out


def _unique_id(row: dict) -> Optional[str]:
    data = row.get("data")
    uid = data.get("unique_id") if isinstance(data, dict) else None
    return None if uid is None else str(uid)


def apply_discards(rounds: list, approvals: list) -> tuple:
    """The export rows without the ones discarded at Step 7, each record's newest relabel in their place.

    ``rounds`` is ``[(relabel_of, created, rows), ...]``, oldest first: the original projects
    (``relabel_of`` None), then each relabel round; ``created`` is when the round was set up
    (epoch seconds). ``approvals`` is ``[(created, discarded_unique_ids), ...]``. A row is left
    out when a newer round has a row for the same ``data.unique_id`` (its relabel), or when an
    approval made after the row's round discarded that unique_id. Returns (rows, the
    unique_ids left with no row, the unique_ids whose row comes from a relabel round, both
    sorted, and the first left-out row of each record left with no row).
    """
    newest = {}
    for i, (_, _, rows) in enumerate(rounds):
        for row in rows:
            uid = _unique_id(row)
            if uid is not None:
                newest[uid] = i
    kept, left_out = [], {}
    for i, (relabel_of, created, rows) in enumerate(rounds):
        later = set().union(*[ids for t, ids in approvals if t > created])
        for row in rows:
            uid = _unique_id(row)
            if uid is not None and (newest[uid] != i or uid in later):
                left_out.setdefault(uid, row)
                continue
            kept.append(row if relabel_of is None else {**row, "relabel_of": relabel_of})
    present = {_unique_id(r) for r in kept}
    relabeled = sorted({_unique_id(r) for r in kept if "relabel_of" in r} - {None})
    missing = sorted(set(left_out) - present)
    return kept, missing, relabeled, [left_out[u] for u in missing]


# ---------------------------------------------------------------------------
# Optional S3 copy of the export
# ---------------------------------------------------------------------------


def _session(region: Optional[str] = None):
    import boto3

    region = region or os.environ.get("AWS_REGION") or None
    session = boto3.session.Session(region_name=region) if region else boto3.session.Session()
    if not session.region_name:
        raise UsageError(
            "No AWS region configured. Set AWS_REGION or AWS_DEFAULT_REGION, or pass --region."
        )
    return session


def parse_s3_uri(uri: str) -> tuple:
    """'s3://bucket/a/b.jsonl' -> ('bucket', 'a/b.jsonl'). Raises UsageError if malformed."""
    parsed = urllib.parse.urlparse(uri or "")
    if parsed.scheme != "s3" or not parsed.netloc:
        raise UsageError(f"Not an s3:// URI: {uri!r}")
    return parsed.netloc, parsed.path.lstrip("/")


def _error_code(e: Exception) -> str:
    return ((getattr(e, "response", None) or {}).get("Error") or {}).get("Code", "") or type(
        e
    ).__name__


def _aws_error(e: Exception, code: Optional[str] = None) -> str:
    """An AWS failure as its exception type, error code and message, the caller's name dropped.

    AWS error messages can name the caller (``assumed-role/<role>/<session>``, whose
    session name is often a person's email), so the message goes through ``scrub_identity``.
    """
    code = code or _error_code(e)
    head = type(e).__name__ if code == type(e).__name__ else f"{type(e).__name__}: {code}"
    message = scrub_identity(str(e))
    return f"{head}: {message}" if message and message != code else head


_PERMISSION_CODES = {
    "AccessDenied",
    "403",
    "AllAccessDisabled",
    "BucketNotFound",
    "NoSuchBucket",
    "404",
    "NotFound",
}


def _s3_outcome(e: Exception) -> str:
    """Error code for a permission/not-found outcome; anything else raises AwsCallError (exit 5)."""
    code = _error_code(e)
    code = "BucketNotFound" if code in ("404", "NoSuchBucket", "NotFound") else code
    if getattr(e, "response", None) and code in _PERMISSION_CODES:
        return code
    raise AwsCallError(f"S3 check failed: {_aws_error(e, code)}") from None


# A person's name in an AWS identity: an assumed role's session, a federated user, an IAM user
# (with its path), or the name after a role/user unique id. IAM names may hold any of [\w+=,.@-].
_NAME = r"[\w+=,.@-]+"
_IDENTITY_NAME = (
    (re.compile(rf"(assumed-role/{_NAME})/{_NAME}"), r"\1"),
    (re.compile(rf"(:federated-user)/{_NAME}"), r"\1"),
    (re.compile(r"(:user)/[\w+=,.@/-]+"), r"\1"),
    (re.compile(rf"\b((?:AROA|AIDA|ASIA)[A-Z0-9]+):{_NAME}"), r"\1"),
)


def scrub_identity(text: str) -> str:
    """``text`` with the person's name dropped from every AWS identity in it.

    ``assumed-role/<role>/<session>`` keeps the role, ``federated-user/<name>`` and
    ``user/<path>/<name>`` keep only the type, and ``<unique id>:<name>`` keeps the id; the rest
    of the text is unchanged.
    """
    for pattern, repl in _IDENTITY_NAME:
        text = pattern.sub(repl, text)
    return text


def caller_arn(region: Optional[str] = None) -> str:
    """The AWS identity running the skill, shown next to the profile the user confirms.

    A person's name in it is dropped: an assumed role's session name
    (``arn:aws:sts::<account>:assumed-role/<role>``), a federated user's name
    (``arn:aws:sts::<account>:federated-user``) and an IAM user's name (``arn:aws:iam::<account>:user``).
    """
    session = _session(region)
    os.environ.setdefault(
        "AWS_STS_REGIONAL_ENDPOINTS", "regional"
    )  # never the global us-east-1 endpoint
    try:
        arn = session.client("sts", region_name=session.region_name).get_caller_identity()["Arn"]
    except Exception as e:
        raise AwsCallError(f"GetCallerIdentity failed: {_aws_error(e)}") from None
    return scrub_identity(arn)


def _caller_fields(region: Optional[str]) -> dict:
    """``caller_arn`` for discover/profiles; it is information only, so a failed lookup doesn't stop them."""
    try:
        return {"caller_arn": caller_arn(region)}
    except AwsCallError as e:
        return {"caller_arn": None, "caller_arn_error": str(e)}


def _own_account(region: Optional[str]) -> str:
    """The account the spaces belong to: the caller's own (sts:GetCallerIdentity needs no grant)."""
    return _caller_account(_session(region))


def _caller_account(session) -> str:
    """The caller's account id; any failure is an AwsCallError (exit 5)."""
    os.environ.setdefault(
        "AWS_STS_REGIONAL_ENDPOINTS", "regional"
    )  # never the global us-east-1 endpoint
    try:
        return session.client("sts", region_name=session.region_name).get_caller_identity()[
            "Account"
        ]
    except Exception as e:  # NoCredentialsError, EndpointConnectionError, ClientError, ...
        raise AwsCallError(f"GetCallerIdentity failed: {_aws_error(e)}") from None


_KEY_SEGMENT = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}")
_KEY_UNSAFE = re.compile(r"[^A-Za-z0-9._-]+")


def _key_segment(value: str) -> str:
    """``value`` as one S3 key segment: other characters become '-', leading '.', '_', '-' are dropped."""
    return re.sub("-{2,}", "-", _KEY_UNSAFE.sub("-", value)).lstrip("._-")[:128].rstrip("-")


def export_upload_uri(destination: str, setup: dict, project_name: Optional[str] = None) -> str:
    """The URI ``export --s3-uri <destination>`` uploads to.

    A bucket or a prefix (``s3://b``, or a URI ending in ``/``) gets
    ``<project-name>/<run-id>/`` appended, so each project and setup run has its own key;
    the export file keeps its name below it. A full object key is used as given.
    ``project_name`` and ``run_id`` come from the setup output; ``project_name`` is the
    fallback for a setup output that does not record it. A character other than a letter,
    digit, '.', '_' or '-' in the project name becomes '-' in the key ("Fix Responses" ->
    "Fix-Responses").
    """
    bucket, key = parse_s3_uri(destination)
    if key and not key.endswith("/"):
        return f"s3://{bucket}/{key}"
    name = setup.get("project_name") or project_name
    run_id = setup.get("run_id")
    if not run_id:
        raise UsageError(
            "The setup output has no run_id; pass the ls_setup.json that 'setup --out' wrote."
        )
    if not name:
        raise UsageError("This setup output does not record the project name; pass --project-name.")
    segment = _key_segment(name)
    for given, part in ((name, segment), (run_id, run_id)):
        if not _KEY_SEGMENT.fullmatch(part):
            raise UsageError(
                f"{given!r} can't be used as one S3 key segment (letters, digits, '.', '_', '-'); "
                "give a full object key as the destination instead."
            )
    return f"s3://{bucket}/{key}{segment}/{run_id}/"


def export_object_uri(upload_uri: str, local_path: str) -> str:
    """The object ``upload_export`` writes for ``upload_uri``: a prefix keeps the file's name."""
    return f"{upload_uri}{os.path.basename(local_path)}" if upload_uri.endswith("/") else upload_uri


def _head_own_bucket(s3, bucket: str, owner: dict, out: dict) -> bool:
    """HeadBucket with the owner check. True if the caller's account owns the bucket.

    Otherwise sets ``out``: a reachable bucket of another account is ``cross_account: true``
    with error ``CrossAccountBucket``; a missing or unreadable bucket gets its error code.
    """
    try:
        s3.head_bucket(Bucket=bucket, **owner)
        out["exists"] = True
        return True
    except Exception as e:
        if _error_code(e) not in ("403", "AccessDenied"):
            out["error"] = _s3_outcome(e)
            return False
    try:  # 403 with the owner check: someone else's bucket, or no access at all
        s3.head_bucket(Bucket=bucket)
    except Exception as e2:
        out["error"] = _s3_outcome(e2)
        return False
    out["exists"], out["cross_account"], out["error"] = True, True, "CrossAccountBucket"
    return False


# Codes that mean "not configured on this bucket". S3 answers them with HTTP 404, and HeadBucket
# has just shown the bucket exists, so any 404 on these reads is read as "not configured" too.
_NOT_CONFIGURED = {
    "public_access_block": "NoSuchPublicAccessBlockConfiguration",
    "account_public_access_block": "NoSuchPublicAccessBlockConfiguration",
    "policy_is_public": "NoSuchBucketPolicy",
    "object_ownership": "OwnershipControlsNotFoundError",
    "default_encryption": "ServerSideEncryptionConfigurationNotFoundError",
}
_BPA_FLAGS = ("BlockPublicAcls", "IgnorePublicAcls", "BlockPublicPolicy", "RestrictPublicBuckets")
_PUBLIC_GROUPS = {
    "http://acs.amazonaws.com/groups/global/AllUsers": "AllUsers",
    "http://acs.amazonaws.com/groups/global/AuthenticatedUsers": "AuthenticatedUsers",
}


def _read_setting(settings: dict, name: str, read):
    """Run one read-only settings call; on "not configured" or a denied read return None.

    A denied read is listed in ``settings["unreadable"]``. Throttling, 5xx and network
    errors raise AwsCallError (exit 5), so a retryable error never looks like a setting.
    """
    try:
        return read()
    except Exception as e:
        code = _error_code(e)
        status = (
            (getattr(e, "response", None) or {}).get("ResponseMetadata", {}).get("HTTPStatusCode")
        )
        if code == _NOT_CONFIGURED.get(name) or status == 404:
            return None
        if getattr(e, "response", None) and code in _PERMISSION_CODES:
            settings["unreadable"][name] = code
            return None
        raise AwsCallError(f"Reading {name} of bucket failed: {_aws_error(e, code)}") from None


def _bucket_settings(session, s3, bucket: str, owner: dict) -> dict:
    """Read-only view of a bucket the caller's account owns: public access, ACLs, encryption.

    ``public_access_block`` / ``account_public_access_block``: the four Block Public Access
    flags, or None when none are set (the account's are read only when the bucket's leave
    a flag off). ``policy_is_public``: S3's own evaluation of the bucket policy (False with
    no policy). ``object_ownership``: ``BucketOwnerEnforced`` means ACLs are off; otherwise
    ``public_acl_grants`` lists ACL grants to AllUsers / AuthenticatedUsers.
    ``default_encryption``: ``{sse_algorithm, kms_key_id, bucket_key_enabled}`` or None.
    """
    s = {
        "public_access_block": None,
        "account_public_access_block": None,
        "policy_is_public": None,
        "object_ownership": None,
        "public_acl_grants": [],
        "default_encryption": None,
        "unreadable": {},
    }

    def flags(resp):
        cfg = (resp or {}).get("PublicAccessBlockConfiguration") or {}
        return {k: bool(cfg.get(k)) for k in _BPA_FLAGS} if resp else None

    s["public_access_block"] = flags(
        _read_setting(
            s, "public_access_block", lambda: s3.get_public_access_block(Bucket=bucket, **owner)
        )
    )
    bpa = s["public_access_block"]
    if not (bpa and all(bpa.values())):  # the account's flags count where the bucket's are off
        account = owner["ExpectedBucketOwner"]
        s["account_public_access_block"] = flags(
            _read_setting(
                s,
                "account_public_access_block",
                lambda: session.client("s3control").get_public_access_block(AccountId=account),
            )
        )
    resp = _read_setting(
        s, "policy_is_public", lambda: s3.get_bucket_policy_status(Bucket=bucket, **owner)
    )
    if "policy_is_public" not in s["unreadable"]:
        s["policy_is_public"] = bool(((resp or {}).get("PolicyStatus") or {}).get("IsPublic"))
    resp = _read_setting(
        s, "object_ownership", lambda: s3.get_bucket_ownership_controls(Bucket=bucket, **owner)
    )
    rules = ((resp or {}).get("OwnershipControls") or {}).get("Rules") or []
    s["object_ownership"] = rules[0].get("ObjectOwnership") if rules else None
    if s["object_ownership"] != "BucketOwnerEnforced":  # ACLs on, or unknown: read the grants
        resp = _read_setting(
            s, "public_acl_grants", lambda: s3.get_bucket_acl(Bucket=bucket, **owner)
        )
        groups = {
            _PUBLIC_GROUPS.get((g.get("Grantee") or {}).get("URI"))
            for g in (resp or {}).get("Grants") or []
        }
        s["public_acl_grants"] = sorted(g for g in groups if g)
    resp = _read_setting(
        s, "default_encryption", lambda: s3.get_bucket_encryption(Bucket=bucket, **owner)
    )
    if resp:
        rule = ((resp.get("ServerSideEncryptionConfiguration") or {}).get("Rules") or [{}])[0]
        default = rule.get("ApplyServerSideEncryptionByDefault") or {}
        s["default_encryption"] = {
            "sse_algorithm": default.get("SSEAlgorithm"),
            "kms_key_id": default.get("KMSMasterKeyID"),
            "bucket_key_enabled": bool(rule.get("BucketKeyEnabled")),
        }
    return s


def bucket_exposure(s: dict) -> tuple:
    """(``public`` | ``weak`` | ``ok``, reasons) from ``_bucket_settings``.

    A flag counts as on when the bucket or the account sets it. ``public``: the policy is
    public and ``RestrictPublicBuckets`` is off (``public_policy``), or ACLs grant access to
    AllUsers / AuthenticatedUsers and neither ``IgnorePublicAcls`` nor ``BucketOwnerEnforced``
    neutralizes them (``public_acl``). ``weak``: a Block Public Access flag is off
    (``block_public_access_off:<flag>``), ACLs are enabled (``acls_enabled``), or a setting
    could not be read (``unreadable:<setting>``). ``ok``: none of these. When the bucket's own
    flags can't be read, no ``block_public_access_off`` code is given: whether they are on is
    unknown, and ``unreadable:public_access_block`` stands for them; the same holds when the
    account's flags can't be read (``unreadable:account_public_access_block``).
    """
    on = {
        f: bool(
            (s.get("public_access_block") or {}).get(f)
            or (s.get("account_public_access_block") or {}).get(f)
        )
        for f in _BPA_FLAGS
    }
    unreadable = s.get("unreadable") or {}
    acls_off = s.get("object_ownership") == "BucketOwnerEnforced"
    public = []
    if s.get("policy_is_public") and not on["RestrictPublicBuckets"]:
        public.append("public_policy")
    if s.get("public_acl_grants") and not (acls_off or on["IgnorePublicAcls"]):
        public.append("public_acl")
    known = not ({"public_access_block", "account_public_access_block"} & set(unreadable))
    weak = [f"block_public_access_off:{f}" for f in _BPA_FLAGS if not on[f]] if known else []
    if not acls_off and "object_ownership" not in unreadable:
        weak.append("acls_enabled")
    weak += [f"unreadable:{name}" for name in unreadable]
    return ("public" if public else "weak" if weak else "ok"), public + weak


def inspect_s3_destination(upload_uri: str, region: Optional[str] = None) -> dict:
    """Read-only: whose bucket is it, and how exposed is it? Writes nothing.

    Same owner check as ``check_s3_destination``. For a bucket the caller's account owns,
    adds ``bucket_settings`` (``_bucket_settings``) and ``exposure`` / ``exposure_reasons``
    (``bucket_exposure``). Exposure is reported for the user to decide; it never blocks.
    """
    bucket, _ = parse_s3_uri(upload_uri)
    session = _session(region)
    s3 = session.client("s3")
    owner = {"ExpectedBucketOwner": _caller_account(session)}
    out = {
        "upload_uri": upload_uri,
        "bucket": bucket,
        "exists": False,
        "cross_account": False,
        "error": None,
    }
    if _head_own_bucket(s3, bucket, owner, out):
        out["bucket_settings"] = _bucket_settings(session, s3, bucket, owner)
        out["exposure"], out["exposure_reasons"] = bucket_exposure(out["bucket_settings"])
    return out


def _sse_args(kms_key_id: Optional[str]) -> dict:
    """S3 write arguments for SSE-KMS with ``kms_key_id``; none (the bucket's default encryption) without one."""
    return {"ServerSideEncryption": "aws:kms", "SSEKMSKeyId": kms_key_id} if kms_key_id else {}


def check_s3_destination(
    s3_uri: str, region: Optional[str] = None, kms_key_id: Optional[str] = None
) -> dict:
    """Can the current credentials write under ``s3_uri``, and whose bucket is it?

    Checks the bucket exists and is owned by the caller's account (``_head_own_bucket``);
    a bucket owned by another account that is still reachable is reported as
    ``cross_account: true`` with error ``CrossAccountBucket`` and is never written to:
    the skill copies exports only to the caller's own buckets. Then writes and deletes
    one empty test object next to the target key — the only way to prove
    PutObject is allowed. Never touches any other object. With ``kms_key_id`` the probe is
    written with SSE-KMS under that key, so the check also proves the key can be used.
    """
    bucket, key = parse_s3_uri(s3_uri)
    session = _session(region)
    s3 = session.client("s3")
    owner = {"ExpectedBucketOwner": _caller_account(session)}
    out = {
        "upload_uri": s3_uri,
        "bucket": bucket,
        "exists": False,
        "writable": False,
        "cross_account": False,
        "error": None,
        "kms_key_id": kms_key_id,
    }
    if not _head_own_bucket(s3, bucket, owner, out):
        return out  # never write to another account's bucket
    prefix = key.rsplit("/", 1)[0] + "/" if "/" in key else ""
    probe = f"{prefix}.hil-write-check-{uuid.uuid4().hex[:8]}"
    try:
        s3.put_object(Bucket=bucket, Key=probe, Body=b"", **owner, **_sse_args(kms_key_id))
    except Exception as e:
        out["error"] = _s3_outcome(e)
        return out
    out["writable"] = True
    try:
        s3.delete_object(Bucket=bucket, Key=probe, **owner)
    except Exception as e:  # writable, but the probe stays behind; say so
        out["probe_left_behind"] = f"s3://{bucket}/{probe} ({_error_code(e)})"
    return out


def upload_export(
    local_path: str, s3_uri: str, region: Optional[str] = None, kms_key_id: Optional[str] = None
) -> str:
    """Upload the export file to ``s3_uri`` (a key, or a prefix ending in '/'), with SSE-KMS under
    ``kms_key_id`` when given, else the bucket's default encryption."""
    bucket, key = parse_s3_uri(s3_uri)
    if not key or key.endswith("/"):
        key = f"{key}{os.path.basename(local_path)}"
    try:
        # Without --s3-kms-key-id, S3 applies the bucket's default encryption (SSE-S3 at minimum, its own
        # SSE-KMS key if set); forcing aws:kms without a key would override a bucket's customer-managed key.
        # The owner check refuses an upload to a bucket another account owns: the skill uses only the caller's buckets.
        session = _session(region)
        session.client("s3").upload_file(
            local_path,
            bucket,
            key,
            ExtraArgs={"ExpectedBucketOwner": _caller_account(session), **_sse_args(kms_key_id)},
        )
    except Exception as e:
        # S3Transfer re-raises the ClientError as S3UploadFailedError (no .response); the original is __context__.
        code = _error_code(
            e.__context__ if type(e).__name__ == "S3UploadFailedError" and e.__context__ else e
        )
        hint = (
            " (if the bucket belongs to another AWS account: the skill copies the export only to a bucket "
            "in the caller's own account)"
            if code in ("403", "AccessDenied")
            else ""
        )
        raise AwsCallError(
            f"Uploading to s3://{bucket}/{key} failed: {_aws_error(e, code)}{hint}"
        ) from None
    return f"s3://{bucket}/{key}"


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _space_from_args(args) -> SpaceInfo:
    spaces = find_label_studio_space(args.space_name, args.domain_id, args.region)
    if len(spaces) > 1:
        raise UsageError(
            "Multiple running Label Studio spaces: %s. Re-run with --domain-id and --space-name."
            % ", ".join(f"{s.domain_name} ({s.domain_id}): {s.space_name}" for s in spaces)
        )
    return spaces[0]


def _load_assignments(path: str) -> dict:
    """{profile: {project_id, ...}} from a setup output or a plain assignments file (UsageError if malformed)."""
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, dict) and "assignments" in data:
        data = data["assignments"]
    if not isinstance(data, dict) or not all(
        isinstance(v, dict) and "project_id" in v for v in data.values()
    ):
        raise UsageError(
            f"{path} is not a setup output or a {{profile: {{project_id: ...}}}} assignments file."
        )
    return data


def _load_setup_output(path: str) -> dict:
    """The full setup output (``setup --out``): the S3 copy needs its ``run_id`` and ``project_name``."""
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict) or not isinstance(data.get("assignments"), dict):
        raise UsageError(f"{path} is not a setup output (ls_setup.json from 'setup --out').")
    return data


S3_CHECK = "s3-export-destination"  # the ``check`` field that marks an s3-check entry
S3_CHECK_STEP = "human-in-the-loop-s3-check"  # the entry's step outside a plan


def _hil_log():
    """The HIL log writer (hil_log.py, beside this script); OSError if it is missing."""
    here = os.path.dirname(os.path.abspath(__file__))
    if here not in sys.path:
        sys.path.insert(0, here)
    try:
        import hil_log
    except ImportError as e:
        raise OSError(f"The HIL log writer was not found in {here}: {e}") from None
    return hil_log


RELABEL_ROUND = (
    "relabel-round"  # the ``artifact`` field value that marks a relabel round's HIL log entry
)


def _approval_entry(project_dir: str, approval_id: str) -> dict:
    """The Step 7 approval entry ``approval_id`` (UsageError if the HIL log doesn't hold it with its list)."""
    entries = _hil_log().read_entries(project_dir, kind="approval", id=approval_id)
    if not entries:
        raise UsageError(
            f"{approval_id} is not an approval entry in {project_dir}'s HIL log. Nothing was changed."
        )
    if not isinstance(entries[-1].get("discarded_unique_ids"), list):
        raise UsageError(
            f"Approval entry {approval_id} has no discarded_unique_ids list. Nothing was changed."
        )
    return entries[-1]


def discarded_unique_ids(project_dir: str, approval_id: str) -> set:
    """The ``discarded_unique_ids`` of the Step 7 approval entry ``approval_id``, as strings."""
    return {
        str(i)
        for i in _approval_entry(project_dir, approval_id)["discarded_unique_ids"]
        if i is not None
    }


def _entry_time(entry: dict) -> float:
    try:
        return _utc_epoch(str(entry.get("created_at", "")))
    except ValueError:
        raise UsageError(
            f"Could not read the time of HIL log entry {entry.get('id')} "
            f"(created_at={entry.get('created_at')!r}). Nothing was changed."
        ) from None


def _recorded_rounds(project_dir: str) -> dict:
    """{absolute setup output path: its relabel-round HIL log entry}."""
    root = _hil_log().resolve_project_dir(project_dir)
    return {
        os.path.realpath(os.path.join(root, e.get("setup") or "")): e
        for e in _hil_log().read_entries(project_dir, kind="artifact", artifact=RELABEL_ROUND)
    }


def record_relabel_round(project_dir: str, setup_path: str, relabel_of: str) -> str:
    """Record a relabel round's setup output in the HIL log, under its approval entry's step; returns the id.

    A setup output already recorded is not recorded twice: its entry's id is returned.
    """
    approval = _approval_entry(project_dir, relabel_of)
    existing = _recorded_rounds(project_dir).get(os.path.realpath(setup_path))
    if existing is not None:
        if existing.get("relabel_of") != relabel_of:
            raise UsageError(
                f"{setup_path} is already recorded as a relabel round of {existing.get('relabel_of')}."
            )
        return existing["id"]
    return _hil_log().write_entry(
        project_dir,
        kind="artifact",
        step=approval["step"],
        iteration=approval["iteration"],
        status="created",
        artifact=RELABEL_ROUND,
        relabel_of=relabel_of,
        setup=os.path.realpath(setup_path),
    )


def _setup_time(setup_path: str) -> float:
    """When the ``--assignments`` setup ran, comparable with HIL log ``created_at`` (UTC).

    Its ``created_at`` (UTC). A setup output written before setup recorded it falls back to
    its ``run_id`` (``YYYYMMDD-HHMMSS``, read as this machine's local time, so it is right
    only where setup ran in the same time zone), then to the file's mtime.
    """
    try:
        data = _load_setup_output(setup_path)
    except UsageError:
        return os.path.getmtime(setup_path)
    try:
        return _utc_epoch(str(data["created_at"]))
    except (KeyError, ValueError):
        pass
    try:
        return datetime.strptime(str(data.get("run_id", "")), "%Y%m%d-%H%M%S").timestamp()
    except ValueError:
        return os.path.getmtime(setup_path)


def relabel_rounds(
    project_dir: str, setup_path: str, approval_id: str, relabel_paths: list
) -> tuple:
    """Check the export's approval and relabel rounds against the HIL log, before anything is read.

    Returns (original round's time, [(relabel_of, time, assignments), ...] oldest first,
    [(time, discarded unique_ids), ...] for ``approval_id`` and every round's approval).
    UsageError when ``approval_id`` or a round's ``relabel_of`` is not an approval made after
    the ``--assignments`` setup, when a round was set up before that setup, or when a
    ``--relabel-setup`` file is not a relabel round recorded in this project's HIL log.
    """
    setup_time = _setup_time(setup_path)
    setup_run = str(_load_setup_output(setup_path).get("run_id", "")) if relabel_paths else ""
    approvals = {}

    def approval(aid):
        if aid not in approvals:
            entry = _approval_entry(project_dir, aid)
            t = _entry_time(entry)
            if t < setup_time:
                raise UsageError(
                    f"Approval entry {aid} was made before {setup_path} was set up, so it belongs to "
                    "another cycle. Nothing was changed."
                )
            approvals[aid] = (t, {str(i) for i in entry["discarded_unique_ids"] if i is not None})
        return approvals[aid]

    approval(approval_id)
    recorded = _recorded_rounds(project_dir)
    rounds = []
    for path in relabel_paths:
        data = _load_setup_output(path)
        entry = recorded.get(os.path.realpath(path))
        if (
            not data.get("relabel_of")
            or entry is None
            or entry.get("relabel_of") != data["relabel_of"]
        ):
            raise UsageError(
                f"{path} is not a relabel round recorded in {project_dir}'s HIL log (setup "
                "--relabel-of). Nothing was changed."
            )
        if not setup_run or str(data.get("run_id", "")) < setup_run:
            raise UsageError(
                f"{path} was set up before {setup_path}, so it belongs to another cycle. "
                "Nothing was changed."
            )
        approval(data["relabel_of"])
        rounds.append((data["relabel_of"], _entry_time(entry), data["assignments"]))
    rounds.sort(key=lambda r: r[1])
    return setup_time, rounds, list(approvals.values())


def record_s3_check(
    project_dir: str, setup_path: str, check: dict, step: str = S3_CHECK_STEP, iteration: int = 0
) -> str:
    """Append the s3-check result to the project's HIL log; returns the entry id.

    ``status`` is ``passed`` when the check proved the upload URI writable in the caller's
    own bucket, else ``failed``. ``step`` and ``iteration`` follow the plan (the plan step's
    name and loop iteration); the entry is found by its ``check`` field, not its step. The
    entry names the setup output by path rather than copying its values.
    """
    fields = {
        "check": S3_CHECK,
        "upload_uri": check["upload_uri"],
        "setup": os.path.realpath(setup_path),
        "kms_key_id": check.get("kms_key_id"),
    }
    if check.get("error"):
        fields["error"] = check["error"]
    return _hil_log().write_entry(
        project_dir,
        kind="analysis",
        step=step,
        iteration=iteration,
        status="passed" if check.get("writable") else "failed",
        **fields,
    )


def _utc_epoch(created_at: str) -> float:
    """Seconds since the epoch for a HIL log ``created_at``; ValueError if it can't be read.

    Accepts the writer's ``…T..:..:..ffffffZ`` and also no microseconds or an explicit offset;
    a time without a zone is taken as UTC.
    """
    t = datetime.fromisoformat(created_at.strip().replace("Z", "+00:00"))
    return (t if t.tzinfo else t.replace(tzinfo=timezone.utc)).timestamp()


def require_passed_s3_check(
    project_dir: str, upload_uri: str, setup_path: str, kms_key_id: Optional[str] = None
) -> None:
    """UsageError unless the project's newest s3-check passed for exactly ``upload_uri`` and ``kms_key_id``.

    A newer check of another destination, or a failed one, supersedes an earlier pass, and so
    does a setup output written after the check (a new setup run needs a new check, even for a
    full key whose URI doesn't change).
    """
    entry = _hil_log().latest_entry(project_dir, kind="analysis", check=S3_CHECK)
    if not entry:
        raise UsageError(
            f"No s3-check is recorded in {project_dir}'s HIL log; run s3-check on this "
            "destination first. Nothing was exported."
        )
    root = _hil_log().resolve_project_dir(project_dir)
    same_setup = os.path.realpath(os.path.join(root, entry.get("setup") or "")) == os.path.realpath(
        setup_path
    )
    if entry.get("status") != "passed" or entry.get("upload_uri") != upload_uri or not same_setup:
        raise UsageError(
            f"{upload_uri} with {setup_path} is not the destination the last s3-check passed "
            f"(HIL log entry {entry.get('id')}: {entry.get('status')} for {entry.get('upload_uri')}, "
            f"setup {entry.get('setup')}); run s3-check on it first. Nothing was exported."
        )
    if (entry.get("kms_key_id") or None) != (kms_key_id or None):
        raise UsageError(
            f"The last s3-check (HIL log entry {entry.get('id')}) used --s3-kms-key-id "
            f"{entry.get('kms_key_id') or '(none)'}, not {kms_key_id or '(none)'}; run s3-check with the "
            "same key. Nothing was exported."
        )
    try:
        checked_at = _utc_epoch(str(entry.get("created_at", "")))
    except ValueError:
        raise UsageError(
            f"Could not read the time of the last s3-check (HIL log entry {entry.get('id')}, "
            f"created_at={entry.get('created_at')!r}); run s3-check again. Nothing was exported."
        ) from None
    if os.path.getmtime(setup_path) > checked_at:
        raise UsageError(
            f"{setup_path} was written after the last s3-check (HIL log entry {entry.get('id')}); "
            "run s3-check again. Nothing was exported."
        )


def _write_jsonl_atomic(path: str, rows: list) -> None:
    """Write ``rows`` as JSONL to ``path`` via a temp file."""
    _write_jsonl_files_atomic([(path, rows)])


def _write_jsonl_files_atomic(files: list) -> None:
    """Write each ``(path, rows)`` as JSONL as one unit: every file goes to a temp file first,
    and the temp files replace their targets only after all of them were written, so a
    failed write leaves every target as it was."""
    tmps = []
    try:
        for path, rows in files:
            os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
            tmp = f"{path}.tmp-{os.getpid()}"
            tmps.append(tmp)
            with open(tmp, "w", encoding="utf-8") as f:
                for row in rows:
                    f.write(json.dumps(row) + "\n")
        for (path, _), tmp in zip(files, tmps):
            os.replace(tmp, path)
    except BaseException:
        for tmp in tmps:
            if os.path.exists(tmp):
                os.remove(tmp)
        raise


def _write_json_atomic(path: Optional[str], data: dict) -> None:
    """Write ``data`` to ``path`` via a temp file, so a failed run never empties an existing file."""
    if not path:
        return
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = f"{path}.tmp-{os.getpid()}"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, path)


def _save_setup_output(path: Optional[str], data: dict) -> bool:
    """Save setup output to ``--out``; on failure report it (stdout already has the result)."""
    try:
        _write_json_atomic(path, data)
        return True
    except OSError as e:
        print(
            json.dumps(
                {
                    "error": "OutputWriteError",
                    "message": f"Projects were created, but saving {path} failed: {e}. "
                    "Save the stdout JSON as that file.",
                }
            ),
            file=sys.stderr,
        )
        return False


# Arguments each subcommand cannot run without (checked before any AWS call).
_REQUIRED_ARGS = {
    "setup": ("admin_profile", "annotators", "project_name", "label_config", "records"),
    "status": ("admin_profile", "assignments"),
    "export": ("admin_profile", "assignments", "out"),
    "s3-inspect": ("s3_uri", "assignments", "out"),
    "s3-check": ("s3_uri", "assignments", "project_dir"),
    "record-relabel-round": ("assignments", "project_dir"),
    "create": ("domain_id", "admin_profile"),
    "start": ("domain_id", "space_name"),
    "estimate-storage": ("records",),
}


class _ArgParser(argparse.ArgumentParser):
    """argparse exits 2 on bad flags, which would read as "no Label Studio space"; use 4. Help
    goes to the real stdout, which the CLI otherwise keeps for its JSON result."""

    def print_help(self, file=None):
        super().print_help(file or _stdout())

    def error(self, message):
        print(json.dumps({"error": "UsageError", "message": message}), file=sys.stderr)
        raise SystemExit(4)


_RESULT_STDOUT = None  # the real stdout while the CLI runs (see __main__)


def _stdout():
    """Where a command's JSON result goes: the real stdout, even while sys.stdout is on stderr."""
    return _RESULT_STDOUT or sys.stdout


def main(argv=None) -> int:
    ap = _ArgParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument(
        "command",
        choices=[
            "discover",
            "profiles",
            "setup",
            "status",
            "export",
            "s3-inspect",
            "s3-check",
            "record-relabel-round",
            "create",
            "start",
            "estimate-storage",
        ],
    )
    ap.add_argument(
        "--space-name",
        help="Label Studio space name (default: each domain's Label Studio space, "
        "found by its image)",
    )
    ap.add_argument("--domain-id")
    ap.add_argument("--region")
    ap.add_argument(
        "--admin-profile",
        help="setup/status/export: the admin profile (the user's own), which the "
        "skill acts as in Label Studio (required; there is no default); "
        "profiles: optional, check these credentials can open the space as it",
    )
    ap.add_argument("--annotators", help="Comma-separated SageMaker user profile names")
    ap.add_argument(
        "--ebs-gb",
        type=int,
        default=None,
        help=f"create: the new space's storage volume in GB (default {DEFAULT_EBS_GB})",
    )
    ap.add_argument(
        "--replace-failed-app",
        action="store_true",
        help="start: delete and recreate a Failed app (the space and its projects are kept)",
    )
    ap.add_argument(
        "--no-wait",
        action="store_true",
        help="create/start: return once the app start is accepted, without waiting for InService",
    )
    ap.add_argument(
        "--project-name",
        help="setup: project name; S3 commands: only for a setup output " "that does not record it",
    )
    ap.add_argument("--label-config", help="Path to label_config XML")
    ap.add_argument("--records", help="Path to JSONL records (setup, estimate-storage)")
    ap.add_argument(
        "--data-fields",
        help="setup: comma-separated record fields annotators see; "
        "each task keeps id, the --id-field, unique_id and these only (default: every "
        "field except _-prefixed and --hide-fields fields)",
    )
    ap.add_argument(
        "--hide-fields",
        help="setup: comma-separated record fields no task carries, "
        "even without --data-fields (such as auto-labeling's split tag)",
    )
    ap.add_argument(
        "--id-field",
        help="setup: the record id field; every record needs a value no other "
        "record shares, or nothing is created",
    )
    ap.add_argument(
        "--assignments",
        help="JSON file with {profile: {project_id: ...}} (or a setup output); "
        "S3 commands: the setup output (ls_setup.json)",
    )
    ap.add_argument(
        "--out",
        help="export / s3-inspect: export JSONL path; setup: where to save ls_setup.json "
        "(written only on success or partial)",
    )
    ap.add_argument(
        "--s3-uri",
        help="S3 destination the user chose: s3://bucket, a prefix ending in '/', or a full key",
    )
    ap.add_argument(
        "--s3-kms-key-id",
        help="s3-check / export --s3-uri: encrypt with SSE-KMS under this KMS key "
        "(ARN, id or alias); without it the bucket's default encryption applies. "
        "export needs the key its s3-check passed with",
    )
    ap.add_argument(
        "--project-dir",
        help="s3-check / export --s3-uri: project directory holding data/hil/hil-log.jsonl",
    )
    ap.add_argument(
        "--step", default=S3_CHECK_STEP, help="s3-check: HIL log step (the plan step's name)"
    )
    ap.add_argument(
        "--iteration",
        type=int,
        default=0,
        help="s3-check: HIL log iteration (the plan's loop iteration)",
    )
    ap.add_argument(
        "--approval-id",
        help="export: the Step 7 approval entry (HIL log id, needs --project-dir); "
        "the export leaves out the rows it discarded",
    )
    ap.add_argument(
        "--relabel-setup",
        action="append",
        default=[],
        help="export --approval-id: a relabel round's setup output (repeatable; recorded in the HIL "
        "log by setup --relabel-of); its rows replace the discarded ones",
    )
    ap.add_argument(
        "--discarded-out",
        help="export --approval-id: also write the rows left out (one per record, "
        "as exported) to this JSONL file, for Step 8",
    )
    ap.add_argument(
        "--relabel-of",
        help="setup: set up a relabel round for the rows this approval entry "
        "discarded (needs --project-dir and --out; --records is the export); "
        "recorded in the HIL log",
    )
    args = ap.parse_args(argv)

    try:
        if args.ebs_gb is not None and args.command != "create":
            raise UsageError(
                "--ebs-gb is used only by create; a reused space keeps its own volume."
            )
        if args.no_wait and args.command not in ("create", "start"):
            raise UsageError("--no-wait is used only by create and start.")
        missing = [
            f"--{a.replace('_', '-')}"
            for a in _REQUIRED_ARGS.get(args.command, ())
            if not getattr(args, a)
        ]
        if args.command == "export" and args.s3_uri and not args.project_dir:
            missing.append("--project-dir")
        if (
            (
                args.approval_id
                and args.command == "export"
                or args.relabel_of
                and args.command == "setup"
            )
            and not args.project_dir
            and "--project-dir" not in missing
        ):
            missing.append("--project-dir")
        if args.relabel_of and args.command == "setup" and not args.out:
            missing.append("--out")
        if missing:
            raise UsageError(f"'{args.command}' requires {', '.join(missing)}.")
        if (
            args.approval_id
            and args.command != "export"
            or args.relabel_of
            and args.command != "setup"
        ):
            raise UsageError(
                "--approval-id is used only by export, and --relabel-of only by setup."
            )
        if args.relabel_setup and not (args.command == "export" and args.approval_id):
            raise UsageError("--relabel-setup is used only by export, with --approval-id.")
        if args.discarded_out and not (args.command == "export" and args.approval_id):
            raise UsageError("--discarded-out is used only by export, with --approval-id.")
        if (
            args.discarded_out
            and getattr(args, "out", None)
            and os.path.realpath(args.discarded_out) == os.path.realpath(args.out)
        ):
            raise UsageError("--discarded-out must be a different file from --out.")
        discard_plan = None
        if args.command == "export" and args.approval_id:  # before any AWS call or local write
            discard_plan = relabel_rounds(
                args.project_dir, args.assignments, args.approval_id, args.relabel_setup
            )
        relabel_discards = None
        if args.command == "setup" and args.relabel_of:
            relabel_discards = discarded_unique_ids(args.project_dir, args.relabel_of)
        if args.command == "s3-check" and (not args.step.strip() or args.iteration < 0):
            raise UsageError(
                "--step must be a non-empty name and --iteration a non-negative integer."
            )
        upload_uri = None
        if args.s3_uri:
            if args.command not in ("s3-inspect", "s3-check", "export"):
                raise UsageError(
                    f"--s3-uri is used only by s3-inspect, s3-check and export, not '{args.command}'."
                )
            parse_s3_uri(args.s3_uri)  # fail fast, before any AWS call or local write
            upload_uri = export_upload_uri(
                args.s3_uri, _load_setup_output(args.assignments), args.project_name
            )
        if args.s3_kms_key_id and (args.command not in ("s3-check", "export") or not args.s3_uri):
            raise UsageError("--s3-kms-key-id is used only with s3-check and export --s3-uri.")
        if args.command == "record-relabel-round":  # local only: no AWS or Label Studio call
            data = _load_setup_output(args.assignments)
            if not data.get("relabel_of"):
                raise UsageError(
                    f"{args.assignments} is not a relabel round's setup output (no relabel_of)."
                )
            entry_id = record_relabel_round(args.project_dir, args.assignments, data["relabel_of"])
            print(
                json.dumps(
                    {
                        "hil_log_entry": entry_id,
                        "setup": args.assignments,
                        "relabel_of": data["relabel_of"],
                    }
                ),
                file=_stdout(),
            )
            return 0
        if args.command == "s3-inspect":
            out = inspect_s3_destination(upload_uri, args.region)
            out["object_uri"] = export_object_uri(upload_uri, args.out)
            print(json.dumps(out, indent=2), file=_stdout())
            return 0
        if args.command == "s3-check":
            try:
                check = check_s3_destination(upload_uri, args.region, args.s3_kms_key_id)
            except (
                Exception
            ) as e:  # any check that doesn't finish is a failure, so an older pass can't unlock export
                try:
                    record_s3_check(
                        args.project_dir,
                        args.assignments,
                        {"upload_uri": upload_uri, "writable": False, "error": type(e).__name__},
                        args.step,
                        args.iteration,
                    )
                except (OSError, ValueError):
                    pass  # the AWS failure is the error to report; an older entry stands until the next check
                raise
            try:
                check["hil_log_entry"] = record_s3_check(
                    args.project_dir, args.assignments, check, args.step, args.iteration
                )
            except (OSError, ValueError) as e:  # HilLogError is a ValueError
                check["recorded"] = False
                print(json.dumps(check, indent=2), file=_stdout())
                print(
                    json.dumps(
                        {
                            "error": "OutputWriteError",
                            "message": f"The check ran, but recording it in the HIL log failed: {e}. "
                            "Fix the project directory and run s3-check again.",
                        }
                    ),
                    file=sys.stderr,
                )
                return 3
            print(json.dumps(check, indent=2), file=_stdout())
            return 0
        if args.command == "export" and upload_uri:
            require_passed_s3_check(
                args.project_dir, upload_uri, args.assignments, args.s3_kms_key_id
            )  # before any AWS call or write
        if args.command == "estimate-storage":  # local only
            print(json.dumps(estimate_storage(args.records), indent=2), file=_stdout())
            return 0
        if args.command == "discover":
            skipped = []
            try:
                spaces = find_label_studio_space(
                    args.space_name, args.domain_id, args.region, skipped
                )
            except (SpaceNotFoundError, AppNotRunningError) as e:
                # What the create-or-start choice needs: the spaces found and where one could be created.
                print(
                    json.dumps(
                        {
                            "spaces": [],
                            "not_running": getattr(e, "not_running", []),
                            "domains": getattr(e, "domains", []),
                            "skipped_domains": skipped,
                            **_caller_fields(args.region),
                        },
                        indent=2,
                    ),
                    file=_stdout(),
                )
                raise
            print(
                json.dumps(
                    {
                        "spaces": [asdict(s) for s in spaces],
                        "skipped_domains": skipped,
                        **_caller_fields(args.region),
                    },
                    indent=2,
                ),
                file=_stdout(),
            )
            return 0
        if args.command in ("create", "start"):
            if args.command == "create":
                if args.replace_failed_app:
                    raise UsageError("--replace-failed-app is used only by start.")
                out = create_label_studio_space(
                    args.domain_id,
                    args.admin_profile,
                    args.region,
                    DEFAULT_EBS_GB if args.ebs_gb is None else args.ebs_gb,
                    wait=not args.no_wait,
                )
            else:
                out = start_label_studio_app(
                    args.space_name,
                    args.domain_id,
                    args.region,
                    wait=not args.no_wait,
                    replace_failed_app=args.replace_failed_app,
                )
            print(json.dumps(out, indent=2), file=_stdout())
            return 0

        if args.command == "profiles" and args.domain_id and not args.admin_profile:
            # Listing needs only the domain, so it works before a Label Studio space is running.
            profiles = list_annotator_profiles(args.domain_id, args.region)
            try:
                space = _space_from_args(args)
            except (SpaceNotFoundError, AppNotRunningError):
                space = None
            out = {
                "space": asdict(space) if space else None,
                **_caller_fields(args.region),
                "owner_profile": space.owner_profile if space else None,
                "profiles": [{"profile": p} for p in profiles],
            }
            print(json.dumps(out, indent=2), file=_stdout())
            return 0

        space = _space_from_args(args)
        admin = args.admin_profile

        if args.command == "profiles":
            profiles = list_annotator_profiles(space.domain_id, space.region)
            out = {
                "space": asdict(space),
                **_caller_fields(space.region),
                "owner_profile": space.owner_profile,
                "profiles": [{"profile": p} for p in profiles],
            }
            if admin:
                out["admin_profile_check"] = check_admin_profile(space, admin, profiles)
            print(json.dumps(out, indent=2), file=_stdout())
        elif args.command == "setup":
            with open(args.label_config, encoding="utf-8") as f:
                label_config = f.read()
            size = os.path.getsize(args.records)
            if size > MAX_RECORDS_BYTES:
                raise UsageError(
                    f"{args.records} is {size / 1024 / 1024:.0f} MB, over the "
                    f"{MAX_RECORDS_BYTES // 1024 // 1024} MB this skill reads client-side. Annotate a "
                    "sample of it (dataset-transformation can write one), or split it. Nothing was changed."
                )
            with open(args.records, encoding="utf-8") as f:
                records = [json.loads(line) for line in f if line.strip()]
            if relabel_discards is not None:
                records = relabel_records(records, relabel_discards, args.relabel_of, args.records)
            annotators = [a.strip() for a in args.annotators.split(",") if a.strip()]
            data_fields = (
                None
                if args.data_fields is None
                else [f.strip() for f in args.data_fields.split(",") if f.strip()]
            )
            hide_fields = [f.strip() for f in (args.hide_fields or "").split(",") if f.strip()]
            result = setup_projects(
                space,
                admin,
                annotators,
                label_config,
                records,
                args.project_name,
                data_fields=data_fields,
                relabel_of=args.relabel_of,
                hide_fields=hide_fields,
                id_field=args.id_field,
            )
            out = {**result.to_dict(), "markdown": result.to_markdown()}
            print(
                json.dumps(out, indent=2), file=_stdout()
            )  # print first: the projects exist even if saving fails
            if not _save_setup_output(args.out, out):
                return 3
            if args.relabel_of:
                try:
                    record_relabel_round(args.project_dir, args.out, args.relabel_of)
                except (OSError, ValueError) as e:  # HilLogError is a ValueError
                    print(
                        json.dumps(
                            {
                                "error": "OutputWriteError",
                                "message": f"The relabel project was created and {args.out} saved, but "
                                f"recording it in the HIL log failed: {e}. Record it with "
                                "'record-relabel-round' before exporting.",
                            }
                        ),
                        file=sys.stderr,
                    )
                    return 3
        elif args.command == "status":
            progress = get_progress(space, admin, _load_assignments(args.assignments))
            print(
                json.dumps({**progress, "markdown": progress_markdown(progress)}, indent=2),
                file=_stdout(),
            )
        elif args.command == "export":
            assignments = _load_assignments(args.assignments)
            if discard_plan is None:
                rows = export_annotations(space, admin, assignments)
            else:
                setup_time, relabel, approvals = discard_plan
                session = LabelStudioSession(space, admin).connect()
                rounds = [
                    (None, setup_time, export_annotations(space, admin, assignments, session))
                ]
                rounds += [
                    (rl, t, export_annotations(space, admin, a, session)) for rl, t, a in relabel
                ]
                rows, left_out, relabeled, discarded_rows = apply_discards(rounds, approvals)
            try:
                files = [(args.out, rows)]
                if discard_plan is not None and args.discarded_out:
                    files.append((args.discarded_out, discarded_rows))
                _write_jsonl_files_atomic(
                    files
                )  # --out and --discarded-out replace their files together
            except (
                OSError
            ) as e:  # a disk or permission problem, not a usage error; nothing was uploaded
                print(
                    json.dumps(
                        {
                            "error": "OutputWriteError",
                            "message": f"Writing the export failed: {e}. Any earlier export file is "
                            "unchanged. Fix the disk or the --out path and run export again.",
                        }
                    ),
                    file=sys.stderr,
                )
                return 3
            out = {
                "exported_tasks": len(rows),
                "out": args.out,
                "attribution_summary": attribution_summary(rows),
            }
            if discard_plan is not None and args.discarded_out:
                out["discarded_out"] = args.discarded_out
            if discard_plan is not None:
                out["approval_id"] = args.approval_id
                out["discarded"] = {"count": len(left_out), "unique_ids": left_out}
                out["relabeled"] = {"count": len(relabeled), "unique_ids": relabeled}
            if upload_uri:
                try:
                    out["s3_uri"] = upload_export(
                        args.out, upload_uri, args.region, args.s3_kms_key_id
                    )
                except AwsCallError as e:
                    # The local export is complete; report it together with why the S3 copy failed.
                    out["s3_error"] = str(e)
                    print(json.dumps(out), file=_stdout())
                    print(
                        json.dumps({"error": "S3UploadError", "message": str(e)}), file=sys.stderr
                    )
                    return 5
            print(json.dumps(out), file=_stdout())
    except (SpaceNotFoundError, AppNotRunningError) as e:
        print(json.dumps({"error": type(e).__name__, "message": str(e)}), file=sys.stderr)
        return 2
    except DomainNotReadyError as e:
        print(json.dumps({"error": "DomainNotReadyError", "message": str(e)}), file=sys.stderr)
        return 6
    except SdkUnavailableError as e:
        print(json.dumps({"error": "SdkUnavailableError", "message": str(e)}), file=sys.stderr)
        return 4
    except LaunchError as e:
        print(json.dumps({"error": "LaunchError", "message": str(e)}), file=sys.stderr)
        return 5
    except (
        ValueError,
        OSError,
    ) as e:  # UsageError, empty annotator list, unreadable/invalid input file
        if _is_sdk_model_error(e):
            # a SageMaker Python SDK modeling error after its AWS call: not the user's input, and
            # the call may have gone through. Its text can hold the response, so it isn't shown.
            print(
                json.dumps(
                    {
                        "error": "AwsCallError",
                        "message": f"The SageMaker Python SDK failed to read "
                        f"an AWS response ({type(e).__name__}); the call may have gone through. "
                        "Run discover to check the space.",
                    }
                ),
                file=sys.stderr,
            )
            return 5
        if type(e).__module__.startswith("botocore") and type(e).__name__ != "InvalidRegionError":
            # botocore network/endpoint errors (ReadTimeout, EndpointConnection, SSLError, ...)
            # subclass OSError/ValueError; they are AWS-side failures, not usage errors.
            print(json.dumps({"error": "AwsCallError", "message": _aws_error(e)}), file=sys.stderr)
            return 5
        print(json.dumps({"error": "UsageError", "message": str(e)}), file=sys.stderr)
        return 4
    except SetupPartialError as e:
        partial = {**e.result.to_dict(), "partial": True, "failed_profile": e.failed_profile}
        print(json.dumps(partial, indent=2), file=_stdout())
        if args.command == "setup":
            _save_setup_output(args.out, partial)
        print(json.dumps({"error": "SetupPartialError", "message": str(e)}), file=sys.stderr)
        return 3
    except LabelStudioError as e:
        print(json.dumps({"error": "LabelStudioError", "message": str(e)}), file=sys.stderr)
        return 3
    except AwsCallError as e:
        print(json.dumps({"error": "AwsCallError", "message": str(e)}), file=sys.stderr)
        return 5
    except Exception as e:
        if type(e).__module__.startswith("botocore"):  # ClientError, NoCredentialsError, ...
            print(json.dumps({"error": "AwsCallError", "message": _aws_error(e)}), file=sys.stderr)
            return 5
        raise
    return 0


if __name__ == "__main__":
    # stdout carries only the command's JSON result. Anything else that writes to stdout (some
    # sagemaker-core versions put a rich log handler on the root logger) goes to stderr.
    _RESULT_STDOUT = sys.stdout
    with contextlib.redirect_stdout(sys.stderr):
        code = main()
    sys.exit(code)
