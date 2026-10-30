#!/usr/bin/env python3
"""Parse only closed, user-provided Render billing aggregate formats."""

from __future__ import annotations

import argparse
import csv
import io
import json
import os
import re
import sys
from datetime import date
from decimal import Decimal, InvalidOperation, ROUND_HALF_EVEN
from pathlib import Path
from typing import Any

from render_common.atomic import PathBoundaryError, require_contained, write_json_atomic
from render_common.canonical import canonical_bytes, sha256_digest

MAX_BYTES = 20 * 1024 * 1024
CURRENCY_RE = re.compile(r"^[A-Z]{3}$")
DECIMAL_RE = re.compile(r"^-?(?:0|[1-9][0-9]{0,11})(?:\.[0-9]{1,6})?$")
REQUIRED_COLUMNS = ["line_id", "period_start", "period_end", "currency", "amount", "amount_basis"]
OPTIONAL_COLUMNS = ["service_id", "plan_id", "quantity", "unit"]
BASIS = {"subtotal_before_tax", "total_after_credits", "credit", "user_stated"}
ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")


class BillingError(ValueError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def _read_source(path: Path, root: Path) -> bytes:
    if not path.is_absolute() or not root.is_absolute():
        raise BillingError("path_not_absolute")
    try:
        root_resolved = root.resolve(strict=True)
        path.resolve(strict=True).relative_to(root_resolved)
    except (OSError, ValueError) as exc:
        raise BillingError("source_outside_workspace") from exc
    if path.is_symlink() or not path.is_file():
        raise BillingError("source_not_regular")
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        before = os.fstat(fd)
        if before.st_size > MAX_BYTES:
            raise BillingError("source_too_large")
        data = bytearray()
        while len(data) <= MAX_BYTES:
            chunk = os.read(fd, min(64 * 1024, MAX_BYTES + 1 - len(data)))
            if not chunk:
                break
            data.extend(chunk)
        after = os.fstat(fd)
    finally:
        os.close(fd)
    if len(data) > MAX_BYTES:
        raise BillingError("source_too_large")
    if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns):
        raise BillingError("source_changed_during_read")
    return bytes(data)


def _decimal(value: Any, code: str, *, positive: bool = False, negative_allowed: bool = False) -> Decimal:
    if not isinstance(value, str) or not DECIMAL_RE.fullmatch(value):
        raise BillingError(code)
    try:
        result = Decimal(value)
    except InvalidOperation as exc:
        raise BillingError(code) from exc
    if (result < 0 and not negative_allowed) or (positive and result <= 0):
        raise BillingError(code)
    return result


def _date(value: Any, code: str) -> date:
    if not isinstance(value, str):
        raise BillingError(code)
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise BillingError(code) from exc


def _currency(value: Any) -> str:
    if not isinstance(value, str) or not CURRENCY_RE.fullmatch(value):
        raise BillingError("currency_invalid")
    return value


def _closed(value: Any, required: set[str], optional: set[str], code: str) -> dict[str, Any]:
    if not isinstance(value, dict) or not required <= set(value) or set(value) - required - optional:
        raise BillingError(code)
    return value


def _format(amount: Decimal) -> str:
    return format(amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_EVEN), "f")


def _user_stated(document: dict[str, Any]) -> dict[str, Any]:
    _closed(document, {"schema_version", "source", "monthly_amount", "currency", "as_of"}, set(), "properties_invalid")
    amount = _decimal(document["monthly_amount"], "amount_invalid")
    currency = _currency(document["currency"])
    as_of = _date(document["as_of"], "as_of_invalid")
    return {"schema_version": "1.0", "source": "user_stated", "currency": currency, "monthly_total": _format(amount), "as_of": as_of.isoformat(), "line_item_count": 0, "conversion": None}


def _billing_export(document: dict[str, Any]) -> dict[str, Any]:
    _closed(document, {"schema_version", "lines"}, {"target_currency", "conversions"}, "properties_invalid")
    lines = document["lines"]
    if not isinstance(lines, list) or not 1 <= len(lines) <= 10_000:
        raise BillingError("lines_invalid")
    target = document.get("target_currency")
    if target is not None:
        target = _currency(target)
    conversions = document.get("conversions", [])
    if not isinstance(conversions, list) or len(conversions) > 100:
        raise BillingError("conversions_invalid")
    rates: dict[tuple[str, str], tuple[Decimal, str]] = {}
    for entry in conversions:
        _closed(entry, {"from", "to", "rate", "as_of"}, set(), "conversion_invalid")
        key = (_currency(entry["from"]), _currency(entry["to"]))
        if key in rates:
            raise BillingError("duplicate_conversion")
        rates[key] = (_decimal(entry["rate"], "conversion_invalid", positive=True), _date(entry["as_of"], "conversion_invalid").isoformat())

    seen_ids: set[str] = set()
    intervals: dict[tuple[str, str, str], list[tuple[date, date]]] = {}
    # Lines are grouped by service_id and normalized once per group over the group's covered
    # reporting interval. Plan segments of one service (sequential or concurrent) and charges
    # split into adjacent prorated lines therefore pool into the same monthly figure as one line.
    groups: dict[str, list[tuple[str, Decimal, date, date]]] = {}
    credit_periods: set[tuple[date, date, str]] = set()
    noncredit_periods: set[tuple[date, date, str]] = set()
    for line in lines:
        _closed(line, set(REQUIRED_COLUMNS), set(OPTIONAL_COLUMNS), "line_properties_invalid")
        line_id = line["line_id"]
        if not isinstance(line_id, str) or not ID_RE.fullmatch(line_id) or line_id in seen_ids:
            raise BillingError("line_id_invalid")
        seen_ids.add(line_id)
        start, end = _date(line["period_start"], "period_invalid"), _date(line["period_end"], "period_invalid")
        if start >= end:
            raise BillingError("period_invalid")
        currency = _currency(line["currency"])
        basis = line["amount_basis"]
        if basis not in BASIS:
            raise BillingError("amount_basis_invalid")
        amount = _decimal(line["amount"], "amount_invalid", negative_allowed=basis == "credit")
        if basis == "credit" and amount > 0:
            amount = -amount
        for optional_id in ("service_id", "plan_id"):
            if optional_id in line and (not isinstance(line[optional_id], str) or not ID_RE.fullmatch(line[optional_id])):
                raise BillingError(f"{optional_id}_invalid")
        if "quantity" in line:
            _decimal(line["quantity"], "quantity_invalid")
        if "unit" in line and (not isinstance(line["unit"], str) or not 1 <= len(line["unit"]) <= 64):
            raise BillingError("unit_invalid")
        overlap_key = (line.get("service_id", "_"), line.get("plan_id", "_"), basis)
        for old_start, old_end in intervals.setdefault(overlap_key, []):
            if start < old_end and old_start < end:
                raise BillingError("overlapping_period")
        intervals[overlap_key].append((start, end))
        period_key = (start, end, currency)
        (credit_periods if basis == "credit" else noncredit_periods).add(period_key)
        groups.setdefault(overlap_key[0], []).append((currency, amount, start, end))
    if credit_periods - noncredit_periods:
        raise BillingError("credit_period_mismatch")

    currencies = {row[0] for rows in groups.values() for row in rows}
    if target is None and len(currencies) != 1:
        raise BillingError("mixed_currency_without_conversion")
    output_currency = target or next(iter(currencies))
    conversion_records: list[dict[str, str]] = []

    def convert(currency: str, amount: Decimal) -> Decimal:
        if currency == output_currency:
            return amount
        evidence = rates.get((currency, output_currency))
        if evidence is None:
            raise BillingError("conversion_missing")
        rate, as_of = evidence
        record = {"from": currency, "to": output_currency, "rate": format(rate, "f"), "as_of": as_of}
        if record not in conversion_records:
            conversion_records.append(record)
        return amount * rate

    total = Decimal(0)
    for rows in groups.values():
        # Merge overlapping or adjacent spans; more than one merged span means a coverage gap.
        spans: list[tuple[date, date]] = []
        for start, end in sorted({(start, end) for _currency, _amount, start, end in rows}):
            if spans and start <= spans[-1][1]:
                spans[-1] = (spans[-1][0], max(spans[-1][1], end))
            else:
                spans.append((start, end))
        if len(spans) != 1:
            raise BillingError("discontiguous_period")
        coverage_days = Decimal((spans[0][1] - spans[0][0]).days)
        group_amount = sum((convert(currency, amount) for currency, amount, _start, _end in rows), Decimal(0))
        total += group_amount / coverage_days * Decimal("30.4375")
    starts = [row[2] for rows in groups.values() for row in rows]
    ends = [row[3] for rows in groups.values() for row in rows]
    return {"schema_version": "1.0", "source": "billing_export", "currency": output_currency, "monthly_total": _format(total), "period_start": min(starts).isoformat(), "period_end": max(ends).isoformat(), "line_item_count": len(lines), "conversion": sorted(conversion_records, key=lambda row: (row["from"], row["to"], row["as_of"])) or None}


def _csv_document(text: str) -> dict[str, Any]:
    first = text.splitlines()[0] if text.splitlines() else ""
    try:
        header = next(csv.reader([first], strict=True))
    except csv.Error as exc:
        raise BillingError("csv_header_invalid") from exc
    if header[: len(REQUIRED_COLUMNS)] != REQUIRED_COLUMNS or header[len(REQUIRED_COLUMNS) :] not in ([], OPTIONAL_COLUMNS[: len(header) - len(REQUIRED_COLUMNS)]):
        raise BillingError("csv_header_invalid")
    try:
        rows = list(csv.DictReader(io.StringIO(text), strict=True))
    except csv.Error as exc:
        raise BillingError("csv_invalid") from exc
    if not rows or len(rows) > 10_000 or any(None in row for row in rows):
        raise BillingError("lines_invalid")
    return {"schema_version": "1.0.0", "lines": rows}


def parse(data: bytes, suffix: str) -> dict[str, Any]:
    try:
        text = data.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise BillingError("invalid_utf8") from exc
    if suffix.lower() == ".csv":
        document = _csv_document(text)
    elif suffix.lower() == ".json":
        try:
            document = json.loads(text)
        except json.JSONDecodeError as exc:
            raise BillingError("json_invalid") from exc
        if not isinstance(document, dict):
            raise BillingError("properties_invalid")
    else:
        raise BillingError("source_type_unsupported")
    if document.get("schema_version") != "1.0.0":
        raise BillingError("schema_version_invalid")
    result = _user_stated(document) if document.get("source") == "user_stated" else _billing_export(document)
    result["source_digest"] = sha256_digest(data)
    result["fingerprint"] = sha256_digest(canonical_bytes({key: value for key, value in result.items() if key != "fingerprint"}))
    return result


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--workspace-root", type=Path, required=True)
    parser.add_argument("--migration-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = _arguments()
    try:
        if not args.migration_dir.is_absolute() or not args.migration_dir.is_dir() or args.migration_dir.is_symlink():
            raise BillingError("migration_dir_invalid")
        require_contained(args.output, args.migration_dir, "output")
        data = _read_source(args.source, args.workspace_root)
        result = parse(data, args.source.suffix)
        write_json_atomic(args.output, args.migration_dir, result)
    except (BillingError, PathBoundaryError, OSError, ValueError) as exc:
        code = exc.code if isinstance(exc, BillingError) else str(exc)
        if not code or any(character.isspace() for character in code):
            code = "internal_validation_error"
        print(f"BILLING_FAIL | code={code}", file=sys.stderr)
        return 1
    # Only the output path is echoed. The source digest and all parsed values stay
    # in the written artifact so nothing derived from the billing file reaches stdout.
    print(f"BILLING_OK | output={args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
