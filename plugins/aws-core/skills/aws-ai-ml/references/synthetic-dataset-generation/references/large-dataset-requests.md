# Large Requests (above ~20,000 records)

The service accepts up to 50,000 records per job, but fine-tuning gains usually
flatten between 10,000 and 15,000 records. Counts in the 25,000-50,000 range mainly
pay off for continued pre-training or for a large, diverse document corpus. When a
fine-tuning request is above ~20,000 records, confirm the count before generating:

> "N records is above where fine-tuning gains usually flatten (10,000-15,000). Larger counts mainly pay off for continued pre-training or a diverse document corpus. Do you want to proceed with N, or size down?"

If the request is grounded in context documents, also suggest one job per document
set rather than one large job. This is guidance, not a cap: once the user confirms,
generate the requested count.
