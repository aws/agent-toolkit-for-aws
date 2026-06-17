---
description: Open a chat session with the AWS DevOps Agent and ask a question
argument-hint: [question]
---

Use the `chatting-with-aws-devops-agent` skill workflow.

1. Gather any obviously relevant local context (IaC, dependency manifest, recent git commits) and inject it alongside the question.
2. Call `aws_devops_agent__chat(message="[Local Context]\n<context>\n\n[Question]\n$ARGUMENTS")`.
3. Show the response to the user.
4. If the user wants follow-ups, use `aws_devops_agent__send_message(execution_id="<from chat response>", content="<follow-up>")`.

If `$ARGUMENTS` is empty, prompt the user for a question first.
