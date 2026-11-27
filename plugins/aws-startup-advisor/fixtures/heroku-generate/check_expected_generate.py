#!/usr/bin/env python3
"""Assert the heroku-to-aws GENERATE report (migration-report.html) over the heroku-generate
golden run.

Sibling of ../heroku-decision-gate/check_expected_decide.py for the full-mode report and of
../azure-iac-terraform/check_expected_generate.py for the oracle shape. The report's structural
contract — required section IDs, TOC integrity, the CSS shell, currency formatting, the
decision-core content, the optimization pair, the glossary and the appendix-config columns —
is owned by the two-command gate heroku-to-aws runs after Generate, so step one is to RUN both
validators against the run's own artifacts and require REPORT_OK:

  * scripts/validate-migration-report.py --profile heroku --mode full
  * skills/heroku-to-aws/scripts/validate-heroku-migration-report.py --mode full

The rest pins what the validators either resolve from the estimate or do not know about —
the facts generate-report.md fixes for this skill and that a plausible improvisation could
drift from:

  * every heroku full-mode required ID is present exactly once, in document order
    (decision-summary before the TOC, exec-risks before exec-assumptions, appendix-glossary
    the final section);
  * the stable appendix lettering (A, B, B.1, E, F, G, I, J) in BOTH the <h2> and the TOC
    label, and no C, D or H section (the three declared PaaS omissions);
  * Appendix B.1 renders exactly the two Savings Plan rows the estimate's
    optimization_opportunities[] carries, in the opportunity table's Optimization cell;
  * the Database Savings Plan Generation 7+ gate: when aws-design.json's RDS
    aws_config.instance_class is pre-Generation-7 (db.t4g.medium here), no B.1 row and no
    Cost Optimization posture row attaches a dollar saving to a Database Savings Plan, the
    estimate's row carries savings_monthly null, and Optimized = Balanced minus the Compute
    Savings Plan discount only (210 - 28 = 182);
  * the migration shape reads from preferences.json global.migration_approach (full_cutover
    → "Full cutover"), never "Phased", in decision-summary, exec-share and exec-timeline;
  * the one-sentence recommendation sits in a class="verdict" callout inside decision-summary;
  * the Pipelines and promote cell counts apps that appear in a pipeline's stages[] (none here);
  * exec-optimization names Optimized and carries the not-additive caveat and the word
    Balanced; exec-costs carries the Premium-equals-Balanced sentence (this estate has no
    resilience uplift left to price, so two tier figures are identical on purpose);
  * developer-workflow renders all ten rows of the generate-report.md table;
  * no bare week range anywhere in the body (the validator's own readability regex);
  * the aws_monthly_balanced anchor inside exec-costs equals projected_costs.aws_monthly_balanced.

Usage:
    python3 check_expected_generate.py <migration_run_dir>

<migration_run_dir> holds migration-report.html, heroku-resource-inventory.json,
estimation-infra.json, aws-design.json, preferences.json, generation-warnings.json and
.phase-status.json (a scratch copy of after-generate/). Exits 0 on PASS, 1 on FAIL.
Stdlib only; the validators are invoked as subprocesses so this script never imports (and
never writes bytecode for) a sibling module.
"""
from __future__ import annotations

import json
import re
import subprocess  # nosec B404 — fixture asserter; runs only committed scripts via sys.executable
import sys
from html.parser import HTMLParser
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parents[2]
VALIDATOR_SHARED = PLUGIN_ROOT / "scripts" / "validate-migration-report.py"
VALIDATOR_ADDON = (
    PLUGIN_ROOT / "skills" / "heroku-to-aws" / "scripts" / "validate-heroku-migration-report.py"
)

# SKILL_PROFILES["heroku"]["required_sections"]["full"] in document order, as
# generate-report.md § Skeleton renders them.
REQUIRED_IDS_IN_ORDER = [
    "decision-summary",
    "exec-share",
    "exec-services",
    "exec-costs",
    "exec-optimization",
    "developer-workflow",
    "exec-timeline",
    "exec-risks",
    "exec-assumptions",
    "appendix-services",
    "appendix-costs",
    "appendix-optimization",
    "appendix-artifacts",
    "appendix-config",
    "appendix-security",
    "appendix-assumptions",
    "appendix-glossary",
]
APPENDIX_LETTERING = {
    "appendix-services": "Appendix A —",
    "appendix-costs": "Appendix B —",
    "appendix-optimization": "Appendix B.1 —",
    "appendix-artifacts": "Appendix E —",
    "appendix-config": "Appendix F —",
    "appendix-security": "Appendix G —",
    "appendix-assumptions": "Appendix I —",
    "appendix-glossary": "Appendix J —",
}
ABSENT_SECTIONS = ("appendix-steps", "appendix-ai", "appendix-security-gap", "exec-tco",
                   "decision-cta", "next-steps", "cost-optimization", "decision-basis")
PREMIUM_SENTENCE = "Premium equals Balanced"
# Same non-stacking vocabulary the shared validator's _NON_STACK_RE accepts.
NON_STACK_RE = re.compile(
    r"(?:not\s+additive|do\s+not\s+add|already\s+embed|already\s+includes|not\s+a\s+sum|already\s+assume)",
    re.I,
)
# The shared validator's bare week-range readability pattern, without its uncalibrated-label escape.
WEEK_RANGE_RE = re.compile(r"\b\d+\s*(?:–|-|to)\s*\d+\+?\s*weeks\b", re.I)
DEVELOPER_WORKFLOW_ROWS = 10
FAILS: list[str] = []


def check(cond: bool, msg: str) -> None:
    if not cond:
        FAILS.append(msg)


class _Sections(HTMLParser):
    """Collect each <section id=...>'s decoded text, its <h2> text, the TOC labels, the
    first-cell text of every <tbody> row per section, and every data-cost-key anchor's
    rendered text tagged by section — all in document order."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.order: list[str] = []
        self.sections: dict[str, str] = {}
        self.h2: dict[str, str] = {}
        self.toc_labels: dict[str, str] = {}
        self.toc_position: int | None = None
        self.rows: dict[str, list[str]] = {}
        self.row_text: dict[str, list[str]] = {}
        self.anchors: list[tuple[str, str, str]] = []
        self._section: str | None = None
        self._parts: list[str] = []
        self._in_h2 = False
        self._h2_parts: list[str] = []
        self._in_toc = False
        self._toc_href: str | None = None
        self._toc_parts: list[str] = []
        self._in_tbody = False
        self._row_first_cell: list[str] | None = None
        self._in_first_cell = False
        self._row_parts: list[str] | None = None
        self._anchor: dict | None = None

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "section" and a.get("id"):
            self._section = a["id"]
            self._parts = []
            self.order.append(a["id"])
            self.rows.setdefault(a["id"], [])
            self.row_text.setdefault(a["id"], [])
        elif tag == "nav" and "toc" in (a.get("class") or ""):
            self._in_toc = True
            self.toc_position = len(self.order)
        elif tag == "a" and self._in_toc and (a.get("href") or "").startswith("#"):
            self._toc_href = a["href"][1:]
            self._toc_parts = []
        if tag == "h2" and self._section:
            self._in_h2 = True
            self._h2_parts = []
        if tag == "tbody" and self._section:
            self._in_tbody = True
        if tag == "tr" and self._in_tbody:
            self._row_first_cell = None
            self._row_parts = []
        if tag in ("td", "th") and self._in_tbody and self._row_first_cell is None:
            self._row_first_cell = []
            self._in_first_cell = True
        if a.get("data-cost-key") and self._section:
            self._anchor = {"key": a["data-cost-key"], "parts": [], "tag": tag}

    def handle_endtag(self, tag):
        if tag == "section" and self._section:
            self.sections[self._section] = " ".join("".join(self._parts).split())
            self._section = None
        elif tag == "nav":
            self._in_toc = False
        elif tag == "a" and self._toc_href is not None:
            self.toc_labels[self._toc_href] = " ".join("".join(self._toc_parts).split())
            self._toc_href = None
        if tag == "h2" and self._in_h2:
            self._in_h2 = False
            self.h2[self._section or ""] = " ".join("".join(self._h2_parts).split())
        if tag in ("td", "th") and self._in_first_cell:
            self._in_first_cell = False
        if tag == "tr" and self._in_tbody and self._row_first_cell is not None and self._section:
            self.rows[self._section].append(" ".join("".join(self._row_first_cell).split()))
            self.row_text[self._section].append(" ".join("".join(self._row_parts or []).split()))
            self._row_first_cell = None
            self._row_parts = None
        if tag == "tbody":
            self._in_tbody = False
        if self._anchor and tag == self._anchor["tag"]:
            self.anchors.append((self._section or "", self._anchor["key"], "".join(self._anchor["parts"])))
            self._anchor = None

    def handle_data(self, data):
        if self._section:
            self._parts.append(data)
        if self._in_h2:
            self._h2_parts.append(data)
        if self._toc_href is not None:
            self._toc_parts.append(data)
        if self._in_first_cell and self._row_first_cell is not None:
            self._row_first_cell.append(data)
        if self._row_parts is not None:
            self._row_parts.append(" " + data)
        if self._anchor:
            self._anchor["parts"].append(data)


def money(text: str) -> int | None:
    m = re.search(r"\$\s*([0-9][0-9,]*)(?:\.[0-9]+)?", text)
    return int(m.group(1).replace(",", "")) if m else None


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__)
        return 2
    run = Path(sys.argv[1]).resolve()
    report = run / "migration-report.html"
    estimate_path = run / "estimation-infra.json"
    design_path = run / "aws-design.json"
    prefs_path = run / "preferences.json"
    check(report.exists(), "missing migration-report.html")
    check(estimate_path.exists(), "missing estimation-infra.json")
    check(design_path.exists(), "missing aws-design.json")
    check(prefs_path.exists(), "missing preferences.json")
    if FAILS:
        return _finish()

    # 1. The two-command gate heroku-to-aws runs after Generate. REPORT_OK from both or nothing.
    shared = subprocess.run(  # nosec B603 — list args, no shell, committed script path only
        [sys.executable, str(VALIDATOR_SHARED), str(report), "--profile", "heroku",
         "--mode", "full", "--estimation-infra", str(estimate_path), "--migration-dir", str(run)],
        capture_output=True, text=True, check=False,
    )
    check(
        shared.returncode == 0 and shared.stdout.startswith("REPORT_OK"),
        "migration-report.html fails the shared validator --profile heroku --mode full:\n"
        f"{shared.stdout}{shared.stderr}",
    )
    addon = subprocess.run(  # nosec B603 — list args, no shell, committed script path only
        [sys.executable, str(VALIDATOR_ADDON), str(report), "--mode", "full", "--migration-dir", str(run)],
        capture_output=True, text=True, check=False,
    )
    check(
        addon.returncode == 0 and addon.stdout.startswith("REPORT_OK"),
        f"migration-report.html fails the heroku add-on --mode full:\n{addon.stdout}{addon.stderr}",
    )

    html = report.read_text(encoding="utf-8")
    est = json.loads(estimate_path.read_text(encoding="utf-8"))
    design = json.loads(design_path.read_text(encoding="utf-8"))
    prefs = json.loads(prefs_path.read_text(encoding="utf-8"))
    p = _Sections()
    p.feed(html)
    p.close()

    # 2. Required IDs: present once each, in the skeleton's order; the TOC sits after
    #    decision-summary; appendix-glossary is the final section.
    for sid in REQUIRED_IDS_IN_ORDER:
        n = p.order.count(sid)
        check(n == 1, f"section {sid} occurs {n} time(s), expected exactly 1")
    present = [sid for sid in p.order if sid in REQUIRED_IDS_IN_ORDER]
    check(present == REQUIRED_IDS_IN_ORDER,
          f"required sections are out of document order: {present}")
    check(p.toc_position == 1 and p.order[:1] == ["decision-summary"],
          "decision-summary must be the only section before <nav class=\"toc\">")
    check(p.order and p.order[-1] == "appendix-glossary",
          f"appendix-glossary must be the final section (last is {p.order[-1] if p.order else None!r})")
    for sid in ABSENT_SECTIONS:
        check(sid not in p.order, f"section {sid} must not be rendered (declared omission or retired ID)")

    # 3. Stable lettering in both the <h2> and the TOC label.
    for sid, letter in APPENDIX_LETTERING.items():
        check(p.h2.get(sid, "").startswith(letter),
              f"{sid} <h2> is {p.h2.get(sid)!r}, expected it to start with {letter!r}")
        check(p.toc_labels.get(sid, "").startswith(letter),
              f"{sid} TOC label is {p.toc_labels.get(sid)!r}, expected it to start with {letter!r}")
    for sid in REQUIRED_IDS_IN_ORDER:
        check(sid in p.toc_labels, f"TOC has no link to #{sid}")

    # 4. Appendix B.1: exactly the two Savings Plan rows the estimate carries.
    opportunities = est.get("optimization_opportunities") or []
    check(len(opportunities) == 2, f"estimate carries {len(opportunities)} optimization_opportunities, expected 2")
    b1_rows = p.rows.get("appendix-optimization", [])
    check(len(b1_rows) == 2, f"appendix-optimization has {len(b1_rows)} data rows, expected 2: {b1_rows}")
    check(all("Savings Plan" in cell for cell in b1_rows),
          f"every appendix-optimization Optimization cell must name a Savings Plan: {b1_rows}")
    for item in opportunities:
        name = item.get("opportunity", "")
        check(any(name in cell for cell in b1_rows), f"appendix-optimization has no row for {name!r}")

    # 4a. Database Savings Plan Generation 7+ gate (commitment-discount-ranges.json
    #     generation_gate): a pre-Generation-7 RDS class gets no dollar saving anywhere.
    rds_classes = [
        (s.get("aws_config") or {}).get("instance_class")
        for s in design.get("services", [])
        if (s.get("aws_config") or {}).get("instance_class", "").startswith("db.")
    ]
    check(rds_classes == ["db.t4g.medium"], f"design RDS instance class is {rds_classes}, expected ['db.t4g.medium']")
    db_rows = [r for r in est.get("optimization_opportunities") or [] if r.get("type") == "database_savings_plan"]
    check(len(db_rows) == 1 and db_rows[0].get("savings_monthly") is None,
          "estimate's Database Savings Plans row must carry savings_monthly null for a pre-Generation-7 class")
    for sid in ("appendix-optimization", "exec-optimization"):
        for row in p.row_text.get(sid, []):
            if "Database Savings Plan" in row:
                check(money(row.replace("$210", "")) is None,
                      f"{sid} attaches a dollar saving to a Database Savings Plan on {rds_classes}: {row!r}")
                check("Generation 7" in row, f"{sid} Database Savings Plan row must name the Generation 7+ gate: {row!r}")
    pc = est.get("projected_costs", {})
    check(pc.get("aws_monthly_optimized") == 182.0 and pc.get("aws_monthly_balanced") == 210.0,
          f"Optimized must be Balanced 210 minus the Compute SP 28 = 182, got {pc.get('aws_monthly_optimized')}")
    check(pc.get("aws_annual_optimized") == 2184.0, f"aws_annual_optimized must be 2184, got {pc.get('aws_annual_optimized')}")
    check("Generation 7" in pc.get("_optimized_basis", "") and "db.t4g.medium" in pc.get("_optimized_basis", ""),
          "_optimized_basis must name the Generation 7+ gate and the db.t4g.medium class")
    check("Est. $182/mo" in p.sections.get("exec-costs", "") and "Est. $182/mo" in p.sections.get("appendix-costs", ""),
          "exec-costs and appendix-costs must render Optimized as Est. $182/mo")
    check("$163" not in html, "report still carries the pre-gate Optimized figure $163")

    # 4b. Migration shape from preferences.json, the verdict callout, the pipeline count.
    check(prefs.get("global", {}).get("migration_approach") == "full_cutover",
          "preferences.json global.migration_approach is not full_cutover")
    for sid in ("decision-summary", "exec-share", "exec-timeline"):
        text = p.sections.get(sid, "")
        check("Full cutover" in text or "full cutover" in text, f"{sid} must state the Full cutover shape")
        check("hased" not in text, f"{sid} describes a phased migration but migration_approach is full_cutover")
    summary_html = re.search(r'<section id="decision-summary".*?</section>', html, re.S)
    check(summary_html is not None and re.search(r'<div class="verdict(?:\s[^"]*)?">', summary_html.group(0)) is not None,
          'decision-summary has no <div class="verdict"> recommendation callout')
    check("0 pipelines covering 0 apps" in p.sections.get("developer-workflow", ""),
          "Pipelines and promote cell must read '0 pipelines covering 0 apps' (no pipeline in the inventory)")

    # 5. exec-optimization and exec-costs content the spec fixes for this estate.
    exec_opt = p.sections.get("exec-optimization", "")
    check("Optimized" in exec_opt, "exec-optimization must name the Optimized tier")
    check("Balanced" in exec_opt, "exec-optimization must name the Balanced on-demand baseline")
    check(NON_STACK_RE.search(exec_opt) is not None,
          "exec-optimization must say Savings Plan savings are not additive to the Optimized tier")
    check(PREMIUM_SENTENCE in p.sections.get("exec-costs", ""),
          f"exec-costs must explain the identical tier figures with {PREMIUM_SENTENCE!r}")

    # 6. developer-workflow renders every row of the generate-report.md table.
    dw_rows = p.rows.get("developer-workflow", [])
    check(len(dw_rows) == DEVELOPER_WORKFLOW_ROWS,
          f"developer-workflow has {len(dw_rows)} data rows, expected {DEVELOPER_WORKFLOW_ROWS}")

    # 7. No bare week range in the body (durations are uncalibrated).
    body = re.sub(r"<style\b.*?</style>", "", html, flags=re.DOTALL | re.IGNORECASE)
    check(WEEK_RANGE_RE.search(body) is None, "report quotes a bare week range")

    # 8. The Balanced anchor inside exec-costs equals the estimate.
    expected = est.get("projected_costs", {}).get("aws_monthly_balanced")
    anchors = {k: t for s, k, t in p.anchors if s == "exec-costs"}
    check("aws_monthly_balanced" in anchors, 'no data-cost-key="aws_monthly_balanced" anchor inside exec-costs')
    if expected is not None and "aws_monthly_balanced" in anchors:
        rendered = money(anchors["aws_monthly_balanced"])
        check(rendered == round(float(expected)),
              f"aws_monthly_balanced renders {anchors['aws_monthly_balanced']!r} but "
              f"projected_costs.aws_monthly_balanced = {expected}")

    # 9. Default parity: exec-assumptions and Appendix F flag the SAME defaulted answers
    # (both tables mark a defaulted row with class="assumption-default"). A default
    # surfaced in one table but not the other is how the pass-1 Q12 gap slipped through.
    def _default_rows(section_id: str) -> int:
        m = re.search(rf'<section id="{section_id}".*?</section>', html, re.S)
        return len(re.findall(r'<tr[^>]*class="assumption-default"', m.group(0))) if m else -1

    ea, ac = _default_rows("exec-assumptions"), _default_rows("appendix-config")
    check(ea > 0, "exec-assumptions flags no assumption-default rows")
    check(ea == ac, f"exec-assumptions flags {ea} defaulted answers but appendix-config flags {ac}")

    return _finish()


def _finish() -> int:
    if FAILS:
        print(f"FAIL — {len(FAILS)} problem(s)")
        for f in FAILS:
            print(" -", f)
        return 1
    print("PASS — migration-report.html passes both validators (--profile heroku --mode full, "
          "heroku add-on) and the full-mode pins (section order, lettering A/B/B.1/E/F/G/I/J, "
          "two Savings Plan rows, Database Savings Plan generation gate, Full cutover shape, verdict "
          "callout, not-additive caveat, Premium equals Balanced, ten workflow rows, no week range, "
          "Balanced anchor)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
