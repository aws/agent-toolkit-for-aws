# Report Issue

Use this when the user reports that the skill gave incorrect guidance, a wrong recommendation, missing information, or could be improved. This is feedback about the skill instructions — not about an AWS service itself.

## Procedure

1. **Offer to help.** Let the user know you can help them submit feedback, and present the available channels:
   - **GitHub** (primary) — for bug reports and feature requests on the skill itself. Publicly tracked at `aws/agent-toolkit-for-aws`.
   - **AWS Support** — for issues tied to their AWS account, service behavior, or billing. Requires an AWS Support plan.
   - **Security concerns** — should not be filed publicly. Direct to AWS vulnerability disclosure.

   Ask which channel they'd prefer. If they decline to submit anything, thank them and move on.

2. **Categorize.** Determine which type of feedback this is:

   | Category | Signals | Example |
   |----------|---------|---------|
   | Wrong recommendation | "you should have said X not Y", "that's the wrong service" | Skill recommended DynamoDB but the user needed SQL joins |
   | Outdated fact | "that's not true anymore", "pricing changed", "that feature launched" | Knowledge card says no free tier but one exists now |
   | Missing service or feature | "you didn't mention X", "what about Y" | Skill didn't consider MemoryDB for a vector search workload |
   | Unclear guidance | "I don't understand", "that's confusing", "contradicts itself" | Selection logic was ambiguous about serverless |
   | Handoff failure | "it didn't load the skill", "I got stuck after choosing", "no service skill" | Skill chose Aurora PostgreSQL but couldn't hand off to the service skill |

3. **Capture as an assertion.** Structure the feedback as a test case — this is the most actionable format for improving the skill:

   ```json
   {
     "prompt": "<what the user asked, paraphrased>",
     "expected_service": "<what the correct answer should be>",
     "actual_service": "<what the skill recommended>",
     "category": "<wrong-recommendation | outdated-fact | missing-coverage | unclear-guidance | handoff-failure>",
     "detail": "<brief explanation of why the expected answer is correct>"
   }
   ```

   For non-selection feedback (outdated facts, unclear guidance), omit `expected_service` and `actual_service` and expand `detail`.

4. **Confirm with the user.** Summarize what you captured in a sentence or two and ask if it's accurate. Let them correct anything before you proceed to submission.

5. **Route to the right channel.**

   Based on what the user chose in step 1:

   **GitHub — Bug report** (wrong recommendation, outdated fact, missing coverage, unclear guidance, handoff failure):
   - Direct the user to: `https://github.com/aws/agent-toolkit-for-aws/issues/new/choose` and select the bug report template.
   - If you have access to GitHub tools (gh CLI, GitHub MCP), help pre-fill the template from the assertion captured above.

   **GitHub — Feature request** (new capability, new service coverage, workflow suggestion):
   - Direct the user to: `https://github.com/aws/agent-toolkit-for-aws/issues/new/choose` and select the feature request template.

   **AWS Support** (private, or account-specific issues):
   - Some users prefer not to file publicly. AWS Support is the right channel for private feedback, account-specific issues, service behavior, billing, or quotas.
   - Direct them to: `https://console.aws.amazon.com/support/home#/case/create`
   - Help them identify the right category: the AWS service involved, whether it's technical or account/billing, and the severity.

   **Security issue:**
   - Do NOT file as a public GitHub Issue. Tell the user: "Security issues should not be reported publicly. Please report security concerns through AWS's vulnerability disclosure process at https://aws.amazon.com/security/vulnerability-reporting/"

6. **Confirm.** Share the issue or support case URL with the user, or confirm they have the link to proceed.
