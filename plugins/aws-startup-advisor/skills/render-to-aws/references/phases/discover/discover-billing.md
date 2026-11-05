---
_fragment: billing
_of_phase: discover
_contributes:
  - render-resource-inventory.json
---

# Discover billing evidence

This `rw` fragment is file-only: the main window already ran `parse-render-billing.py` (see `discover.md` "Pre-dispatch main-window actions", Step 2) and listed its output in the active attempt manifest. Read only the manifest-listed `transport: billing` capture under `$MIGRATION_DIR/live-capture/`; never run the parser or read the invoice, export, or CSV source yourself.

Verify before contributing: `schema_version` is `1.0`, the SHA-256 digest equals the manifest `digest`, `source` is `user_stated` or `billing_export`, and the capture carries only the closed `render-billing` output set from `references/shared/schema-render-billing.json` (`source`, `currency`, `monthly_total`, `as_of` or `period_start`/`period_end`, `line_item_count`, `conversion`, `source_digest`, `fingerprint`). The parser accepted only its closed JSON user-stated/monthly-export contracts or exact CSV header and rejected unknown properties or headers, overlapping service periods, invalid dates, negative/non-decimal amounts, mixed currencies without an explicit dated conversion, and duplicate/missing conversions before row processing. Only aggregate Decimal arithmetic, period, currency, count, digest, and provenance are retained—never raw rows; a capture carrying raw rows is invalid and stops this contribution.

If the manifest lists no billing capture, record current spend as unavailable; never recall or invent Render prices.
