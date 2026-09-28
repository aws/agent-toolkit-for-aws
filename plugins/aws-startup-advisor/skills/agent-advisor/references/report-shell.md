# Shared report shell — v3 document style

A single source of truth for the shared visual system of every HTML report in this skill
(recommendation-report.html, poc-report.html). The v3 style is document-first (sober typography,
numbered sections, ruled tables) with one accent data visualization (score bars). Keeping it
here means these rules are maintained in ONE place, so reports stop drifting.

Content-specific CSS (score bars, unit cards, diagram cards, cost cards, etc.) does NOT
live here — each report keeps its own content rules in its own generator, ADDED AFTER this
block. Never restate a shell rule locally.

## Chart color tokens (validated)

The two chart fill colors are design-system constants, validated with the dataviz
six-checks palette validator on the white document surface (lightness band PASS, CVD ΔE 66+
PASS; the muted tone is a deliberate de-emphasis, and every bar always carries a visible
value label, which satisfies the contrast-relief obligation):

- `--chart-accent: #C77700` — the WINNER / primary magnitude fill. (NOT `#FF9900`: raw AWS
  orange fails 3:1 contrast on white. `#FF9900` is reserved for chrome on DARK surfaces —
  where it has ample contrast.)
- `--chart-muted: #94a3b8` — every de-emphasized bar/track mark.

## CSS (inline this block into each report's `<style>` block)

```css
  :root { --chart-accent: #C77700; --chart-muted: #94a3b8; --ink: #1f2328; --muted: #57606a;
          --rule: #d8dee4; --soft: #f6f8fa; }

  /* ── Reset & base ── */
  *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
         background: #fff; color: var(--ink); font-size: 15px; line-height: 1.65; }

  /* ── Layout ── */
  .page { max-width: 920px; margin: 0 auto; padding: 0 32px 90px; }

  /* ── Document header ── */
  .doc-head { border-bottom: 3px solid var(--ink); padding: 40px 0 18px; }
  .doc-kicker { font-size: 12px; font-weight: 600; letter-spacing: 1.2px; text-transform: uppercase;
                color: var(--muted); }
  .doc-title { font-size: 27px; font-weight: 700; letter-spacing: -0.4px; margin-top: 6px; }
  .doc-meta { display: flex; gap: 24px; flex-wrap: wrap; font-size: 12.5px; color: var(--muted);
              margin-top: 10px; }
  .doc-meta b { color: var(--ink); font-weight: 600; }

  /* ── Typography ── */
  h2 { font-size: 17px; font-weight: 700; margin: 42px 0 12px; padding-bottom: 6px;
       border-bottom: 1px solid var(--rule); }
  h2 .no { color: var(--muted); font-weight: 600; margin-right: 10px; }
  h3 { font-size: 15px; font-weight: 700; margin: 26px 0 8px; }
  h3 .no { color: var(--muted); font-weight: 600; margin-right: 8px; }
  p  { margin: 8px 0; }
  .lede { font-size: 15.5px; }
  .note { font-size: 13px; color: var(--muted); }

  /* ── Tables (document style: 2px ink header rule) ── */
  table { width: 100%; border-collapse: collapse; font-size: 13.5px; margin: 12px 0; }
  th { text-align: left; font-weight: 600; font-size: 12px; text-transform: uppercase;
       letter-spacing: 0.4px; color: var(--muted); padding: 8px 12px;
       border-bottom: 2px solid var(--ink); }
  td { padding: 9px 12px; border-bottom: 1px solid var(--rule); vertical-align: top; }
  tr:last-child td { border-bottom: 1px solid var(--ink); }
  td.em, .em { font-weight: 650; }
  .target { font-weight: 650; }

  /* ── Inline marks ── */
  .rule-cite { font-size: 11px; font-weight: 600; color: var(--muted);
               background: var(--soft); border: 1px solid var(--rule); border-radius: 4px;
               padding: 0 6px; font-family: ui-monospace, "SF Mono", monospace; white-space: nowrap; }
  .pre-flag { font-size: 10.5px; font-weight: 700; color: #9a3412; border: 1px solid #9a3412;
              border-radius: 3px; padding: 0 5px; letter-spacing: 0.4px; white-space: nowrap; }
  code { font-family: ui-monospace, "SF Mono", monospace; font-size: 12.5px;
         background: var(--soft); border: 1px solid var(--rule); border-radius: 4px; padding: 1px 5px; }

  /* ── Score bars (the one visualization, kept sober) ── */
  .scores { margin: 10px 0 4px; max-width: 560px; }
  .score-row { display: grid; grid-template-columns: 150px 1fr 40px; align-items: center;
               gap: 12px; margin-bottom: 8px; }
  .score-name { font-size: 13px; }
  .score-name.winner { font-weight: 700; }
  .bar-track { background: var(--soft); border: 1px solid var(--rule); border-radius: 3px;
               height: 12px; overflow: hidden; }
  .bar-fill { height: 100%; background: var(--chart-muted); }
  .bar-fill.winner { background: var(--chart-accent); }
  .score-val { font-size: 12.5px; font-weight: 600; text-align: right; color: var(--muted);
               font-variant-numeric: tabular-nums; }
  .score-val.winner { color: var(--ink); }

  /* ── Callouts ── */
  .callout { border: 1px solid var(--rule); border-left: 3px solid var(--ink);
             background: var(--soft); padding: 12px 16px; font-size: 13.5px; margin: 14px 0; }
  .callout.warn { border-left-color: #9a3412; }
  .callout b { font-weight: 700; }

  /* ── Lists ── */
  ol.steps { margin: 10px 0 0 20px; }
  ol.steps li { margin-bottom: 8px; font-size: 14px; }
  ul.plain { margin: 6px 0 0 20px; }
  ul.plain li { margin-bottom: 5px; font-size: 13.5px; }

  /* ── Diagram ── */
  .mermaid { min-height: 200px; margin: 10px 0; }
  .figure { border: 1px solid var(--rule); padding: 16px 18px; }
  .figcap { font-size: 12px; color: var(--muted); margin-top: 6px; }

  /* ── Unit cards (multi-unit topology) ── */
  .unit-sec { border: 1px solid var(--rule); margin-top: 16px; }
  .unit-sec-head { display: flex; justify-content: space-between; align-items: baseline;
                   flex-wrap: wrap; gap: 8px; padding: 12px 18px; background: var(--soft);
                   border-bottom: 1px solid var(--rule); }
  .unit-sec-body { padding: 14px 18px 16px; }
  .us-name { font-size: 15px; font-weight: 750; }
  .us-kind { font-size: 12px; color: var(--muted); margin-left: 10px; }
  .us-target { font-size: 14px; font-weight: 700; }

  /* ── Help strip (replaces the gradient help banner INSIDE this report family) ── */
  .help-strip { border: 1px solid var(--rule); border-radius: 6px; padding: 12px 16px;
                margin-top: 26px; display: flex; justify-content: space-between;
                align-items: center; gap: 16px; flex-wrap: wrap; background: var(--soft); }
  .help-strip .txt { font-size: 13.5px; }
  .help-strip .txt b { font-weight: 700; }
  .help-strip a.btn { font-size: 13px; font-weight: 700; color: #fff; background: var(--ink);
                      text-decoration: none; padding: 7px 16px; border-radius: 5px; white-space: nowrap; }

  /* ── Icon feature grid (poc-report uses this) ── */
  .feat-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(210px, 1fr));
               gap: 12px; }
  .feat { display: flex; gap: 12px; align-items: flex-start; background: var(--soft);
          border: 1px solid var(--rule); border-radius: 8px; padding: 14px 16px; }
  .feat-icon { flex: none; width: 30px; height: 30px; border-radius: 8px;
               background: var(--ink); color: #fff; display: flex; align-items: center;
               justify-content: center; font-size: 15px; }
  .feat-name { font-size: 13px; font-weight: 700; color: var(--ink); }
  .feat-desc { font-size: 12px; color: var(--muted); line-height: 1.45; margin-top: 1px; }

  /* ── Timeline (numbered next steps / runbooks) ── */
  .timeline { display: flex; flex-direction: column; }
  .tstep { display: flex; gap: 16px; position: relative; padding-bottom: 22px; }
  .tstep:last-child { padding-bottom: 0; }
  .tstep::before { content: ""; position: absolute; left: 13px; top: 30px; bottom: 2px;
                   width: 2px; background: var(--rule); }
  .tstep:last-child::before { display: none; }
  .tnum { flex: none; width: 28px; height: 28px; border-radius: 50%; background: var(--ink);
          color: #fff; font-size: 13px; font-weight: 700; display: flex;
          align-items: center; justify-content: center; }
  .tstep-title { font-size: 14px; font-weight: 700; color: var(--ink); }
  .tstep-body { font-size: 13px; color: var(--muted); margin-top: 2px; }
  .tstep-body code, .tstep-body pre { font-size: 12px; background: var(--soft);
          border: 1px solid var(--rule); border-radius: 6px; padding: 1px 6px; }

  /* ── Document footer ── */
  .doc-foot { margin-top: 48px; padding-top: 14px; border-top: 1px solid var(--rule);
              font-size: 12px; color: var(--muted); }

  /* ── Links ── */
  a { color: #0757ba; }
  .dl-link { font-weight: 600; text-decoration: none; }
```

## Mermaid script tag (part of the shared shell for any report with a diagram)

Any report that renders a Mermaid diagram loads the SAME SRI-pinned mermaid@10.9.3 script tag
in its `<head>` — copy it VERBATIM (the integrity hash must not change):

```html
<script src="https://cdn.jsdelivr.net/npm/mermaid@10.9.3/dist/mermaid.min.js"
        integrity="sha384-R63zfMfSwJF4xCR11wXii+QUsbiBIdiDzDbtxia72oGWfkT7WHJfmD/I/eeHPJyT"
        crossorigin="anonymous"></script>
```

## Usage note

Each report generator inlines the CSS block above into its own `<style>` block, then adds
its OWN content-specific rules after it. The union of (this shell + the report's own
content CSS) must reproduce that report's full rule set — do not drop or restyle a shared
rule locally, or the reports drift again.

Component contract (what each shared piece is FOR):

| Component                          | Use                                                                                     |
| ---------------------------------- | --------------------------------------------------------------------------------------- |
| `.doc-head` family                 | document header: kicker, title, meta row (run ID, date, entry point, region, status)    |
| `.help-strip`                      | compact help CTA (v3 report family uses this; see report-help-banner.md for a note)     |
| `h2` / `h3` + `.no`                | numbered sections (the `.no` span is the muted section number)                          |
| `table` / `th` / `td` / `.em`      | document tables with 2px ink header rule; `.target` is bold runtime verdicts            |
| `.lede` / `.note`                  | lead paragraph (slightly larger) / muted footnote text                                  |
| `.rule-cite` / `.pre-flag`         | inline rule citations (e.g., `Tier1-R5`) / PRE-RELEASE flag                             |
| `.scores` / `.score-row`           | sober score bars (the v3 form, moved into the shell since Temporal sections reuse them) |
| `.callout` / `.callout.warn`       | bordered info callouts with left accent; `.warn` is amber                               |
| `.unit-sec` family                 | multi-unit topology cards (head + body; .us-name/.us-kind/.us-target)                   |
| `.figure` / `.figcap`              | bordered diagram box + caption                                                          |
| `.feat-grid` / `.feat`             | icon + name + desc grids (poc-report file maps; minimally restyled to v3 tokens)        |
| `.timeline` / `.tstep`             | numbered sequential steps (next steps, Temporal runbooks)                               |
| `.doc-foot`                        | document footer (freshness, status)                                                     |
| `--chart-accent` / `--chart-muted` | the ONLY chart fill colors (see Chart color tokens above)                               |

- **recommendation-report.html** — `references/phases/generate/generate-report.md` inlines
  this block plus its unit-card/diagram/alternatives/service/cost content rules.
- **Temporal sections** — Temporal migration content renders as a CONDITIONAL section of
  recommendation-report.html (`references/phases/generate/generate-report.md`, gated on
  temporal units); its tier tables use the shared `table`, its cutover runbook the shared
  `.timeline`, and any diagram the shared mermaid tag.
- **poc-report.html** — `references/phases/poc/poc-report.md`; its file map uses
  `.feat-grid`, its deploy steps use `.timeline`.

The shared "Need help?" CTA: `references/report-help-banner.md` documents the full 3-card
banner form. The v3 report family renders it as `.help-strip` (the compact inline variant
defined in this shell).
