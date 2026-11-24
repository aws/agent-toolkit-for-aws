---
name: context-login
description: Sign this agent in to AWS Context, or check that it is signed in
---

The user wants to sign in to AWS Context. Read
`${CLAUDE_PLUGIN_ROOT}/skills/aws-context/references/connecting.md` (the `connecting.md` reference of this plugin's aws-context skill) and follow it.

1. If the AWS Context tools are loaded, make one read-only call (a search against the
   user's graph) to check the connection. If it works, tell the user they are signed in
   and stop.
2. Otherwise pick the mode from `connecting.md` and tell the user exactly what to run or
   click to sign in. The user runs it. Do not run login commands yourself and do not ask
   for tokens or keys.
3. When the user says they are done, retry the read-only call and report the result.
