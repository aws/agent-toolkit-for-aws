from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

SCRIPT_DIR = Path(__file__).resolve().parent
SCRIPT = SCRIPT_DIR / "parse-render-billing.py"
FIXTURES = SCRIPT_DIR.parent / "fixtures/render-billing"
SCHEMA = SCRIPT_DIR.parent / "references/shared/schema-render-billing.json"
spec = importlib.util.spec_from_file_location("parse_render_billing", SCRIPT)
assert spec and spec.loader
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_user_stated_and_csv_aggregate_are_closed_and_deterministic() -> None:
    stated_data = (FIXTURES / "user-stated.json").read_bytes()
    stated = module.parse(stated_data, ".json")
    assert stated["monthly_total"] == "123.45"
    export_data = (FIXTURES / "export.csv").read_bytes()
    first = module.parse(export_data, ".csv")
    second = module.parse(export_data, ".csv")
    assert first == second
    assert first["monthly_total"] == "56.56"
    assert first["line_item_count"] == 2
    assert "service_id" not in json.dumps(first)
    schema = json.loads(SCHEMA.read_text())
    Draft202012Validator(schema).validate(stated)
    Draft202012Validator(schema).validate(first)


def test_unknown_headers_and_properties_reject_before_rows() -> None:
    with pytest.raises(module.BillingError, match="csv_header_invalid"):
        module.parse(b"service_id,amount,secret\nsrv,1,nope\n", ".csv")
    document = {"schema_version": "1.0.0", "source": "user_stated", "monthly_amount": "1.00", "currency": "USD", "as_of": "2026-10-21", "raw_rows": []}
    with pytest.raises(module.BillingError, match="properties_invalid"):
        module.parse(json.dumps(document).encode(), ".json")


def test_decimal_dates_overlap_and_currency_fail_closed() -> None:
    base = {"schema_version": "1.0.0", "lines": [
        {"line_id": "line-1", "service_id": "srv-safe", "period_start": "2026-09-01", "period_end": "2026-10-01", "amount": "10.00", "currency": "USD", "amount_basis": "subtotal_before_tax"},
        {"line_id": "line-2", "service_id": "srv-safe", "period_start": "2026-09-15", "period_end": "2026-10-15", "amount": "10.00", "currency": "USD", "amount_basis": "subtotal_before_tax"},
    ]}
    with pytest.raises(module.BillingError, match="overlapping_period"):
        module.parse(json.dumps(base).encode(), ".json")
    base["lines"][1]["service_id"] = "srv-other"
    base["lines"][1]["currency"] = "EUR"
    with pytest.raises(module.BillingError, match="mixed_currency_without_conversion"):
        module.parse(json.dumps(base).encode(), ".json")
    base["target_currency"] = "USD"
    base["conversions"] = [{"from": "EUR", "to": "USD", "rate": "1.10", "as_of": "2026-10-21"}]
    result = module.parse(json.dumps(base).encode(), ".json")
    assert result["monthly_total"] == "21.31"


def _line(line_id: str, start: str, end: str, amount: str, *, service_id: str | None = "srv-web", plan_id: str | None = None, currency: str = "USD", basis: str = "subtotal_before_tax") -> dict:
    line = {"line_id": line_id, "period_start": start, "period_end": end, "currency": currency, "amount": amount, "amount_basis": basis}
    if service_id is not None:
        line["service_id"] = service_id
    if plan_id is not None:
        line["plan_id"] = plan_id
    return line


def _export(lines: list[dict], **extra) -> bytes:
    return json.dumps({"schema_version": "1.0.0", "lines": lines, **extra}).encode()


def test_split_charge_is_invariant_to_line_layout() -> None:
    whole = module.parse(_export([_line("l1", "2026-09-01", "2026-10-01", "30.00")]), ".json")
    halves = module.parse(_export([
        _line("l1", "2026-09-01", "2026-09-16", "15.00"),
        _line("l2", "2026-09-16", "2026-10-01", "15.00"),
    ]), ".json")
    thirds = module.parse(_export([
        _line("l3", "2026-09-21", "2026-10-01", "10.00"),
        _line("l1", "2026-09-01", "2026-09-11", "10.00"),
        _line("l2", "2026-09-11", "2026-09-21", "10.00"),
    ]), ".json")
    assert whole["monthly_total"] == "30.44"
    assert halves["monthly_total"] == whole["monthly_total"]
    assert thirds["monthly_total"] == whole["monthly_total"]
    assert (halves["period_start"], halves["period_end"]) == ("2026-09-01", "2026-10-01")
    assert halves["line_item_count"] == 2


def test_concurrent_services_credits_and_conversion_aggregate_per_group() -> None:
    # web: 25.00 - 5.00 credit = 20.00 USD over 30 days -> 20 / 30 * 30.4375 = 20.291666...
    # worker: 10.00 EUR * 1.10 = 11.00 USD over 30 days -> 11 / 30 * 30.4375 = 11.160416...
    # total 31.452083... -> 31.45
    data = _export(
        [
            _line("web-1", "2026-09-01", "2026-10-01", "25.00", plan_id="starter"),
            _line("web-credit", "2026-09-01", "2026-10-01", "5.00", plan_id="starter", basis="credit"),
            _line("worker-1", "2026-09-01", "2026-10-01", "10.00", service_id="srv-worker", currency="EUR"),
        ],
        target_currency="USD",
        conversions=[{"from": "EUR", "to": "USD", "rate": "1.10", "as_of": "2026-10-21"}],
    )
    result = module.parse(data, ".json")
    assert result["monthly_total"] == "31.45"
    assert result["conversion"] == [{"from": "EUR", "to": "USD", "rate": "1.10", "as_of": "2026-10-21"}]
    # The same worker charge split across two adjacent EUR lines yields the same total.
    split = _export(
        [
            _line("web-1", "2026-09-01", "2026-10-01", "25.00", plan_id="starter"),
            _line("web-credit", "2026-09-01", "2026-10-01", "5.00", plan_id="starter", basis="credit"),
            _line("worker-1", "2026-09-01", "2026-09-11", "4.00", service_id="srv-worker", currency="EUR"),
            _line("worker-2", "2026-09-11", "2026-10-01", "6.00", service_id="srv-worker", currency="EUR"),
        ],
        target_currency="USD",
        conversions=[{"from": "EUR", "to": "USD", "rate": "1.10", "as_of": "2026-10-21"}],
    )
    assert module.parse(split, ".json")["monthly_total"] == "31.45"


def test_discontiguous_group_is_rejected() -> None:
    data = _export([
        _line("l1", "2026-09-01", "2026-09-10", "9.00"),
        _line("l2", "2026-09-20", "2026-09-30", "10.00"),
    ])
    with pytest.raises(module.BillingError, match="discontiguous_period"):
        module.parse(data, ".json")
    # Different services may legitimately cover different intervals.
    separate = _export([
        _line("l1", "2026-09-01", "2026-09-10", "9.00"),
        _line("l2", "2026-09-20", "2026-09-30", "10.00", service_id="srv-other"),
    ])
    assert module.parse(separate, ".json")["monthly_total"] == "60.88"


def test_sequential_plan_segments_of_one_service_pool_before_normalizing() -> None:
    # starter 15.00 for 15 days, then standard 30.00 for 15 days, same service:
    # 45.00 over the 30-day interval -> 45 / 30 * 30.4375 = 45.65625 -> 45.66.
    # Normalizing each plan segment separately would give 91.31.
    data = _export([
        _line("starter-sep", "2026-09-01", "2026-09-16", "15.00", plan_id="starter"),
        _line("standard-sep", "2026-09-16", "2026-10-01", "30.00", plan_id="standard"),
    ])
    result = module.parse(data, ".json")
    assert result["monthly_total"] == "45.66"
    assert (result["period_start"], result["period_end"]) == ("2026-09-01", "2026-10-01")
    assert result["line_item_count"] == 2


def test_negative_exponent_nan_and_bad_dates_reject() -> None:
    for amount in ("-1.00", "1e3", "NaN", "Infinity"):
        document = {"schema_version": "1.0.0", "source": "user_stated", "monthly_amount": amount, "currency": "USD", "as_of": "2026-10-21"}
        with pytest.raises(module.BillingError, match="amount_invalid"):
            module.parse(json.dumps(document).encode(), ".json")
    bad_date = {"schema_version": "1.0.0", "source": "user_stated", "monthly_amount": "1.00", "currency": "USD", "as_of": "2026-02-30"}
    with pytest.raises(module.BillingError, match="as_of_invalid"):
        module.parse(json.dumps(bad_date).encode(), ".json")


def test_json_input_version_is_exact_and_output_version_is_independent() -> None:
    document = {
        "schema_version": "1.0.0",
        "lines": [{
            "line_id": "line-1",
            "period_start": "2026-09-01",
            "period_end": "2026-10-01",
            "currency": "USD",
            "amount": "10.00",
            "amount_basis": "subtotal_before_tax",
        }],
    }
    assert module.parse(json.dumps(document).encode(), ".json")["schema_version"] == "1.0"
    document["schema_version"] = "1.0"
    with pytest.raises(module.BillingError, match="schema_version_invalid"):
        module.parse(json.dumps(document).encode(), ".json")
