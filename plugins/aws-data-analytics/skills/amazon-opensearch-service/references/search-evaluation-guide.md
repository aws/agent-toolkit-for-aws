# Search Quality Evaluation Guide

Data-driven evaluation that runs real queries against the live index, computes quantitative metrics, and diagnoses issues with actionable recommendations.

## When to Evaluate

Offer evaluation after the search pipeline is configured and working:
> "Would you like to evaluate the search quality? I can run test queries, measure relevance metrics, and suggest improvements."

## Evaluation Workflow

### Step 1: Generate Test Queries

Ask the user to provide test queries. Assign a capability to each query based on its form:

| Capability | How to detect | Example |
|-----------|---------------|---------|
| `exact` | Matches a known title/name in the data | `The Matrix` |
| `structured` | Contains `field:value` syntax | `genres:Drama` |
| `combined` | Free text + `field:value` | `space adventure genres:Sci-Fi` |
| `autocomplete` | Short prefix (< 5 chars or partial word) | `The Ma` |
| `fuzzy` | Contains apparent misspelling | `Teh Matrx` |
| `semantic` | Natural language describing a concept | `movies about redemption in prison` |

### Step 2: Run Queries

Run all test queries through the search pipeline and collect top-k results for each.

### Step 3: Judge Relevance

For each query, review the returned documents and assign a relevance grade to each query-document pair. Grade every document in the top-k results — do not skip any.

**Grading scale:**

| Grade | Label | Criteria |
|-------|-------|----------|
| 3 | Perfect | The document is exactly what a user searching this query would want. For exact queries, the title matches. For semantic queries, the document directly addresses the concept. |
| 2 | Relevant | The document is clearly useful and related to the query intent, but is not the ideal result. |
| 1 | Marginal | The document shares a topic or keyword with the query but does not satisfy the search intent. |
| 0 | Irrelevant | The document has no meaningful connection to the query. |

**Judgment prompt — for each query-document pair, evaluate:**

1. **Intent match**: What is the user trying to find with this query? Does this document satisfy that intent?
2. **Content relevance**: How well does the document's content relate to the query?
3. **Would a real user click this?** If yes, grade >= 2. If maybe, grade 1. If no, grade 0.

### Step 4: Compute Metrics

Three metrics are computed per query per method, all at cutoff `k`:

| Metric | Formula | What it measures |
|--------|---------|------------------|
| **nDCG@k** | Normalized Discounted Cumulative Gain | Ranking quality — are the best docs at the top? |
| **P@k** | Precision at k | What fraction of top-k results are relevant? |
| **MRR** | Mean Reciprocal Rank | How quickly does the first relevant result appear? |

### Target Thresholds

| Metric | Good (>= ) | Acceptable (>=) | Poor (<) |
|--------|-----------|-----------------|----------|
| Mean nDCG@k | 0.70 | 0.50 | 0.30 |
| Mean P@k | 0.60 | 0.40 | 0.20 |
| Mean MRR | 0.70 | 0.50 | 0.20 |

### Step 5: Diagnose Issues

Apply diagnostic rules comparing across methods:

#### Rule 1: All methods fail (nDCG < 0.3 for every method)

- **Severity**: HIGH
- **Meaning**: No retrieval strategy can find relevant documents for this query
- **Fix**: Check field mappings, analyzers, or upgrade embedding model

#### Rule 2: Pairwise method gaps

- **Severity**: MEDIUM
- **Triggers when**: A vector method fails (nDCG < 0.3) while a lexical method succeeds (nDCG > 0.5), or vice versa
- **Fix**: Upgrade embedding model, or add proper text analyzers/boosting

#### Rule 3: Hybrid worse than single signals

- **Severity**: MEDIUM/LOW
- **Triggers when**: A hybrid method's nDCG is > 0.15 below the best non-hybrid method
- **Fix**: Adjust hybrid weights, or use query-type-aware routing

#### Rule 4: Irrelevant docs in top-2

- **Severity**: MEDIUM
- **Triggers when**: An irrelevant document (grade 0) appears in positions 1-2 and nDCG < 0.8
- **Fix**: Reduce field boosts, restructure query, or upgrade model

#### Rule 5: Missed relevant documents

- **Severity**: LOW
- **Triggers when**: High-relevance documents (grade >= 2) don't appear in any method's top-k
- **Fix**: Embed more fields, use a higher-capacity model

## Finding Tags

| Tag | What it targets | Example fix |
|-----|----------------|-------------|
| `[INDEX_MAPPING]` | Field types, analyzers, `.keyword` sub-fields | Add `.keyword` to filterable fields |
| `[EMBEDDING_FIELDS]` | Which fields are embedded | Concatenate `title + genres` before embedding |
| `[MODEL_SELECTION]` | Embedding model quality/type | Switch from sparse to dense, or upgrade model size |
| `[SEARCH_PIPELINE]` | Hybrid weights, normalization | Shift from 0.8/0.2 to 0.5/0.5 balanced |
| `[QUERY_TUNING]` | Field boosts, fuzziness, filter placement | Move filters to `bool.filter` to avoid score pollution |

## Completion Criteria

The evaluation passes if **any** of:

- Mean nDCG@k across all methods > 0.7
- All findings are LOW severity only
- No HIGH severity findings and setup matches the use case

## After Evaluation

Present results, then offer:

1. **Restart with improvements** — Apply recommended fixes and rebuild the search setup
2. **Deploy as-is** — Current configuration is acceptable
3. **Done for now** — Keep experimenting

If HIGH severity findings exist, recommend option 1 and explain the specific fix.
