# Application-Source Contract

`application-source-contract.schema.json` defines a request and findings document for a future
application-source reviewer. It is data only: no current phase or target reads it.

Requests expose only selected question names, application identity, process/configuration names,
attachment and Private Space presence, add-on IDs, and selected estate application IDs.
Configuration values, credentials, connection strings, and source excerpts have no dedicated
fields. Free-text fields must contain concise summaries or redacted commands, never literal secret
values or copied source. JSON Schema cannot establish that property from arbitrary text; the
producer and executable validator must enforce it before retaining findings.

`PRESENT` carries a non-empty typed record array; `ABSENT_WITHIN_REVIEWED_SCOPE`, `UNKNOWN`, and
`NOT_APPLICABLE` carry `null`. JSON Schema requires an explanation for `UNKNOWN`. The executable
validator must also require exactly one finding per requested question, reject unrequested
findings, reject unsupported absence claims, check cross-record references when their defining
questions are present, and reject reversed source line bounds. Sources are optional direct relative
paths with optional line bounds.

Heroku process and configuration names provide non-secret inventory context, not an allowlist.
Source review may discover additional names; those differences must be retained for later drift or
missing-configuration assessment rather than rejected.

Configuration-name context and each typed record array are capped at 256 entries. Callers must
report an exceeded bound rather than silently truncating the submitted information.

## Field-Purpose Review

The field set was trimmed before implementation. Shared component/process/listener/dependency/
relationship IDs make references checkable; setting names never carry values.

| Question                      | Retained fields                                                                                                                                                                            | Approved purpose                                                                             |
| ----------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | -------------------------------------------------------------------------------------------- |
| `runtime_framework`           | `component_id`, `root`, `runtime`, `runtime_version`, `framework`                                                                                                                          | Identify deployable units and Beanstalk platform/runtime assessment.                         |
| `build_method`                | `component_id`, `method`, `authority_path`, `context_path`                                                                                                                                 | Determine required build artifacts and customer build work.                                  |
| `build_time_settings`         | `component_id`, `setting_name`, `stage`, `required`                                                                                                                                        | Identify build inputs that artifact generation must declare by name.                         |
| `process_commands`            | `process_id`, `component_id`, `type`, `name`, `command`, `entrypoint`                                                                                                                      | Generate process launch artifacts and assess non-web work.                                   |
| `runtime_settings`            | `component_id`, `process_ids`, `setting_name`, `use`, `required`, `default_present`, `loaded_dynamically`                                                                                  | Generate named runtime inputs and flag customer work for unresolved dynamic loading.         |
| `network_listeners`           | `listener_id`, `component_id`, `process_id`, `transport`, `port_setting_name`, `default_port`, `intended_traffic`                                                                          | Assess Beanstalk ingress and provide listener inputs to generated artifacts.                 |
| `port_host_binding`           | `listener_id`, `host_setting_name`, `port_setting_name`, `fixed_host`, `fixed_port`, `host_configurable`, `port_configurable`, `beyond_loopback`                                           | Determine whether generated deployment settings can satisfy binding behavior.                |
| `heroku_runtime_behavior`     | `component_id`, `process_ids`, `metadata_name`, `use`, `effect`                                                                                                                            | Identify Heroku metadata dependencies requiring customer action.                             |
| `native_dependencies`         | `component_id`, `kind`, `name`, `phase`, `process_ids`, `os_constraints`, `architecture_constraints`                                                                                       | Assess platform compatibility and required build/runtime packages.                           |
| `release_setup_commands`      | `component_id`, `process_id`, `command`, `timing`, `purpose`                                                                                                                               | Generate deployment hooks or record required customer-run setup.                             |
| `recurring_jobs`              | `job_id`, `component_id`, `process_ids`, `name`, `mechanism`, `command`, `schedule`, `coordination`                                                                                        | Identify scheduler artifacts and coordination work.                                          |
| `health_routes`               | `component_id`, `process_id`, `listener_id`, `path`, `methods`, `success_statuses`, `redirects`, `authentication`, `required_headers`                                                      | Generate health checks and assess whether unauthenticated checks are viable.                 |
| `local_file_writes`           | `component_id`, `process_ids`, `setting_name`, `default_path`, `read_after_write`, `purpose`, `required_lifetime`, `cross_instance_required`                                               | Assess ephemeral storage compatibility and required persistent/shared storage work.          |
| `network_protocols`           | `component_id`, `process_ids`, `direction`, `listener_id`, `transport`, `application_protocol`, `port`, `application_managed_tls`                                                          | Assess Beanstalk protocol support and retain inputs for a private adapter.                   |
| `potential_private_endpoints` | `component_id`, `process_ids`, `reference_kind`, `reference_id`, `setting_name`, `literal_host`, `host_pattern`, `protocol`, `port`                                                        | Preserve endpoint candidates for a later private adapter without asserting privacy.          |
| `logs_telemetry`              | `component_id`, `process_ids`, `signal`, `destination`, `setting_name`, `file_path`                                                                                                        | Assess log/telemetry collection and required configuration artifacts.                        |
| `postgresql_extensions`       | `component_id`, `database_setting_name`, `extension`, `declaration_kind`, `action`                                                                                                         | Record database compatibility and customer follow-up, without selecting a replacement.       |
| `redis_usage`                 | `component_id`, `setting_name`, `roles`, `disposability`                                                                                                                                   | Assess persistence/failover needs; unknown disposability remains explicit.                   |
| `external_services`           | `dependency_id`, `component_id`, `process_ids`, `direction`, `category`, `service_reference`, `setting_name`, `role`, `protocol`, `port`, `authentication_mechanism`, `allowlist_behavior` | Identify connectivity and allowlist work and retain private-adapter inputs.                  |
| `application_connections`     | `relationship_id`, `caller_component_id`, `caller_process_ids`, `callee_application_id`, `setting_name`, `protocol`, `ports`, `mechanism`                                                  | Preserve selected-estate relationships for required connectivity work and a private adapter. |
| `addon_usage`                 | `inventory_addon_id`, `component_id`, `setting_name`, `usage`, `roles`                                                                                                                     | Classify retained/external, customer-owned follow-up, blocking, or unknown add-on use only.  |
| `webhooks`                    | `component_id`, `process_id`, `listener_id`, `path`, `methods`, `provider_reference`, `verification_mechanism`, `verification_setting_name`, `required_headers`                            | Generate ingress/health-adjacent settings and identify webhook verification work.            |

Runtime filesystem and symlink containment checks are intentionally deferred until a reviewer is
wired in; this contract checks only lexical path safety.
