# Pausing and stopping AWS DevOps Agent

Cover this **during DISCLOSE, before the user commits** — not only when they ask. A founder deciding
whether to enable a metered agent needs to know the exit before they take the entrance.

## What pausing stops

Say all four. A partial answer makes the pause look safer than it is:

1. **Autonomous incident investigation.** If something breaks while paused, they are investigating by hand.
2. **Proactive incident-prevention recommendations.**
3. **Release-readiness review** on pull requests.
4. **Continuous learning of their environment.** This is the one people do not expect — on resume, the
   agent needs time to rebuild that context. Investigations immediately after a resume may be less sharp.

While paused, the agent does not run and does not draw down credits or incur charges. Setup is preserved,
so resuming does not mean starting over. Say both parts — the second is what makes pausing feel safe
enough to actually use.

## Cancelling a running investigation

An investigation runs 5–8 minutes and bills per second throughout. If a user starts one by mistake, cancel
it rather than letting it finish — that is real money, roughly $0.50 per minute.

Use the `CancelTask` operation on the Agent Space. Confirm it stopped; do not assume.

## Stopping completely

Disconnecting the MCP server stops *this client* from invoking the agent. It does **not** disable the
agent itself — anything scheduled or autonomous inside the Agent Space keeps running and keeps billing.

So when a user says "turn it off," establish which they mean:

- **"Stop it costing me money"** → pause or disable in the Agent Space. Removing the MCP config is not enough.
- **"Get it out of my editor"** → removing the MCP server config is sufficient.

Getting this wrong is the expensive direction. If in doubt, do both and say so.

## Revoking a token

If a bearer token was used and may be exposed:

1. Web app → Settings → Access Tokens → select → **Revoke**. Immediate and irreversible.
2. To block all token access at once: Agent Space → Configuration → Access tokens → **Disable**. Existing
   tokens survive but stop working until re-enabled.

Rotating preserves the token's name, scopes, and IP allowlist while invalidating the old value — usually
what someone wants when a token has simply aged rather than leaked.

## Never do this unprompted

Do not pause, disable, revoke, or cancel on the user's behalf without asking — even when it would clearly
save them money. Pausing during an active incident could leave them blind at the worst moment.

Surface the cost, recommend the action, and let them decide. The decision is theirs to make.
