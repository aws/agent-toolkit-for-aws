# Dependency Conflict Resolution — Allowlist Gate

A **mechanical safety gate**, not a recipe book. Solver-driven verification already lives in llm2bedrock-code-rewriter §12.3 (`poetry lock`, `uv lock`, `npm install --package-lock-only`, etc.) and stop-and-report-on-conflict already lives in §12.4. This skill adds **one** thing on top: prevent the agent from "fixing" a resolver failure by silently deleting a dependency the customer's project relied on before this rewrite session.

All commands run on the host against the repository checkout. `<REPO>` is the repository path supplied in your context.

## When to load

Load **before llm2bedrock-code-rewriter §14's `git commit`**, after §12.3 has run lockfile regeneration cleanly. The gate inspects the working-tree manifest diff for removals and decides whether each removal is permitted.

The skill is also useful any time another agent (`infra-deployer`, `app-migrator`) edits a manifest and is about to commit — wire it into those flows when needed.

## The rule

A removal of `<pkg>` from `pyproject.toml` / `requirements*.txt` / `setup.py` / `setup.cfg` / `package.json` is permitted **only if** `<pkg>` was _added in this rewrite session_. If `<pkg>` existed before the rewriter began, the agent must NOT delete it — even if removing it would make the resolver pass.

Why: a name-based "is this package still imported anywhere?" blocklist is unreliable. Package name ≠ import name in many ecosystems (`beautifulsoup4` → `import bs4`, `Pillow` → `import PIL`, `google-cloud-storage` → `import google.cloud.storage`). The allowlist (only allow removing what we just added) requires no name-mapping table and handles namespace packages and JS scoped packages by construction.

## How to run the gate

The rewriter's §7 persists the baseline commit SHA in `/tmp/dcr-baseline-sha`. The gate uses it as the comparison anchor (a branch name like `bedrock-migration` would be wrong here — the rewriter works on that branch, so `bedrock-migration..HEAD` is empty by definition).

### Step A: list removed package names

Diff the working tree against the baseline SHA (not `HEAD`) so the gate catches removals across any intermediate commits between the §7 baseline and the §14 commit:

```bash
cd <REPO> && BASELINE=$(cat /tmp/dcr-baseline-sha 2>/dev/null) && [ -n "$BASELINE" ] && git diff --unified=0 $BASELINE -- pyproject.toml requirements*.txt setup.py setup.cfg package.json 2>/dev/null
```

A line starting with `-` (and not `---`) inside a dependency list is a removal. Extract the package name from each. Examples of how the name appears per format:

- `pyproject.toml` (Poetry / PEP 621): `langchain = "^0.1.14"` → name is `langchain`.
- `requirements.txt`: `openai==1.2.3` → name is `openai`.
- `package.json`: `"langchain-openai": "^0.1.0",` → name is `langchain-openai`.

### Step B: per removed package, ask "did the rewriter add this?"

Use `git diff $BASELINE` (same anchor as Step A) — `git log -p $BASELINE..HEAD` would miss everything because the gate runs before §14's commit, so the rewriter's edits are still uncommitted in the working tree.

Use a **format-aware, delimiter-anchored** match — never plain substring search. A substring match on `openai` would falsely match an addition of `openai-agents`, and the gate would let a customer-pre-existing `openai` removal slip through. Pick the pattern matching the manifest the package was removed from:

```bash
# package.json (quoted keys, JSON-style)
cd <REPO> && BASELINE=$(cat /tmp/dcr-baseline-sha 2>/dev/null) && [ -n "$BASELINE" ] && git diff $BASELINE -- package.json 2>/dev/null | grep -E '^\+[^+]' | grep -F '"<pkg-name>":'

# pyproject.toml (name followed by whitespace + `=` or `[`, e.g. `langchain = "^0.1"` / `langchain = [...]`)
cd <REPO> && BASELINE=$(cat /tmp/dcr-baseline-sha 2>/dev/null) && [ -n "$BASELINE" ] && git diff $BASELINE -- pyproject.toml 2>/dev/null | grep -E '^\+[^+]' | grep -E '^\+[[:space:]]*<pkg-name>[[:space:]]*[=\[]'

# requirements.txt / setup.py / setup.cfg (name followed by a version specifier or EOL)
cd <REPO> && BASELINE=$(cat /tmp/dcr-baseline-sha 2>/dev/null) && [ -n "$BASELINE" ] && git diff $BASELINE -- requirements*.txt setup.py setup.cfg 2>/dev/null | grep -E '^\+[^+]' | grep -E '^\+[[:space:]]*<pkg-name>([=<>~!;[:space:]]|$)'
```

If grep finds at least one matching addition since `$BASELINE`, the rewriter introduced the package — removing it is fine.

If grep finds nothing, the package was pre-existing. **Abort the commit and stop**, recording in the rewriter's returned notes field something such as: `"gate blocked removal of pre-existing package <pkg> from <manifest>. The rewriter must not delete customer-pre-existing dependencies — only the package(s) it added itself. Resolver-failure recovery requires human judgment here."`

### Step C: fail closed if baseline is missing

If `/tmp/dcr-baseline-sha` does not exist, the gate has nothing to compare against. Treat **all removals as forbidden** and record in the rewriter's returned notes field: `"baseline SHA file missing at /tmp/dcr-baseline-sha — caller must run rewriter §7 first; cannot verify removals are session-introduced"`. Better to block all removals than silently allow them.

## Expected false positive — document, don't loop

A legitimate package rename (`pkg-A` removed in the same edit that adds `pkg-A-new`) will trigger the gate because `pkg-A` is pre-existing. This is **correct conservative behavior**. The agent must stop and explain the rename in its returned notes field so a human approves; it must NOT loop trying to satisfy the gate.

## What this skill is NOT responsible for

- Picking the right solver (`poetry lock` vs `uv lock` vs `npm install` etc.) — llm2bedrock-code-rewriter §12.3 handles that.
- Diagnosing or auto-fixing resolver failures — §12.4's policy is "stop and report; do not modify the manifest further to make resolution succeed." This skill aligns with that policy and only adds a safety check on the _kind_ of edit the agent is allowed to commit.
- Managing retry budgets for resolver failures — there is no auto-retry in this flow by design.
