"""azure-to-aws maps each Azure region to a default AWS Region from `azure-region-map.json`.

A region that is missing from the map is resolved by the model from geography
(`_unlisted_region`), so it gets an inferred answer instead of a looked-up one. These tests pin
the map against two lists read on 2026-11-19, and the rules the file states about itself.
Update both snapshots when the map is next refreshed.
"""
from __future__ import annotations

import json
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
MAP = PLUGIN_ROOT / "skills" / "azure-to-aws" / "knowledge" / "design" / "azure-region-map.json"

# Programmatic names in the public Azure cloud, from
# https://learn.microsoft.com/en-us/azure/reliability/regions-list (read 2026-11-19).
# The page's "All" tab has 60 rows, each with one programmatic name. The count is asserted below.
# Sweden South and Taiwan Northwest are paired regions the page lists only as another region's
# pair, with no row or programmatic name of their own, so they are not here.
AZURE_REGIONS = {
    "australiacentral", "australiacentral2", "australiaeast", "australiasoutheast", "austriaeast",
    "belgiumcentral", "brazilsouth", "brazilsoutheast", "canadacentral", "canadaeast", "centralindia",
    "centralus", "chilecentral", "denmarkeast", "eastasia", "eastus", "eastus2", "francecentral",
    "francesouth", "germanynorth", "germanywestcentral", "indiasouthcentral", "indonesiacentral",
    "israelcentral", "italynorth", "japaneast", "japanwest", "koreacentral", "koreasouth",
    "malaysiawest", "mexicocentral", "newzealandnorth", "northcentralus", "northeurope", "norwayeast",
    "norwaywest", "polandcentral", "qatarcentral", "saudiarabiaeast", "southafricanorth",
    "southafricawest", "southcentralus", "southindia", "southeastasia", "southeastasia3", "spaincentral",
    "swedencentral", "switzerlandnorth", "switzerlandwest", "taiwannorth", "uaecentral", "uaenorth",
    "uksouth", "ukwest", "westcentralus", "westeurope", "westindia", "westus", "westus2", "westus3",
}
# Azure Government and China regions the map already covers on purpose.
SOVEREIGN = {"usgovvirginia", "usgovarizona", "chinanorth3", "chinaeast3"}

# AWS Region codes from the AWS Region list (aws___list_regions, read 2026-11-19).
AWS_REGIONS = {
    "af-south-1", "ap-east-1", "ap-east-2", "ap-northeast-1", "ap-northeast-2", "ap-northeast-3",
    "ap-south-1", "ap-south-2", "ap-southeast-1", "ap-southeast-2", "ap-southeast-3", "ap-southeast-4",
    "ap-southeast-5", "ap-southeast-6", "ap-southeast-7", "ca-central-1", "ca-west-1", "eu-central-1",
    "eu-central-2", "eu-north-1", "eu-south-1", "eu-south-2", "eu-west-1", "eu-west-2", "eu-west-3",
    "il-central-1", "me-central-1", "me-south-1", "mx-central-1", "sa-east-1", "us-east-1", "us-east-2",
    "us-gov-east-1", "us-gov-west-1", "us-west-1", "us-west-2",
}
# Regions an account must enable before use, from
# https://docs.aws.amazon.com/accounts/latest/reference/manage-acct-regions.html (read 2026-11-19).
OPT_IN = {
    "af-south-1", "ap-east-1", "ap-east-2", "ap-south-2", "ap-southeast-3", "ap-southeast-4",
    "ap-southeast-5", "ap-southeast-6", "ap-southeast-7", "ca-west-1", "eu-central-2", "eu-south-1",
    "eu-south-2", "il-central-1", "me-central-1", "me-south-1", "mx-central-1",
}


def _regions() -> dict[str, dict]:
    return json.loads(MAP.read_text(encoding="utf-8"))["regions"]


def test_every_public_azure_region_is_mapped() -> None:
    missing = AZURE_REGIONS - set(_regions())
    assert not missing, f"Azure regions with no row (the model would infer them): {sorted(missing)}"


def test_the_map_has_no_unknown_or_misspelled_region_keys() -> None:
    extra = set(_regions()) - AZURE_REGIONS - SOVEREIGN
    assert not extra, f"keys that are not Azure programmatic names: {sorted(extra)}"


def test_every_target_is_a_real_aws_region() -> None:
    for key, row in _regions().items():
        if row["aws"] is not None:
            assert row["aws"] in AWS_REGIONS, (key, row["aws"])


def test_rows_carry_exactly_the_documented_fields() -> None:
    for key, row in _regions().items():
        assert set(row) <= {"aws", "same_country", "geo", "note"}, key
        assert {"aws", "same_country", "geo"} <= set(row), key
        assert isinstance(row["same_country"], bool), key
        assert row["geo"].strip(), key


def test_crossing_a_border_or_having_no_target_always_explains_itself() -> None:
    # `_residency_warning`: a row with same_country false must not be resolved silently.
    for key, row in _regions().items():
        if row["same_country"] is False or row["aws"] is None:
            assert row.get("note", "").strip(), key


def test_opt_in_targets_say_so() -> None:
    # A default that needs an account setting is a surprise at apply time unless the row says so.
    for key, row in _regions().items():
        if row["aws"] in OPT_IN and key != "newzealandnorth":
            assert "opt-in" in row.get("note", ""), (key, row["aws"])
    # The older row said it in its own words and is left as written.
    assert "opted in" in _regions()["newzealandnorth"]["note"]


def test_new_rows_use_the_nearest_enabled_by_default_region_when_no_same_country_region_exists() -> None:
    rows = _regions()
    # Vienna is as close to Zurich (opt-in) as to Frankfurt (enabled by default).
    assert rows["austriaeast"]["aws"] == "eu-central-1"
    assert rows["austriaeast"]["same_country"] is False
    # Same-country Regions where one exists, including opt-in ones, which say so.
    assert (rows["mexicocentral"]["aws"], rows["mexicocentral"]["same_country"]) == ("mx-central-1", True)
    assert (rows["malaysiawest"]["aws"], rows["malaysiawest"]["same_country"]) == ("ap-southeast-5", True)
    assert (rows["taiwannorth"]["aws"], rows["taiwannorth"]["same_country"]) == ("ap-east-2", True)
    assert (rows["indiasouthcentral"]["aws"], rows["indiasouthcentral"]["same_country"]) == ("ap-south-2", True)
    # No AWS Region in Chile: the nearest is Sao Paulo and the row says it crosses a border.
    assert (rows["chilecentral"]["aws"], rows["chilecentral"]["same_country"]) == ("sa-east-1", False)
    # No AWS Region in Saudi Arabia: Bahrain is 56 km from Dammam, and it is opt-in and preview.
    assert (rows["saudiarabiaeast"]["aws"], rows["saudiarabiaeast"]["same_country"]) == ("me-south-1", False)
    assert "preview" in rows["saudiarabiaeast"]["note"]


def test_restricted_access_regions_say_who_can_see_them() -> None:
    restricted = ("australiacentral2", "brazilsoutheast", "francesouth", "germanynorth", "norwaywest",
                  "southafricawest", "switzerlandwest", "uaecentral")
    for key in restricted:
        assert "restricts access" in _regions()[key]["note"], key


def test_the_file_is_still_valid_and_keeps_its_rules() -> None:
    data = json.loads(MAP.read_text(encoding="utf-8"))
    for rule in ("_selection_rule", "_override", "_residency_warning", "_provenance", "_unlisted_region"):
        assert data[rule].strip(), rule
    assert "2026-11-19" in data["_provenance"]


def test_the_azure_list_is_the_size_of_the_page_it_cites() -> None:
    # The cited page has 60 programmatic names. A list that loses one (or never had it) would
    # make `test_every_public_azure_region_is_mapped` pass while a region has no row.
    assert len(AZURE_REGIONS) == 60
    # Every public region in the map is one of them, and every one of them has a row.
    public_rows = set(_regions()) - SOVEREIGN
    assert public_rows == AZURE_REGIONS
