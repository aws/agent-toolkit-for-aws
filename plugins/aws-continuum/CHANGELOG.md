# Changelog

Changes to the `aws-continuum` plugin that can change how it behaves for a user. Read this when a skill or command stops working as it used to.

## 1.0.1

### Reporting

- Findings with different indentation or whitespace inside strings are no longer merged, so distinct flaws keep their own verdicts. Only identical code in the same file can share a classification.
- Moved braces and other structural lines now require review instead of being marked Open with unchanged code. Every non-blank cited code line must match its exact source position; fuzzy matches only locate evidence.

### Setup

- SSE-KMS setup guidance separates source decryption from destination patch encryption. Encrypted patch uploads require `kms:GenerateDataKey` and the matching key-policy grant; patch readback or multipart uploads also require `kms:Decrypt`.

### Tests

- Offline regression tests now ship beside both scripts and run with `node --test plugins/aws-continuum/skills/*/scripts/test/`. They cover code identity and positions, unsafe paths, and external-ID format, private file permissions and overwrite refusal.

## 1.0.0

Initial release.

### Skills

- `setting-up-continuum` connects a repository to AWS Continuum with explicit identity, quota, permission and write approvals.
- `reporting-continuum-security` writes the current security state as a private, self-contained Markdown report.
- `fixing-continuum-issues` groups validated issues, records decisions and prepares tested draft fixes without merging.

### Commands

- `/aws-continuum:setup` starts the guided setup workflow.
- `/aws-continuum:status` writes or refreshes the security report.
- `/aws-continuum:fix` starts the reviewed remediation workflow.
