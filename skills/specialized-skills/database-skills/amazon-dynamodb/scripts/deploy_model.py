#!/usr/bin/env python3
"""Deploy benchmark resources from dynamodb_data_model.json to an AWS account.

Reads the design JSON consumed by calculate_costs.py plus a benchmark_config.json
(see references/performance-model-schema.md). Runs a safety preflight
(caller-identity + prod-marker refusal), creates DynamoDB tables concurrently
with a benchmark prefix, deploys the benchmark Lambda and its IAM role, and
writes a manifest describing everything created.

The bench-only deploy deliberately diverges from SKILL.md Best Practices:

    DeletionProtection = False    (bench tables are meant to be deleted)
    PITR                = off     (2-minute lifetime — PITR adds cost, no value)
    TTL                 = not set (sweep cadence is hours — bench ends first)

These defaults match SKILL.md Data modeling #3's own logic for ephemeral /
cache-like tables. Production designs still get Best Practices defaults —
this is a tooling choice for the benchmark, not a rule change.

Safety contract:
  - Refuses unless --yes-deploy is passed.
  - Aborts on caller-identity ARN / alias containing prod, production, prd, live.
  - On an interactive terminal, prints the target account and waits a few
    seconds for a Ctrl-C abort before creating anything; non-interactive
    (agent/CI) runs proceed immediately on the --yes-deploy consent.
  - resource_prefix is optional: if absent it is auto-generated as
    ddb-skill-bench-<date>-<uuid8>; if supplied it MUST start with
    ddb-skill-bench- (so teardown can scope deletions) or the deploy refuses.
  - Refuses if boto3 is missing, credentials are missing/expired,
    access_patterns is empty, any pattern has missing/zero peak_rps, or any
    table is missing key_schema.

Usage:
    python3 deploy_model.py \\
        --model dynamodb_data_model.json \\
        --config benchmark_config.json \\
        --manifest-out created_resources.json \\
        --yes-deploy
"""
from __future__ import annotations

import argparse
import datetime as _dt
import io
import json
import sys
import time
import uuid
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

PROD_MARKERS = ("prod", "production", "prd", "live")
REQUIRED_PREFIX = "ddb-skill-bench-"
TYPE_MAP = {"S": "S", "N": "N", "B": "B"}


# Lambda role trust policy — the only principal allowed to assume is the Lambda
# service itself, and only when the source account matches the deploying account
# (aws:SourceAccount guards against confused-deputy assumption from other
# accounts). The account is known from the preflight identity check, so we build
# the document at role-creation time rather than hardcoding it.
def _build_lambda_trust_policy(account: str) -> dict:
    return {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Principal": {"Service": "lambda.amazonaws.com"},
                "Action": "sts:AssumeRole",
                "Condition": {"StringEquals": {"aws:SourceAccount": str(account)}},
            }
        ],
    }


# 1769 MB is the threshold where Lambda allocates a full vCPU. The benchmark
# driver runs up to concurrency_per_pattern (default 32) I/O-bound threads; a
# full vCPU gives headroom for the GIL-bound boto3/JSON work between round trips
# so the open-loop scheduler can sustain the higher single-Lambda rps ceiling.
# Cost impact is negligible (a benchmark runs minutes). Override via config.
DEFAULT_LAMBDA_MEMORY_MB = 1769
DEFAULT_LAMBDA_TIMEOUT_S = 900
LAMBDA_RUNTIME = "python3.12"
LAMBDA_HANDLER = "benchmark.handler"

# Brief abort window shown ONLY on an interactive terminal, after the
# caller-identity banner and before any resource is created. Non-interactive
# (agent/CI) runs skip it — consent was already given via --yes-deploy.
_ABORT_WINDOW_S = 5


def _die(msg: str, code: int = 2) -> None:
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(code)


def _require_boto3():
    try:
        import boto3  # noqa: F401
        from botocore.exceptions import ClientError  # noqa: F401

        return boto3
    except ImportError:
        _die("boto3 not installed. Run: pip install boto3>=1.34")


def _load_json(path: Path) -> dict:
    if not path.exists():
        _die(f"file not found: {path}")
    with path.open() as f:
        return json.load(f)


def _validate_design(model: dict) -> None:
    if not model.get("tables"):
        _die("design JSON has no tables")
    aps = model.get("access_patterns") or []
    if not aps:
        _die(
            "design JSON has no access_patterns — refusing (Mechanics #2: "
            "unknown RPS is a design gap, not a benchmark input)."
        )
    for ap in aps:
        if not ap.get("peak_rps"):
            _die(
                f"access pattern {ap.get('pattern_id', '?')} has missing or "
                "zero peak_rps — refusing per Mechanics #2."
            )
    for t in model["tables"]:
        ks = t.get("key_schema") or {}
        if not ks.get("partition_key"):
            _die(
                f"table {t.get('table_name', '?')} has no "
                "key_schema.partition_key. Live deploy requires an explicit "
                '{"key_schema": {"partition_key": "<attr>", "sort_key": '
                '"<attr>?"}} block per table. Add it to the JSON and re-run. '
                "(The cost calculator does not require this; live deploy does.)"
            )
    _validate_pattern_refs(model)


def _validate_pattern_refs(model: dict) -> None:
    """Every access pattern must point at a table that exists, and any Query/Scan
    `index` must name a GSI defined on that table. Catching this up front turns a
    silent benchmark failure (the operation errors on 100% of calls, observed CU
    reads as 0, and a naive report calls it cheap) into a clear, pre-deploy
    refusal. This guards the structural-reference class of mistakes the real-AWS
    run surfaced (Query on a missing GSI, pattern on a missing table)."""
    tables_by_name = {t.get("table_name"): t for t in model.get("tables", [])}
    for ap in model.get("access_patterns") or []:
        pid = ap.get("pattern_id", "?")
        tn = ap.get("table")
        if not tn:
            _die(
                f'access pattern {pid} has no "table" — every pattern must '
                "name the table it runs against."
            )
        td = tables_by_name.get(tn)
        if td is None:
            _die(
                f"access pattern {pid} references table {tn!r}, which is not "
                f"defined in tables[]. Defined tables: "
                f'{sorted(tables_by_name)}. Fix the "table" field or add the '
                "table."
            )
        idx = ap.get("index")
        op = ap.get("operation")
        vec_names = {v.get("index_name") for v in ((td or {}).get("vector_indexes") or [])}
        gsi_names = {g.get("index_name") for g in ((td or {}).get("gsis") or [])}

        # SearchVectors reads a VECTOR index, never a GSI — and the reverse is also
        # true, so each operation is checked against the right index family. Getting
        # this wrong fails every call at runtime while the observed CU reads as 0,
        # which a naive report then calls cheap.
        if op == "SearchVectors":
            if not idx:
                _die(
                    f'access pattern {pid} is a SearchVectors but has no "index" — '
                    "it must name the vector index to search."
                )
            if idx not in vec_names:
                _die(
                    f"access pattern {pid} searches vector index {idx!r} on table "
                    f"{tn!r}, but that table defines no such vector index. Defined "
                    f"vector indexes on {tn}: {sorted(n for n in vec_names if n)}. "
                    'Add it to vector_indexes[] or correct the "index" field.'
                )
        elif idx:
            if idx in vec_names:
                _die(
                    f"access pattern {pid} targets {idx!r} on table {tn!r} with "
                    f"operation {op!r}, but {idx!r} is a VECTOR index. Query and Scan "
                    "are rejected against a vector index with "
                    "'ValidationException: Query operation not supported on this index "
                    'type.\' Use operation "SearchVectors" to read it.'
                )
            if idx not in gsi_names:
                _die(
                    f"access pattern {pid} uses index {idx!r} on table {tn!r}, "
                    f"but that table defines no such GSI. Defined GSIs on {tn}: "
                    f"{sorted(n for n in gsi_names if n)}. A Query/Scan against a "
                    "non-existent index fails every call at runtime — add the GSI "
                    'to the table or correct the "index" field.'
                )


def _ensure_resource_prefix(cfg: dict, today: str) -> bool:
    """Fill in resource_prefix when the caller did not supply one.

    The agent should NOT have to hand-build the prefix (date + uuid8) and get
    its shape exactly right only to be refused — the script can generate a
    valid, run-unique prefix itself. `today` is the YYYYMMDD already derived
    from this run's clock so the prefix and the manifest's created_at agree.

    Returns True if a prefix was auto-generated (so the caller can surface it),
    False if the caller supplied one explicitly. An explicitly supplied prefix
    is still validated for the required namespace by _validate_config.
    """
    if cfg.get("resource_prefix"):
        return False
    cfg["resource_prefix"] = f"{REQUIRED_PREFIX}{today}-{uuid.uuid4().hex[:8]}"
    return True


def _validate_config(cfg: dict) -> None:
    for k in ("aws_profile", "region"):
        if not cfg.get(k):
            _die(f"benchmark_config.json missing required field: {k}")
    # resource_prefix is auto-generated by _ensure_resource_prefix when absent,
    # so by the time we get here it is always set; we only police its namespace
    # (which matters most for caller-supplied values).
    if not cfg.get("resource_prefix"):
        _die("benchmark_config.json missing required field: resource_prefix")
    if not cfg["resource_prefix"].startswith(REQUIRED_PREFIX):
        _die(
            f"resource_prefix must start with {REQUIRED_PREFIX!r} so teardown "
            f"can scope deletions safely. Got: {cfg['resource_prefix']!r}. "
            "Tip: omit resource_prefix entirely and the deploy generates a "
            f"valid one ({REQUIRED_PREFIX}<date>-<uuid8>) for you."
        )


def _preflight(boto3_mod, cfg: dict, dry_run: bool = False) -> dict:
    """Run sts get-caller-identity, refuse on prod markers, return identity dict.

    On an interactive terminal (and only for a real deploy, not a dry run) this
    prints the target account and waits a brief window for a Ctrl-C abort before
    returning. Non-interactive runs and dry runs return immediately.
    """
    from botocore.exceptions import (
        ClientError,
        EndpointConnectionError,
        NoCredentialsError,
    )

    try:
        session = boto3_mod.Session(profile_name=cfg["aws_profile"], region_name=cfg["region"])
        sts = session.client("sts")
        ident = sts.get_caller_identity()
    except NoCredentialsError:
        _die(
            "AWS credentials not found for profile "
            f"{cfg['aws_profile']!r}. Try: aws sso login --profile "
            f"{cfg['aws_profile']}"
        )
    except ClientError as e:
        code = e.response.get("Error", {}).get("Code", "Unknown")
        _die(
            f"sts get-caller-identity failed ({code}): {e}. "
            f"Credentials may be expired — try: aws sso login --profile "
            f"{cfg['aws_profile']}"
        )
    except EndpointConnectionError as e:
        _die(f"cannot reach AWS endpoint: {e}")
    except Exception as e:
        _die(f"AWS credential check failed: {type(e).__name__}: {e}")

    arn = ident.get("Arn", "")
    account = ident.get("Account", "")
    account_alias = ""
    try:
        iam = session.client("iam")
        aliases = iam.list_account_aliases().get("AccountAliases", [])
        account_alias = aliases[0] if aliases else ""
    except Exception:
        # list_account_aliases can fail with no permission; prod-check still
        # works off the ARN alone.
        pass

    lower = f"{arn} {account_alias}".lower()
    matched = [m for m in PROD_MARKERS if m in lower]
    if matched:
        _die(
            f"caller identity appears to be production ({matched}). "
            f"ARN: {arn}. Alias: {account_alias or '<none>'}. "
            "REFUSING to deploy benchmark resources against a prod account."
        )

    bar = "#" * 72
    print(bar)
    print("# WARNING — this will create REAL AWS resources in the account shown")
    print("# below. A benchmark run typically costs single-digit cents but")
    print("# involves:")
    print("#   - Multiple DynamoDB tables and GSIs with live capacity.")
    print("#   - A Lambda function and IAM role.")
    print("#   - Seed + warmup + measurement traffic (hundreds to thousands")
    print("#     of reads/writes).")
    print("#")
    print("# USE AN AWS ACCOUNT DEDICATED TO TESTING.")
    print("# Do NOT run this against production or any account holding real")
    print("# user data. The teardown script is generated separately and must")
    print("# be run by you.")
    print(bar)
    print()
    print("=" * 72)
    print("Caller identity confirmation:")
    print(f"  Account: {account}")
    print(f"  Alias:   {account_alias or '<none>'}")
    print(f"  ARN:     {arn}")
    print(f"  Region:  {cfg['region']}")
    print("=" * 72)
    # Consent was already given via --yes-deploy (validated in main before we
    # got here), so the deploy proceeds immediately. Only when this is an
    # interactive terminal AND a real deploy do we offer a real, brief abort
    # window — in an agent/CI run (no TTY) there is no human to press Ctrl-C, so
    # we must not print a "cancel now" prompt that nobody can act on, and a dry
    # run creates nothing so there is nothing to abort.
    if dry_run:
        return {"account": account, "alias": account_alias, "arn": arn}
    interactive = False
    try:
        interactive = sys.stdin.isatty() and sys.stdout.isatty()
    except Exception:
        interactive = False
    if interactive:
        print(
            f"\nThis account is shown above. Deploying in {_ABORT_WINDOW_S}s — "
            "press Ctrl-C now to abort if it is NOT a testing account."
        )
        try:
            time.sleep(_ABORT_WINDOW_S)
        except KeyboardInterrupt:
            _die("aborted by user before any resource was created.", code=130)
    else:
        print(
            "\nProceeding (consent given via --yes-deploy; non-interactive run, "
            "no abort prompt). Verify the account above is a testing account."
        )
    return {"account": account, "alias": account_alias, "arn": arn}


def _collect_attr_types(tables: list[dict]) -> dict[str, dict[str, str]]:
    """Per-table map of attribute-name → DynamoDB type letter ("S"/"N"/"B").

    Types are read from TWO sources, in increasing precedence:
      1. entities[].attributes[] as {"name","type"} — the canonical schema form
         documented in references/cost-model-schema.md.
      2. a table-level "attribute_definitions" block — the raw-CreateTable-API
         spelling an author (or LLM) naturally reaches for. Accepts BOTH
         {"attribute_name","attribute_type"} (API style) and the {"name","type"}
         shorthand. An explicit attribute_definitions entry WINS over an
         entities-derived type for the same attribute.

    A key attribute whose type is never declared falls through to "S" in
    _build_create_kwargs. Declaring a numeric/binary key as anything other than
    its true type (or leaving it to default to "S") makes CreateTable build the
    wrong AttributeType, so writes of the real value fail with
    ValidationException in production. scripts/benchmark_lambda.py builds the
    identical map with the same precedence — keep the two in sync.
    """

    def _norm_t(v) -> str:
        return TYPE_MAP.get((v or "S").upper(), "S")

    by_table: dict[str, dict[str, str]] = {}
    for t in tables:
        tm = by_table.setdefault(t["table_name"], {})
        # 1. entities[].attributes[]  (lower precedence)
        for e in t.get("entities") or []:
            for a in e.get("attributes") or []:
                name = a.get("name")
                if name:
                    tm[name] = _norm_t(a.get("type"))
        # 2. table-level attribute_definitions  (higher precedence)
        for a in t.get("attribute_definitions") or []:
            name = a.get("attribute_name") or a.get("name")
            if name:
                tm[name] = _norm_t(a.get("attribute_type") or a.get("type"))
    return by_table


def _build_create_kwargs(
    table_def: dict,
    prefix: str,
    tags: dict,
    attr_types: dict[str, str],
    _global_provisioned: dict | None = None,
) -> dict:
    ks = table_def["key_schema"]
    pk = ks["partition_key"]
    sk = ks.get("sort_key")

    referenced_attrs: dict[str, str] = {pk: attr_types.get(pk, "S")}
    if sk:
        referenced_attrs[sk] = attr_types.get(sk, "S")

    key_schema = [{"AttributeName": pk, "KeyType": "HASH"}]
    if sk:
        key_schema.append({"AttributeName": sk, "KeyType": "RANGE"})

    gsis = []
    for g in table_def.get("gsis") or []:
        g_pk = g.get("partition_key")
        g_sk = g.get("sort_key")
        if not g_pk:
            _die(
                f"GSI {g.get('index_name', '?')} on table "
                f"{table_def['table_name']} has no partition_key"
            )
        referenced_attrs[g_pk] = attr_types.get(g_pk, "S")
        g_key_schema = [{"AttributeName": g_pk, "KeyType": "HASH"}]
        if g_sk:
            referenced_attrs[g_sk] = attr_types.get(g_sk, "S")
            g_key_schema.append({"AttributeName": g_sk, "KeyType": "RANGE"})

        proj = g.get("projection") or {"type": "ALL"}
        p_type = (proj.get("type") or "ALL").upper()
        proj_kwargs: dict = {"ProjectionType": p_type}
        if p_type == "INCLUDE":
            # Accept any of the three spellings the rest of the toolchain reads
            # (`attributes` is canonical per cost-model-schema.md; calculate_costs
            # and iterate_design's fingerprint also accept `non_key_attributes` /
            # `NonKeyAttributes`). Reading only `attributes` here would silently
            # create the GSI with an EMPTY include list — projecting nothing —
            # when the design used another spelling, while the calculator and
            # fingerprint happily saw the attributes. Stay consistent.
            include_attrs = (
                proj.get("attributes")
                or proj.get("non_key_attributes")
                or proj.get("NonKeyAttributes")
                or []
            )
            if not include_attrs:
                _die(
                    f"GSI {g['index_name']} on table {table_def['table_name']} "
                    "has projection type INCLUDE but no projected attributes. "
                    'Add a non-empty "attributes" list to the projection, or '
                    'use "ALL"/"KEYS_ONLY".'
                )
            proj_kwargs["NonKeyAttributes"] = list(include_attrs)

        gsis.append(
            {
                "IndexName": g["index_name"],
                "KeySchema": g_key_schema,
                "Projection": proj_kwargs,
            }
        )

    # Vector indexes. Two things bite here and both are hard failures at CreateTable
    # rather than at write time, so they are handled before AttributeDefinitions is built:
    #   * every SearchSchema attribute must ALSO be declared in AttributeDefinitions,
    #     exactly as a GSI key attribute must ("One element in SearchSchema is not
    #     defined in attribute definitions"), and
    #   * vector indexes require on-demand capacity, so a provisioned bench run cannot
    #     carry one.
    vector_indexes = []
    for v in table_def.get("vector_indexes") or []:
        name = v.get("index_name")
        attr = v.get("vector_attribute")
        dims = v.get("dimensions")
        fn = (v.get("distance_function") or "").upper()
        if not (name and attr and dims and fn):
            _die(
                f"vector index {name or '?'} on table {table_def['table_name']} needs "
                "index_name, vector_attribute, dimensions and distance_function"
            )
        if fn not in {"COSINE", "EUCLIDEAN", "DOT_PRODUCT"}:
            _die(
                f"vector index {name}: distance_function must be COSINE, EUCLIDEAN or "
                f"DOT_PRODUCT, got {v.get('distance_function')!r}"
            )
        if not 1 <= int(dims) <= 4096:
            _die(f"vector index {name}: dimensions must be 1-4096, got {dims!r}")

        vproj = v.get("projection") or {"type": "ALL"}
        # Accept the bare-string shorthand: "KEYS_ONLY" == {"type": "KEYS_ONLY"}. Writing the
        # string is the natural mistake (it is how the API-level value reads), and without this
        # the next line raised a bare AttributeError instead of anything actionable. Mirrors the
        # attribute_definitions shorthand accepted elsewhere in these scripts.
        if isinstance(vproj, str):
            vproj = {"type": vproj}
        vp_type = (vproj.get("type") or "ALL").upper()
        vproj_kwargs: dict = {"ProjectionType": vp_type}
        if vp_type == "INCLUDE":
            inc = (
                vproj.get("attributes")
                or vproj.get("non_key_attributes")
                or vproj.get("NonKeyAttributes")
                or []
            )
            if not inc:
                _die(
                    f"vector index {name} has projection INCLUDE but no projected "
                    'attributes. Add a non-empty "attributes" list, or use '
                    '"ALL"/"KEYS_ONLY".'
                )
            vproj_kwargs["NonKeyAttributes"] = list(inc)

        spec: dict = {
            "IndexName": name,
            "VectorAttribute": {"AttributeName": attr},
            "Projection": vproj_kwargs,
            "Dimensions": int(dims),
            "DistanceFunction": fn,
        }

        schema = v.get("search_schema") or {}
        elements = []
        v_pk = schema.get("partition_key")
        if v_pk:
            referenced_attrs[v_pk] = attr_types.get(v_pk, "S")
            elements.append({"AttributeName": v_pk, "SearchSchemaElementType": "HASH"})
        for f in schema.get("inline_filters") or []:
            referenced_attrs[f] = attr_types.get(f, "S")
            elements.append({"AttributeName": f, "SearchSchemaElementType": "INLINE_FILTER"})
        if elements:
            spec["SearchSchema"] = elements
        vector_indexes.append(spec)

    attr_defs = [
        {"AttributeName": name, "AttributeType": t} for name, t in sorted(referenced_attrs.items())
    ]

    kwargs: dict = {
        "TableName": f"{prefix}{table_def['table_name']}",
        "AttributeDefinitions": attr_defs,
        "KeySchema": key_schema,
        "BillingMode": "PAY_PER_REQUEST",
        # Bench-only: deletion protection OFF (see module docstring).
        "DeletionProtectionEnabled": False,
        # Encryption at rest: DynamoDB ALWAYS encrypts at rest. The default is an
        # AWS-owned key (no cost, no key management) — correct for ephemeral bench
        # tables — and is the implicit state when no SSESpecification is sent. We
        # intentionally do NOT pass SSESpecification here: DynamoDB's SSEType only
        # accepts "KMS" (a customer-/AWS-managed CMK); there is no "AES256" SSEType
        # on DynamoDB (that is an S3 spelling) and sending one is rejected with a
        # ValidationException. The at-rest state is surfaced in the manifest from
        # DescribeTable instead. Production designs that need a customer-managed CMK
        # for audit/compliance set SSESpecification={"Enabled": true, "SSEType":
        # "KMS", "KMSMasterKeyId": "<arn>"}; see SKILL.md "Security considerations".
        "Tags": [{"Key": k, "Value": str(v)} for k, v in tags.items()],
    }

    # Optional PROVISIONED capacity for a deliberate capacity-ceiling test. On
    # on-demand, adaptive capacity auto-scales the table and absorbs a hot key,
    # so a single load generator rarely produces throttles. A low provisioned
    # total imposes a HARD table-wide ceiling adaptive capacity cannot exceed —
    # the reliable way to observe hot-partition throttling (Mechanics #3) and to
    # validate a planned provisioned capacity (Mechanics #19). Set via the
    # design's table.provisioned_capacity = {"read": N, "write": M}, or globally
    # via benchmark_config.provisioned_capacity. Bench-only; production designs
    # still default to on-demand.
    prov = table_def.get("provisioned_capacity") or _global_provisioned
    if prov and vector_indexes:
        _die(
            f"table {table_def['table_name']} declares a vector index AND provisioned "
            "capacity. Vector indexes are supported only on on-demand "
            "(PAY_PER_REQUEST) tables, so this table cannot be created as declared. "
            "Remove provisioned_capacity for this table (or drop the vector index) and "
            "re-run. Note a provisioned-ceiling throttle experiment is therefore not "
            "available on a vector-indexed table."
        )
    if prov:
        kwargs["BillingMode"] = "PROVISIONED"
        kwargs["ProvisionedThroughput"] = {
            "ReadCapacityUnits": int(prov.get("read", 5)),
            "WriteCapacityUnits": int(prov.get("write", 5)),
        }

    if gsis:
        if prov:
            for g in gsis:
                g["ProvisionedThroughput"] = {
                    "ReadCapacityUnits": int(prov.get("read", 5)),
                    "WriteCapacityUnits": int(prov.get("write", 5)),
                }
        kwargs["GlobalSecondaryIndexes"] = gsis

    if vector_indexes:
        # A single CreateTable may define several vector indexes (up to the per-table
        # limit of 5), and creating them inline avoids the UpdateTable backfill path
        # entirely — measured at 20s inline versus 8m33s for an add-to-existing-table on
        # a six-item table.
        if len(vector_indexes) > 5:
            _die(
                f"table {table_def['table_name']} declares {len(vector_indexes)} vector "
                "indexes; the per-table limit is 5"
            )
        kwargs["VectorIndexes"] = vector_indexes

    streams = table_def.get("streams") or {}
    if streams.get("enabled"):
        view = streams.get("view_type", "NEW_AND_OLD_IMAGES")
        kwargs["StreamSpecification"] = {
            "StreamEnabled": True,
            "StreamViewType": view,
        }
    return kwargs


def _create_table_one(client, kwargs: dict) -> None:
    """Issue CreateTable. Swallow ResourceInUseException as a rerun-safety."""
    from botocore.exceptions import ClientError

    try:
        client.create_table(**kwargs)
    except ClientError as e:
        code = e.response.get("Error", {}).get("Code", "")
        if code == "ResourceInUseException":
            print(f"  note: {kwargs['TableName']} already exists — reusing.")
        else:
            raise


def _wait_table_active(client, table_name: str) -> dict:
    waiter = client.get_waiter("table_exists")
    waiter.wait(TableName=table_name)
    desc = client.describe_table(TableName=table_name)["Table"]
    if desc.get("VectorIndexes"):
        desc = _wait_vector_indexes_ready(client, table_name)
    return desc


def _wait_vector_indexes_ready(client, table_name: str, timeout_s: int = 1800) -> dict:
    """Wait until every vector index is ACTIVE and not backfilling.

    The `table_exists` waiter returns when the TABLE is ACTIVE and says nothing about a
    vector index, so returning there hands the benchmark an index that rejects
    SearchVectors. There is no `BACKFILLING` index status: the correct predicate is
    `IndexStatus == "ACTIVE" and not Backfilling`, and it is the only one correct on both
    creation paths — measured, the two report `Backfilling` differently:

      inline CreateTable : CREATING with the Backfilling key ABSENT, then ACTIVE (~20s)
      UpdateTable add    : CREATING/Backfilling=false, then CREATING/Backfilling=true,
                           then ACTIVE (8m33s on a six-item table)

    So "wait for the Backfilling key to disappear" returns immediately-but-wrongly on the
    inline path, and "wait for Backfilling == false" returns minutes early on the other.
    """
    deadline = time.time() + timeout_s
    announced = False
    while True:
        desc = client.describe_table(TableName=table_name)["Table"]
        vis = desc.get("VectorIndexes") or []
        pending = [v for v in vis if v.get("IndexStatus") != "ACTIVE" or v.get("Backfilling")]
        if not pending:
            return desc
        if not announced:
            names = ", ".join(v.get("IndexName", "?") for v in pending)
            print(f"  waiting on vector index/indexes: {names} " f"(ACTIVE and not backfilling)")
            announced = True
        if time.time() > deadline:
            states = {v.get("IndexName"): (v.get("IndexStatus"), v.get("Backfilling")) for v in vis}
            _die(
                f"vector index on {table_name} not ready after {timeout_s}s: {states}. "
                "Backfill duration is driven by index construction, not item count, so a "
                "small table can still take many minutes."
            )
        time.sleep(5)


def _deploy_tables_concurrent(client, table_specs: list[tuple[dict, str]]):
    """Fire CreateTable for each spec in parallel, then wait on all concurrently.

    Each spec is (create_kwargs, original_table_name); the name element is unused
    here (the kwargs already carry the prefixed TableName) and is kept only so the
    caller can correlate results back to the source table.
    """
    # Phase 1: fire all CreateTable calls.
    for kwargs, _ in table_specs:
        print(f"  CreateTable: {kwargs['TableName']}")
        _create_table_one(client, kwargs)

    # Phase 2: wait on all waiters concurrently.
    descriptions: dict[str, dict] = {}
    with ThreadPoolExecutor(max_workers=min(16, len(table_specs) or 1)) as pool:
        futures = {
            pool.submit(_wait_table_active, client, kwargs["TableName"]): kwargs["TableName"]
            for kwargs, _ in table_specs
        }
        for fut in as_completed(futures):
            tn = futures[fut]
            descriptions[tn] = fut.result()
            print(f"  ACTIVE: {tn}")
    return descriptions


# DynamoDB vector operations (SearchVectors and friends) ship in botocore 1.43.64. The
# managed Lambda python3.12 runtime bundles a much older boto3, so a vector benchmark run
# MUST carry its own SDK or every SearchVectors call dies with AttributeError while the
# observed capacity reads as zero — i.e. it looks like a free pattern rather than a broken
# one.
#
# Shipping only the newer dynamodb service model via AWS_DATA_PATH does NOT work: the new
# endpoint rule set uses a `stringArray` parameter type the old botocore cannot parse
# (`EndpointResolutionError: Unknown parameter type: stringArray`), and SearchVectors is
# served by a dedicated endpoint that must be resolved from those rules. Verified.
#
# So the whole SDK is vendored from the LOCAL install — which the skill already requires —
# rather than pip-installed at deploy time. No network, no new dependency. The cost (~18 MB
# zipped, a few seconds of upload) is paid ONLY by designs that declare a vector index;
# every other design gets the same few-KB package as before.
VECTOR_SDK_MIN = (1, 43, 64)


def _local_sdk_paths() -> tuple[Path, Path]:
    import boto3 as _b3
    import botocore as _bc

    ver = tuple(int(x) for x in _bc.__version__.split(".")[:3])
    if ver < VECTOR_SDK_MIN:
        _die(
            f"this design declares a vector index, which the benchmark Lambda can only "
            f"drive with botocore >= {'.'.join(map(str, VECTOR_SDK_MIN))}. The locally "
            f"installed botocore is {_bc.__version__}, and it is what gets vendored into "
            f"the Lambda package. Upgrade locally first:\n"
            f"    pip install 'boto3>={'.'.join(map(str, VECTOR_SDK_MIN))}'"
        )
    return Path(_b3.__file__).resolve().parent, Path(_bc.__file__).resolve().parent


def _build_lambda_zip(bundle_vector_sdk: bool = False) -> bytes:
    """Zip the handler source into an in-memory Lambda deployment package.

    With bundle_vector_sdk, also vendor the local boto3/botocore so the handler can call
    SearchVectors. Lambda puts /var/task ahead of the runtime's site-packages on sys.path,
    so the vendored copy wins.
    """
    here = Path(__file__).resolve().parent
    handler_src = here / "benchmark_lambda.py"
    if not handler_src.exists():
        _die(
            f"lambda handler not found at {handler_src}. The skill is missing "
            "the scripts/benchmark_lambda.py file — reinstall the skill."
        )
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        # The deployed module is named benchmark.py inside the zip so the Lambda
        # Handler config (LAMBDA_HANDLER = "benchmark.handler") resolves; the
        # local source file is scripts/benchmark_lambda.py.
        z.writestr("benchmark.py", handler_src.read_text())
        if bundle_vector_sdk:
            b3_dir, bc_dir = _local_sdk_paths()
            n = 0
            for pkg_dir in (b3_dir, bc_dir):
                root = pkg_dir.parent
                for f in pkg_dir.rglob("*"):
                    if not f.is_file():
                        continue
                    # Skip caches and test trees; they are dead weight in a Lambda.
                    if "__pycache__" in f.parts or f.suffix in (".pyc", ".pyo"):
                        continue
                    z.write(f, str(f.relative_to(root)))
                    n += 1
            print(
                f"  vendoring local boto3/botocore into the Lambda package "
                f"({n} files) so SearchVectors can be driven"
            )
    return buf.getvalue()


def _build_role_policy(prefix: str, region: str, account: str) -> dict:
    table_arn = f"arn:aws:dynamodb:{region}:{account}:table/{prefix}*"
    return {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Action": [
                    "dynamodb:DescribeTable",
                    "dynamodb:GetItem",
                    "dynamodb:Query",
                    "dynamodb:Scan",
                    "dynamodb:BatchGetItem",
                    "dynamodb:PutItem",
                    "dynamodb:UpdateItem",
                    "dynamodb:DeleteItem",
                    "dynamodb:BatchWriteItem",
                    "dynamodb:TransactWriteItems",
                    "dynamodb:TransactGetItems",
                ],
                "Resource": [
                    table_arn,
                    f"{table_arn}/index/*",
                ],
            },
            {
                # dynamodb:SearchVectors gets its OWN statement, scoped to the index
                # resource, and deliberately carries NO condition block.
                #
                # This is not stylistic. DynamoDB's fine-grained access control condition
                # keys (dynamodb:LeadingKeys, dynamodb:Attributes, dynamodb:Select) are
                # absent from the SearchVectors request context, so a statement whose
                # Condition references one does not match a SearchVectors call and the
                # result is a DENIAL rather than a grant. Folding this action into a
                # conditioned statement silently breaks vector search while that
                # statement's other actions keep working — which presents as a broken
                # index rather than a policy fault. See SKILL.md "Security
                # considerations" #6 and references/vector-search.md.
                #
                # The `/index/*` wildcard is deliberate HERE and only here: this is a
                # throwaway benchmark role whose table ARN is already bounded by the bench
                # prefix, and whose indexes this same run creates and destroys. Do NOT copy
                # the wildcard into a production policy — name the specific index(es) the
                # workload searches, or a vector index added to the table later inherits
                # the grant silently. references/vector-search.md shows the scoped form.
                "Effect": "Allow",
                "Action": ["dynamodb:SearchVectors"],
                "Resource": [f"{table_arn}/index/*"],
            },
            {
                "Effect": "Allow",
                "Action": [
                    "logs:CreateLogGroup",
                    "logs:CreateLogStream",
                    "logs:PutLogEvents",
                ],
                # Least privilege: scope to this bench run's own Lambda log
                # groups (prefix-namespaced) — never account-wide "*".
                "Resource": (
                    f"arn:aws:logs:{region}:{account}:" f"log-group:/aws/lambda/{prefix}*:*"
                ),
            },
        ],
    }


def _deploy_lambda(
    session, cfg: dict, ident: dict, prefix: str, tags: dict, bundle_vector_sdk: bool = False
) -> dict:
    """Create the IAM role and the Lambda function. Returns their ARNs."""
    from botocore.exceptions import ClientError

    iam = session.client("iam")
    lam = session.client("lambda")

    role_name = f"{prefix}bench-role"[:64]  # IAM role name max 64 chars
    fn_name = f"{prefix}bench"[:64]

    # --- IAM role ---
    try:
        role = iam.create_role(
            RoleName=role_name,
            AssumeRolePolicyDocument=json.dumps(_build_lambda_trust_policy(ident["account"])),
            Description=f"ddb-skill-bench role for run {tags['run_id']}",
            Tags=[{"Key": k, "Value": str(v)} for k, v in tags.items()],
        )["Role"]
        role_arn = role["Arn"]
        print(f"  CreateRole: {role_name}")
    except ClientError as e:
        code = e.response.get("Error", {}).get("Code", "")
        if code == "EntityAlreadyExists":
            role = iam.get_role(RoleName=role_name)["Role"]
            role_arn = role["Arn"]
            print(f"  note: role {role_name} already exists — reusing.")
        else:
            raise

    iam.put_role_policy(
        RoleName=role_name,
        PolicyName=f"{prefix}bench-policy",
        PolicyDocument=json.dumps(_build_role_policy(prefix, cfg["region"], ident["account"])),
    )
    print(f"  PutRolePolicy: {role_name}/{prefix}bench-policy")

    # --- Lambda function ---
    zip_bytes = _build_lambda_zip(bundle_vector_sdk)
    memory = int(cfg.get("lambda_memory_mb") or DEFAULT_LAMBDA_MEMORY_MB)
    timeout = int(cfg.get("lambda_timeout_seconds") or DEFAULT_LAMBDA_TIMEOUT_S)

    # IAM role is eventually consistent — CreateFunction can fail on "cannot
    # be assumed by Lambda" even after CreateRole returns. Retry with backoff.
    create_kwargs = dict(
        FunctionName=fn_name,
        Runtime=LAMBDA_RUNTIME,
        Role=role_arn,
        Handler=LAMBDA_HANDLER,
        Code={"ZipFile": zip_bytes},
        Timeout=timeout,
        MemorySize=memory,
        Architectures=["arm64"],
        Tags={k: str(v) for k, v in tags.items()},
        Description=f"ddb-skill-bench Lambda for run {tags['run_id']}",
    )

    deadline = time.monotonic() + 45.0  # up to ~45s of retries
    delay = 2.0
    last_err = None
    fn_arn = None
    while time.monotonic() < deadline:
        try:
            resp = lam.create_function(**create_kwargs)
            fn_arn = resp["FunctionArn"]
            print(f"  CreateFunction: {fn_name}")
            break
        except ClientError as e:
            code = e.response.get("Error", {}).get("Code", "")
            msg = str(e)
            last_err = e
            if code == "ResourceConflictException":
                print(f"  note: function {fn_name} already exists — updating code + config.")
                lam.update_function_code(FunctionName=fn_name, ZipFile=zip_bytes)
                waiter = lam.get_waiter("function_updated")
                waiter.wait(FunctionName=fn_name)
                # Keep memory/timeout/role in sync with the current config on
                # a same-prefix rerun.
                lam.update_function_configuration(
                    FunctionName=fn_name,
                    Role=role_arn,
                    MemorySize=memory,
                    Timeout=timeout,
                )
                waiter.wait(FunctionName=fn_name)
                fn_arn = lam.get_function(FunctionName=fn_name)["Configuration"]["FunctionArn"]
                break
            if code == "InvalidParameterValueException" and (
                "cannot be assumed" in msg or "role defined" in msg
            ):
                print(f"  waiting for IAM role to be assumable… ({delay:.0f}s)")
                time.sleep(delay)
                delay = min(delay * 1.5, 8.0)
                continue
            raise
    if fn_arn is None:
        _die(
            "Lambda CreateFunction kept failing after IAM-consistency backoff. "
            f"Last error: {last_err}"
        )

    # Wait for Active state before returning.
    waiter = lam.get_waiter("function_active_v2")
    waiter.wait(FunctionName=fn_name)

    return {
        "function_name": fn_name,
        "function_arn": fn_arn,
        "role_name": role_name,
        "role_arn": role_arn,
        "policy_name": f"{prefix}bench-policy",
    }


def main():
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--model", required=True, help="path to dynamodb_data_model.json")
    p.add_argument("--config", required=True, help="path to benchmark_config.json")
    p.add_argument(
        "--manifest-out", required=True, help="path to write the created-resources manifest"
    )
    p.add_argument(
        "--yes-deploy",
        action="store_true",
        help="required: explicit consent to create real AWS resources",
    )
    args = p.parse_args()

    if not args.yes_deploy:
        _die("refusing to deploy without --yes-deploy")

    boto3_mod = _require_boto3()
    model = _load_json(Path(args.model))
    cfg = _load_json(Path(args.config))

    # One clock for the whole run: the manifest's created_at and any
    # auto-generated resource_prefix share the same UTC timestamp.
    run_now = _dt.datetime.now(_dt.timezone.utc).replace(microsecond=0)
    created_at = run_now.isoformat().replace("+00:00", "Z")
    run_id = uuid.uuid4().hex

    _validate_design(model)
    prefix_was_generated = _ensure_resource_prefix(cfg, run_now.strftime("%Y%m%d"))
    _validate_config(cfg)
    if prefix_was_generated:
        print(
            f"No resource_prefix supplied — generated {cfg['resource_prefix']!r} "
            "for this run (override by setting resource_prefix in the config)."
        )

    dry_run = bool(cfg.get("dry_run"))
    ident = _preflight(boto3_mod, cfg, dry_run=dry_run)
    session = boto3_mod.Session(profile_name=cfg["aws_profile"], region_name=cfg["region"])
    ddb = session.client("dynamodb")

    prefix = cfg["resource_prefix"].rstrip("-") + "-"

    built_in_tags = {
        "purpose": "ddb-skill-bench",
        "run_id": run_id,
        "created_at": created_at,
        "prefix": prefix,
    }
    tags = {**(cfg.get("tags") or {}), **built_in_tags}

    attr_types_by_table = _collect_attr_types(model["tables"])

    # Optional global provisioned-capacity override from the benchmark config
    # (a per-table table.provisioned_capacity still wins). Used for deliberate
    # capacity-ceiling tests where on-demand adaptive capacity would mask
    # hot-partition throttling.
    global_provisioned = cfg.get("provisioned_capacity")
    if global_provisioned:
        print(
            f"Provisioned-capacity mode: {global_provisioned} "
            "(hard ceiling; bench-only — production designs default to "
            "on-demand)."
        )

    # Build specs. Each spec is (create_kwargs, original_table_name).
    specs: list[tuple[dict, str]] = []
    for t in model["tables"]:
        kwargs = _build_create_kwargs(
            t,
            prefix,
            tags,
            attr_types_by_table.get(t["table_name"], {}),
            global_provisioned,
        )
        specs.append((kwargs, t["table_name"]))

    if dry_run:
        print("\nDRY RUN — intended resources:")
        for k, orig in specs:
            print(f"  table: {k['TableName']} (from {orig})")
        print(f"  lambda: {prefix}bench  (not built in dry run)")
        print(f"  role:   {prefix}bench-role")
        return

    # --- Deploy tables concurrently ---
    print(f"\nDeploying {len(specs)} table(s) concurrently …")
    descs = _deploy_tables_concurrent(ddb, specs)

    deployed_tables = []
    for kwargs, orig in specs:
        tn = kwargs["TableName"]
        desc = descs.get(tn) or {}
        sse_desc = desc.get("SSEDescription") or {}
        deployed_tables.append(
            {
                "name": tn,
                "original_name": orig,
                "arn": desc.get("TableArn"),
                "gsis": [g["IndexName"] for g in kwargs.get("GlobalSecondaryIndexes") or []],
                "stream_arn": desc.get("LatestStreamArn"),
                # Surface encryption-at-rest from DescribeTable so the user can verify
                # it. DynamoDB always encrypts at rest; with the AWS-owned-key default
                # DescribeTable returns NO SSEDescription block, so an empty/absent
                # SSEDescription means "encrypted with the AWS-owned key" (the implicit
                # default), and a present block means a customer-/AWS-managed CMK is in
                # use (Status/SSEType/KMSMasterKeyArn populated).
                "encryption": {
                    "sse_type": sse_desc.get("SSEType", "AWS_OWNED"),
                    "status": sse_desc.get("Status", "ENABLED (AWS-owned key, default)"),
                    "kms_key_arn": sse_desc.get("KMSMasterKeyArn"),
                },
                "key_schema": {
                    "partition_key": kwargs["KeySchema"][0]["AttributeName"],
                    "sort_key": (
                        kwargs["KeySchema"][1]["AttributeName"]
                        if len(kwargs["KeySchema"]) > 1
                        else None
                    ),
                },
            }
        )

    # --- Deploy Lambda + IAM role ---
    print(f"\nDeploying benchmark Lambda and IAM role …")
    has_vectors = any(t.get("vector_indexes") for t in (model.get("tables") or []))
    lambda_info = _deploy_lambda(session, cfg, ident, prefix, tags, bundle_vector_sdk=has_vectors)

    manifest = {
        "account": ident["account"],
        "alias": ident["alias"],
        "aws_profile": cfg["aws_profile"],
        "region": cfg["region"],
        "run_id": run_id,
        "created_at": created_at,
        "prefix": prefix,
        "tables": deployed_tables,
        "lambda": lambda_info,
    }
    out_path = Path(args.manifest_out)
    with out_path.open("w") as f:
        json.dump(manifest, f, indent=2, default=str)
    print(f"\nManifest written to {out_path}")
    print(
        f"Created {len(deployed_tables)} table(s), 1 Lambda "
        f"({lambda_info['function_name']}), 1 IAM role "
        f"({lambda_info['role_name']}). Run benchmark_model.py next."
    )


if __name__ == "__main__":
    main()
