# Recommend Two Options — LTS vs Latest (Task 5)

Part of the Mode B workflow (see [mode-b-discovery.md](upgrade-planning-mode-b-discovery.md) for Tasks 1–4). Also used by Mode A advisory answers.

Always present both:

- **Latest version**: highest minor within the newest supported major. More features and performance, but shorter support window before the next required upgrade.
- **LTS version**: Aurora MySQL 3.10 (a designated LTS minor). Extended support window (~3 years), critical fixes only, fewer required upgrade cycles.

## Designated LTS versions

This table is authoritative for "what's the LTS version right now" questions when live AWS is unreachable. AWS designates an LTS release **per supported major version simultaneously** — there is no single engine-wide LTS value. The correct LTS minor is whatever `describe-db-engine-versions` / the AWS LTS page lists for the major the customer targets. You MUST answer "what's the current LTS version" per the major the customer is on (the LTS minor depends on the major), not as a single engine-wide answer, and you MUST NOT list every minor version as if each were LTS. These move over time — verify via `describe-db-engine-versions`.

| Engine | Designated LTS (one per major) | Non-LTS (also supported) | Aurora's LTS commitment |
|---|---|---|---|
| Aurora MySQL | **3.10.\*** and **3.04.\*** (designated LTS minors) | 8.4.x (latest major, compatible with community MySQL 8.4 LTS — verify available minors via `describe-db-engine-versions`), 3.11+/3.12 (MySQL 8.0-compatible, prior major; non-LTS) | Minimum ~3 years of Aurora-extended support on each LTS minor, with only critical / security patches. |

**Important clarifications (address these explicitly when the user asks about LTS):**

1. **LTS is not a separate MAJOR version**. It's a specific MINOR release within a supported major that Aurora designates as "Long-Term Support." For Aurora MySQL, 3.10 is an LTS minor within the version-3 (MySQL-8.0-compatible) major; other 3.y minors are released on the regular cadence but the designated LTS minor receives only critical fixes and is supported for ~3 years. AWS designates one LTS minor per supported major simultaneously (3.10 and 3.04 are both designated LTS minors).
2. **Older versions are NOT LTS just because they're older — but a major can have more than one designated LTS minor.** Do not treat any old minor as LTS. For Aurora MySQL the designated LTS minors are 3.10 and 3.04; other 3.x minors (e.g. 3.11/3.12) are non-LTS, and the real lifecycle caveat for older minors is end-of-standard-support, not LTS status.
3. **LTS is opt-in via parameter choice at upgrade time** — you're not automatically on LTS. When upgrading, you choose an LTS minor (e.g. 3.10) vs. a latest non-LTS minor.
4. **Why pick LTS over latest:**
   - **Longer stability window**: ~3 years of support vs. ~1 year for a non-LTS minor.
   - **Patch cadence is predictable**: only critical fixes land; no quarterly feature-or-behaviour changes that force re-testing.
   - **Fewer required upgrade cycles**: reduce operational overhead for teams that can't test upgrades quarterly.
   - **Regulatory alignment**: auditors often expect 1–3 year rolling platform refresh cycles; LTS fits cleanly.
5. **Why pick latest over LTS:**
   - **Access to new features**: window functions and CTEs (MySQL 8.0), instant DDL improvements, JSON enhancements, newer SQL syntax, better optimizer/parallelism.
   - **Performance improvements**: newer versions are typically 5–15% faster on analytic workloads.
   - **Security modernization**: deprecated crypto removed sooner.
6. **Trade-offs you MUST surface when the user asks:**
   - On LTS you must **disable automatic minor version upgrades**, or Aurora will move you off the LTS minor onto the latest non-LTS during the next maintenance window. Set `AutoMinorVersionUpgrade: false` on the cluster and its instances.
   - Staying on LTS means you will not get non-critical bug fixes or new features until you deliberately upgrade to a later LTS or the current latest.
   - LTS versions also get upgraded eventually — when Aurora designates a new LTS minor for a newer major (the current LTS minors change over time; verify via `describe-db-engine-versions`), you'll need a major-version upgrade cycle then too.

**Constraints:**

- You MUST present both options with trade-offs, not just one
- You MUST NOT recommend LTS unconditionally — frame it as a choice based on risk tolerance and upgrade-cadence capacity
- You MUST NOT list every minor version as if it were LTS. AWS designates one LTS minor per supported major, so the answer depends on the major the customer targets.
- When the user asks "what's the LTS version right now", you MUST cite the table above and the specific LTS minor for the relevant major (e.g. "the current Aurora MySQL LTS minors are 3.10 and 3.04"), not a long list of minor versions.
