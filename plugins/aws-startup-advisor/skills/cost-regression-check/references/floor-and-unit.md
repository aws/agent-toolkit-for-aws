# Floor and Unit

## What changes for a startup

Report two numbers for every change, the floor added and the change in cost per unit, and never one blended monthly figure.

A large company usually reviews one monthly delta at an assumed volume. A new fixed charge is a rounding error in its bill, so a blended figure loses nothing it cares about. Against a small ceiling the company pays itself, a new NAT gateway or database minimum can take a visible share of the ceiling before the product has users, while the cost per unit decides whether the bill grows in line with usage or faster. The two move on different timelines, and a blended figure hides which one moved.

- Floor added: what the change adds to the monthly bill at zero traffic. These are charges that accrue whether or not anything uses the resource. The floor is what the company pays today, before the product has users.
- Change in cost per unit: how much more or less one unit of the team's own usage costs to serve after the change.

A change can move one and not the other. A new NAT gateway raises the floor even if no traffic reaches it. A chattier function or a per-tenant index raises the cost per unit and leaves the floor where it was.

## Classify price dimensions, not resources

Many resources carry both kinds of charge, so classify each price dimension the stack uses. A NAT gateway is charged for each hour it is available and for each gigabyte it processes ([NAT gateway pricing](https://docs.aws.amazon.com/vpc/latest/userguide/nat-gateway-pricing.html)): the hourly charge is floor, the per-gigabyte charge is usage.

| Dimension kind                        | Examples                                                                                                                                                                                 | Counts toward |
| ------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------- |
| Hourly while provisioned              | NAT gateway hour; Application Load Balancer hour; interface VPC endpoint hour in each Availability Zone; public IPv4 address hour; EC2 instance hour; provisioned database instance hour | Floor         |
| Provisioned capacity per month        | EBS storage per GiB-month; gp3 IOPS and throughput provisioned above the included baseline                                                                                               | Floor         |
| Minimum capacity of a scaling service | Aurora serverless minimum ACUs                                                                                                                                                           | Floor         |
| Per request, per byte, per duration   | Lambda requests and GB-seconds; NAT gateway and interface endpoint data processed; load balancer capacity units; data transfer                                                           | Usage         |

What each service charges, and its minimums, is service knowledge that lives upstream. Check each row the stack uses there rather than here: `Skill("aws-core:aws-billing-and-cost-management")` for Price List dimensions, the gp3 included baseline, and the 730-hour month the job uses to convert hourly charges; `Skill("aws-core:aws-database")` for Aurora serverless minimum capacity and when auto-pause brings the instance floor to zero; `Skill("aws-core:aws-compute")` for public IPv4 addresses, which are charged per hour whether attached or not. For the two rows no upstream skill prices, read the pricing pages: [Elastic Load Balancing](https://aws.amazon.com/elasticloadbalancing/pricing/) charges each hour a load balancer runs plus capacity units, and [AWS PrivateLink](https://aws.amazon.com/privatelink/pricing/) charges each hour an interface endpoint is provisioned in each Availability Zone plus data processed.

## Where floors hide in a plan

Read the resource changes in the plan, not the module call in the diff. The line a reviewer sees is rarely the line that costs money.

- Module defaults. A network module can create one NAT gateway per Availability Zone, interface endpoints for several services, and public addresses on every instance. A storage module can provision IOPS and throughput above the baseline.
- Multipliers. `count`, `for_each`, one resource per Availability Zone, per environment, or per tenant. A one-line change to that list can multiply every floor the module creates; an interface endpoint in three Availability Zones is three hourly charges.
- Changes to existing resources. A larger instance class, a higher minimum capacity, or more provisioned IOPS raises the floor with no new resource in the plan. The cost script must price the before and after of updates, not only creates.
- Environments. A change merged once can apply to several stacks. Price each stack the change reaches, or state which one the comment covers.

## Choose the unit

Pick one primary unit the team already counts or can count: requests, active tenants, jobs, processed documents, generated images. Prefer the unit the product is priced on, because that is the one the bill owner can compare with revenue to see whether the ceiling holds as usage grows.

Write a usage assumptions file in the repository. For each usage-priced dimension in the stack, it states the quantity consumed per unit, where that quantity came from, and when it was measured. For example: the API function uses 1,024 MB for a measured average duration per request, taken from function metrics on a given date; the NAT gateway processes a measured number of megabytes per 1,000 requests, taken from flow logs or gateway metrics.

- Every value carries a source and a date. A value without a source is a guess, and the comment says so next to the number it produced.
- Keep the file small. Cover the dimensions that dominate cost per unit, and list the rest as not modelled rather than inventing values.
- Store raw measurements, not derived costs. The script multiplies by current prices on every run, so a price change shows up without editing the file.
- Model resources the application creates at runtime, such as per-tenant indexes or queues, as usage per tenant here, since the plan cannot see them. List them as not covered if they cannot be measured.

## How a usage assumption goes wrong

Lambda charges per request and for duration in GB-seconds, which is memory multiplied by duration ([Lambda pricing](https://aws.amazon.com/lambda/pricing/)). Raising memory from 512 MB to 1,024 MB at unchanged duration doubles the duration charge per request and leaves the request charge alone. Duration often falls when memory rises, because CPU scales with memory ([Lambda performance](https://aws.amazon.com/blogs/compute/operating-lambda-performance-optimization-part-2/)), so the real change can be close to zero.

The script cannot know the new duration until the change runs. Make it detect when a change touches an input of an assumption (memory for duration, instance size for throughput) and print the assumption as unchanged and unverified in the comment. A confident number from a stale assumption is worse than a flagged one.
