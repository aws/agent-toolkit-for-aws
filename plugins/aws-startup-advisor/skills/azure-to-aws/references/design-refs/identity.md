# Identity and secrets

Pass-2 rubric for identity and secret types that reach it. Thin by design: Key Vault and
user-assigned managed identities are Direct Mappings, so most of this resolves in pass 1.

**Outcome is `confidence: inferred`.** Never `deterministic`.

> **This file is about WORKLOAD identity — how a running resource authenticates.** HUMAN
> identity is not a resource mapping: it is Clarify category J, it always fires, and it
> defaults to a **fresh IAM Identity Center re-invite, not Entra ID federation**
> (decision 13.5f). Nothing in this file changes that default, and finding managed
> identities or workload federation in the estate is **not** consent to federate human
> sign-in. Defaulting to federation would leave the migration depending on the cloud being
> left — the exit is not an exit if AWS sign-in breaks when the Entra tenant lapses.

## 1. Eliminators

| Candidate           | Eliminated when                                                                                                                                                                                                                                   |
| ------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Secrets Manager** | the material is a **key used for cryptographic operations** rather than a stored credential. A key that is wrapped, unwrapped or used to sign belongs in **KMS**; Secrets Manager stores bytes, it does not perform crypto                        |
| **Secrets Manager** | the value is a **TLS certificate served by a load balancer**. That is **ACM**                                                                                                                                                                     |
| **Parameter Store** | the value needs automatic rotation with a rotation function. That is Secrets Manager                                                                                                                                                              |
| **IAM user**        | **ALWAYS, for a workload.** A managed identity becomes an IAM **role** assumed by the compute, never a long-lived access key. Emitting an IAM user with keys for a workload that had no keys is a security regression introduced by the migration |

## 2. Operational model

| Source                                                | Target                                                                                                                | Why                                                                                                                                       |
| ----------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------- |
| `Microsoft.KeyVault/vaults`                           | **Secrets Manager**, plus **KMS** if the vault has keys and **ACM** if it has certificates                            | Fast-path row. The split is by what the vault CONTAINS, which is why the row's note records whether a keys or certificates child was seen |
| `Microsoft.KeyVault/vaults/secrets`                   | **no target** — names feed the parent vault                                                                           | Fast-path skip. **Names only, never values** — the secret boundary in `extract-terraform.md` applies                                      |
| `Microsoft.KeyVault/vaults/keys`                      | **KMS key** on the parent's mapping                                                                                   | A key is a crypto object, not a stored string                                                                                             |
| `Microsoft.KeyVault/vaults/certificates`              | **ACM**, or Secrets Manager when the certificate is consumed by application code rather than terminated at a balancer | The consumer decides, and the consumer is visible in the cluster's edges                                                                  |
| `Microsoft.ManagedIdentity/userAssignedIdentities`    | **IAM role**                                                                                                          | Fast-path row                                                                                                                             |
| `.../federatedIdentityCredentials`                    | **IRSA** or **EKS Pod Identity** on the parent role                                                                   | Genuinely equivalent: a Kubernetes service account trades a token for cloud credentials on both sides                                     |
| System-assigned identity (a property, not a resource) | the compute resource's **instance profile** or **task role**                                                          | It has no `resources[]` entry of its own, so it lands in the compute entry's `aws_config`                                                 |
| `Microsoft.Authorization/roleAssignments`             | **no target** — IAM policy is authored                                                                                | See § 3                                                                                                                                   |
| `Microsoft.AppConfiguration/configurationStores`      | **AppConfig**, or Parameter Store for plain key/value                                                                 | Values are not read; the secret boundary applies to a config store too                                                                    |

## 3. RBAC is authored, not translated

`Microsoft.Authorization/roleAssignments` and `roleDefinitions` are Skip Mappings, and
that is a deliberate refusal rather than a gap.

Azure RBAC and AWS IAM differ in the things that matter for a mechanical translation:
Azure assigns a role at a **scope** in a resource hierarchy that AWS does not have; AWS
policies attach to principals and carry resource ARNs, conditions and explicit denies with
different evaluation semantics. A translated policy would be **plausible and wrong**, and
the failure mode is either a privilege escalation or an outage — both silent until
exercised.

So:

1. **Read** the assignment for its `identity_grant` edge — "app X reads storage Y" is real
   architectural information and clustering uses it.
2. **Do not** emit an IAM policy document from it.
3. Record the _intent_ in the migration guide: the principal, the resource, and the access
   level, so a human authors the equivalent policy deliberately.
4. `azurerm_role_assignment` is the one borderline case in the association-only class: it
   **does** have an ARM type, so it gets an inventory entry AND contributes its edge.

**Least privilege does not survive a mechanical translation.** Saying so is more useful
than shipping a policy nobody reviewed.

## 4. Cluster context

- A vault referenced by more than one cluster is **ambient**: `secret_ref` is an ambient
  edge and never merges clusters (decision 13.4c). One Key Vault commonly serves the whole
  estate, and merging on it collapses the partition.
- A vault whose only referrer is one cluster maps inside that cluster.
- A managed identity with role assignments spanning clusters signals a shared platform
  service. Map the identity once; do not duplicate the role per cluster.

## 5. Output

Per `schema-design-aws.md` § `services[]`: `aws_service`, `aws_config` (secret names — never
values, KMS key usage, ACM domain), `confidence: "inferred"`,
`rubric_applied: "identity.md"`, and a `rationale` naming which criterion fired.

Every skipped role assignment emits `skipped_config_source` whose `detail` names the
`identity_grant` edge it produced.

## Status — build step 5b

Thin on purpose. Vaults and managed identities are fast-path rows; this file carries the
secret-versus-key-versus-certificate split, the RBAC refusal and its reasoning, and the
`namespace_routing` landing zone for `Microsoft.KeyVault/*` and
`Microsoft.ManagedIdentity/*` types with no row.
