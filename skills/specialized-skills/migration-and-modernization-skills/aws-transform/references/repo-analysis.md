# Repo Analysis & TD Matching

**Local mode only.** Repo analysis inspects files on the local filesystem — it
cannot run inside remote containers. For remote mode, skip this step and let the
user specify which TDs to apply. If the user selected remote mode, do NOT attempt
to run the detection commands below.

Inspect repositories and match them against available Transformation Definitions.

## TD Discovery (Required First Step)

```bash
atx custom def list          # Human-readable
atx custom def list --json   # Programmatic parsing
```

Never hardcode TD names. Only match repos against TDs that appear in this output.
If `atx` is not installed, install it first — do not fall back to guessed names.

## Known AWS-Managed TDs (Reference Only)

This table is a guide for signal detection, NOT a substitute for `atx custom def list --json`.
TD names change over time. Always use actual names from the live output.

| TD Name (may change) | Description | Key Config |
|---------|-------------|------------|
| `AWS/java-version-upgrade` | Upgrade Java/JDK version (any source → any target) | Target JDK version (e.g., 17, 21) |
| `AWS/python-version-upgrade` | Upgrade Python version (3.8/3.9 → 3.11/3.12/3.13) | Target Python version |
| `AWS/nodejs-version-upgrade` | Upgrade Node.js version (any source → any target) | Target Node.js version |
| `AWS/java-aws-sdk-v1-to-v2` | Migrate AWS SDK for Java v1 → v2 (Maven or Gradle) | None required |
| `AWS/python-boto2-to-boto3` | Migrate Python boto2 → boto3 | None required |
| `AWS/nodejs-aws-sdk-v2-to-v3` | Migrate AWS SDK for JavaScript v2 → v3 | None required |
| `AWS/early-access-java-x86-to-graviton` | Migrate Java x86 code to ARM64/Graviton | None required |
| `AWS/comprehensive-codebase-analysis` | Tech debt analysis + documentation generation | Optional: `additionalPlanContext` for focus area |

## Transformation Patterns

| Pattern | Complexity | Examples |
|---------|-----------|----------|
| Language Version Upgrades | Low-Medium | Java 8→17, Python 3.9→3.13, Node.js 12→22 |
| API and Service Migrations | Medium | AWS SDK v1→v2, Boto2→Boto3, JUnit 4→5, javax→jakarta |
| Framework Upgrades | Medium | Spring Boot 2.x→3.x, React 17→18, Angular, Django |
| Framework Migrations | High | Angular→React, Redux→Zustand, Vue.js→React |
| Library and Dependency Upgrades | Low-Medium | Pandas 1.x→2.x, NumPy, Hadoop/HBase/Hive |
| Code Refactoring | Low-Medium | Print→Logging, string concat→f-strings, type hints |
| Script/File Translations | Low-Medium | CDK→Terraform, Terraform→CloudFormation, Bash→PowerShell |
| Architecture Migrations | Medium-High | x86→Graviton, on-prem→Lambda, server→containers |
| Language-to-Language Migrations | Very High | Java→Python, JavaScript→TypeScript, C→Rust |
| Custom/Org-Specific | Varies | Internal library migrations, coding standards enforcement |

Service routing: COBOL/mainframe → use AWS Transform for Mainframe. .NET Framework → consider AWS Transform for Windows. VMware → consider AWS Transform for VMware.

## Detection Commands

### Python

```bash
cat <repo>/.python-version 2>/dev/null
cat <repo>/pyproject.toml 2>/dev/null | head -30
cat <repo>/setup.cfg 2>/dev/null | head -30
cat <repo>/requirements.txt 2>/dev/null | head -10
```

### Java

```bash
cat <repo>/pom.xml 2>/dev/null | head -60       # Look for <java.version>, <maven.compiler.source>
cat <repo>/build.gradle 2>/dev/null | head -40   # Look for sourceCompatibility
cat <repo>/.java-version 2>/dev/null
```

### Node.js

```bash
cat <repo>/package.json 2>/dev/null              # Look for engines.node
cat <repo>/.nvmrc 2>/dev/null
cat <repo>/.node-version 2>/dev/null
```

## AWS SDK Detection

| Signal | Language | What It Means |
|--------|----------|---------------|
| `import boto` / `from boto` (NOT boto3) | Python | Legacy boto2 — needs migration |
| `com.amazonaws` or `aws-java-sdk` in pom.xml | Java | SDK v1 — needs migration |
| `"aws-sdk"` in package.json (NOT `@aws-sdk`) | Node.js | SDK v2 — needs migration |

```bash
# Python boto2
grep -rlE "import boto([^3]|$)|from boto([^3]|$)" <repo> --include="*.py" 2>/dev/null | head -3
# Java SDK v1
grep -rl "com.amazonaws" <repo> --include="*.java" 2>/dev/null | head -3
cat <repo>/pom.xml 2>/dev/null | grep -i "aws-java-sdk"
# Node.js SDK v2
cat <repo>/package.json 2>/dev/null | grep '"aws-sdk"'
```

## Graviton Detection

```bash
grep -rlE "x86_64|amd64|x86-64" <repo> --include="*.yml" --include="*.yaml" --include="Dockerfile" 2>/dev/null | head -3
```

Currently Java-only. Match against Graviton migration TD if available.

## Match Report Format

```
Transformation Match Report
=============================
Repository: <name> (<path>)
  Language: <lang> <version>
  Matching TDs:
    - <td-name> — <description>

  Other available TDs (may also apply):
    - <custom-td> — <description>

Summary: N repos analyzed, M have matches (T total jobs)
```

Group by repository. Show detected version. Include repos with no matches.
List custom TDs (non-`AWS/` prefix) under "Other available TDs".

## Edge Cases

| Case | Handling |
|------|----------|
| Repo already up-to-date | List upgrade TD but note current version |
| Monorepo (multiple languages) | List all matching TDs — each is a separate job |
| Mixed local + remote repos | Clone git URL repos locally for inspection, inspect local paths directly |
| Custom TDs in account | Show under "Other available TDs" per repo |
| Git clone fails | Report error, continue with remaining repos |

## Cleanup

Do NOT delete cloned repos after analysis — they are needed for local execution.
Track cloned repo paths and inform the user at session end so they can delete them.
