# Risk Assessment Procedure

Read this file before Step 6. Use the matrix consistently for every finding before producing the final report.

## Step 6: Risk Assessment

For each finding, assess using Impact x Likelihood:

**Impact**: Minor (limited blast radius) | Moderate (subset of users affected) | Severe (full outage, data loss, regulatory violation)

**Likelihood**: Low (specific conditions required) | Medium (possible under normal operations) | High (common failure mode, weak controls)

| Impact   | Likelihood | Risk Level |
|----------|------------|------------|
| Severe   | High       | Critical   |
| Severe   | Medium     | High       |
| Severe   | Low        | High       |
| Moderate | High       | High       |
| Moderate | Medium     | Medium     |
| Moderate | Low        | Medium     |
| Minor    | High       | Medium     |
| Minor    | Medium     | Low        |
| Minor    | Low        | Low        |

Identify cross-pillar conflicts:

- Security controls that impact performance
- Cost optimizations that reduce reliability
- Reliability patterns that increase cost

## Internal gate: risk assessment complete

Confirm internally before producing the report — on a non-interactive review, do NOT stop for the user:

- Every finding has an Impact × Likelihood risk level from the matrix above.
- Cross-pillar conflicts identified.
- Counts tallied (Critical / High / Medium / Low / cross-pillar conflicts) for the report's executive summary.

If these hold, proceed to the report step. Pause for the user ONLY when the user explicitly requested interactive checkpoints; otherwise continue without confirmation.
