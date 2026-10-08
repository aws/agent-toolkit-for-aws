# Reviewing Security Lake Configuration

## Overview

Produces a configuration summary of Amazon Security Lake reporting current state. Verifies data lake enablement, AWS log source coverage, subscriber setup, and organization-level rollout.

Works from both standalone and delegated administrator accounts.

## Classify the Request

| Request Pattern | Workflow |
|---|---|
| "Is Security Lake configured correctly?" | A: Review Single Account |
| "Check org-wide Security Lake coverage" | B: Review Organization Coverage |

## Workflow A: Review Single Account

1. Check data lake status:

   ```bash
   aws securitylake list-data-lakes
   ```

   Verify each expected region has a data lake with `createStatus` = COMPLETED.

   **Security check:** Verify the data lake has KMS encryption configured — check
   `encryptionConfiguration.kmsKeyId` in the `list-data-lakes` output — and separately verify
   TLS in transit for delivery and subscriber or consumer access. Apply the parent S3
   destination-policy requirements. If the scoped reads do not prove transport protection,
   report it UNKNOWN.

2. Discover current supported AWS sources, then read configured coverage:

   - Use the current Amazon Security Lake documentation as the source of truth for supported AWS log source names and regional availability. Prefer AWS MCP documentation search/read when available; otherwise use the official Security Lake documentation over HTTPS. Do not treat examples in this Skill as a closed source list.
   - If current documentation is unavailable, report the source names returned by the account APIs and mark supported-but-unconfigured coverage UNKNOWN rather than comparing against a remembered list.

   ```bash
   aws securitylake get-data-lake-sources
   ```

   Report every returned `sourceName`, account and `sourceStatuses` entry, including source names not previously seen. A source absent from this response is not proven unsupported or unconfigured outside the queried account and Region scope.

3. List configured log sources for detail:

   ```bash
   aws securitylake list-log-sources
   ```

   Treat `list-log-sources` as configured-source inventory, not as the catalog of every source type Security Lake supports.

4. Check subscribers:

   ```bash
   aws securitylake list-subscribers
   ```

   For each subscriber, report returned access type and configuration fields. Do not invent an active/healthy status; subscriber existence does not prove consumption or delivery.

5. Present results:

   | Check | Status | Detail |
   |---|---|---|
   | Data lake enabled (region) | Configured | createStatus=COMPLETED |
   | AWS source `<sourceName>` | Configured / Not Configured / UNKNOWN | Account, Region, version and returned status |
   | Subscribers | N configurations observed | Delivery/consumption NOT ASSESSED unless evidenced |

6. MUST report every configured source returned by the account APIs and assess every supported source identified from the latest documentation for the reviewed Region. Newly supported source names are included automatically.

7. SHOULD flag any source with a non-healthy status. If current supported-source documentation could not be read, state that completeness against the supported catalog is UNKNOWN.

## Workflow B: Review Organization Coverage

1. Get organization configuration:

   ```bash
   aws securitylake get-data-lake-organization-configuration
   ```

   Check which sources have auto-enable configured.

2. List exceptions:

   ```bash
   aws securitylake list-data-lake-exceptions
   ```

   Identify accounts/regions with failures.

3. Present organization summary:

   | Check | Status | Detail |
   |---|---|---|
   | Org auto-enable (each source) | Configured / Not Configured | ... |
   | Exceptions | Count | ... |

4. For each exception:

   | Account | Region | Source | Exception Reason |
   |---|---|---|---|
   | `<account-id>` | us-east-1 | VPC_FLOW | INTERNAL_ERROR |

5. MUST report all exceptions.

6. SHOULD compare auto-enable sources against the current supported and default source set from official documentation for each reviewed Region. If that documentation could not be read, report the comparison as UNKNOWN.

7. MUST NOT paginate through all member accounts by default.

8. MUST only enumerate individual member status if user explicitly requests it.

## Constraints

- MUST NOT modify Security Lake configuration
- MUST NOT query data stored in Security Lake
- SHOULD handle AccessDeniedException — indicate caller may not be delegated admin

## Troubleshooting

| Issue | Resolution |
|---|---|
| list-data-lakes returns empty | Security Lake not enabled in this account/region |
| AccessDeniedException | Caller is not the Security Lake delegated admin or not enabled. Note: may have empty error body |
| UnauthorizedException | Same as above |
| get-data-lake-organization-configuration fails | Organization features may not be enabled |
| Sources show FAILED status | Note in report — may indicate IAM or SLR issues |

## Output Sensitivity

Configuration output reveals data lake S3 bucket details, KMS key ARNs, subscriber identities and access types, log source coverage across accounts and regions, and organization exception details. Present source enablement and subscriber summary first; offer raw API responses on request.
