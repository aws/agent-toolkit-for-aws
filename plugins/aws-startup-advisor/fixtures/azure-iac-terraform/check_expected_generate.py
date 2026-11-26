#!/usr/bin/env python3
"""Assert the azure-to-aws GENERATE report (migration-report.html) over the azure-iac-terraform corpus.

Sibling of check_expected_estimate.py. The report's structural contract — required section
IDs, TOC integrity, the CSS readability shell, currency formatting, decision-core content —
is owned by scripts/validate-migration-report.py, so step one here is to RUN that validator
with the corpus's own estimate and design and require REPORT_OK. The rest pins what the
validator either resolves from the estimate or does not know about, and where a plausible
improvisation diverges from the spec:

  * the two REQUIRED cost anchors (`aws_monthly_balanced`, `current_monthly`) sit inside
    exec-costs and equal the estimate. `current_monthly` resolves from
    current_costs.azure_monthly for this skill; before the validator carried that fallback,
    an Azure report's current-spend figure was never asserted at all;
  * the stable appendix lettering from generate-artifacts-report.md Step 3.75, in BOTH the
    <h2> and the TOC — this infra-only run has no Appendix D, and the letters after it must
    not slide;
  * Appendices C, G, H and I exist with the content Step 3.8 requires — these four had no
    build instructions in the Azure spec before, so a report could pass the validator while
    the Step 3.75 table promised sections it never emitted;
  * the Step 3.5 accounting split (30 discovered · 16 mapped · 17 accounted) is stated
    verbatim, so the discovered count and the plan headline are not conflated;
  * the not-comparable chip on the stated Azure baseline, no savings-percentage headline, the
    specialist callout for the deferred IoT Hub, and cluster rationale leading the body.

Usage:
    python3 check_expected_generate.py <migration_run_dir>

<migration_run_dir> holds migration-report.html. The estimate and design it is checked
against are the corpus goldens (after-estimate/, after-design/) unless the run dir carries
its own estimation-infra.json / aws-design.json. Exits 0 on PASS, 1 on FAIL. Stdlib only;
the validator is invoked as a subprocess so this script never imports (and never writes
bytecode for) a sibling module.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from html.parser import HTMLParser
from pathlib import Path

HERE = Path(__file__).resolve().parent
FAILS: list[str] = []


def check(cond: bool, msg: str) -> None:
    if not cond:
        FAILS.append(msg)


def load_json(path: Path) -> dict:
    if not path.exists():
        FAILS.append(f"missing {path}")
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        FAILS.append(f"{path.name} is not valid JSON: {e}")
        return {}


def dig(d: dict, path: list[str]):
    cur = d
    for key in path:
        if not isinstance(cur, dict) or key not in cur:
            return None
        cur = cur[key]
    return cur


class _Sections(HTMLParser):
    """Collect each <section id=...>'s raw inner text, its <h2> text, and every
    data-cost-key anchor's rendered text (in document order, tagged by section)."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.sections: dict[str, str] = {}
        self.h2: dict[str, str] = {}
        self.anchors: list[tuple[str, str, str]] = []  # (section, key, text)
        self.order: list[str] = []
        self.toc_labels: dict[str, str] = {}
        self._section: str | None = None
        self._parts: list[str] = []
        self._in_h2 = False
        self._h2_parts: list[str] = []
        self._anchor: dict | None = None
        self._in_toc = False
        self._toc_href: str | None = None
        self._toc_parts: list[str] = []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "section" and a.get("id"):
            self._section = a["id"]
            self._parts = []
            self.order.append(a["id"])
        elif tag == "nav" and "toc" in (a.get("class") or ""):
            self._in_toc = True
        elif tag == "a" and self._in_toc and (a.get("href") or "").startswith("#"):
            self._toc_href = a["href"][1:]
            self._toc_parts = []
        if tag == "h2" and self._section:
            self._in_h2 = True
            self._h2_parts = []
        if a.get("data-cost-key") and self._section:
            self._anchor = {"key": a["data-cost-key"], "parts": [], "tag": tag}

    def handle_endtag(self, tag):
        if tag == "section" and self._section:
            self.sections[self._section] = "".join(self._parts)
            self._section = None
        elif tag == "nav":
            self._in_toc = False
        elif tag == "a" and self._toc_href is not None:
            self.toc_labels[self._toc_href] = " ".join("".join(self._toc_parts).split())
            self._toc_href = None
        if tag == "h2" and self._in_h2:
            self._in_h2 = False
            self.h2[self._section or ""] = " ".join("".join(self._h2_parts).split())
        if self._anchor and tag == self._anchor["tag"]:
            self.anchors.append((self._section or "", self._anchor["key"], "".join(self._anchor["parts"])))
            self._anchor = None

    def handle_data(self, data):
        if self._section:
            self._parts.append(data)
        if self._in_h2:
            self._h2_parts.append(data)
        if self._anchor:
            self._anchor["parts"].append(data)
        if self._toc_href is not None:
            self._toc_parts.append(data)


def money(text: str) -> int | None:
    m = re.search(r"\$\s*([0-9][0-9,]*)(?:\.[0-9]+)?", text)
    return int(m.group(1).replace(",", "")) if m else None


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__)
        return 2
    run_dir = Path(sys.argv[1]).resolve()
    exp = load_json(HERE / "expected-generate.json")
    if not exp:
        return _finish()

    report = run_dir / exp["report_file"]
    if not report.exists():
        FAILS.append(f"missing {report}")
        return _finish()
    estimation = run_dir / "estimation-infra.json"
    if not estimation.exists():
        estimation = HERE / exp["estimation_relpath"]
    design = run_dir / "aws-design.json"
    if not design.exists():
        design = HERE / exp["design_relpath"]
    validator = (HERE / exp["validator_relpath"]).resolve()

    # 1. The shared validator owns the structural contract. REPORT_OK or nothing.
    proc = subprocess.run(  # nosec B603 — list args, committed script path, no shell
        [sys.executable, str(validator), str(report), "--estimation-infra", str(estimation),
         "--aws-design", str(design), "--migration-dir", str(run_dir)],
        capture_output=True, text=True, check=False,
    )
    check(proc.returncode == 0,
          f"validate-migration-report.py exited {proc.returncode}:\n{proc.stdout}{proc.stderr}")

    html = report.read_text(encoding="utf-8")
    est = load_json(estimation)
    p = _Sections()
    p.feed(html)
    p.close()

    # 2. Both required cost anchors, inside exec-costs, equal to the estimate.
    exec_costs_anchors = {k: t for s, k, t in p.anchors if s == "exec-costs"}
    for key, spec in exp["cost_anchors"].items():
        if key.startswith("_"):
            continue
        expected = dig(est, spec["path"])
        check(expected is not None, f"estimate has no {'.'.join(spec['path'])} to anchor {key} against")
        check(key in exec_costs_anchors, f'no data-cost-key="{key}" anchor inside exec-costs')
        if expected is not None and key in exec_costs_anchors:
            rendered = money(exec_costs_anchors[key])
            check(rendered == round(float(expected)),
                  f'{key} renders {exec_costs_anchors[key]!r} but {".".join(spec["path"])} = {expected}')

    # 3. Stable lettering in both the <h2> and the TOC label.
    for sid, letter in exp["appendix_lettering"].items():
        if sid.startswith("_"):
            continue
        check(sid in p.sections, f"section {sid} is absent")
        check(p.h2.get(sid, "").startswith(letter + " "),
              f"{sid} <h2> is {p.h2.get(sid)!r}, expected it to start with {letter!r}")
        check(p.toc_labels.get(sid, "").startswith(letter + " "),
              f"{sid} TOC label is {p.toc_labels.get(sid)!r}, expected it to start with {letter!r}")
    for sid in exp["absent_sections"]:
        check(sid not in p.sections, f"{sid} should be absent on this infra-only run (no AI track, no scenarios)")
    if "appendix-artifacts" in p.order and "appendix-config" in p.order:
        check(p.order.index("appendix-artifacts") < p.order.index("appendix-config"),
              "appendix-artifacts must render before appendix-config")

    # 4. Appendices C, G, H, I carry the Step 3.8 content.
    for sid, spec in exp["required_appendices"].items():
        if sid.startswith("_"):
            continue
        body = p.sections.get(sid)
        if body is None:
            check(False, f"required appendix {sid} is absent")
            continue
        for phrase in spec.get("must_mention", []):
            check(phrase.lower() in body.lower(), f"{sid} does not mention {phrase!r}")
        if "min_phases" in spec:
            phases = len(re.findall(r"Phase\s+\d", body))
            check(phases >= spec["min_phases"], f"{sid} has {phases} 'Phase N' headings, need >= {spec['min_phases']}")

    # 5. Accounting split stated verbatim; discovered != accounted.
    acc = exp["accounting"]
    flat = " ".join(" ".join(p.sections.values()).split())  # decoded text, entities resolved
    check(acc["split_phrase"] in flat, f"accounting split {acc['split_phrase']!r} not stated in the report")
    check(acc["mapped"] + acc["deferred"] != acc["discovered"],
          "fixture self-check: the split only tests something when discovered != accounted")

    # 6. Decision-core facts the validator does not pin for Azure.
    dc = exp["decision_core"]
    summary = p.sections.get("decision-summary", "")
    check(dc["verdict_headline"] in summary, f"verdict headline {dc['verdict_headline']!r} missing from decision-summary")
    check(dc["specialist_callout_phrase"] in summary.lower() and dc["deferred_resource_phrase"] in summary,
          "decision-summary lacks the specialist-engagement callout naming the deferred IoT Hub")
    check(re.search(r'class="[^"]*\b' + re.escape(dc["not_comparable_chip_class"]) + r'\b', html) is not None,
          f"stated Azure baseline carries no {dc['not_comparable_chip_class']} not-comparable chip")
    check(re.search(dc["forbidden_savings_headline_regex"], flat, re.I) is None,
          "report prints the non-credible 89% saving as a headline figure")
    order = p.order
    if dc["cluster_rationale_section"] in order and dc["per_resource_table_section"] in order:
        check(order.index(dc["cluster_rationale_section"]) < order.index(dc["per_resource_table_section"]),
              "cluster-level rationale must lead; the per-resource table belongs in the appendix")
    check(exp["fixture_canary_must_be_absent"] not in html,
          f"GCP reference-fixture canary {exp['fixture_canary_must_be_absent']} appears in the Azure report")

    return _finish()


def _finish() -> int:
    if FAILS:
        print(f"FAIL — {len(FAILS)} problem(s)")
        for f in FAILS:
            print(" -", f)
        return 1
    print("PASS — migration-report.html matches expected-generate.json (validator REPORT_OK, "
          "anchors, lettering, appendices C/G/H/I, accounting split)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
