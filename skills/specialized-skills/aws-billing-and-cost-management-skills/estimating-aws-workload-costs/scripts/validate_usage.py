#!/usr/bin/env python3
"""Check the usage step's lines against the usage playbook before anything is priced.

Input (JSON on stdin): the request file Step 8 writes, the same one render_report.py
reads. Nothing is priced and no AWS call is made.

Like render_report.py, it rejects a line missing serviceCode, usageType or
operation, and a SCUTO repeated across lines. Each other rule comes from
references/usage-interpretation.md:
  - source is one of the four tags (§Source taxonomy);
  - an UNKNOWN line carries no amounts (§Unresolved lines);
  - every other line has numeric low <= mid <= high, none negative, and an
    assumption, which the priced-lines file keeps (§What the final report shows);
  - CUSTOMER_STATED has Low = Mid = High (§Low, mid, high rule).
ASSUMED and DERIVED bands are not checked: they follow the line's inputs. Nor is a rate
conversion's duty cycle (§Duty cycle and rate conversion): whether a line converts a rate can't be
told reliably from its assumption text, so that rule is left to SKILL.md.

Two checks catch an amount entered in the wrong unit, which can outweigh every
other line:
  - a -Bytes line, which bills in GB, whose Mid is 1,000 or 1,024 times a GB
    figure its assumption gives and matches none of them;
  - a line that bills per item per month sized in hours: CloudWatch dashboards,
    and Contributor Insights rules, whose unit reads Rule-Hour.

It also warns, without failing, when a line in PAIRED has no paired line. The
price list may not carry the pair in every region, so only the agent can tell.

Output (exit 0): "OK: <n> lines checked." on stdout, then one "WARN: ..." line
per missing pair.
On failure (exit 1): nothing on stdout, and one JSON object on the last line of
stderr whose `error` names every problem, by line.

Usage:
  python scripts/validate_usage.py < cost-estimate-request.json
"""

import argparse
import json
import math
import re
import sys
import traceback

SOURCES = (
    "CUSTOMER_STATED",
    "DERIVED",
    "ASSUMED",
    "UNKNOWN",
)
BANDS = ("low", "mid", "high")
SCUTO_FIELDS = ("serviceCode", "usageType", "operation")
HINT = "Fix each line named in cost-estimate-request.json, then run the same command again."
# (serviceCode, usageType without its region prefix) -> the usage types the bill puts next to
# it, often at $0. Step 6 says to keep them, and they are easy to drop as free.
PAIRED = {
    ("AWSDataTransfer", "DataTransfer-Regional-Bytes"): (
        "DataTransfer-xAZ-In-Bytes",
        "DataTransfer-xAZ-Out-Bytes",
    ),
    ("AmazonS3", "Global-Bucket-Hrs"): ("Global-Bucket-Hrs-FreeTier",),
    # Most dashboards bill on the Basic line; only those above the Price List's metric count don't.
    ("AmazonCloudWatch", "DashboardsUsageHour"): ("DashboardsUsageHour-Basic",),
}
# A GB figure in an assumption, such as "~1,385 GB/month".
GB_FIGURE = re.compile(r"(\d[\d,]*(?:\.\d+)?)\s*GB\b")
# 730 as a figure of its own, such as "x 730h", not inside 7,300 or 0.730.
HOURS_PER_MONTH = re.compile(r"(?<![\d.,])730(?![\d.,])")
# Usage types that bill per item per month whatever their name or unit says, and what to enter.
PER_MONTH_COUNTS = {
    "DashboardsUsageHour": (
        "dashboards bill per dashboard per month, whatever the usage type's "
        "name; enter the dashboard count, not dashboard-hours"
    ),
    "CW:ContributorRulesManaged": (
        "Contributor Insights rules bill per rule per month, though the "
        "unit reads Rule-Hour; enter the rule count, not rule-hours"
    ),
    "CW:ContributorInsightRules": (
        "Contributor Insights rules bill per rule per month; enter the "
        "rule count, not rule-hours"
    ),
}
# A region prefix such as USE1-, EU- or APN1-, as the price list writes it.
REGION_PREFIX = re.compile(r"^[A-Z]{2,4}\d?-(?=[A-Za-z])")


def fail(message, hint=HINT, error_type="ValidationException", retry_strategy="modify_request"):
    """Write the error contract's JSON as the last stderr line and return exit status 1."""
    payload = {
        "error": message,
        "error_type": error_type,
        "retry_strategy": retry_strategy,
        "hint": hint,
    }
    sys.stderr.write(json.dumps(payload, separators=(",", ":")) + "\n")
    return 1


class _ContractArgumentParser(argparse.ArgumentParser):
    """Reports argument errors in the error contract instead of argparse's usage text."""

    def error(self, message):
        sys.exit(fail(message, " ".join(self.format_usage().split())))


def label(index, line):
    """Name a line the way the agent can find it: its lineId, else its index, and its SCUTO."""
    name = line.get("lineId") or f"lines[{index}]"
    scuto = " / ".join(str(line.get(k)) for k in ("serviceCode", "usageType") if line.get(k))
    return f"{name} ({scuto})" if scuto else name


def is_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def unit_problems(line, mid, assumption):
    """Return the unit mistakes in one line's amount, as short sentences."""
    usage_type = str(line.get("usageType", ""))
    if usage_type.endswith("-Bytes") and mid > 0:
        gbs = [float(x.replace(",", "")) for x in GB_FIGURE.findall(assumption)]
        gbs = [gb for gb in gbs if gb > 0]
        if gbs and not any(math.isclose(mid, gb, rel_tol=0.05) for gb in gbs):
            for gb in gbs:
                if any(math.isclose(mid, gb * k, rel_tol=0.05) for k in (1000, 1024)):
                    return [
                        f"mid is about 1,000 times the {gb:g} GB the assumption gives; "
                        "this line bills in GB, so enter the GB figure"
                    ]
    if HOURS_PER_MONTH.search(assumption):
        for name, problem in PER_MONTH_COUNTS.items():
            if name in usage_type:
                return [problem]
    return []


def line_problems(line):
    """Return the playbook rules this one line breaks, as short sentences."""
    source = line.get("source")
    if source not in SOURCES:
        return [f"source must be one of {', '.join(SOURCES)}"]
    if source == "UNKNOWN":
        present = [band for band in BANDS if band in line]
        return (
            [f"an UNKNOWN line carries no amounts; remove {', '.join(present)}"] if present else []
        )

    amounts = [line.get(band) for band in BANDS]
    if not all(is_number(amount) for amount in amounts):
        return ["low, mid and high must all be numbers"]
    low, mid, high = amounts
    problems = []
    if low < 0:
        problems.append("low must not be negative")
    if not low <= mid <= high:
        problems.append("amounts must satisfy low <= mid <= high")
    assumption = line.get("assumption")
    if not isinstance(assumption, str) or not assumption.strip():
        problems.append("needs an assumption, which the priced-lines file keeps")
        assumption = ""

    if source == "CUSTOMER_STATED" and not (low == mid == high):
        problems.append("CUSTOMER_STATED needs low = mid = high")
    return problems + unit_problems(line, mid, assumption)


def validate(request):
    """Return every problem in the request as "<line>: <problem>" strings."""
    if (
        not isinstance(request, dict)
        or not isinstance(request.get("lines"), list)
        or not request["lines"]
    ):
        return ["the request must be an object with a non-empty lines list"]
    problems = []
    seen = set()
    for index, line in enumerate(request["lines"]):
        if not isinstance(line, dict):
            problems.append(f"lines[{index}]: must be an object")
            continue
        # render_report.py rejects these too, so catch them here before pricing.
        missing = [field for field in SCUTO_FIELDS if field not in line]
        if missing:
            problems.append(f"{label(index, line)}: is missing {', '.join(missing)}")
        else:
            # Two Bedrock models can share a SCUTO, so a line's model is part of its identity.
            scuto = tuple(str(line[field]) for field in SCUTO_FIELDS) + (str(line.get("model")),)
            if scuto in seen:
                problems.append(f"{label(index, line)}: repeats an earlier line's SCUTO")
            seen.add(scuto)
        problems += [f"{label(index, line)}: {p}" for p in line_problems(line)]
    return problems


def missing_pairs(request):
    """Return a warning for each PAIRED line whose paired lines aren't all in the request."""
    lines = [line for line in request["lines"] if isinstance(line, dict)]
    present = {
        (str(line.get("serviceCode")), REGION_PREFIX.sub("", str(line.get("usageType", ""))))
        for line in lines
    }
    warnings = []
    for index, line in enumerate(lines):
        service_code = str(line.get("serviceCode"))
        usage_type = str(line.get("usageType", ""))
        stem = REGION_PREFIX.sub("", usage_type)
        for pair in PAIRED.get((service_code, stem), ()):
            if (service_code, pair) not in present:
                warnings.append(
                    f"{label(index, line)}: no {pair} line; add it, under the name Step 5 "
                    "listed it (with or without a region prefix), even at $0"
                )
    return warnings


def main(argv=None):
    _ContractArgumentParser(
        description="Check usage lines against the usage playbook (request JSON on stdin)."
    ).parse_args(argv)
    try:
        request = json.load(sys.stdin)
        problems = validate(request)
        warnings = [] if problems else missing_pairs(request)
    except json.JSONDecodeError as exc:
        return fail(f"stdin is not valid JSON: {exc}")
    except Exception as exc:  # keep the error contract for anything unexpected
        traceback.print_exc()  # stderr, before the contract line
        return fail(
            f"the usage check failed unexpectedly ({type(exc).__name__})",
            hint="Tell the user the usage check could not run.",
            error_type="InternalError",
            retry_strategy="do_not_retry",
        )
    if problems:
        return fail(f"{len(problems)} problem(s): " + "; ".join(problems))
    sys.stdout.write(f"OK: {len(request['lines'])} lines checked.\n")
    for warning in warnings:
        sys.stdout.write(f"WARN: {warning}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
