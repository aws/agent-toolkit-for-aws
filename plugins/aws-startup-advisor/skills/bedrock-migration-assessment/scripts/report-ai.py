#!/usr/bin/env python3
"""Plan, write and check migration-report.html for a standalone bedrock-migration-assessment run, rendered only from checked artifacts."""
from __future__ import annotations

import argparse
import hashlib
import html
import importlib.util
import json
import os
import re
import sys
import tempfile
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent


def _load(name: str, file: str):
    spec = importlib.util.spec_from_file_location(name, HERE / file)
    module = importlib.util.module_from_spec(spec)
    written = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        spec.loader.exec_module(module)
    finally:
        sys.dont_write_bytecode = written
    return module


readiness = _load("bma_report_readiness", "readiness.py")

REPORT = "migration-report.html"
USAGE_FILES = ("openai-usage-profile.json", "anthropic-usage-profile.json", "openrouter-usage-profile.json")
# The plugin's AI-only report section ids (scripts/validate-migration-report.py) plus exec-share and exec-optimization.
SECTIONS = ("decision-summary", "exec-share", "exec-assumptions", "exec-optimization", "exec-risks",
            "appendix-ai", "appendix-artifacts", "appendix-config", "appendix-glossary")
TITLES = {"decision-summary": "Recommendation", "exec-share": "Leadership brief", "exec-assumptions": "Assumptions",
          "exec-optimization": "Cost optimization", "exec-risks": "Risks", "appendix-ai": "Models and workloads",
          "appendix-artifacts": "Artifacts", "appendix-config": "Your answers", "appendix-glossary": "Glossary"}
DIGEST_META = re.compile(r'<meta name="bma-report-digest" content="([0-9a-f]*)">')
SECTION_OPEN = re.compile(r"<section\b[^>]*\bid=([\"'])([^\"']+)\1", re.I)
TOC_HREF = re.compile(r'<nav class="toc"[^>]*>(.*?)</nav>', re.S)
SOURCES = {"user": "Your answer", "derived": "Derived from your answers", "default": "Default", "extracted": "Found in your code"}
# The target_aws_service enum in references/contracts/aws-design-ai.schema.json.
AWS_SERVICES = {"textract": "Amazon Textract", "rekognition": "Amazon Rekognition", "transcribe": "Amazon Transcribe",
                "comprehend": "Amazon Comprehend", "translate": "Amazon Translate", "polly": "Amazon Polly", "sagemaker": "Amazon SageMaker AI"}
SECTION_INPUTS = {"decision-summary": "estimation-ai.json, preferences.json or generation-ai.json", "exec-share": "estimation-ai.json or aws-design-ai.json",
                  "exec-assumptions": "estimation-ai.json or preferences.json", "exec-optimization": "estimation-ai.json",
                  "exec-risks": "aws-design-ai.json or generation-ai.json", "appendix-ai": "aws-design-ai.json or estimation-ai.json",
                  "appendix-artifacts": "generation-ai.json", "appendix-config": "preferences.json", "appendix-glossary": "no artifact"}
GLOSSARY = (("Amazon Bedrock", "The AWS service that runs foundation models through one API, billed per token."),
            ("Inference profile", "A Bedrock model id with a Geo or global prefix (for example us.) that routes requests across Regions."),
            ("Converse", "The Bedrock API that sends the same request shape to every chat model."),
            ("bedrock-mantle", "The Bedrock endpoint that serves the OpenAI and Anthropic APIs with provider-run tools."),
            ("Volume band", "The monthly token range you chose when usage was not measured; figures for it are a low and a high bound."),
            ("Price unavailable", "AWS has not published a rate for that model or Region, so no figure that depends on it is shown."))
CSS = """body { background: #f6f8fa; color: #1f2328; font: 16px/1.5 system-ui, sans-serif; margin: 0; }
.report { max-width: 960px; margin: 0 auto; padding: 24px; }
section { background: #ffffff; border: 1px solid #d0d7de; border-radius: 8px; padding: 16px 20px; margin: 16px 0; }
.metrics { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 12px; }
.metric { border: 1px solid #d0d7de; border-radius: 8px; padding: 12px; }
.metric .label { display: block; color: #59636e; font-size: 14px; }
.metric .value { display: block; font-size: 22px; font-weight: 600; }
.verdict { background: #ddf4ff; border: 1px solid #54aeff; border-radius: 8px; padding: 12px 16px; }
.savings { color: #1a7f37; }
.share-card { border-left: 4px solid #54aeff; padding-left: 12px; }
.appendix-header { border-top: 2px solid #d0d7de; margin-top: 32px; padding-top: 8px; }
table { border-collapse: collapse; width: 100%; font-size: 14px; }
caption { text-align: left; font-weight: 600; padding: 4px 0; }
th, td { border: 1px solid #d0d7de; padding: 6px 8px; text-align: left; vertical-align: top; }
code { overflow-wrap: anywhere; }
:focus-visible { outline: 2px solid #0969da; outline-offset: 2px; }
@media (max-width: 700px) { .report { padding: 12px; } table { font-size: 12px; } }
@media print { body { background: #ffffff; } section { break-inside: avoid; } nav.toc { display: none; } }"""


class ReportError(Exception):
    def __init__(self, code: str, detail: str) -> None:
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (list, tuple)):
        return ", ".join(str(v) for v in value)
    if isinstance(value, dict):
        return json.dumps(value, sort_keys=True, ensure_ascii=False)
    return str(value)


def e(value: Any) -> str:
    return html.escape(_text(value), quote=True)


def _num(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def money(value: Any) -> str:
    if not _num(value):
        return "Price unavailable"
    if abs(value) >= 1.995:
        return f"${int(Decimal(f'{value:.2f}').quantize(Decimal(1), ROUND_HALF_UP)):,}"
    return f"${value:.2f}"


def money_range(low: Any, high: Any) -> str:
    if not _num(low):
        return "Price unavailable"
    if not _num(high):
        return f"from {money(low)}"
    return money(low) if money(low) == money(high) else f"{money(low)} to {money(high)}"


def cost_cell(value: Any) -> str:
    if isinstance(value, dict):
        return money_range(value.get("low"), value.get("high"))
    return money(value)


def signed(value: float) -> str:
    return ("+" if value >= 0 else "-") + money(abs(value))


def _table(caption: str, headers: list[str], rows: list[list[str]]) -> str:
    head = "".join(f'<th scope="col">{e(h)}</th>' for h in headers)
    body = "".join("<tr>" + "".join(f"<td>{c}</td>" for c in row) + "</tr>" for row in rows)
    return f"<table><caption>{e(caption)}</caption><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"


def _ul(items: list[str], cls: str = "") -> str:
    attr = f' class="{cls}"' if cls else ""
    return f"<ul{attr}>" + "".join(f"<li>{i}</li>" for i in items) + "</ul>"


def _ol(items: list[str]) -> str:
    return '<ol class="compact">' + "".join(f"<li>{i}</li>" for i in items) + "</ol>"


def _section(sid: str, body: str) -> str:
    return f'<section id="{sid}">\n<h2>{e(TITLES[sid])}</h2>\n{body}\n</section>'


def _read(run_dir: Path, name: str) -> tuple[Any, bytes]:
    try:
        raw = (run_dir / name).read_bytes()
        return json.loads(raw.decode("utf-8")), raw
    except FileNotFoundError:
        raise ReportError("artifact_missing", f"{name} is not in the run directory")
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ReportError("artifact_unreadable", f"{name}: {exc}")


def gather(run_dir: Path) -> dict:
    """Check the run, then read every input the report renders from, with its SHA-256."""
    try:
        status = readiness._status(run_dir)
        if readiness.is_combined(run_dir, status.get("initiated_by")):
            raise ReportError("combined_run", f"run {status['migration_id']!r} is a host skill's run; the host skill writes its report")
        generated = status["phases"].get("generate") == "completed"
        ready = readiness.check(run_dir, "generate" if generated else "estimate")
    except readiness.NotReady as exc:
        raise ReportError(exc.reason, exc.detail)
    inputs = {name: a["sha256"] for name, a in ready["artifacts"].items()}
    data = {}
    for name in ("ai-workload-profile.json", "preferences.json", "aws-design-ai.json", "estimation-ai.json") + \
            (("generation-ai.json",) if generated else ()):
        data[name], raw = _read(run_dir, name)
        if hashlib.sha256(raw).hexdigest() != inputs[name]:
            raise ReportError("artifact_changed", f"{name} changed while the report was being rendered; run the command again")
    for name in USAGE_FILES:
        if (run_dir / name).is_file():
            try:
                inputs[name] = hashlib.sha256((run_dir / name).read_bytes()).hexdigest()
            except OSError as exc:
                raise ReportError("artifact_unreadable", f"{name}: {exc}")
    return {"migration_id": status["migration_id"], "generated": generated, "data": data,
            "inputs": dict(sorted(inputs.items(), key=lambda kv: ("/" in kv[0], kv[0])))}


def _current(est: dict) -> tuple[str, str]:
    cc, roi = est["cost_comparison"], est["roi_analysis"]
    if _num(cc.get("current_source_monthly")):
        how = "measured spend" if est["current_costs"].get("source") == "measured_usage" else "at list price"
        return money(cc["current_source_monthly"]), how
    src = roi.get("source_list_monthly_range") or {}
    if _num(src.get("low")):
        return money_range(src.get("low"), src.get("high")), "at list price for your volume band"
    return "Unknown", "no measured spend or list price"


def _projected(est: dict) -> str:
    point = est["cost_comparison"].get("projected_bedrock_monthly")
    if _num(point):
        return money(point)
    rng = est["roi_analysis"].get("projected_bedrock_monthly_range") or {}
    return money_range(rng.get("low"), rng.get("high"))


def _region(prefs: dict) -> str | None:
    wrapper = (prefs.get("design_constraints") or {}).get("target_region")
    return wrapper.get("value") if isinstance(wrapper, dict) else None


def render_decision(ctx: dict) -> str:
    est, gen = ctx["data"]["estimation-ai.json"], ctx["data"].get("generation-ai.json")
    rec = est["recommendation"]
    current, how = _current(est)
    cc = est["cost_comparison"]
    if _num(cc.get("monthly_difference")):
        pct = f" ({cc['percent_change']:+.0f}%)" if _num(cc.get("percent_change")) else ""
        diff, diff_note = signed(cc["monthly_difference"]) + pct, "Bedrock minus current, a month"
    else:
        diff, diff_note = "Not computed", "needs a single current and a single Bedrock figure"
    metrics = [("Current monthly cost", current, how), ("Estimated Bedrock monthly cost", _projected(est), est["accuracy_confidence"]),
               ("Monthly difference", diff, diff_note), ("Recommended model", est["recommended_model"].get("model"), rec.get("confidence") and f"{rec['confidence']} confidence")]
    cards = "".join(f'<div class="metric"><span class="label">{e(a)}</span><span class="value">{e(b)}</span>'
                    f'<span class="label">{e(c)}</span></div>' for a, b, c in metrics)
    region = _region(ctx["data"]["preferences.json"])
    if gen is not None:
        steps = ["Review the files in the ai-migration folder; your code was not changed.",
                 "Run the setup script in dry-run mode, then attach the IAM policy to your application role.",
                 "Run the comparison harness with representative prompts before you move any traffic.",
                 f"Move traffic with the {e(gen['rollback_plan'].get('flag_name'))} flag one service at a time."]
    else:
        steps = ["Resume this run with bedrock-migration-assessment and ask it to generate the migration artifacts.",
                 f"Confirm Bedrock model access for {e(est['recommended_model'].get('model'))}" + (f" in {e(region)}." if region else "."),
                 "Check the Bedrock quotas for each recommended model before you plan a cutover."]
    return _section("decision-summary", f'<div class="verdict"><p><strong>{e(rec["path_label"])}.</strong> {e(rec["rationale"])}</p></div>\n'
                    f'<div class="metrics">{cards}</div>\n<h3>Migrate if</h3><p>{e(rec["migrate_if"])}</p>\n'
                    f'<h3>Stay entirely if</h3><p>{e(rec["stay_if"])}</p>\n<h3>Next steps</h3>{_ol(steps)}')


def _and(items: list[str]) -> str:
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " and " + items[-1]


def _elsewhere(skipped: list[dict]) -> str:
    by_service: dict[str, list[str]] = {}
    for s in skipped:
        by_service.setdefault(s["target_aws_service"], []).append(f"<code>{e(s['workload_id'])}</code>")
    parts = [f"{_and(ids)} {'goes' if len(ids) == 1 else 'go'} to {e(AWS_SERVICES.get(svc, svc))}" for svc, ids in by_service.items()]
    its = "its" if len(skipped) == 1 else "their"
    return f" {_and(parts)}; {its} cost and setup are outside this estimate."


def render_share(ctx: dict) -> str:
    est, design = ctx["data"]["estimation-ai.json"], ctx["data"]["aws-design-ai.json"]
    rec = est["recommendation"]
    current, how = _current(est)
    on_bedrock = [b for b in design["design_blocks"] if b.get("target_bedrock_model")]
    sources = sorted({b["model_id"] for b in on_bedrock})
    one = len(on_bedrock) == 1
    text = (f"Draft estimate for {len(on_bedrock)} AI workload{'' if one else 's'} that use{'s' if one else ''} {e(sources)}: "
            f"running {'it' if one else 'them'} on Amazon Bedrock "
            f"with {e(est['recommended_model'].get('model'))} as the main model is estimated at {e(_projected(est))} a month, "
            f"against {e(current)} today ({e(how)}). The recommendation is {e(rec['path_label'])}, with {e(rec['confidence'])} confidence, "
            f"and every figure is an estimate to confirm before any commitment.")
    skipped = est.get("services_not_estimated") or []
    return _section("exec-share", f'<div class="share-card"><p>{text}{_elsewhere(skipped) if skipped else ""}</p></div>')


def render_assumptions(ctx: dict) -> str:
    est, prefs = ctx["data"]["estimation-ai.json"], ctx["data"]["preferences.json"]
    tv = est["token_volume"]
    if tv.get("basis") == "measured":
        volume = (f"Volume is measured: {tv.get('monthly_input_tokens', 0):,} input and {tv.get('monthly_output_tokens', 0):,} "
                  "output tokens a month.")
    else:
        high = f"{tv['max_tokens']:,}" if _num(tv.get("max_tokens")) else "no upper bound"
        volume = (f"Volume is the {e(tv.get('tier'))} band you chose: {tv.get('min_tokens', 0):,} to {high} tokens a month, "
                  f"{round(tv.get('input_share', 0) * 100)}% of them input. Costs show both bounds.")
    pricing = ("Bedrock prices come from the plugin's cached list prices." if est["pricing_source"] == "cached" else
               "At least one Bedrock price is not published, so totals that depend on it show Price unavailable.")
    items = [volume, pricing, f"Accuracy: {e(est['accuracy_confidence'])}."]
    if _region(prefs):
        items.append(f"Target Region: {e(_region(prefs))}.")
    note = (est.get("migration_cost_considerations") or {}).get("note")
    if note:
        items.append(e(note))
    return _section("exec-assumptions", _ul(items))


def render_optimization(ctx: dict) -> str:
    opps = ctx["data"]["estimation-ai.json"]["optimization_opportunities"]
    rows = [[e(o.get("opportunity")), e(o.get("target_services")), e(o.get("commitment")), e(o.get("implementation_effort")),
             f'<span class="savings">{e(money(o["potential_savings_monthly"]) if _num(o.get("potential_savings_monthly")) else o.get("potential_savings_percent"))}</span>',
             e(o.get("available")), e(o.get("description"))] for o in opps]
    return _section("exec-optimization", "<p>Each saving is measured against the Balanced on-demand baseline, the estimated Bedrock "
                    "monthly cost above. The levers overlap, so do not add their savings together.</p>\n"
                    + _table("Cost optimization opportunities", ["Optimization", "Target", "Commitment", "Effort", "Est. savings",
                                                                 "Available", "Description"], rows))


def render_risks(ctx: dict) -> str:
    design, gen = ctx["data"]["aws-design-ai.json"], ctx["data"].get("generation-ai.json")
    risks = [e(r) for r in (gen["recommendation"].get("key_risks") or [])] if gen else []
    for row in design["ai_architecture"]["bedrock_models"]:
        pair = f"{e(row['source_model_id'])} to {e(row['aws_model_id'])}"
        risks += [f"{pair}: {e(gap)}" for gap in row.get("capability_gaps") or []]
        if row.get("model_change"):
            risks.append(f"{pair} is a model change: compare outputs before you move traffic.")
        if row.get("quota_risk") == "high":
            risks.append(f"Quota risk is high for {e(row['aws_model_id'])}: request a quota increase before you move traffic.")
    risks += [e(w) for w in (design.get("regional_warnings") or []) + (design.get("multi_model_warnings") or [])]
    risks = list(dict.fromkeys(risks)) or ["No risk was recorded beyond the confidence of the estimate."]
    return _section("exec-risks", _ul(risks))


def render_ai(ctx: dict) -> str:
    design, est = ctx["data"]["aws-design-ai.json"], ctx["data"]["estimation-ai.json"]
    arch = design["ai_architecture"]
    mapping = [[f"<code>{e(r['source_model_id'])}</code>", f"<code>{e(r['aws_model_id'])}</code>", e(r.get("required_client_api")),
                e(r.get("migration_path")), e(r.get("source_provider_price")), e(r.get("bedrock_price")), e(r.get("honest_assessment"))]
               for r in arch["bedrock_models"]]
    costs = [[f"<code>{e(m.get('model'))}</code>", e(cost_cell(m.get("monthly_cost"))), e(m.get("vs_current") or "Not computed"),
              e(m.get("quality")), e(m.get("missing_capabilities") or "None")] for m in est["model_comparison"]]
    blocks = [[f"<code>{e(b['workload_id'])}</code>", f"<code>{e(b['model_id'])}</code>",
               e(b.get("target_bedrock_model") or b.get("target_aws_service") or "Not migrated"), e(b.get("rationale"))]
              for b in design["design_blocks"]]
    body = [f"<p>Design assessment: {e(arch.get('honest_assessment'))}.</p>",
            _table("Model mapping", ["Source model", "Bedrock model", "Client API", "Endpoint path", "Source price", "Bedrock price",
                                     "Assessment"], mapping),
            _table("Estimated monthly cost by Bedrock model", ["Bedrock model", "Monthly cost", "Compared with now", "Quality",
                                                              "Missing capabilities"], costs),
            _table("Workloads", ["Workload", "Source model", "Target", "Rationale"], blocks)]
    emb = est.get("embeddings")
    if isinstance(emb, dict):
        body.append(f"<p>Embeddings: <code>{e(emb.get('model'))}</code>, {e(money(emb.get('monthly_cost')))} a month. {e(emb.get('note'))}</p>")
    skipped = est.get("services_not_estimated") or []
    if skipped:
        body.append("<p>Not estimated, because they are not priced per token:</p>"
                    + _ul([f"<code>{e(s.get('workload_id'))}</code>: {e(AWS_SERVICES.get(s.get('target_aws_service'), s.get('target_aws_service')))}" for s in skipped]))
    return _section("appendix-ai", "\n".join(body))


def render_artifacts(ctx: dict) -> str:
    gen = ctx["data"].get("generation-ai.json")
    inputs = [[f"<code>{e(name)}</code>", f"<code>{sha}</code>"] for name, sha in ctx["inputs"].items() if "/" not in name]
    body = [f"<p>Run <code>{e(ctx['migration_id'])}</code>. The report was rendered from these files; it is out of date when any of them "
            "changes.</p>", _table("Input artifacts", ["File", "SHA-256"], inputs)]
    if gen is None:
        body.append("<p>No migration artifacts were generated in this run.</p>")
    else:
        plan, rollback = gen["migration_plan"], gen["rollback_plan"]
        files = [[f"<code>{e(name)}</code>", f"<code>{sha}</code>"] for name, sha in ctx["inputs"].items() if "/" in name]
        phases = [f"{e(p.get('name'))}: {e(p.get('activities'))}" for p in sorted(plan.get("phases") or [], key=lambda p: p.get("sequence", 0))]
        body += [f"<p>Approach: {e(gen['recommendation'].get('approach'))}</p>",
                 _table("Generated migration artifacts", ["File", "SHA-256"], files),
                 "<h3>Migration stages</h3>" + _ol(phases),
                 f"<p>Rollback: set <code>{e(rollback.get('flag_name'))}={e(rollback.get('default_value'))}</code>. "
                 f"{e(rollback.get('rollback_time'))}.</p>"]
    return _section("appendix-artifacts", "\n".join(body))


def render_config(ctx: dict) -> str:
    prefs = ctx["data"]["preferences.json"]
    rows = []
    for group in ("design_constraints", "ai_constraints"):
        for key, w in sorted((prefs.get(group) or {}).items()):
            if isinstance(w, dict) and "value" in w:
                rows.append([e(w.get("prompt") or key), e(w["value"]), e(SOURCES.get(w.get("chosen_by"), w.get("chosen_by"))),
                             e(w.get("design_consequence"))])
    return _section("appendix-config", _table("Answers that shaped the design", ["Question", "Your choice", "Source", "Design consequence"], rows))


def render_glossary(ctx: dict) -> str:
    rows = "".join(f"<tr><td>{e(t)}</td><td>{e(m)}</td></tr>" for t, m in GLOSSARY)
    return _section("appendix-glossary", '<table class="glossary-table"><caption>Terms used in this report</caption>'
                    f'<thead><tr><th scope="col">Term</th><th scope="col">Meaning</th></tr></thead><tbody>{rows}</tbody></table>')


RENDERERS = {"decision-summary": render_decision, "exec-share": render_share, "exec-assumptions": render_assumptions,
             "exec-optimization": render_optimization, "exec-risks": render_risks, "appendix-ai": render_ai,
             "appendix-artifacts": render_artifacts, "appendix-config": render_config, "appendix-glossary": render_glossary}


def sections_for(ctx: dict) -> list[str]:
    opps = ctx["data"]["estimation-ai.json"]["optimization_opportunities"]
    return [s for s in SECTIONS if s != "exec-optimization" or opps]


def digest(document: str) -> str:
    return hashlib.sha256(DIGEST_META.sub('<meta name="bma-report-digest" content="">', document, count=1).encode("utf-8")).hexdigest()


def _render_section(sid: str, ctx: dict) -> str:
    try:
        return RENDERERS[sid](ctx)
    except (AttributeError, KeyError, TypeError, ValueError, IndexError) as exc:
        raise ReportError("report_render_failed", f"{sid}: {SECTION_INPUTS[sid]} has a shape the report cannot read "
                                                  f"({type(exc).__name__}: {exc})")


def render(ctx: dict) -> str:
    ids = sections_for(ctx)
    frag = {sid: _render_section(sid, ctx) for sid in ids}
    toc = '<nav class="toc" aria-label="Contents"><h2>Contents</h2>' + _ul([f'<a href="#{sid}">{e(TITLES[sid])}</a>' for sid in ids]) + "</nav>"
    est = ctx["data"]["estimation-ai.json"]
    execs = "\n".join(frag[s] for s in ids if s.startswith("exec-"))
    appendix = "\n".join(frag[s] for s in ids if s.startswith("appendix-"))
    doc = (f'<!DOCTYPE html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n'
           f'<meta name="viewport" content="width=device-width, initial-scale=1">\n'
           f'<meta name="bma-report-run" content="{e(ctx["migration_id"])}">\n<meta name="bma-report-digest" content="">\n'
           f"<title>Amazon Bedrock migration assessment</title>\n<style>\n{CSS}\n</style>\n</head>\n<body>\n<main class=\"report\">\n"
           f"<header><h1>Amazon Bedrock migration assessment</h1><p>Run <code>{e(ctx['migration_id'])}</code>, estimate of "
           f"{e(est.get('timestamp'))}.</p></header>\n{frag['decision-summary']}\n{toc}\n{execs}\n"
           f'<div class="appendix-header"><h2>Technical appendix</h2></div>\n{appendix}\n'
           "<footer><p>This report is a draft for review. Every cost is an estimated monthly figure: Bedrock and source figures use list "
           "prices, and the current cost is measured spend when usage was measured. Confirm them in the AWS Pricing Calculator before "
           "any commitment.</p></footer>\n</main>\n</body>\n</html>\n")
    return doc.replace('<meta name="bma-report-digest" content="">', f'<meta name="bma-report-digest" content="{digest(doc)}">', 1)


def _target(run_dir: Path) -> Path:
    path = run_dir / REPORT
    if path.is_symlink() or (path.exists() and not path.is_file()):
        raise ReportError("report_target_invalid", f"{REPORT} is a symlink or not a regular file; remove it and run write again")
    return path


def existing(run_dir: Path) -> dict | None:
    path = _target(run_dir)
    try:
        raw = path.read_bytes()
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise ReportError("report_unreadable", f"{REPORT}: {exc}")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        text = None
    meta = DIGEST_META.search(text) if text is not None else None
    return {"sha256": hashlib.sha256(raw).hexdigest(), "text": text,
            "written_by_this_skill": bool(meta and meta.group(1) == digest(text))}


def plan(run_dir: Path) -> dict:
    ctx = gather(run_dir)
    document = render(ctx)
    prior = existing(run_dir)
    result = {"ok": True, "report": REPORT, "generated": ctx["generated"], "inputs": ctx["inputs"], "sections": sections_for(ctx)}
    if prior is None:
        return {**result, "state": "absent", "sha256": None, "current": False}
    return {**result, "state": "unchanged" if prior["written_by_this_skill"] else "edited", "sha256": prior["sha256"],
            "current": prior["text"] == document}


def write(run_dir: Path, expected: str | None) -> dict:
    ctx = gather(run_dir)
    document = render(ctx)
    prior = existing(run_dir)
    if prior is None and expected is not None:
        raise ReportError("report_hash_unexpected", f"--expected-sha256 was given but {REPORT} does not exist; run plan again")
    if prior is not None and expected is None:
        raise ReportError("report_exists", f"{REPORT} exists; run plan and pass its sha256 as --expected-sha256 to replace it")
    if prior is not None and prior["sha256"] != expected.lower():
        raise ReportError("report_hash_mismatch", f"{REPORT} changed since plan read it (sha256 {prior['sha256']}); run plan again")
    try:
        fd, tmp = tempfile.mkstemp(dir=run_dir, prefix=f".{REPORT}.", suffix=".tmp")
    except OSError as exc:
        raise ReportError("report_write_failed", f"cannot create a file in the run directory: {exc}")
    try:
        with os.fdopen(fd, "wb") as out:
            out.write(document.encode("utf-8"))
            out.flush()
            os.fsync(out.fileno())
        _target(run_dir)
        os.replace(tmp, run_dir / REPORT)
    except OSError as exc:
        Path(tmp).unlink(missing_ok=True)
        raise ReportError("report_write_failed", f"{REPORT}: {exc}")
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
    return {"ok": True, "written": REPORT, "sha256": hashlib.sha256(document.encode("utf-8")).hexdigest(),
            "replaced": prior is not None, "sections": sections_for(ctx)}


def check(run_dir: Path) -> dict:
    ctx = gather(run_dir)
    prior = existing(run_dir)
    if prior is None:
        raise ReportError("report_not_found", f"{REPORT} is not in the run directory; run write")
    if prior["text"] is None:
        return {"ok": False, "errors": [{"code": "report_edited", "detail": f"{REPORT} is not UTF-8, so this skill did not write it"}]}
    text, fresh = prior["text"], render(ctx)
    if text == fresh:
        return {"ok": True, "sha256": prior["sha256"], "sections": sections_for(ctx)}
    if prior["written_by_this_skill"]:
        return {"ok": False, "errors": [{"code": "report_stale",
                                         "detail": "an input artifact changed after the report was written; run plan and write"}]}
    errors = []
    counts: dict[str, int] = {}
    for m in SECTION_OPEN.finditer(text):
        counts[m.group(2)] = counts.get(m.group(2), 0) + 1
    for sid in sections_for(ctx):
        if counts.get(sid, 0) == 0:
            errors.append({"code": "report_section_missing", "detail": f'<section id="{sid}"> is missing'})
        elif counts[sid] > 1:
            errors.append({"code": "report_section_duplicate", "detail": f'<section id="{sid}"> appears {counts[sid]} times'})
    nav = TOC_HREF.search(text)
    for href in re.findall(r'href="#([^"]+)"', nav.group(1)) if nav else []:
        if href not in counts:
            errors.append({"code": "report_toc_broken", "detail": f'the contents link #{href} has no matching section'})
    if not nav:
        errors.append({"code": "report_toc_broken", "detail": '<nav class="toc"> is missing'})
    if not errors:
        errors.append({"code": "report_edited", "detail": f"{REPORT} was changed after this skill wrote it, or another tool wrote it"})
    return {"ok": False, "errors": errors}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("plan", "write", "check"))
    parser.add_argument("run_dir", type=Path, help="the $MIGRATION_DIR with a completed Estimate")
    parser.add_argument("--expected-sha256", help="for write: the sha256 plan reported for the existing report")
    args = parser.parse_args(argv)
    try:
        if args.command == "plan":
            result = plan(args.run_dir)
        elif args.command == "write":
            result = write(args.run_dir, args.expected_sha256)
        else:
            result = check(args.run_dir)
    except ReportError as exc:
        result = {"ok": False, "error": exc.code, "detail": exc.detail}
    print(json.dumps(result, indent=2))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
