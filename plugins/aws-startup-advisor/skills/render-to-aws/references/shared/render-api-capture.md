# Render API capture boundary

The main window invokes `capture-render-api.py` only after explicit read-only consent and exactly one workspace confirmation. The helper accepts a typed category and IDs, never a URL, method, token, or header. It constructs only the exact `render-rest-contracts.json` GET endpoint at `https://api.render.com`, reads `RENDER_API_KEY` from its own environment, and never prints or persists the key.

`RejectRedirects`, a custom `urllib.request.HTTPRedirectHandler`, raises before any 301, 302, 303, 307, or 308 target request is built or sent. No same-origin exception exists. The stable outcome is `redirect_rejected`; redirect destinations receive neither a request nor an authorization header.

Every response is bounded before persistence: 4 MiB compressed wire bytes, 12 MiB decompressed bytes, 30 seconds, JSON depth 50, 100,000 nodes, 20 pages, 10 MiB projected category output, and 50 MiB attempt output. Two retries are permitted only for 429, 5xx, or transport-transient outcomes, with retry delay capped at five seconds. Authentication, redirects, ownership, envelopes, bounds, capability drift, and schema failures are not retried.

Every direct or wrapped object must prove the confirmed workspace through its owner field or the active digest-bound ownership index and parent resource. Events retain only ID, resource ID, type, timestamp, status code, request window, and provenance. Build Sources retain only identity, owner, repository, branch, commit or immutable artifact, build command, linked service IDs, environment promotion IDs, and build/runtime variable names. Unknown event or Build Source fields are capability drift and fail closed.

REST workspace enumeration, PostgreSQL listing, Key Value listing, and service-instance listing are inactive because their REST contracts are unreviewed. Requests for `workspaces_list`, `postgres_list`, `keyvalues_list`, or `service_instances` fail before network access as `unsupported_contract`; the reviewed Render CLI 2.30.0 projections are the canonical discovery sources for those surfaces. Do not infer REST enrichment from the presence of an inactive table row.

Environment-variable values, environment-group values, secret files, connection information, database rows, Key Value contents, exports, tokens, and application logs have no active endpoint row.
