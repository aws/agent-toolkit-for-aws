# Contributing

Thank you for your interest in this project! This project is not accepting external contributions at this time. Please feel free to open issues for bug reports and feature requests.

## Table of Contents

- [Reporting Bugs](#reporting-bugs)
- [Feature Requests](#feature-requests)
- [Skill Authoring](#skill-authoring)
- [Local Development](#local-development)
- [Publishing your Change](#publishing-your-change)
- [Security](#security)

## Reporting Bugs

- Before reporting bugs, please make sure you are on the latest version.
- Go through existing issues and check no users have reported the same bug.
- Submit a [GitHub Issue](https://github.com/aws/agent-toolkit-for-aws/issues/new?template=bug_report.yml) with detailed steps on how to reproduce this bug, as well as your system information such as your AI assistant (Claude Code, Codex, Kiro, etc.), its version, and operating system.

## Feature Requests

- Before submitting a feature request, please make sure you are on the latest version.
- Go through existing issues and check no users have requested the same feature.
- Submit a [GitHub Issue](https://github.com/aws/agent-toolkit-for-aws/issues/new?template=feature_request.yml) with a clear description of the feature and your use case.

## Skill Authoring

Skills live in two places and must be added to both:

- `skills/<skill-name>/` — the canonical source for all skills in the repository.
- `plugins/<plugin-name>/skills/<skill-name>/` — bundled inside the plugin that ships the skill.

Each skill directory must contain a `SKILL.md` with YAML frontmatter:

```yaml
---
name: my-skill-name
description: >
  A description of what this skill does (minimum 20 characters).
---
```

Validation rules enforced by `tools/validate.py`:

- `name` must be kebab-case, at most 64 characters, and match the directory name.
- `description` must be at least 20 characters.

Run `mise run build` to validate before submitting.

## Local Development

1. Clone the repository:

   ```bash
   git clone https://github.com/aws/agent-toolkit-for-aws.git
   cd agent-toolkit-for-aws
   ```

2. Install [Mise](https://mise.jdx.dev/) and trust the repo config:

   ```bash
   mise trust
   mise install
   ```

3. Run the full build (lint + validate + security):

   ```bash
   mise run build
   ```

## Publishing your Change

1. Create a new branch from `main`:

   ```bash
   git checkout main
   git pull origin main
   git checkout -b feat/your-feature-name
   ```

2. Make your changes and validate:

   ```bash
   mise run build
   ```

3. Commit and push:

   ```bash
   git add .
   git commit -m "feat: add descriptive commit message"
   git push -u origin feat/your-feature-name
   ```

4. Open a pull request against `main` using the [PR template](.github/pull_request_template.md).

## Security

If you discover a potential security issue, please notify AWS/Amazon Security via the [vulnerability reporting page](https://aws.amazon.com/security/vulnerability-reporting/). Please do **not** create a public GitHub issue.
