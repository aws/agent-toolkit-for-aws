# Cost-Optimization Levers

This document is the only legal source for cost-optimization levers referenced in agent-advisor outputs. When generating estimates or reports, cite only the levers documented in the table below. Do not invent or suggest discounts, optimizations, or cost-reduction strategies that are not explicitly listed here.

## Available Levers

| Lever                                                     | Applies to                                   | Effect (order of magnitude)        | Caveat                                   |
| --------------------------------------------------------- | -------------------------------------------- | ---------------------------------- | ---------------------------------------- |
| Model tier routing (Sonnet→Haiku for triage/simple items) | any LLM unit                                 | ≈5× cheaper on routed traffic      | quality-gate the routing                 |
| Prompt caching                                            | repeated system/preamble tokens              | up to ~90% off cached input tokens | cache-friendly prompt structure required |
| Batch inference                                           | latency-tolerant workloads (scheduled/batch) | ~50% off tokens                    | async only                               |
| Scale-to-zero runtimes                                    | spiky/idle-heavy units                       | eliminates idle compute            | cold-start tolerance                     |
| Quota scheduling                                          | shared Bedrock TPM across units              | avoids provisioned throughput      | schedule heavy runs off-peak             |

## Citation Rule

When referencing a cost lever in `estimate.json.drivers[]` or in any report or plan section, cite the lever name exactly as it appears in the table above.
