# Sensitive-data discovery decisions

Use the parent skill’s focused-recommendation rules. Load the [full workflow](references/service-recommendations.md) only for collection, broad review or cost reduction.
Read only the matching [enablement checks](references/service-recommendations/enablement-checks.md) when collection is needed.

## Assurance and scanability

| Customer requirement and evidence | Decision and common trap |
|---|---|
| Broad S3 sensitivity discovery; automated discovery scope and existing results | Sampling can support estate discovery. Do not translate enabled discovery or a sensitivity score into proof that every object was examined. |
| Named dataset requiring examination beyond sampling; job selection and completion evidence | Consider a separately planned targeted job in addition. Compare included objects with the required dataset and unresolved exclusions before claiming full coverage. A job configuration alone cannot meet an exhaustive assurance requirement. |
| Unscannable objects, format/storage-class metadata, permissions and explicit denies | Diagnose the recorded reason against current supported formats and limits. An absence of positive findings can reflect unexamined data rather than the absence of sensitive data; requesting another job without resolving scanability may repeat the blind spot. |
| Organization-specific identifiers and sanitized expected/misclassified examples | Compare identifier semantics with actual data classes. Propose accuracy validation where detection misses the required class; do not use allow lists to hide accepted findings. |

For example, a dataset with successful sampled discovery but known unscannable files has two
separate questions: whether sampling meets the assurance need, and whether the excluded files
can be examined. Keep the second UNKNOWN until its cause is resolved; do not label the whole
dataset clean or assume an additional job solves both. Sources: [Macie automated discovery,
resource coverage and identifier guidance][MA], [discovery jobs](https://docs.aws.amazon.com/macie/latest/user/discovery-jobs.html).

## Evidence delivery and use

Request export destination/encryption metadata and a sanitized delivery/completion record
for the selected dataset. Require the destination to use KMS encryption at rest and TLS in
transit for delivery and consumer access, then compare observed retention with the required
evidence window. A configured export destination and positive findings do not show which objects
were examined or that evidence arrived. The matrix's export recommendation needs this
delivery check before being reported complete.

Check sensitive-data publication separately from export. Publication supports correlation;
export supports retained discovery evidence. Neither substitutes for the other. Compare
consumer and ownership evidence with the intended use: expected sensitive-data placement
may be context for prioritization, while unexpected placement/exposure needs the data or
application owner's response. Preserve the source findings in both cases.

GuardDuty suspicious-access and malware signals do not replace classification. Conversely,
Macie presence does not prove malware inspection. Keep publication dependencies when considering
[Hub/CSPM consolidation](references/service-recommendations/posture-and-investigation.md#standards-and-recorder-context).
Source: [Macie discovery results, publication and findings guidance][MA].

[MA]: https://github.com/aws/aws-security-services-best-practices/blob/f2b28d7c31c490ad676273307cbdb900c16daed8/docs/en/guides/macie/index.md
