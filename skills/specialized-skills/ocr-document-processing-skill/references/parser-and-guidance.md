# parse.py reference, mode-selection guidance, and error recovery

## parse.py reference

```
python3 parse.py --mode MODE [-i FILE... | stdin] [-f markdown|plain|html|csv]
                 [--no-tables] [--figures] [--headers-footers]
                 [--flag-below N] [--threshold N] [-o OUT]
```

Modes: `linearize · raw-text · tables · forms · queries · expense · identity · blocks · confidence-route`.
Text → stdout (or `--out`); diagnostics/warnings → stderr. Exits 2 on bad input, 3 if textractor missing.

## Confidence thresholds (guidance)

≥95% use directly · 80–95% review for critical fields · 50–80% flag · <50% don't use.
`confidence-route` uses a single threshold: auto-accept fields at/above `--threshold`
(default 80), and send everything below it — plus any field with missing/low-trust
confidence — to human review. The default of 80 aligns with the band guidance above:
it auto-accepts only the "use directly" (≥95%) and "review for critical fields"
(80–95%) ranges and routes the entire 50–80% "flag" band and below to a human.
For higher-assurance identity/KYC/financial flows, raise it (e.g. `--threshold 95`).

## Cost notes

Relative cost: `detect-document-text` is the cheapest call; `analyze-document`
costs more per page and scales with the number of features requested
(LAYOUT/TABLES/FORMS/QUERIES). For current per-1K-page prices, fetch live Textract
pricing (`aws pricing get-products --service-code AmazonTextract`, or the Textract
pricing page) rather than relying on a baked-in number. Use plain detect-text when
you only need characters; reserve the structured features for when structure
matters, and request only the features you use.

## Linearize vs raw-text — which one

Use `--mode linearize` (`analyze-document` LAYOUT [TABLES]) when:

- output feeds an LLM (summarization, Q&A, reasoning)
- multi-column layout (research papers, newspapers)
- complex structure (titles, headers, nested lists)
- you need Markdown headings/tables (`--format markdown`)

Use `--mode raw-text` (`detect-document-text`) instead when:

- you only need raw characters (e.g. keyword search)
- single-column, simple text
- cost matters — detect-text is cheaper (fetch the live figure; see Cost notes)
- speed matters — detect-text is faster; linearize calls `analyze-document` LAYOUT

## Geometry — when to keep it

`--mode blocks` surfaces per-block geometry + confidence. Keep geometry when:

- you need to know WHERE on the page text appears
- building a UI that highlights extracted regions
- validating a low-confidence value against its visual position
- answering spatial questions ("what's in the top-right corner?")

Skip geometry when:

- you only want the text content
- output goes to an LLM for reasoning (bounding boxes add noise)

## Error recovery

| Error | Cause | Recovery |
| --- | --- | --- |
| `InvalidS3ObjectException` | wrong bucket, key, or region | bucket region must match `AWS_REGION`; confirm the key exists |
| `UnsupportedDocumentException` | unsupported/corrupt format, or a multi-page PDF hit a sync call | confirm PNG/JPEG/PDF/TIFF; if it's a multi-page PDF, switch to async (Procedure B) |
| `DocumentTooLargeException` | >10 MB (sync) or >500 MB (async) | split or downsample; use S3 + async |
| `ThrottlingException` | rate limit hit | back off and retry; shrink the agent batch loop |
| `ProvisionedThroughputExceededException` | account quota exhausted | wait and retry; request a Textract quota increase |
| `InvalidParameterException` | bad request params | check feature names, ≤15 queries, query text <200 chars |
