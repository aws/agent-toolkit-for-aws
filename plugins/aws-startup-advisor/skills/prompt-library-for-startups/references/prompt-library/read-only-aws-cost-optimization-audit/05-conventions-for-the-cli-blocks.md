<!-- markdownlint-disable -->

## CONVENTIONS FOR THE CLI BLOCKS

**Region scoping.** Resource-level blocks below are written for a single `$region` and omit the loop. Wrap any of them:

```bash
for region in $CONFIRMED_REGIONS; do
  echo "=== $region ==="
  # paste the region-scoped block here
done
```

Cost Explorer blocks are global and need no region loop.

**Account scoping.** The audit covers one account, `AUDIT_ACCOUNT`, through one CLI profile, `AUDIT_PROFILE`, both set in 1.1. From 1.1.2 on, `use_audit_profile` (PowerShell: `Use-AuditProfile`) exports `AWS_PROFILE`, so no block below carries a `--profile` flag and every CLI call runs under the audit role. The 1.1 discovery calls are the only ones made under the user's original identity; Appendix B logs them under that identity. A profile built on `role_arn` and `source_profile` renews its session automatically, which matters because assuming a role from another role session is role chaining and caps each session at one hour.

**Management-account scoping.** In an organization, the management account sees every account's costs in Cost Explorer, a member account sees only its own, and a standalone account is its own payer. The blocks below are written for a member or standalone account. When 1.1.2 records `account_type: management`, scope every cost-side call to `AUDIT_ACCOUNT`, or the report describes the whole organization while claiming to describe one account:

- **Cost Explorer** (cost and usage, forecast, coverage, utilization, dimension values, tags): add `{"Dimensions":{"Key":"LINKED_ACCOUNT","Values":["<AUDIT_ACCOUNT>"]}}`, combined with any existing filter under `"And"`.
- **Savings Plans purchase recommendations:** `--filter` on `LINKED_ACCOUNT` with the audited account ID, which is the only dimension this API accepts.
- **RI purchase recommendations:** their `Filter` cannot select one account, so request `--account-scope LINKED` and keep only detail rows whose `AccountId` is the audited account.
- **Cost Optimization Hub:** add `"accountIds":["<AUDIT_ACCOUNT>"]` to the `--filter`.
- **Compute Optimizer:** pass `--account-ids "$AUDIT_ACCOUNT"` wherever the command accepts it.

Resource-level blocks need no change: they only ever see the account the credentials belong to. AWS recommends keeping workloads out of the management account, so resource spend found there is a finding in its own right.

**Quoting.** In bash, quote every variable expansion. Resource names and tag values are user-controlled. One deliberate exception: `for x in $(aws ... --output text)` loops rely on word-splitting the command substitution and appear below only over identifier types that cannot contain whitespace (instance and volume IDs, ARNs, bucket, table, cluster, endpoint, and repository names). Never copy that pattern for tag values or `Name` tags; the PowerShell translation note below handles names with spaces.

**CloudWatch rules**, applying to every metric query in any shell:

1. One call returns at most 1,440 data points. Widen the period, not the range.
2. Period granularity depends on `StartTime` age: multiple of 60 under 15 days, 300 between 15 and 63 days, 3600 beyond 63. `--period 86400` satisfies all three, so every block uses it.
3. Data points come back unordered. Never index `Datapoints[0]`; aggregate with `max(Datapoints[].Maximum)` or `sum(Datapoints[].Sum)`.
4. Match aggregation to statistic: `Maximum`/`max()` for gauges (`DatabaseConnections`, `CPUUtilization`), `Sum`/`sum()` for counters (`Invocations`, `BytesOutToDestination`). Mismatching returns null, which reads as zero and manufactures false positives.
5. Resolution degrades with age: 1-minute for 15 days, 5-minute for 63, 1-hour for 455. A 90-day lookback is hourly aggregates, fine for idle detection, too coarse for peak-sensitive sizing.

### Dates

Every dated call in this document, CLI or MCP, uses the same thirteen values. They are **agent-computed literals**, never shell date arithmetic. Relative date syntax differs between GNU and BSD `date` (`-d '12 months ago'` versus `-v-12m`); on stock macOS the GNU form fails, the variables end up set but empty, and every idle check then runs on fabricated values while looking healthy. The MCP cost tools already take literal date parameters, so this convention makes the CLI path work the same way.

Derive the values in this order:

1. **Anchor.** Run `date -u +%Y-%m-%dT%H:%M:%S` (PowerShell: `[datetime]::UtcNow.ToString('yyyy-MM-ddTHH:mm:ss')`) and use its output as the only source of "now". Never use internal knowledge of today's date; it drifts.
2. **Derive** the thirteen values from the anchor. Month-anchored values are always the first of a month, so no day-overflow case exists. Day-based values subtract exact day counts; count carefully across month boundaries and February.

| Variable | Rule | Example for anchor `2026-09-03T14:12:09` |
| --- | --- | --- |
| `TODAY` | anchor date | `2026-09-03` |
| `MONTH_START` | first of the anchor month | `2026-09-01` |
| `START_1M` | first of month, 1 month back (start of the last complete month) | `2026-08-01` |
| `START_12M` | first of month, 12 months back | `2025-09-01` |
| `START_3M` | first of month, 3 months back | `2026-06-01` |
| `START_90D` | anchor date minus 90 days | `2026-06-05` |
| `START_30D` | anchor date minus 30 days | `2026-08-04` |
| `START_7D` | anchor date minus 7 days | `2026-08-27` |
| `TS_NOW` | the anchor, verbatim | `2026-09-03T14:12:09` |
| `TS_90D` | anchor minus 90 days | `2026-06-05T14:12:09` |
| `TS_32D` | anchor minus 32 days | `2026-08-02T14:12:09` |
| `TS_14D` | anchor minus 14 days | `2026-08-20T14:12:09` |
| `TS_7D` | anchor minus 7 days | `2026-08-27T14:12:09` |

3. **Fill, verify, record.** Replace the placeholders in the preamble below with the derived literals. The preamble refuses to continue while any placeholder or malformed value remains, and prints the full table. Check the printed table against a calendar before Phase 1, and record it in Appendix B. A malformed date fails loudly at the Cost Explorer API; a plausible-but-wrong one does not, which is why the printed table is mandatory.

### Preamble

Paste into the session, or `source` in bash and dot-source in PowerShell (`. .\preamble.ps1`). Running a saved script directly executes in a child scope, the variables do not survive, and every later block then fails with empty date arguments.

```bash
set -uo pipefail

# Agent-computed date literals per the Dates convention. Replace every
# placeholder with a value derived from the anchor command output.
TODAY=YYYY-MM-DD                # anchor date
MONTH_START=YYYY-MM-01          # first of the anchor month
START_1M=YYYY-MM-01             # first of month, 1 month back
START_12M=YYYY-MM-01            # first of month, 12 months back
START_3M=YYYY-MM-01             # first of month, 3 months back
START_90D=YYYY-MM-DD            # anchor date minus 90 days
START_30D=YYYY-MM-DD            # anchor date minus 30 days
START_7D=YYYY-MM-DD             # anchor date minus 7 days
TS_NOW=YYYY-MM-DDThh:mm:ss      # the anchor timestamp, verbatim
TS_90D=YYYY-MM-DDThh:mm:ss      # anchor minus 90 days
TS_32D=YYYY-MM-DDThh:mm:ss      # anchor minus 32 days
TS_14D=YYYY-MM-DDThh:mm:ss      # anchor minus 14 days
TS_7D=YYYY-MM-DDThh:mm:ss       # anchor minus 7 days

CONFIRMED_REGIONS=""            # set in 1.6
ENV_TAG_KEY="Environment"; NONPROD_VALUES="dev,test,staging,qa"  # overwrite from the 1.5 environment answer

AUDIT_RUN_ID=YYYYMMDDThhmmZ     # agent-computed literal from the anchor timestamp
AUDIT_ACCOUNT=""                # 12-digit ID of the account chosen in 1.1.1
AUDIT_PROFILE=""                # CLI profile for the audit role, set in 1.1.2

# Switch this shell to the audit role (1.1.2). Static keys in the environment take
# precedence over AWS_PROFILE in the CLI credential chain, so refuse to switch while they
# are set: every later call would silently keep running under the old identity.
use_audit_profile () {
  if [ -n "${AWS_ACCESS_KEY_ID:-}" ]; then
    echo "PROFILE ERROR: AWS_ACCESS_KEY_ID is set in this shell and would override AWS_PROFILE." >&2
    echo "Unset AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, and AWS_SESSION_TOKEN, then retry." >&2
    return 1
  fi
  export AWS_PROFILE="$AUDIT_PROFILE"
  aws sts get-caller-identity --query '[Account,Arn]' --output text
}

# Bash keeps ONE handler per signal: a later `trap ... EXIT` silently replaces an earlier
# one, so per-block traps overwrite each other depending on paste order. Every cleanup
# obligation in this document therefore lives in this single handler. Blocks that create
# a temp file (2.1, 2.4, 3.5) name it here instead of setting their own trap.
cleanup () {
  rm -f -- "${PROBE_LOG:-}" "${TOP_BUCKETS:-}" "${SPEND_INVENTORY:-}" 2>/dev/null
}
trap cleanup EXIT

date_check () {   # refuse unfilled or malformed date literals, print the table
  local v val ok=1
  for v in TODAY MONTH_START START_1M START_12M START_3M START_90D START_30D \
           START_7D TS_NOW TS_90D TS_32D TS_14D TS_7D; do
    val="${!v}"
    case "$val" in
      [0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]) ;;
      [0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9][0-9]:[0-9][0-9]:[0-9][0-9]) ;;
      *) echo "PREAMBLE ERROR: $v='$val' is not a filled date literal" >&2; ok=0 ;;
    esac
    printf '  %-12s %s\n' "$v" "$val"
  done
  [ "$ok" -eq 1 ] || { echo "Fix the dates above before continuing." >&2; return 1; }
  echo "Preamble OK. Verify this table against a calendar; record it in Appendix B."
}

# Used by every idle check below. Dimensions are variadic and MUST be passed as one
# argument each: the CLI shorthand parser does not split "Name=A,Value=B Name=C,Value=D"
# inside a single argument; it silently mis-parses, the metric returns None, num()
# coerces it to 0, and idle detection then runs on fabricated zeros.
metric_agg () {  # namespace metric region stat dimension...  (stat = Maximum|Sum)
  local ns=$1 metric=$2 region=$3 stat=$4; shift 4
  local agg=max; [ "$stat" = "Sum" ] && agg=sum
  aws --region "$region" cloudwatch get-metric-statistics \
    --namespace "$ns" --metric-name "$metric" --dimensions "$@" \
    --start-time "${LOOKBACK:-$TS_14D}" --end-time "$TS_NOW" \
    --period 86400 --statistics "$stat" \
    --query "$agg(Datapoints[].$stat)" --output text
}
# absent() tests for missing data. CloudWatch returns the literal "None" when a metric has no
# datapoints in the window, which per Rule 3 is missing data and never a measured zero. Guard
# with absent() BEFORE any comparison and emit METRICS UNAVAILABLE rather than an idle verdict.
absent () { [ "$1" = "None" ] || [ -z "$1" ]; }

# Coerce a CloudWatch scalar to an integer for comparison, after absent() has cleared it.
# Truncates, so a value below 1 becomes 0 and scientific notation such as 1.0E-5 becomes 1.
# Truncation errs toward NOT flagging in a threshold test (conns<10, cpu<5): the safe direction.
# It errs the OTHER way in an equality-to-zero test, where a missing metric and 0.9 GB of real
# traffic both become 0 and both read as idle. Every "-eq 0" comparison below therefore guards
# with absent() first, and no new one may be added without that guard: a missing guard turns a
# merely denied metrics call into a removal recommendation for a busy resource.
# Where absence and a real zero cannot be told apart from the value alone - list-metrics being
# the case in 4.7 - test the CLI exit status too, not just the value.
num () { absent "$1" && echo 0 || echo "${1%%.*}"; }

date_check
```

```powershell
$ErrorActionPreference = 'Continue'
# PowerShell date math is deterministic across platforms, so deriving here is
# safe; the Dates convention's printed-table and Appendix B requirements still apply.
$U = [datetime]::UtcNow
function D  { param([int]$Days = 0, [int]$Months = 0) $U.AddDays($Days).AddMonths($Months).ToString('yyyy-MM-dd') }
function M  { param([int]$Months = 0) $U.AddMonths($Months).ToString('yyyy-MM-01') }
function TS { param([int]$Days = 0) $U.AddDays($Days).ToString('yyyy-MM-ddTHH:mm:ss') }

$TODAY = D; $MONTH_START = M; $START_1M = M -Months -1
$START_12M = M -Months -12; $START_3M = M -Months -3
$START_90D = D -Days -90; $START_30D = D -Days -30; $START_7D = D -Days -7
$TS_NOW = TS; $TS_90D = TS -Days -90; $TS_32D = TS -Days -32
$TS_14D = TS -Days -14; $TS_7D = TS -Days -7
$CONFIRMED_REGIONS = @()
$AUDIT_ACCOUNT = ''; $AUDIT_PROFILE = ''   # set in 1.1.1 and 1.1.2
# Switch to the audit role in 1.1.2. Static keys in the environment override AWS_PROFILE,
# so the switch refuses to run while they are set.
function Use-AuditProfile {
  if ($env:AWS_ACCESS_KEY_ID) { Write-Error 'AWS_ACCESS_KEY_ID is set and would override AWS_PROFILE; remove the static key variables first.'; return }
  $env:AWS_PROFILE = $AUDIT_PROFILE
  aws sts get-caller-identity --query '[Account,Arn]' --output text
}
$ENV_TAG_KEY = 'Environment'; $NONPROD_VALUES = 'dev,test,staging,qa'  # overwrite from the 1.5 environment answer

function Get-MetricAgg {   # An absent metric returns the literal "None"
  # Pass -Dimensions as an array, one 'Name=...,Value=...' string per dimension,
  # e.g. -Dimensions @('Name=BucketName,Value=x','Name=StorageType,Value=StandardStorage').
  # PowerShell expands the array into separate CLI arguments; a single space-joined
  # string would mis-parse exactly like the bash pitfall noted in the preamble.
  param($Namespace, $MetricName, [string[]]$Dimensions, $Region, $StartTime, $Stat = 'Maximum')
  $agg = if ($Stat -eq 'Sum') { 'sum' } else { 'max' }
  $v = aws cloudwatch get-metric-statistics --region $Region `
        --namespace $Namespace --metric-name $MetricName --dimensions $Dimensions `
        --start-time $StartTime --end-time $TS_NOW --period 86400 --statistics $Stat `
        --query "$agg(Datapoints[].$Stat)" --output text
  # Returns $null for an absent metric, never 0. A missing metric is Rule 3 missing data, and
  # returning 0 makes it indistinguishable from a measured zero in an equality test. Callers
  # test `if ($null -eq $v) { 'METRICS UNAVAILABLE' }` before comparing.
  if ($v -eq 'None' -or [string]::IsNullOrWhiteSpace($v)) { return $null } else { return [double]$v }
}
foreach ($v in 'TODAY','MONTH_START','START_1M','START_12M','START_3M','START_90D',
               'START_30D','START_7D','TS_NOW','TS_90D','TS_32D','TS_14D','TS_7D') {
  '  {0,-12} {1}' -f $v, (Get-Variable $v -ValueOnly)
}
"Preamble OK. Verify this table against a calendar; record it in Appendix B."
```

**Translating the remaining bash blocks to PowerShell.** Replace `for region in $CONFIRMED_REGIONS` with `foreach ($region in $CONFIRMED_REGIONS)`. Replace `$(aws ... --output text)` list capture with `aws ... --output json | ConvertFrom-Json`, which survives names containing spaces. Replace `jq` filtering with `ConvertFrom-Json | Where-Object | Sort-Object`. For the Phase 2 probe, wrap each call in `try/catch` or test `$LASTEXITCODE`.

---

<!-- markdownlint-enable -->
