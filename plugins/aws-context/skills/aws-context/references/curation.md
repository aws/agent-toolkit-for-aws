# Curating AWS Context

You change the graph by submitting a **change set**. The graph's curation policies decide
whether it applies right away or waits for a curator in the AWS Context console. You record
a session by sending a **trace**.

Change sets take the graph's ID or ARN. Traces take the graph's full agent context ARN
(`arn:aws:context:<region>:<account>:agent-context/<id>`). If you only have the ID, ask the
user for the ARN from the graph's Settings tab in the AWS Context console.

## Change sets

1. **Find the target.** Search for the entity, then traverse one level. Done when you know the node's ID, its `nodeType`, its source (for example AWS Glue) and what connects to it. Names repeat across sources, so match on type and source, not just the name.
2. **Pick the kind of change.**
   - **Add.** First search for the entity under other names. If it exists, update or merge instead.
   - **Update.** Use the UPDATE operation. It changes only the properties you send. Copy the node's `nodeType` and the properties its ID is built from (for a Glue column, `tableArn` and `name`) from the traverse result into the operation, next to the properties you change. Do not use PUT on an existing node: PUT replaces all of the node's properties and is refused on nodes a source owns.
   - **Delete.** You can delete single nodes and edges, including a Glue column. A source re-creates a node it owns the next time it syncs, so tell the user that and offer to remove it at the source instead. A root that a source wrote, such as a Glue table, cannot be deleted with a change set, so do not send one: to remove a Glue table and its columns, the user drops the table in AWS Glue and the next sync removes it. Send the delete of a root no source wrote on its own, not with other operations. Ontology nodes cannot be deleted.
   - **Merge duplicates.** Name exactly two nodes of the same type. Both stay in the graph and stay searchable. The service adds a combined node that unions their properties and links each duplicate to it. Tell the user the duplicates are linked, not that one was removed.
   - **Import an ontology.** A failed import that applied without review is retried as in step 4, with the same `clientToken`. One that a curator accepted cannot be retried: import a new ontology version instead.
3. **Show the change, then wait.** Describe exactly what will change and why, such as what the user said or which source shows the correct value. Tell the user it may apply immediately, ask whether to send it, and end your turn. The request that asked for the change does not approve the exact change you prepared. Done when the user approves it in a later message, for example "yes" or "send it".
4. **Call CreateChangeSet** with a new UUID as `clientToken`. If the call times out, loses its connection or returns an internal error, resend the identical request with the same token once. A resend never applies a change twice. It retries a write that failed, though a retried delete of a whole root can come back PENDING. If it fails again, check the request against the rules in step 2, because the service can report an invalid request as an internal error. If you change the request, show the new change and wait for the user's approval as in step 3, then send it with a new token; otherwise show the error and stop. A resend can report an out-of-date status, so check it afterwards with GetChangeSet.
5. **Explain the status** it returns:

   | Status | Meaning | Tell the user |
   |---|---|---|
   | PUBLISHED | Applied to the graph | The change is live |
   | PENDING | A curation policy held it for review | A curator accepts or rejects it in the AWS Context console |

6. **Track.** Use GetChangeSet for one change set, and ListChangeSets with a status to show, for example, everything still PENDING for the graph. Later statuses:

   | Status | Meaning | Tell the user |
   |---|---|---|
   | AUTHORIZED | A curator accepted it and it is being applied | Check again shortly with GetChangeSet |
   | SUPPRESSED | A curator rejected it, its review window expired, or a newer change replaced it | It will not apply. Resubmit only with a different change |
   | FAILED | It could not be applied, either when it was created or after a curator accepted it | Show the error. If it failed when created (CreateChangeSet returned an error), resend the identical request with the same `clientToken`, as in step 4. If a curator had accepted it, create a new change set with a new `clientToken` after the user approves it as in step 3, or for an ontology import, import a new ontology version |

## Traces

1. Record a trace only when the user asks.
2. Remove credentials, tokens, keys, personal data the user has not approved, and anything they ask to leave out.
3. Show the user what the trace will contain and which graph it is for, and in the same message ask who may see what AWS Context learns from it: only them, everyone who can read the graph, or specific people or groups. Then end your turn: asking to save the session does not approve the content you prepared. Done when the user approves the content in a later message and has chosen the readers.
4. Call PutTrace with the graph's agent context ARN in `agentContextArns`. Set `accessControlConfig` from the user's choice:
   - **Only them:** leave `accessControlConfig` out. If PutTrace refuses because the caller has no end user, nothing was stored: tell the user this connection cannot limit a trace to them, and ask them to choose again.
   - **Everyone who can read the graph:** one entry, `ALLOW` with principal `*`.
   - **Specific people or groups:** one `ALLOW` entry each, with `principalType` `USER` and the person's sign-in email, or `GROUP` and the group ID the user gives you. Ask for the exact values. A wrong value is accepted but matches no one, so nobody sees the insights.
5. If PutTrace says trace analysis is disabled for the graph, nothing was stored. Tell the user that an administrator must turn on trace analysis, with a trace analysis role, in the graph's settings before traces can be sent.
