# Deployment profile reference

The profile tells the fixing workflow how the application **actually runs**. Source configuration is only a draft; the developer confirms reality before a deployment-sensitive fix is designed.

## Collect and confirm

Explain why each question matters and recommend the safest compatible answer:

1. **Exposure:** localhost, tunnel, reverse proxy, load balancer, or direct public listener; external origin and TLS termination.
2. **Process topology:** listeners, ports, containers, supervisors, child processes, health checks, and which hops are directly reachable.
3. **Header trust:** trusted proxy peers and the identity, host, origin, scheme, and client-address headers each hop removes, overwrites, or preserves.
4. **Authentication:** enabled human sign-in methods, API-token clients, bootstrap and recovery, browser intent checks, WebSockets, and reconnect.
5. **Runtime mode:** production and development flags, debug middleware, background workers, and configuration source.
6. **Must-keep journeys:** ordinary user paths, machine integrations, deploy, restart, recovery, rollback, and observability.
7. **Freshness:** who confirmed the facts, when, against which deployed version, and which fields remain unknown.

Inspect source, local process configuration, container metadata, and non-secret runtime state where the developer authorizes it. Label each fact `source-derived`, `observed`, `developer-confirmed`, or `unknown`. Never turn a default into a confirmed deployment fact.

## Storage boundary

Private deployment facts are local only:

```text
.continuum/deployment-profile.local.md
```

With developer consent, create the file and append that exact path to the repository's `.git/info/exclude`. Verify it with:

```bash
git check-ignore --no-index .continuum/deployment-profile.local.md
```

Then check `git status --short` and ensure it is never staged. If the checkout has no `.git` metadata, store the profile in another developer-approved private path. Do not add a tracked ignore rule that advertises the existence of private deployment data unless the developer chooses to.

The profile may contain private origins and topology, but never passwords, keys, tokens, cookies, external IDs, credential-process output, or secret values. Prefer descriptions such as “owner-only HTTPS tunnel” where the exact identifier is unnecessary.

## Suggested headings

```markdown
# Continuum deployment profile

- Repository and source commit:
- Captured and confirmed at:
- Confirmed by:
- Overall provenance:

## Exposure and TLS
## Process and network topology
## Proxy and trusted headers
## Authentication and machine clients
## Production and development modes
## Must-keep journeys
## Deployment, restart, rollback, and recovery
## Field-level provenance
## Unknowns
```

This file informs design and rehearsal. It is not merge authorization. This plugin never merges; it only records a shadow prediction after real tests.

## House rules are separate

A product decision such as “normal use must not gain an extra confirmation step” is non-secret and reusable. Propose it in the tracked `.continuum/house-rules.md`, protected by normal repository review. Do not copy private topology into that file. Record the decision maker, rationale, scope, exceptions, and how a future change demonstrates compliance.

The public Continuum API does not ingest this local profile for GitHub repository sources. Do not state otherwise. Any future customer-context upload is a separate, explicitly approved feature.
