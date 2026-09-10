# Document Processing with Docling

This guide covers how to process PDF, DOCX, PPTX, XLSX, HTML, and other document formats for ingestion into OpenSearch using [Docling](https://docling.site/).

> The AWS MCP server is recommended for executing these commands but is not required — all steps use standard AWS CLI syntax.

## Overview

Docling is an open-source Python library (MIT license) by IBM Research that converts unstructured documents into structured data. It detects page layout, reading order, table structure, code blocks, formulas, and images using AI models, and runs locally on commodity hardware.

## Supported Input Formats

PDF, DOCX, PPTX, XLSX, HTML, Markdown, AsciiDoc, CSV, images (PNG, JPEG, TIFF, BMP, WEBP), audio (MP3, WAV).

## Choosing a processing approach

Match the Docling pipeline to the document's dominant content, because a single
default pipeline degrades on tables, scans, and figures.

| Document character | Approach | What to enable | Why |
|---|---|---|---|
| Digital-text, prose-heavy (papers, reports, contracts) | Semantic | Hierarchy-aware `HybridChunker` respecting headings | Preserves section boundaries so chunks stay self-contained |
| Table-heavy (financial reports, spec sheets) | Tables | TableFormer table extraction; serialize tables to markdown | You MUST enable table extraction explicitly, because auto-detection does NOT reliably recognize table-heavy documents and untreated tables collapse into unusable text |
| Scanned / image-only pages | Scanned | OCR (`do_ocr=True`; RapidOCR / PP-OCRv4) before chunking | Digital-text pipelines produce empty chunks on scans because there is no extractable text layer |
| Figure / diagram-rich | Multimodal | VLM picture descriptions (e.g. SmolVLM-256M) | Figures carry meaning that is lost unless described, because embeddings index text only |

You SHOULD default to the semantic approach for digital-text documents and disable OCR
(`do_ocr=False`, since Docling enables it by default), because OCR adds significant
latency and is unnecessary when a text layer exists.

## Chunking for Search Ingestion

Docling provides two chunking strategies for breaking documents into search-ready pieces:

### HierarchicalChunker (structure-based)

Splits at every section/heading boundary. Produces many small chunks that respect document structure.

### HybridChunker (recommended for OpenSearch)

Combines structure-aware splitting with token limits. Preserves document hierarchy while ensuring chunks fit within embedding model constraints.

Parameters: `max_tokens=512` (HybridChunker takes no overlap parameter — it merges adjacent peer chunks rather than applying a fixed overlap).

## Processing Pipeline for Document Search

The recommended end-to-end flow:

1. **Convert** — Use Docling to parse the document into structured form.
2. **Chunk** — Use `HybridChunker` with token limits matching your embedding model.
3. **Export** — Write chunks as JSONL with text + metadata fields.
4. **Index** — Load into OpenSearch using the ingest pipeline.
5. **Search** — Query using your configured search pipeline.

## JSONL chunk format

Each line of the exported `.jsonl` MUST be a standalone JSON object with at
minimum a `text` field, because the downstream bulk-index and OSIS ingestion
paths reject lines that lack indexable content.

```json
{"text": "...", "headings": ["Section Title"], "source_file": "doc.pdf", "chunk_id": 0, "page_number": 1}
```

| Field | Type | Description |
|---|---|---|
| `text` | string | Chunk content (required) |
| `headings` | array | Section headings this chunk belongs to |
| `source_file` | string | Original source filename |
| `chunk_id` | int | Sequential chunk index within the file |
| `page_number` | int | Source page number |

You SHOULD validate that every line parses as JSON and carries a non-empty
`text` field before uploading to S3, because a single malformed line can fail an
entire bulk request.

## Choosing Chunk Size

- For BM25 (keyword search): larger chunks (1000+ tokens) work well since BM25 benefits from more context.
- For dense vector / semantic search: 256–512 tokens is typical, matching embedding model input limits.
- For hybrid search: 512 tokens is a good default. The `HybridChunker` above has no overlap parameter (it merges adjacent peer chunks); a fixed ~50-token overlap applies only if you use a custom, non-Docling chunker.

## Adjusting chunking when retrieval quality is poor

Re-processing is expensive, so you SHOULD change chunking only when a quality
check provides evidence, because blind re-ingestion wastes compute without a
targeted fix.

| Symptom | Likely cause | Fix |
|---|---|---|
| Results lack surrounding context | Chunks too small | Increase `max_tokens` |
| Results contain irrelevant noise | Chunks too large | Decrease `max_tokens` |
| Tables absent from results | Table extraction not run | Re-process with TableFormer enabled |
| Scanned pages return empty or garbled text | OCR not run | Re-process with OCR enabled |
| Figures / diagrams missing from results | Visual content not described | Re-process with VLM picture descriptions |

You MUST NOT automatically re-ingest on a poor result, because re-ingestion is
costly and may not address the true cause; confirm the symptom and the intended
fix first.

## Evaluating chunk quality

Before indexing at scale, you SHOULD sample chunks and judge them against the
dimensions that matter for the document type, because indexing low-fidelity
chunks propagates the defect into every downstream search result.

| Document type | Dimensions to judge |
|---|---|
| Prose / semantic | text fidelity, reading order, chunk boundaries, heading structure |
| Tables | table structure, table-content fidelity, text fidelity, completeness |
| Scanned | OCR text fidelity, reading order, completeness |
| Multimodal | image descriptions, text fidelity, reading order, completeness |

Rate each dimension `good | fair | poor`. When any dimension is `poor`, explain
the cause and recommend a specific re-process; you MUST NOT re-ingest without
user confirmation, because re-processing is expensive.

## Performance Tips

- Skip page images if not needed to save memory.
- Use `max_num_pages` or `page_range` to limit processing for large documents.
- Enable parallel processing for multi-core systems.
- Docling enables OCR by default (`do_ocr=True`); disable it (`do_ocr=False`) for digital-text documents in the semantic profile, and keep it on only for scanned / image-only pages, since OCR adds significant latency.

## Security Considerations

Exported chunks (JSONL) and the S3 objects that stage them carry the full text of
the source documents, so treat them with the same sensitivity as the originals.

- **Encryption at rest.** Enable server-side encryption on the target S3 bucket —
  SSE-S3 at minimum, and SSE-KMS with a customer-managed KMS key for compliance
  workloads (PCI-DSS, HIPAA) so you retain key control and an audit trail. Apply
  the same encryption posture (AWS-owned key by default, customer-managed KMS key for compliance) to
  the destination OpenSearch collection or domain that ingests the chunks.
- **Access control.** Restrict the S3 bucket with a bucket policy (and, where
  applicable, `aws:SourceVpce` / IAM principal conditions) so only the ingestion
  role and authorized operators can read the staged JSONL. Block public access at
  the account and bucket level.
- **Sensitive / PII content.** Source documents may contain PII or other regulated
  data, which propagates verbatim into chunks, the index, and any search result or
  agent response. Classify sources before ingesting, redact or exclude fields you
  do not intend to make searchable, and delete the intermediate JSONL from S3 once
  indexing is confirmed rather than leaving it as a long-lived copy of the corpus.
