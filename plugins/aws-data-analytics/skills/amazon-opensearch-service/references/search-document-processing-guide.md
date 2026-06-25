# Document Processing with Docling

This guide covers how to process PDF, DOCX, PPTX, XLSX, HTML, and other document formats for ingestion into OpenSearch using [Docling](https://docling.site/).

## Overview

Docling is an open-source Python library (MIT license) by IBM Research that converts unstructured documents into structured data. It detects page layout, reading order, table structure, code blocks, formulas, and images using AI models, and runs locally on commodity hardware.

## Supported Input Formats

PDF, DOCX, PPTX, XLSX, HTML, Markdown, AsciiDoc, CSV, images (PNG, JPEG, TIFF, BMP, WEBP), audio (MP3, WAV).

## Chunking for Search Ingestion

Docling provides two chunking strategies for breaking documents into search-ready pieces:

### HierarchicalChunker (structure-based)

Splits at every section/heading boundary. Produces many small chunks that respect document structure.

### HybridChunker (recommended for OpenSearch)

Combines structure-aware splitting with token limits. Preserves document hierarchy while ensuring chunks fit within embedding model constraints.

Parameters: `max_tokens=512, overlap_tokens=50`

## Processing Pipeline for Document Search

The recommended end-to-end flow:

1. **Convert** — Use Docling to parse the document into structured form.
2. **Chunk** — Use `HybridChunker` with token limits matching your embedding model.
3. **Export** — Write chunks as JSONL with text + metadata fields.
4. **Index** — Load into OpenSearch using the ingest pipeline.
5. **Search** — Query using your configured search pipeline.

## Choosing Chunk Size

- For BM25 (keyword search): larger chunks (1000+ tokens) work well since BM25 benefits from more context.
- For dense vector / semantic search: 256–512 tokens is typical, matching embedding model input limits.
- For hybrid search: 512 tokens with 50-token overlap is a good default.

## Performance Tips

- Skip page images if not needed to save memory.
- Use `max_num_pages` or `page_range` to limit processing for large documents.
- Enable parallel processing for multi-core systems.
- For scanned PDFs, OCR is enabled by default. Disable if not needed.
