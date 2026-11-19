# Execution Environment

Synthetic dataset generation turns a spec into Python code and then runs that
code to produce the dataset. The generated code can only import a fixed set
of modules. A spec that asks for behavior requiring a module outside this
set cannot be implemented as written.

Read this before authoring a spec, and cross-check that the operations the
spec calls for can be expressed using only what's listed below.

## Allowed Modules

**Pre-imported standard library** — available in generated code without an
`import` statement:

```
abc, base64, collections, copy, csv, dataclasses, datetime, decimal, enum,
functools, glob, hashlib, io, itertools, json, logging, math, operator,
random, re, statistics, string, struct, textwrap, threading, time, typing,
uuid
```

**Optional third-party packages** — installed in the container, but generated
code must use an explicit `import` statement to bring them in:

```
faker, numpy, pandas
```

**Allowed stdlib submodules** — reachable by attribute or explicit import:

```
collections.abc
```

Any module not listed above is unavailable at run time. A spec that requires
one cannot be implemented as written.

## Consequences for Spec Authoring

These follow directly from the module set. Keep them in mind when writing
the spec's Input Data Preparation, Data Generation, and Data Verification
sections.

- **Retrieval is lexical.** No embedding, vector-store, or ANN library is on
  the allowlist. Semantic search, reranking, and dense retrieval cannot be
  specified — index via `re`, `pandas`, `hashlib`, or token counts instead.
  If a spec needs "look up the most relevant chunk", express it as a lexical
  operation (BM25 / TF-IDF / substring match), not as embedding similarity.

- **No external calls.** `subprocess` and every HTTP client are absent.
  Generated code cannot shell out to a converter, download a helper package,
  fetch a parser, or call an external API. Any preprocessing that needs those
  must happen *before* the data is uploaded, not as part of the spec.

- **Multi-file corpora work.** `glob` is present, so a spec's Input Data
  Preparation can walk a directory of input files.
