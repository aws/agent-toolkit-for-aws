# Artifact Delivery and Harness Handoff

Load this reference whenever a request asks you to save a query, report, traversal, execution plan, or resource handoff at a named path.

## Required artifact contract

A downstream validator reads the saved file, not the natural-language response. When a prompt says "save ... at `<path>`":

1. Write the artifact before any long explanation. As soon as the deliverable is ready, call `file_write(path="<exact path from the prompt>", content="<complete file content>")`.
2. Use the exact relative path from the prompt. Paths such as `artifacts/neptune/migration-compat-report.json` are relative to the working directory; parent directories are created by the tool.
3. Wait for the successful `file_write` result, then keep the response to one or two sentences.
4. Never paste the content into chat and ask the user or harness to save it. That does not create the artifact and fails downstream validation.

## Time-bounded tasks

Artifact tasks have a finite execution budget. Produce and save the requested content directly instead of writing a long preamble or performing exploratory work first. The most common failure is a correct answer that is never written because the response spends its budget explaining before calling `file_write`.

## Harness-owned infrastructure

Follow the ownership boundary in the prompt. If the task says to author a query and the harness owns the graph, write the query artifact and stop; do not create, poll, query, or delete infrastructure. If the task says to create a resource and hand it off:

1. Perform only the explicitly requested and confirmed create action, following [action-safety.md](action-safety.md).
2. Apply the required inline tags and follow-up `tag-resource` call.
3. Immediately write the returned resource identifier and name to the exact artifact path.
4. Stop at the requested handoff point. Do not wait for `AVAILABLE`, run data-plane queries, or delete the resource when the prompt assigns those steps to the harness.

The artifact is the deliverable. Prose is only a brief confirmation after the file exists.
