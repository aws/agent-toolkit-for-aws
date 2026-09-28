# Metering Dimension Reference

## Known Dimensions

These dimensions represent the usage metrics reported via AWS Marketplace BatchMeterUsage API:

| Dimension | Description |
|-----------|-------------|
| `fgt_cnf_hours` | FortiGate CNF instance running hours. Measures the number of hours the CNF firewall instances are active. May include UsageAllocations with SecurityVPC tags. |
| `fgt_cnf_ips_proc` | FortiGate CNF IPS (Intrusion Prevention System) data processed. Measures the volume of traffic inspected by the IPS engine. |
| `fgt_cnf_sec_proc` | FortiGate CNF security processing. Measures general security processing workload. |
| `fgt_cnf_eco_instance_hrs` | FortiGate CNF economy instance hours. Measures running hours for economy-tier firewall instances. May include UsageAllocations with SecurityVPC tags. |
| `Site_Number` | Number of monitored sites. |
| `Transfer_Data` | Data transfer volume. |
| `Vulnerability_Scan` | Number of vulnerability scans performed. |

## UsageAllocations

Some records include `UsageAllocations` with tags that break down usage by SecurityVPC. This is common for:

- `fgt_cnf_hours` — allocated per SecurityVPC
- `fgt_cnf_eco_instance_hrs` — allocated per SecurityVPC
- `fgt_cnf_ips_proc` — allocated per SecurityVPC (for centralized firewall policies)

## Data Period

Do not assume a fixed billing cycle or date range. Determine the current dimensions and active billing period dynamically:

- Query the product's configured dimensions via the Catalog API: `aws marketplace-catalog describe-entity --catalog AWSMarketplace --entity-id <PRODUCT_ID> --region us-east-1`
- Metered usage bills on the 2nd–3rd of each month for the prior month; use the seller's requested window for queries rather than a hardcoded range.
