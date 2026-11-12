# Full code-version publishing contract

Read all of this before publishing. All S3 calls use the same AWS profile and region, `--expected-bucket-owner <caller-account>`, JSON output, and no pager. Bucket ownership mismatch is fatal. Copy also checks the source owner. The examples are command templates, not a bundled script.

## Preflight scanner support before writing

Before creating an upload record or ZIP, count all repositories planned for the environment across every integration. For S3, count repository ZIPs, including existing direct-child ZIPs at the intended prefix; upload records do not count. The public [AWS Continuum quotas page](https://docs.aws.amazon.com/continuum/latest/userguide/quotas.html) limits an environment to 10 repositories across all integrations. Calculate and show the per-integration subtotals and total directly; exactly 10 passes, while 11 or more stops all uploads and environment writes. No quota script is needed. Offer choosing 10 or fewer, splitting into logically grouped environments of 10 or fewer, or asking the AWS account team for an increase. Never drop or combine repositories to evade the quota. A higher limit requires the developer's statement that it was granted, recorded with the plan's account, Region, count, limit, and provenance.

Measure every ZIP's exact byte size and the largest archive, and verify the bucket and Continuum account and Region. The public quotas page and getting-started guide currently state no per-ZIP byte-size limit, so preserve that measurement as an explicit **not publicly documented** ZIP-size risk. The installed CLI model caps configured `s3Sources` at one. Upload success is not scanner-support evidence.

## What the service reads

List `<codePrefix>` with delimiter `/`. The backend selects the numerically highest folder named EXACTLY `v<digits>/` and scans every DIRECT CHILD lowercase `*.zip` in that folder. The stem becomes a repository name, replacing characters outside `[A-Za-z0-9_-]` with `_`. Only if there are no version folders does it read flat direct-child zips under the bare prefix. Flat zips are ignored once any version folder exists. Nested zip directories are not repositories.

There is no atomic folder rename. The backend ignores bookkeeping under `<codePrefix>.continuum/uploads/` and does not wait for an upload record to become complete. Scheduled scans during an upload can read a partial version. Explain this risk; do not change schedules without consent.

## Discover the complete current repository set

1. `aws s3api list-objects-v2 --bucket <bucket> --prefix <codePrefix> --delimiter / --expected-bucket-owner <caller-account>`: collect EVERY page of CommonPrefixes and Contents. Standard S3 CLI auto-pagination is acceptable; do not truncate with max-items.
2. List `<codePrefix>.continuum/uploads/` similarly and read every direct-child `v<digits>.json` upload record. Accept only a bounded JSON object whose version and codePrefix match its key and target, whose status is exactly `uploading` or `complete`, and whose repository entries are valid. A missing, malformed, mismatched, or unexpected record makes that version unknown; never infer completion.
3. Next N = one plus the NUMERIC maximum of version-folder numbers and upload-record numbers (default maximum 0). An `uploading` record with no populated version folder is an interrupted upload; its number is spent. Never reuse it.
4. Current observed set = direct-child zips of the highest actual folder, or the flat set if there are no folders. Match by normalized build repository name; reject collisions rather than silently discard one.
5. A populated version is complete only when its upload record has status `complete` and the record matches the observed repository set. Status `uploading` means incomplete. A version folder without a new upload record is unknown. For an incomplete or unknown highest folder, recover missing repository names from lower version folders, continuing backwards until the last verified `complete` set. Do not replace names already present in the newer set. If there is no lower verified complete set, preserve the actual uploaded set and explain the uncertainty. The preceding flat set is not used once versions exist, matching the reference publisher.
6. Show ignored flat zips, recovered repositories, interrupted versions, and unknown versions. Build the new complete repository set as recovered current set MINUS repositories explicitly replaced PLUS new archives. For carry-forward preserve the original archive basename.

Do not read or migrate the former bookkeeping objects under `<codePrefix>.continuum/versions/`. A folder produced with that layout has no new upload record and is therefore unknown. Explain that recovery uses the last version verified by a new `complete` upload record, or preserves the observed files with explicit uncertainty when none exists.

## Prepare one upload record

Write one local JSON file for version N. It contains `status`, `version`, `codePrefix`, `basedOn` (layout, latestVersion, repositories, ignoredFlatZips, incompleteVersions, unknownVersions), and `repositories` entries. Each entry holds repositoryName, destination key, and source `carried` or `uploaded`. Carried entries record copiedFrom; uploaded entries record fileCount and sizeBytes. This is bookkeeping, not a security authority.

Start with status `uploading`:

```json
{"status":"uploading","version":"v<N>","codePrefix":"<codePrefix>","basedOn":{"layout":"versioned","latestVersion":"v<previous-N>","repositories":["<repository-name>"],"ignoredFlatZips":[],"incompleteVersions":[],"unknownVersions":[]},"repositories":[{"repositoryName":"<repository-name>","key":"<codePrefix>v<N>/<repository-name>.zip","source":"uploaded","fileCount":12,"sizeBytes":34567}]}
```

Use observed fileCount and sizeBytes; never use placeholder zeroes as measurements. Show every exact write and obtain consent before creating the upload record. In the setup plan, describe this step plainly: **Write a small upload record so an interrupted upload is never mistaken for a complete one.**

## Required write order

1. Create N's upload record without overwriting anything. Save the returned ETag exactly as returned for the later conditional update:

    ```bash
    aws s3api put-object --bucket <bucket> --key <codePrefix>.continuum/uploads/v<N>.json --body <scratch>/upload-record.json --if-none-match '*' --expected-bucket-owner <caller-account>
    ```

2. Carry unchanged zips FIRST with server-side copies. Pin source ETag from discovery, URL-encode copy-source keys while preserving `/`, and use destination no-overwrite:

    ```bash
    aws s3api copy-object --bucket <bucket> --key <codePrefix>v<N>/<archive-basename>.zip --copy-source <bucket>/<encoded-source-key> --copy-source-if-match <source-etag> --if-none-match '*' --expected-bucket-owner <caller-account> --expected-source-bucket-owner <caller-account>
    ```

    If the installed CLI does not support conditional destination copy, STOP rather than replace it with unsafe `s3 cp` or remove `--if-none-match`. Explain the limitation to the user. An alternative approved plan may download with guarded get-object, verify source ETag, then conditionally put the object, but must account for extra bandwidth and require fresh consent.

3. Upload all new archives:

    ```bash
    aws s3api put-object --bucket <bucket> --key <codePrefix>v<N>/<repository-name>.zip --body <scratch>/<repository-name>.zip --if-none-match '*' --expected-bucket-owner <caller-account>
    ```

4. List and head the new folder. Verify every expected repository is present, no unexpected repository is present, and observed sizes match the prepared archives or pinned copies. Record each ETag; an ETag is not generally a content hash. Do not continue on a missing, extra, changed, or unverifiable object.
5. Change the same local upload record's status to `complete` and add the observed repository sizes and ETags. Only after step 4 succeeds, replace the same S3 object conditionally with the ETag returned by step 1:

    ```bash
    aws s3api put-object --bucket <bucket> --key <codePrefix>.continuum/uploads/v<N>.json --body <scratch>/upload-record.json --if-match <upload-record-etag> --expected-bucket-owner <caller-account>
    ```

6. Read the upload record again and verify its status is `complete`, its version and codePrefix match, and its repository entries still match the verified folder. Only then create a scan.

## Failure rules

PreconditionFailed/412 while creating the upload record means another publisher reserved that version or it is already spent. Re-read, choose the next N, and obtain consent for changed keys. Never overwrite, delete, or blindly resume an existing record. Failure before the first zip leaves an interrupted upload record; builds still use the previous folder. Failure after any zip leaves an incomplete high folder the backend MAY already read. Report the exact written and missing keys, do not scan, and propose a fresh complete version that restores missing repositories. A failed `If-Match` completion update means the record changed or another publisher intervened: stop, re-read, and treat the version as incomplete or unknown. Status `uploading` remains incomplete even if every zip appears present; do not report success.

## Packaging comparison

`git archive HEAD` meets the S3 root and version layout contract but intentionally differs from the Python publisher's working-tree collection: it omits `.git` history, dirty changes, and untracked nonignored files, and honors export-ignore. Disclose this difference in the plan and report. If the scanner requires history, stop and explain that this skills-only archive workflow cannot promise equivalent inputs; do not state that the uploaded archives are byte-identical.
