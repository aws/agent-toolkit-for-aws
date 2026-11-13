# Changelog

Changes to the `aws-continuum` plugin that can change how it behaves for a user. Read this when a skill or command stops working as it used to.

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
