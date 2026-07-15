#!/usr/bin/env python3
"""DynamoDB Cost Calculator — reads dynamodb_data_model.json directly.

Reads the structured JSON data model (tables, entities, access_patterns),
calculates RRU/WRU consumption and monthly on-demand costs, outputs a
standalone cost_report.md.

Formulas were empirically verified against live DynamoDB
ReturnConsumedCapacity responses. See verify/ for the validation suite.

Rules enforced (all verified):
  - WRU rounding: ceil(item_size / 1024). Item size = sum of attribute-name + value bytes.
  - RRU rounding: ceil(item_size / 4096); eventually consistent = strong / 2.
  - Non-existent GetItem still consumes 0.5 RRU (eventual) or 1 RRU (strong).
  - Query/Scan: aggregate bytes read, rounded up to next 4 KB, then halved if eventual.
  - Filters and projections DO NOT reduce capacity.
  - BatchGetItem / BatchWriteItem: rounded per-item, then summed.
  - PutItem / UpdateItem: sized on LARGER of before and after.
  - Transactional writes: 2× multiplier applies to BASE TABLE ONLY.
    GSI and LSI writes remain 1×. (Verified.)
  - Transactional reads: 2× multiplier.
  - Conditional write failure still consumes capacity based on the existing
    item size (or new item size for PutItem on a non-existent key).
  - GSI write amplification:
      * Only fires if the item has the GSI's partition-key attribute.
      * Only fires if a projected attribute changed (UpdateItem).
      * GSI write is sized by the PROJECTED attributes, not the base item.
  - Storage: (raw_bytes + 100 bytes per item) / 1_000_000_000 (decimal GB),
    billed at the full public Standard rate. Global tables add +48 bytes/item.
    The 25 GB free tier is intentionally NOT applied (account-wide, often
    already consumed) — see _storage_cost.

Usage:
    python3 calculate_costs.py --model artifacts/{app}/dynamodb_data_model.json
    python3 calculate_costs.py --model artifacts/{app}/dynamodb_data_model.json \
                               --requirements artifacts/{app}/{app}-requirements.json
    python3 calculate_costs.py --model artifacts/{app}/dynamodb_data_model.json \
                               --output cost_report.md
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

# -----------------------------------------------------------------------------
# Pricing constants — DynamoDB Standard table class, on-demand public rates.
# Rates vary by region; confirm against the AWS DynamoDB pricing page.
# -----------------------------------------------------------------------------
SECONDS_PER_MONTH = 2_592_000
SECONDS_PER_DAY = 86_400
DAYS_PER_MONTH = 30

# Per-request prices (dollars per unit, converted from "$X per million").
WRU_PRICE = 0.625 / 1_000_000  # Standard on-demand write
RRU_PRICE = 0.125 / 1_000_000  # Strongly-consistent on-demand read
# (Eventually-consistent and transactional rates derive from these via multiplier.)

# Storage.
STORAGE_PRICE_PER_GB_MONTH = 0.25  # Standard class, full public rate
# NOTE: the 25 GB Standard storage free tier is intentionally NOT modeled — it is
# account-wide and often already consumed, so we price all storage at full rate.
BYTES_PER_GB = 1_000_000_000  # Decimal GB per AWS billing convention

# Capacity-unit sizing (bytes).
RCU_SIZE_BYTES = 4 * 1024  # 4 KB
WCU_SIZE_BYTES = 1 * 1024  # 1 KB

# Per-item storage overhead (AWS docs: "100 bytes per item for indexing").
PER_ITEM_STORAGE_OVERHEAD = 100
GLOBAL_TABLES_OVERHEAD = 48  # Additional bytes when global tables enabled

# Query/Scan pagination cap. DynamoDB returns at most 1 MB per page; we use a
# conservative 900 KB to leave headroom for metadata.
PAGE_CAP_KB = 900

# -----------------------------------------------------------------------------
# Operation sets.
# -----------------------------------------------------------------------------
READ_OPS = {"GetItem", "Query", "Scan", "BatchGetItem", "TransactGetItems"}
WRITE_OPS = {"PutItem", "UpdateItem", "DeleteItem", "BatchWriteItem", "TransactWriteItems"}
TRANSACTIONAL_OPS = {"TransactGetItems", "TransactWriteItems"}
MULTI_ITEM_READ = {"Query", "Scan", "BatchGetItem", "TransactGetItems"}

# Default write_action when requirements aren't provided.
DEFAULT_WRITE_ACTION = {
    "PutItem": "create",
    "UpdateItem": "update",
    "DeleteItem": "delete",
    "BatchWriteItem": "mixed",
    "TransactWriteItems": "mixed",
}

# Fraction of writes that create new items, by write_action.
CREATE_RATIO = {
    "create": 1.0,
    "update": 0.0,
    "delete": 0.0,
    "mixed": 0.3,
}

DEFAULT_RETENTION_DAYS = 30

# Fraction of effective item bytes projected, by GSI projection type.
# Used to size the GSI write that fires as amplification.
PROJECTION_WRITE_RATIO = {
    "ALL": 1.0,
    "INCLUDE": 0.3,  # conservative default when include list is unknown
    "KEYS_ONLY": 0.1,  # keys + optional sort key, typically ≤ 1 KB
}

# Storage ratio relative to base table, by GSI projection type.
PROJECTION_STORAGE_RATIO = {
    "ALL": 1.0,
    "INCLUDE": 0.3,
    "KEYS_ONLY": 0.1,
}

DISCLAIMER = (
    "> **Disclaimer:** This estimate covers **read/write request costs** and "
    "**storage costs** only, at DynamoDB Standard table class on-demand **full "
    "public rates** (the 25 GB storage free tier is NOT applied — it is "
    "account-wide and often already used). **Rates vary by region** — confirm "
    "the figure against the AWS DynamoDB pricing page (or `aws pricing "
    "get-products --service-code AmazonDynamoDB`) for the region you will "
    "deploy in before quoting it. The headline figure "
    "is **peak-sustained** — it assumes every pattern runs at its declared "
    "`peak_rps` continuously, 24/7 for a month (the worst case). Real on-demand "
    "spend tracks actual request volume; set `avg_rps` on patterns to also get "
    "an expected average-volume figure. For up-to-date pricing, refer to "
    "the [Amazon DynamoDB Pricing](https://aws.amazon.com/dynamodb/pricing/) page."
)

GSI_FOOTNOTE = (
    "¹ **GSI additional writes** — When a table write changes attributes "
    "projected into a GSI, DynamoDB performs an additional write to that index. "
    "The additional write is sized by the projected attributes (not the base "
    "item), which is why KEYS_ONLY / INCLUDE projections are cheaper. "
    "[Learn more](https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/GSI.html"
    "#GSI.ThroughputConsiderations.Writes)"
)


# =============================================================================
# Core capacity-consumption formulas (verified against live DynamoDB).
# =============================================================================
def wru_for_item(item_size_bytes: int) -> int:
    """WRUs consumed for a standard write of a given item size.

    Empirically verified: ceil(size / 1024), with a minimum of 1 WRU.
    """
    if item_size_bytes <= 0:
        return 1
    return math.ceil(item_size_bytes / WCU_SIZE_BYTES)


def rru_for_item(item_size_bytes: int, strong: bool = False) -> float:
    """RRUs consumed reading a single item.

    Strong: ceil(size / 4096), min 1. Eventual: half of strong, min 0.5.
    Non-existent items still consume the minimum (verified).
    """
    strong_rru = max(1, math.ceil(max(1, item_size_bytes) / RCU_SIZE_BYTES))
    return float(strong_rru) if strong else strong_rru / 2.0


def rru_for_query(total_bytes_read: int, strong: bool = False) -> float:
    """RRUs for a Query/Scan that reads `total_bytes_read` from storage.

    Query/Scan aggregates all items, rounds the TOTAL to next 4 KB, then
    halves for eventual consistency. (Verified: 5×1KB items = 1 RCU eventual,
    10×512B items = 1 RCU eventual, etc.)
    """
    strong_rru = max(1, math.ceil(max(1, total_bytes_read) / RCU_SIZE_BYTES))
    return float(strong_rru) if strong else strong_rru / 2.0


def rru_for_batch_read(item_sizes: list[int], strong: bool = False) -> float:
    """BatchGetItem rounds each item individually, then sums. Verified."""
    total = 0.0
    for sz in item_sizes:
        total += rru_for_item(sz, strong=strong)
    return total


def wru_for_batch_write(item_sizes: list[int]) -> int:
    """BatchWriteItem rounds each item individually, then sums. Verified."""
    return sum(wru_for_item(sz) for sz in item_sizes)


# =============================================================================
# GSI amplification (verified empirically).
# =============================================================================
def gsi_write_wru(
    base_item_size_bytes: int, projection_type: str, projection_ratio_override: float | None = None
) -> int:
    """WRU consumed for the GSI write that amplifies from a base-table write.

    The GSI item size is driven by PROJECTED attributes only. Empirically:
      - ALL projection on a 4 KB base: GSI consumed = 4 WCU (full item)
      - KEYS_ONLY / INCLUDE on a 4 KB base: GSI consumed = 1 WCU (tiny projected item)
    """
    ratio = (
        projection_ratio_override
        if projection_ratio_override is not None
        else PROJECTION_WRITE_RATIO.get(projection_type, 1.0)
    )
    projected_size = max(1, int(base_item_size_bytes * ratio))
    return wru_for_item(projected_size)


# =============================================================================
# Model loading and helpers.
# =============================================================================
def load_model(path: str) -> dict:
    with open(path) as f:
        return json.load(f)


def _build_entity_attr_sizes(tables: list[dict]) -> dict:
    """Build {entity_name: {attr_name: size_bytes}} from entity definitions."""
    # Heuristic sizes used by modeling instructions.
    type_sizes = {
        "S": 100,
        "N": 8,
        "BOOL": 1,
        "B": 256,
        "L": 200,
        "M": 200,
        "SS": 200,
        "NS": 200,
        "BS": 200,
        "NULL": 1,
    }
    # Attribute-name overhead. Average name ~10 bytes.
    name_overhead = 10
    result = {}
    for t in tables:
        for ent in t.get("entities", []):
            attr_sizes = {}
            for attr in ent.get("attributes", []):
                attr_sizes[attr["name"]] = (
                    type_sizes.get(attr.get("type", "S"), 100) + name_overhead
                )
            result[ent["entity_name"]] = attr_sizes
    return result


def _cap_items_per_request(ap: dict, entity_sizes: dict) -> int:
    """Cap items_per_request at the 1 MB page limit using projected attribute sizes."""
    items = ap.get("items_per_request", 1)
    if ap["operation"] not in ("Query", "Scan"):
        return items

    projection = ap.get("projection")
    if not projection:
        return items

    projected_bytes = 0
    for attr in projection:
        found = False
        for ent_key, attr_sizes in entity_sizes.items():
            if attr in attr_sizes:
                projected_bytes += attr_sizes[attr]
                found = True
                break
        if not found:
            projected_bytes += 100  # default fallback per attribute

    if projected_bytes <= 0:
        return items

    page_cap_bytes = PAGE_CAP_KB * 1024
    items_per_page = max(1, page_cap_bytes // projected_bytes)
    return min(items, items_per_page)


def _resolve_write_action(ap: dict, requirements: dict | None) -> str:
    wa = ap.get("write_action")
    if wa:
        return wa
    if requirements:
        source_req = ap.get("source_requirement", "")
        updates = requirements.get("updates", {})
        if source_req in updates:
            wa = updates[source_req].get("write_action")
            if wa:
                return wa
    return DEFAULT_WRITE_ACTION.get(ap["operation"], "mixed")


def _resolve_retention_days(ap: dict, tables: list[dict], requirements: dict | None) -> int:
    # A per-pattern retention_days (documented in cost-model-schema.md) is the
    # most specific signal and wins over the requirements lookup and the default.
    # Without this, a write pattern declaring e.g. retention_days: 365 was
    # silently priced at the 30-day default, understating storage ~12×.
    if "retention_days" in ap:
        return int(ap["retention_days"])
    if not requirements:
        return DEFAULT_RETENTION_DAYS
    entity_name = None
    table_name = ap.get("table", "")
    for t in tables:
        if t["table_name"] == table_name:
            entities = t.get("entities", [])
            if entities:
                entity_name = entities[0].get("entity_name")
            break
    if entity_name:
        ent_def = requirements.get("entities", {}).get(entity_name, {})
        ret = ent_def.get("retention_days")
        if ret is not None:
            return ret
    ret = requirements.get("metadata", {}).get("retention_days_default")
    if ret is not None:
        return ret
    return DEFAULT_RETENTION_DAYS


def _fmt(cost: float) -> str:
    return f"${cost:.2f}"


def _padded_table(headers: list[str], rows: list[list[str]]) -> str:
    widths = [len(h) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            if i < len(widths):
                widths[i] = max(widths[i], len(cell))
    lines = [
        "| " + " | ".join(h.ljust(widths[i]) for i, h in enumerate(headers)) + " |",
        "| " + " | ".join("-" * w for w in widths) + " |",
    ]
    for row in rows:
        lines.append(
            "| "
            + " | ".join(
                row[i].ljust(widths[i]) if i < len(row) else "".ljust(widths[i])
                for i in range(len(headers))
            )
            + " |"
        )
    return "\n".join(lines)


# =============================================================================
# Per-access-pattern capacity and cost.
# =============================================================================
def calc_pattern_capacity(ap: dict) -> dict:
    """Compute {rcus, wcus, notes} for one access pattern.

    Returns a dict with:
      op, rcus, wcus, strong, transactional, notes
    Only read OR write is non-zero for a given pattern.
    """
    op = ap["operation"]
    size = ap.get("estimated_item_size_bytes", 1024)
    items = ap.get("items_per_request", 1)
    strong = ap.get("consistency", "eventual") == "strong"
    transactional = op in TRANSACTIONAL_OPS
    notes = []

    rcus = 0.0
    wcus = 0.0

    if op == "GetItem":
        rcus = rru_for_item(size, strong=strong)
        if ap.get("non_existent_rate"):
            notes.append("Non-existent items still consume the minimum RRU.")

    elif op == "Query":
        total_bytes = size * items
        rcus = rru_for_query(total_bytes, strong=strong)
        if ap.get("filter"):
            notes.append("FilterExpression does not reduce cost.")
        if ap.get("projection"):
            notes.append("ProjectionExpression does not reduce cost.")

    elif op == "Scan":
        total_bytes = size * items
        rcus = rru_for_query(total_bytes, strong=strong)
        notes.append("Scan reads every evaluated item regardless of filter.")

    elif op == "BatchGetItem":
        item_sizes = ap.get("item_sizes") or [size] * items
        rcus = rru_for_batch_read(item_sizes, strong=strong)

    elif op == "TransactGetItems":
        item_sizes = ap.get("item_sizes") or [size] * items
        rcus = rru_for_batch_read(item_sizes, strong=True) * 2.0
        notes.append("Transactional reads consume 2× RRUs.")

    elif op == "PutItem":
        # Replacement costs the LARGER of before/after.
        before = ap.get("previous_item_size_bytes", 0)
        wcus = wru_for_item(max(size, before))

    elif op == "UpdateItem":
        before = ap.get("previous_item_size_bytes", size)
        wcus = wru_for_item(max(size, before))

    elif op == "DeleteItem":
        wcus = wru_for_item(size)

    elif op == "BatchWriteItem":
        item_sizes = ap.get("item_sizes") or [size] * items
        wcus = float(wru_for_batch_write(item_sizes))

    elif op == "TransactWriteItems":
        item_sizes = ap.get("item_sizes") or [size] * items
        # Txn multiplier applies to base table only. GSI amplification is
        # billed elsewhere (standard 1× per GSI write).
        wcus = float(wru_for_batch_write(item_sizes)) * 2.0
        notes.append(
            "Transactional writes: 2× multiplier on base table; "
            "GSI amplification remains 1× per GSI write."
        )

    # Conditional-failure handling
    cond_fail_rate = ap.get("conditional_fail_rate", 0.0)
    if cond_fail_rate and op in WRITE_OPS:
        # Failed writes still consume capacity sized by existing/new item.
        # We assume the rate is a fraction of total calls; those calls still
        # compute WRUs the same way.
        notes.append(
            f"Conditional failures (rate={cond_fail_rate}) still " f"consume the same WRUs."
        )

    return {
        "op": op,
        "rcus": rcus,
        "wcus": wcus,
        "strong": strong,
        "transactional": transactional,
        "notes": notes,
    }


def _entity_attr_names(table_def: dict) -> dict:
    """{entity_name: set(attribute names)} for one table.

    A DynamoDB item only appears in (and only amplifies a write to) a GSI whose
    key attributes it actually CARRIES. In a single-table design with
    heterogeneous entities, each GSI is keyed on an attribute only some entities
    have — so this per-entity attribute-name set is what decides GSI membership.
    """
    out = {}
    for ent in table_def.get("entities", []) or []:
        name = ent.get("entity_name")
        if not name:
            continue
        out[name] = {a["name"] for a in ent.get("attributes", []) or [] if a.get("name")}
    return out


def _gsi_key_attrs(gsi: dict) -> tuple:
    """(pk_attr, sk_attr|None) for a GSI, tolerating key-name spellings."""
    pk = gsi.get("partition_key") or gsi.get("hash_key")
    sk = gsi.get("sort_key") or gsi.get("range_key")
    return pk, sk


def _table_key_attrs(table_def: dict) -> set:
    """The table's own PK/SK attribute names — every item carries these."""
    ks = table_def.get("key_schema") or {}
    return {a for a in (ks.get("partition_key"), ks.get("sort_key")) if a}


def _item_carries_gsi_key(attr_names: set, gsi: dict, table_key_attrs: set | None = None) -> bool:
    """True iff an item with these attributes is INDEXED by this GSI.

    Membership rule, verified live (ReturnConsumedCapacity=INDEXES): an item is
    written to a GSI only if it carries the GSI partition key AND, for a
    composite GSI, the GSI sort key. An item carrying the PK but missing the SK
    of a composite GSI is NOT indexed (live: a g2-without-g2sk put fired ZERO
    GSI writes). A GSI key that is also a TABLE key is carried by every item.
    """
    tk = table_key_attrs or set()
    pk, sk = _gsi_key_attrs(gsi)
    if not pk or (pk not in attr_names and pk not in tk):
        return False
    if sk and sk not in attr_names and sk not in tk:
        return False
    return True


def _gsi_membership_determinable(table_def: dict, gsi: dict) -> bool:
    """Can we reason about which items belong to this GSI from the model?

    Determinable only when the GSI's partition key is positively declared
    somewhere we can attribute to items: by at least one entity's attribute
    list, or as a table key (every item carries table keys). A GSI key declared
    nowhere — or only at table level (`attribute_definitions`, which can't say
    WHICH entity carries it) — is INDETERMINATE: we must not infer absence and
    silently drop the GSI's cost. Callers fall back to the conservative
    charge-everything bound for such a GSI.
    """
    pk, sk = _gsi_key_attrs(gsi)
    if not pk:
        return False
    table_keys = _table_key_attrs(table_def)
    declared = set(table_keys)
    for ent in table_def.get("entities") or []:
        declared |= {a["name"] for a in (ent.get("attributes") or []) if a.get("name")}
    # Both the GSI PK and (for a composite GSI) the GSI SK must be declared
    # somewhere we can attribute to items, or we cannot reason about which items
    # are members and must fall back to the conservative full-size charge.
    if pk not in declared:
        return False
    if sk and sk not in declared:
        return False
    return True


def _projection_type(gsi: dict) -> str:
    proj = gsi.get("projection", {}) or {}
    ptype = proj.get("type", "ALL")
    return ptype.upper() if isinstance(ptype, str) else "ALL"


def _resolve_written_items(ap: dict, table_def: dict) -> tuple[list, bool]:
    """Resolve the per-item entity attribute-name sets a single call writes.

    Returns (item_attr_sets, resolved). Each element of item_attr_sets is the
    attribute-name set of ONE written item, so a transaction creating 1 order +
    3 line items yields 4 sets. `resolved=False` means we could not identify the
    written entities and the caller must fall back to a conservative upper bound.

    Resolution order:
      1. explicit `entities_written` on the access pattern — a list of entity
         names (repeats allowed) or `[{"entity": "X", "count": n}]`.
      2. exactly one entity declared on the table — the unambiguous single-entity
         / classic-multi-table case; each of the items_per_request written items
         is that entity.
      3. otherwise unresolved (multi-entity single-table design with no
         entities_written): conservative upper bound.
    """
    ent_attrs = _entity_attr_names(table_def)
    items_per = int(ap.get("items_per_request", 1) or 1)

    ew = ap.get("entities_written")
    if ew:
        flat = []
        for e in ew:
            if isinstance(e, dict):
                name = e.get("entity") or e.get("entity_name")
                cnt = int(e.get("count", 1) or 1)
            else:
                name, cnt = e, 1
            # A named entity we can't find contributes items that carry no known
            # key — i.e. amplify nowhere. That's the honest reading of a typo'd
            # or undeclared entity name; it surfaces as a visibly low number
            # rather than silently inheriting the full fan-out.
            attrs = ent_attrs.get(name, set())
            flat.extend([attrs] * max(1, cnt))
        return flat, True

    if len(ent_attrs) == 1:
        only = next(iter(ent_attrs.values()))
        return [only] * items_per, True

    return [], False


def _gsi_index_writes_for_item(
    item_attrs: set, gsi: dict, op: str, attrs_written, table_key_attrs: set | None = None
) -> int:
    """How many index writes ONE item's write costs against this GSI: 0, 1, or 2.

    Membership (carries the GSI key) is necessary for every op. Verified live
    against ReturnConsumedCapacity=INDEXES:
      - Put / create / Delete, or an UpdateItem with no attrs_written info:
        1 index write per member item (the projected-size write).
      - UpdateItem that CHANGES the GSI's own key attribute (PK or SK): **2**
        index writes — DynamoDB deletes the old index entry and inserts a new
        one (a "ByStatus" KEYS_ONLY index cost 2 WCU when `status` changed).
      - UpdateItem that changes a NON-key but projected attribute:
          ALL → 1 (the whole item is re-projected);
          INCLUDE → 1 if a projected attr changed, else 0;
          KEYS_ONLY → 0 (nothing projected but the keys, which didn't move).
      - UpdateItem touching nothing the GSI projects and no key it indexes: 0.
    Each returned write is later sized by gsi_write_wru (ALL=full item,
    INCLUDE/KEYS_ONLY=small).
    """
    if not _item_carries_gsi_key(item_attrs, gsi, table_key_attrs):
        return 0
    if op == "UpdateItem" and attrs_written is not None:
        ptype = _projection_type(gsi)
        pk, sk = _gsi_key_attrs(gsi)
        keys = {k for k in (pk, sk) if k}
        key_moved = bool(set(attrs_written) & keys)
        if key_moved:
            # Old entry deleted + new entry inserted on this index.
            return 2
        if ptype == "ALL":
            return 1
        if ptype == "INCLUDE":
            proj = gsi.get("projection", {}) or {}
            inc = set(
                proj.get("attributes")
                or proj.get("non_key_attributes")
                or proj.get("NonKeyAttributes")
                or []
            )
            return 1 if (set(attrs_written) & inc) else 0
        if ptype == "KEYS_ONLY":
            return 0  # keys didn't move (handled above) and nothing else projected
    return 1


def calc_gsi_amplification_wru(ap: dict, table_def: dict) -> tuple[float, list[str]]:
    """Compute per-request WRU consumed by GSI amplification for this write.

    Returns (total_wru_amp, details_strings).

    A write amplifies to a GSI only when the written item CARRIES that GSI's key
    attributes (PK, plus SK if the GSI is composite) — verified live against
    ReturnConsumedCapacity=INDEXES. In a single-table design with heterogeneous
    entities, each GSI is keyed on an attribute only some entities have, so a
    given write touches only the few GSIs its entity is a member of — not all of
    them. The per-GSI write is sized by the PROJECTED attributes (ALL = full
    item; INCLUDE / KEYS_ONLY = small), which the live run also confirmed.
    """
    if ap["operation"] not in WRITE_OPS:
        return 0.0, []
    gsis = table_def.get("gsis", []) or []
    if not gsis:
        return 0.0, []

    op = ap["operation"]
    size = ap.get("estimated_item_size_bytes", 1024)
    attrs_written = ap.get("attributes_written")  # optional: list of attr names
    items_per = int(ap.get("items_per_request", 1) or 1)

    written_items, resolved = _resolve_written_items(ap, table_def)
    table_keys = _table_key_attrs(table_def)
    total = 0.0
    details: list[str] = []

    if resolved:
        # Accurate path: each written item amplifies only to the GSIs whose key
        # it carries. A GSI whose key is declared NOWHERE attributable to an item
        # (not on any entity, not a table key) is INDETERMINATE — we can't infer
        # absence, so charge it conservatively (fires for every item, honoring
        # the UpdateItem projection gate) rather than silently dropping its cost.
        per_gsi_writes: dict = {}  # index_name -> total index writes (1 or 2 each)
        indeterminate: list[str] = []
        member_but_gated = []  # member items whose UpdateItem projection gate excluded them
        for gsi in gsis:
            name = gsi.get("index_name", "?")
            determinable = _gsi_membership_determinable(table_def, gsi)
            gsi_gated_member = False
            for item_attrs in written_items:
                if determinable:
                    is_member = _item_carries_gsi_key(item_attrs, gsi, table_keys)
                    writes = _gsi_index_writes_for_item(
                        item_attrs, gsi, op, attrs_written, table_keys
                    )
                    if is_member and writes == 0:
                        gsi_gated_member = True
                else:
                    # Indeterminate membership → conservative: count it unless the
                    # UpdateItem projection gate provably excludes it.
                    pk_a, sk_a = _gsi_key_attrs(gsi)
                    synthetic = {pk_a} | ({sk_a} if sk_a else set())
                    writes = _gsi_index_writes_for_item(
                        synthetic, gsi, op, attrs_written, table_keys
                    )
                if writes:
                    total += gsi_write_wru(size, _projection_type(gsi)) * writes
                    per_gsi_writes[name] = per_gsi_writes.get(name, 0) + writes
            if not determinable and name in per_gsi_writes:
                indeterminate.append(name)
            if gsi_gated_member and name not in per_gsi_writes:
                member_but_gated.append(name)
        if per_gsi_writes:
            details = [
                f"{name} (×{n} index write{'s' if n != 1 else ''}"
                + (
                    ", membership unverified — GSI key not declared on any entity"
                    if name in indeterminate
                    else ""
                )
                + ")"
                for name, n in per_gsi_writes.items()
            ]
        elif member_but_gated:
            details = [
                f"no GSI amplification — {op} touched no attribute "
                f"projected into {', '.join(member_but_gated)} "
                f"(projection gate)"
            ]
        else:
            details = ["no GSI amplification — written item(s) carry no GSI key"]
        return total, details

    # Unresolved: multi-entity single-table design with no `entities_written`.
    # We cannot know which entity each written item is, so we keep the
    # conservative UPPER BOUND (every item is assumed a member of every GSI) and
    # say so loudly — declaring `entities_written` on the pattern refines it. A
    # synthetic full-key item drives the same write-count logic (incl. the
    # UpdateItem projection gate and the key-move 2× factor) as the accurate path.
    for gsi in gsis:
        pk_a, sk_a = _gsi_key_attrs(gsi)
        synthetic = {a for a in (pk_a, sk_a) if a}
        writes = _gsi_index_writes_for_item(synthetic, gsi, op, attrs_written, table_keys)
        total += gsi_write_wru(size, _projection_type(gsi)) * writes
    if op in ("BatchWriteItem", "TransactWriteItems"):
        total *= items_per
    details.append(
        f"UPPER BOUND — '{ap.get('table', '?')}' has multiple entities and this "
        f"pattern has no `entities_written`, so every written item is charged "
        f"against every GSI. Declare `entities_written` to bill only the GSIs "
        f"each written entity is a member of."
    )
    return total, details


def pattern_monthly_cost(
    ap: dict,
    table_def: dict | None,
    entity_attr_sizes: dict | None = None,
) -> dict:
    """Return per-pattern monthly cost and capacity detail for one access pattern.

    Inputs:
      ap              — one access-pattern dict (see cost-model-schema.md).
      table_def       — the table-def dict (used for GSI amplification); may be None.
      entity_attr_sizes — output of _build_entity_attr_sizes(tables); needed to cap
                          Query/Scan items_per_request at the 900 KB page limit.

    Returns:
      {
        "ap":               the effective ap dict (post-cap),
        "cap":              output of calc_pattern_capacity,
        "base_cost":        monthly dollars for base-table RCU/WCU,
        "gsi_amp_wru":      observed-equivalent GSI amp WRU per call,
        "gsi_amp_details":  list[str] of "IndexName (PROJ): +X WRU",
        "gsi_amp_cost":     monthly dollars for GSI amplification,
        "total_cost":       base_cost + gsi_amp_cost,
      }

    No AWS calls; no side effects. The same formulas the CLI uses.
    """
    if ap["operation"] in ("Query", "Scan") and entity_attr_sizes is not None:
        capped = _cap_items_per_request(ap, entity_attr_sizes)
        ap = dict(ap, items_per_request=capped)

    cap = calc_pattern_capacity(ap)
    rps = ap.get("peak_rps", 0)
    # Optional expected/average-volume scenario. `avg_rps` defaults to peak_rps,
    # so a model without it produces byte-identical numbers to before. When set,
    # `expected_*` is the same per-op CU (scale-invariant) driven at the lower
    # average rate — the realistic monthly figure, computed by the calculator
    # instead of hand-derived.
    avg_rps = ap.get("avg_rps", rps)

    per_op_cu_cost = cap["rcus"] * RRU_PRICE + cap["wcus"] * WRU_PRICE
    base_cost = per_op_cu_cost * rps * SECONDS_PER_MONTH
    expected_base_cost = per_op_cu_cost * avg_rps * SECONDS_PER_MONTH

    gsi_amp_wru = 0.0
    gsi_amp_details: list[str] = []
    if ap["operation"] in WRITE_OPS and table_def:
        gsi_amp_wru, gsi_amp_details = calc_gsi_amplification_wru(ap, table_def)
    gsi_amp_cost = gsi_amp_wru * WRU_PRICE * rps * SECONDS_PER_MONTH
    expected_gsi_amp_cost = gsi_amp_wru * WRU_PRICE * avg_rps * SECONDS_PER_MONTH

    cond_fail_rate = ap.get("conditional_fail_rate", 0.0)
    if cond_fail_rate and ap["operation"] in WRITE_OPS:
        fail_multiplier = cond_fail_rate
        base_cost *= 1.0 + fail_multiplier
        gsi_amp_cost *= 1.0 + fail_multiplier
        expected_base_cost *= 1.0 + fail_multiplier
        expected_gsi_amp_cost *= 1.0 + fail_multiplier

    return {
        "ap": ap,
        "cap": cap,
        "base_cost": base_cost,
        "gsi_amp_wru": gsi_amp_wru,
        "gsi_amp_details": gsi_amp_details,
        "gsi_amp_cost": gsi_amp_cost,
        "total_cost": base_cost + gsi_amp_cost,
        "expected_cost": expected_base_cost + expected_gsi_amp_cost,
    }


def _gsi_membership_byte_fraction(table_def: dict, gsi: dict) -> float:
    """Fraction of the base table's BYTES that this GSI actually indexes.

    A GSI holds only the items that carry its key (PK + SK if composite), so its
    storage is base_storage × (member-entity bytes / all-entity bytes), NOT the
    full base table. Computed from entity declarations; an ALL-projection GSI on
    a single-entity table yields 1.0 (unchanged from legacy behavior).

    Guard: the refinement only applies when the GSI's partition key is declared
    by at least one entity's attribute list — proof that attributes are
    specified meaningfully. If no entity declares the GSI PK at all (attributes
    underspecified, or a key that lives only in `attribute_definitions`), we
    cannot reason about membership and return 1.0 (conservative — never silently
    zeroes a GSI's storage on a thin model).
    """
    ents = table_def.get("entities") or []
    if not ents:
        return 1.0
    # Indeterminate membership (GSI key declared on no entity and not a table
    # key) → conservative full size; never silently shrink a GSI's storage on a
    # thin model. A GSI key that IS a table key is carried by every item → 1.0.
    if not _gsi_membership_determinable(table_def, gsi):
        return 1.0
    table_keys = _table_key_attrs(table_def)

    total = 0.0
    member = 0.0
    for ent in ents:
        cnt = ent.get("estimated_item_count", 100_000)
        sz = ent.get("estimated_item_size_bytes", 1024)
        b = cnt * sz
        total += b
        attrs = {a["name"] for a in (ent.get("attributes") or []) if a.get("name")}
        if _item_carries_gsi_key(attrs, gsi, table_keys):
            member += b
    if total <= 0:
        return 1.0
    return member / total


def _storage_cost(tables: list, by_table: dict) -> tuple[list, float]:
    """Storage rows + total dollars for a given per-table byte map.

    Factored out so the peak and the expected (average-volume) scenarios run
    through identical projection-ratio logic — no drift between the two
    headlines. `by_table` maps table_name → steady-state bytes (write-driven);
    tables with no write traffic fall back to entity-count storage.

    All storage is billed at the **full public rate** — the 25 GB Standard free
    tier is deliberately NOT applied. The free tier is account-wide and is often
    already consumed by other tables in the same account, so assuming it here
    understates the bill and produces a "$0.00, storage is free" claim a user
    cannot safely repeat. Pricing at full rate is the honest, account-agnostic
    default.
    """
    rows = []
    total = 0.0
    for t in tables:
        tname = t["table_name"]
        total_bytes = by_table.get(tname, 0)
        # Fallback: if no write patterns hit this table, use entity counts.
        if total_bytes == 0:
            for ent in t.get("entities", []):
                item_size = ent.get("estimated_item_size_bytes", 1024)
                item_count = ent.get("estimated_item_count", 100_000)
                overhead = PER_ITEM_STORAGE_OVERHEAD
                if t.get("global_tables"):
                    overhead += GLOBAL_TABLES_OVERHEAD
                total_bytes += item_count * (item_size + overhead)

        gb = total_bytes / BYTES_PER_GB
        sc = gb * STORAGE_PRICE_PER_GB_MONTH
        rows.append([tname, "Table", f"{gb:.2f}", _fmt(sc)])
        total += sc

        for g in t.get("gsis", []):
            proj = g.get("projection", {}) or {}
            ptype = proj.get("type", "ALL")
            ptype = ptype.upper() if isinstance(ptype, str) else "ALL"
            ratio = PROJECTION_STORAGE_RATIO.get(ptype, 1.0)
            # A GSI stores only the items that carry its key (PK + SK if
            # composite), not the whole base table. Scale by the fraction of
            # base BYTES whose entity is a member of this index. On a
            # single-entity table (or an underspecified model) this is 1.0, so
            # legacy single-table-single-entity output is unchanged.
            membership = _gsi_membership_byte_fraction(t, g)
            ggb = gb * ratio * membership
            gsc = ggb * STORAGE_PRICE_PER_GB_MONTH
            rows.append([g["index_name"], "GSI", f"{ggb:.2f}", _fmt(gsc)])
            total += gsc

    return rows, total


# =============================================================================
# Main reporting.
# =============================================================================
def calculate_and_report(model: dict, requirements: dict | None = None) -> str:
    tables = model.get("tables", [])
    access_patterns = model.get("access_patterns", [])

    # Lookups.
    table_map = {t["table_name"]: t for t in tables}
    entity_attr_sizes = _build_entity_attr_sizes(tables)

    # Per-pattern costs.
    results = []
    for ap in access_patterns:
        table_def = table_map.get(ap.get("table", ""))
        pc = pattern_monthly_cost(ap, table_def, entity_attr_sizes)
        eff_ap = pc["ap"]
        cap = pc["cap"]

        results.append(
            {
                "pattern_id": eff_ap["pattern_id"],
                "description": eff_ap.get("description", ""),
                "op": eff_ap["operation"],
                "table": eff_ap.get("table", ""),
                "index": eff_ap.get("index"),
                "rps": eff_ap.get("peak_rps", 0),
                "rcus": cap["rcus"],
                "wcus": cap["wcus"],
                "strong": cap["strong"],
                "transactional": cap["transactional"],
                "base_cost": pc["base_cost"],
                "gsi_amp_cost": pc["gsi_amp_cost"],
                "gsi_amp_details": pc["gsi_amp_details"],
                "total_cost": pc["total_cost"],
                "expected_cost": pc["expected_cost"],
                "notes": cap["notes"],
            }
        )

    # -------------------------------------------------------------------------
    # Storage estimates.
    # -------------------------------------------------------------------------
    storage_by_table: dict = {}
    # Parallel accumulation at avg_rps so the expected (average-volume) headline
    # uses average-rate storage growth, not peak — otherwise storage (often
    # ~10-15% of the bill) would keep the "expected" number peak-inflated.
    expected_storage_by_table: dict = {}
    for ap in access_patterns:
        if ap["operation"] not in WRITE_OPS:
            continue
        write_action = _resolve_write_action(ap, requirements)
        create_ratio = CREATE_RATIO.get(write_action, 0.3)
        if create_ratio <= 0:
            continue
        rps = ap.get("peak_rps", 0)
        if rps <= 0:
            continue
        avg_rps = ap.get("avg_rps", rps)

        raw_item_size = ap.get("estimated_item_size_bytes", 1024)
        overhead = PER_ITEM_STORAGE_OVERHEAD
        # Optional: add global tables overhead if configured on the table.
        table_name = ap.get("table", "")
        table_def = table_map.get(table_name, {})
        if table_def.get("global_tables"):
            overhead += GLOBAL_TABLES_OVERHEAD
        item_size = raw_item_size + overhead

        retention_days = _resolve_retention_days(ap, tables, requirements)
        create_rate = rps * create_ratio
        steady_state_bytes = item_size * create_rate * SECONDS_PER_DAY * retention_days
        storage_by_table[table_name] = storage_by_table.get(table_name, 0) + steady_state_bytes
        expected_bytes = item_size * (avg_rps * create_ratio) * SECONDS_PER_DAY * retention_days
        expected_storage_by_table[table_name] = (
            expected_storage_by_table.get(table_name, 0) + expected_bytes
        )

    storage_rows, storage_total = _storage_cost(tables, storage_by_table)
    # Expected (average-volume) storage uses the same logic on avg-rate bytes.
    # Only computed/rendered when avg_rps is in play; otherwise identical to peak.
    _, expected_storage_total = _storage_cost(tables, expected_storage_by_table)

    rw_total = sum(r["total_cost"] for r in results)
    total = storage_total + rw_total
    # Expected (average-volume) headline. `avg_rps` defaults to peak_rps per
    # pattern, so when no pattern sets it, expected_total == total exactly and
    # the two-headline block is suppressed (legacy byte-identical output).
    any_avg_rps = any("avg_rps" in ap for ap in access_patterns)
    expected_rw_total = sum(r["expected_cost"] for r in results)
    expected_total = expected_storage_total + expected_rw_total

    # Sort results by cost descending.
    results.sort(key=lambda r: r["total_cost"], reverse=True)

    # Cost concentration note: if a single pattern drives >30% of the RW
    # total, item-size drift on that pattern could move the headline number
    # materially. Surface it so the user knows where to scrutinise inputs.
    concentration_notes = []
    if rw_total > 0:
        for r in results:
            share = r["total_cost"] / rw_total
            if share > 0.30:
                concentration_notes.append(
                    f"- `{r['pattern_id']}` contributes {share*100:.0f}% of "
                    f"read/write cost. A 50% error in `estimated_item_size_bytes` "
                    f"on this pattern would move the headline number by "
                    f"~{share*50:.0f}%. Revisit its attribute walkthrough if "
                    f"you haven't already, or rely on live validation to "
                    f"confirm the number."
                )

    # Build report.
    lines = [
        "# DynamoDB Cost Report",
        "",
        DISCLAIMER,
        "",
    ]
    if any_avg_rps:
        # Two labeled headlines: the peak-sustained worst case and the
        # expected figure at the stated average volume. This is the calculator
        # producing the "realistic" number so the agent never hand-derives it.
        lines += [
            f"**Peak-Sustained Monthly Cost: {_fmt(total)}**  *(every pattern at "
            "its declared `peak_rps`, sustained 24/7 — the worst case)*",
            "",
            f"**Expected Monthly Cost (your stated average volume): "
            f"{_fmt(expected_total)}**  *(patterns driven at `avg_rps`; on-demand "
            "bills per request, so this is the realistic figure)*",
            "",
            _padded_table(
                ["Source", "Peak-Sustained", "Expected"],
                [
                    ["Storage", _fmt(storage_total), _fmt(expected_storage_total)],
                    ["Read and write requests", _fmt(rw_total), _fmt(expected_rw_total)],
                ],
            ),
        ]
    else:
        lines += [
            f"**Peak-Sustained Monthly Cost: {_fmt(total)}**  *(every pattern at "
            "its declared `peak_rps`, sustained 24/7; set `avg_rps` on patterns "
            "for a realistic average-volume figure)*",
            "",
            _padded_table(
                ["Source", "Monthly Cost"],
                [
                    ["Storage", _fmt(storage_total)],
                    ["Read and write requests", _fmt(rw_total)],
                ],
            ),
        ]
    if concentration_notes:
        lines += [
            "",
            "> **Cost concentration — item-size sensitivity.** One or more "
            "patterns drive a disproportionate share of the estimate. The "
            "calculator formulas are empirically verified; the remaining risk "
            "is in the inputs — particularly `estimated_item_size_bytes`. If "
            "any of these patterns' item sizes were guessed without an "
            "attribute walkthrough, the headline number could be off by "
            "tens of percent.",
            "",
            *concentration_notes,
        ]
    lines += [
        "",
        "## Storage Costs",
        "",
        f"**Monthly Cost:** {_fmt(storage_total)}",
        "",
        "*Priced at the full public Standard rate ($0.25/GB-month). The 25 GB "
        "free tier is not applied — it is account-wide and often already "
        "consumed by other tables.*",
        "",
        _padded_table(["Resource", "Type", "Storage (GB)", "Monthly Cost"], storage_rows),
        "",
        "## Access Pattern Costs",
        "",
        f"**Monthly Cost:** {_fmt(rw_total)}",
        "",
    ]

    has_gsi_footnote = False
    detail_headers = ["Pattern", "Operation", "Table/Index", "Peak RPS", "RRU/WRU", "Monthly Cost"]
    detail_rows = []
    for r in results:
        target = r["table"]
        if r["index"]:
            target += f" / {r['index']}"
        ru = r["wcus"] if r["wcus"] > 0 else r["rcus"]
        flag = ""
        if r["transactional"]:
            flag += " (txn)"
        if r["strong"] and r["wcus"] == 0:
            flag += " (strong)"
        detail_rows.append(
            [
                r["pattern_id"],
                r["op"] + flag,
                target,
                f"{r['rps']:.1f}",
                f"{ru:.2f}",
                _fmt(r["base_cost"]),
            ]
        )
        if r["gsi_amp_cost"] > 0:
            detail_rows.append(
                [
                    f"{r['pattern_id']}¹",
                    "GSI writes",
                    r["table"],
                    f"{r['rps']:.1f}",
                    "-",
                    _fmt(r["gsi_amp_cost"]),
                ]
            )
            has_gsi_footnote = True

    lines.append(_padded_table(detail_headers, detail_rows))

    if has_gsi_footnote:
        lines += ["", GSI_FOOTNOTE]

    return "\n".join(lines)


# =============================================================================
# CLI.
# =============================================================================
def main():
    parser = argparse.ArgumentParser(description="DynamoDB Cost Calculator — reads data model JSON")
    parser.add_argument("--model", required=True, help="Path to dynamodb_data_model.json")
    parser.add_argument(
        "--requirements",
        "-r",
        help="Path to requirements artifact JSON " "(enables write-action storage modeling)",
    )
    parser.add_argument(
        "--output", "-o", help="Output file (default: cost_report.md " "in same directory)"
    )
    args = parser.parse_args()

    model_path = Path(args.model)
    try:
        model = load_model(str(model_path))
    except (json.JSONDecodeError, FileNotFoundError) as e:
        print(f"Error loading model: {e}", file=sys.stderr)
        sys.exit(1)

    requirements = None
    if args.requirements:
        try:
            requirements = load_model(args.requirements)
        except (json.JSONDecodeError, FileNotFoundError) as e:
            print(f"Warning: Could not load requirements ({e}), using defaults.", file=sys.stderr)

    if not model.get("access_patterns"):
        print("Error: No access patterns found in the data model.", file=sys.stderr)
        sys.exit(1)

    report = calculate_and_report(model, requirements)

    output_path = Path(args.output) if args.output else model_path.parent / "cost_report.md"
    output_path.write_text(report)
    print(f"Cost report written to {output_path}")
    print(
        f"Analyzed {len(model['access_patterns'])} access patterns "
        f"across {len(model.get('tables', []))} tables."
    )


if __name__ == "__main__":
    main()
