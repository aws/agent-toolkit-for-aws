---
_fragment: identity
_of_phase: clarify
_contributes:
  - preferences.json
---
# Clarify identity and team access
Ask once per estate, in the first assumption batch. Render dashboard SSO, team roles, and who can deploy are not in the inventory, so these facts are never discovered. A user who states "small team, no SSO, deploys from CI" resolves both rows without follow-up.

| `question_id` | Topic | Ask | Default and consequence | `decision_changed` | Consumer |
| --- | --- | --- | --- | --- | --- |
| `identity.human_sign_in` | `global` | Do people keep an existing identity provider (Okta, Entra ID, Google Workspace) for AWS sign-in, or start with a new IAM Identity Center directory? Ask only when the Render workspace uses SSO or more than one human operator is named. | `identity_center_directory`: create users and groups in IAM Identity Center and re-invite the team. | IAM Identity Center identity source | Generate `MIGRATION_GUIDE.md` Prerequisites names the source and the SAML/SCIM steps. |
| `identity.deploy_principal` | `global` | Who or what deploys after cutover: a CI system, named engineers, or Render still deploying during coexistence? | `ci_oidc_role`: a CI-assumed role scoped to ECR push and the selected deploy action. No long-lived access keys. | Deployment identity and its IAM trust | Generate `MIGRATION_GUIDE.md` Build and deployment section and promote-image script prerequisites. |

Both rows have `resource_id` null. When `deploy_principal` is `render_during_coexistence`, reuse the OIDC facts the global fragment already collects. Do not ask them twice.
