# Shared report CTA banner — "Need help?"

A single source of truth for the help/CTA banner embedded in every HTML report
(recommendation-report.html, poc-report.html, and the migration-report.html produced during
the migration plan). Keeping it here means the copy and the destination URL are maintained in
ONE place.

## Status: SUPPRESSED (pre-launch)

```
banner_status: SUPPRESSED
```

The destination support page is **not yet launched**, so the banner is SUPPRESSED: every
consumer MUST check this status FIRST and, while it reads `SUPPRESSED`, OMIT the banner
entirely — do NOT render or inject the `<style>` rules or the HTML block into ANY report
(recommendation, POC, or the migration-report post-process). The report simply starts with its
first content section, no "Need help?" block.

**To re-enable after launch:** flip `banner_status` to `LIVE` here and set the production URL
in the Destination URL section below — every report picks both up from this one file. This is
the ONLY switch; the CSS/HTML below is kept intact so re-enabling is a one-line change.

## Destination URL (single constant)

```
https://staging.d3jgt60vik5gbm.amplifyapp.com/mvp-v4/support
```

**NOTE:** this is currently the STAGING URL. When the production URL is available, update it
HERE only — every report picks it up from this file.

## CSS (add to each report's `<style>` block if not already present)

```css
.help-banner { background: linear-gradient(135deg, #f5f7ff 0%, #fdf4fb 100%);
               border: 1px solid #e5e7eb; border-radius: 10px; padding: 14px 16px;
               margin-top: 20px; }
.help-banner .hb-head { display: flex; align-items: center; justify-content: space-between;
                        gap: 12px; margin-bottom: 10px; }
.help-banner h3 { font-size: 15px; font-weight: 700; color: #1a1a2e; margin: 0; }
.help-banner .hb-link { flex: none; font-size: 13px; font-weight: 700; color: #1a1a2e;
                        background: #FF9900; text-decoration: none; white-space: nowrap;
                        padding: 7px 16px; border-radius: 7px; }
.help-banner .hb-link:hover { background: #e88b00; }
.help-cards { display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px; }
.help-card { display: flex; align-items: center; gap: 10px; background: #fff;
             border-radius: 8px; padding: 10px 12px; box-shadow: 0 1px 3px rgba(0,0,0,.05);
             text-decoration: none; }
.help-card:hover { box-shadow: 0 2px 6px rgba(0,0,0,.10); }
.help-card .hc-icon { flex: none; width: 26px; height: 26px; border-radius: 6px;
                      background: #2563eb; color: #fff; display: flex; align-items: center;
                      justify-content: center; font-size: 14px; }
.help-card .hc-title { font-size: 13px; font-weight: 700; color: #1a1a2e; line-height: 1.3; }
.help-card .hc-desc { font-size: 11px; color: #6b7280; line-height: 1.3; }
@media (max-width: 640px) { .help-cards { grid-template-columns: 1fr; }
                            .help-banner .hb-head { flex-direction: column; align-items: flex-start; gap: 4px; } }
```

## HTML (insert at the TOP — right after the header, before the first content section)

Substitute `{{ HELP_URL }}` with the destination URL constant above. All three cards + the
button point to the same support page (it hosts all three paths).

```html
<div class="help-banner">
  <div class="hb-head">
    <h3>Need help getting to AWS?</h3>
    <a class="hb-link" href="{{ HELP_URL }}" target="_blank" rel="noopener">Explore your options →</a>
  </div>
  <div class="help-cards">
    <a class="help-card" href="{{ HELP_URL }}" target="_blank" rel="noopener">
      <div class="hc-icon">⚡</div>
      <div><div class="hc-title">Install the AI agent</div><div class="hc-desc">Hands-on guidance in your IDE.</div></div>
    </a>
    <a class="help-card" href="{{ HELP_URL }}" target="_blank" rel="noopener">
      <div class="hc-icon">💬</div>
      <div><div class="hc-title">Talk with an AWS expert</div><div class="hc-desc">Answers on your migration & data.</div></div>
    </a>
    <a class="help-card" href="{{ HELP_URL }}" target="_blank" rel="noopener">
      <div class="hc-icon">👥</div>
      <div><div class="hc-title">Work with an AWS Partner</div><div class="hc-desc">A certified partner runs it for you.</div></div>
    </a>
  </div>
</div>
```

The banner is compact by design: a single header row (title + inline "Explore" link) above
three short cards (icon + title + one-line description), each card itself a link to the
support page. No oversized standalone CTA button, no subtitle — the whole block is ~2 rows tall.

## Usage note

**This whole usage note applies ONLY while `banner_status` is `LIVE`.** It currently reads
`SUPPRESSED`, so every report OMITS the banner entirely (see the Status section above) — the
"goes at the TOP of every report" instruction below is what happens once it is re-enabled, not
now.

When LIVE, the banner goes at the **TOP** of every report — right after the header/title bar,
before the first content section — so the help paths are the first thing the user sees.

- **recommendation-report.html / poc-report.html** (agent-advisor's own reports, v3 shell):
  the v3 shell defines `.help-strip` (the compact inline variant), which renders the help CTA
  as a single-row strip (text + inline button) instead of the 3-card form above. The v3
  template uses `.help-strip` — the full 3-card HTML above is NOT used in the v3 family. The
  canonical URL and copy are still maintained here; v3 just renders them more compactly.
- **migration-report.html** (produced by the inline gcp-to-aws Generate, which is read-only):
  do NOT edit gcp-to-aws's report generator. Instead, migration-plan.md post-processes the
  generated `migration-report.html` after Generate completes — inject this banner's `<style>`
  rules before `</style>` (or in a new `<style>` before `</head>`) and the HTML block right
  after the opening `<body>` / the report's header, before the first content block. This
  edits the OUTPUT file, not the gcp-to-aws instructions.
