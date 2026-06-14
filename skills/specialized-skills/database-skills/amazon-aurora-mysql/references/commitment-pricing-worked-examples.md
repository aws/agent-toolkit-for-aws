# Worked Examples

Back to [instructions.md](commitment-pricing-instructions.md). Pricing rules and tables are in [mechanics.md](commitment-pricing-mechanics.md).

## Worked example — DSP for Aurora serverless

User: Aurora serverless, ~6 ACU average. Would an RI or savings plan save money?

Agent response pattern:

1. Announce reference: "Loading `references/commitment-pricing-instructions.md` for the commitment-pricing workflow."
2. **Critical fact first**: **Reserved Instances do NOT apply to Aurora serverless.** Only DSP applies, and only 1-year DSP (no 3-year DSP for Aurora).
3. Print the script command:

    ```bash
    python3 scripts/commitment_pricing_analyzer.py offline \
      --serverless --avg-acu 6 --region us-east-1
    ```

4. Compute inline:
    - On-demand: 6 × $0.12 × 730 = **$526/mo compute**.
    - 1-year DSP No Upfront — DSP's only payment option (serverless reaches up to ~35% off; actual rate varies by usage type per the DSP pricing page): at the ~35% serverless ceiling, $526 × 0.65 ≈ **$342/mo**, saving **~$184/mo, ~35%**. There is no Partial/All Upfront DSP.
5. **Size-warning**: DSP charges the committed $/hr continuously, including during auto-pause. Your "6 ACU average" should be interpreted as steady baseline — if actual usage drops to 0 ACU for long stretches (overnight, weekends), the commitment is wasted on paused hours. Consider committing to the **steady-baseline ACU** (probably closer to 2–3 if your workload auto-pauses), and let peaks run on-demand.
6. Recommendation: **1-year DSP No Upfront at 2 ACU baseline** if the cluster auto-pauses, or **1-year DSP No Upfront at 6 ACU** if it runs steady 24/7 (No Upfront is DSP's only payment option). Don't over-commit.

## Worked example — DSP-ineligible family

User: "4 Aurora clusters on db.r6g.xlarge. What commitments make sense?"

Agent response pattern:

1. Announce reference: "Loading `references/commitment-pricing-instructions.md`."
2. **Print the script command** even though we'll compute inline:

    ```bash
    python3 scripts/commitment_pricing_analyzer.py offline \
      --instance db.r6g.xlarge --num-instances 4 --region us-east-1
    ```

3. **Critical fact first**: **DSP does NOT cover db.r6g.** Per the coverage table above, r6g is DSP-ineligible. **RI is the only commitment option** for this family today.
4. Compute inline — on-demand: 4 × $0.58 × 730 = **$1,694/mo**.
    - 1-year RI All Upfront (~30%): $1,694 × 0.70 = **$1,186/mo**. Upfront ≈ $14,222. Saves **$508/mo, ~30%**.
    - 3-year RI All Upfront (~55%): $1,694 × 0.45 = **$762/mo**. Upfront ≈ $27,432. Saves **$932/mo, ~55%**.
5. **Migration recommendation**: if you're willing to migrate to **db.r7g.xlarge** (roughly 10% more expensive on-demand — ~$467/mo each vs $423 — but ~15% more performant, and DSP-eligible), DSP unlocks size-flex so you could reshape without losing the commit. That flexibility is typically worth ~5–10% on a 1–3 year horizon for fleets that change over time.
6. Recommendation: if the fleet is stable and will stay on r6g, **3-year RI All Upfront** for the largest savings (55%). If the fleet composition might change within 1-3 years, **migrate to r7g first** and then take a 1-year DSP. Do not wait for DSP on r6g — it is not on the roadmap.

## Worked example — commitment on a single cluster

User: "Should I buy reserved instances for my Aurora cluster `analytics-cluster` in us-west-2? 2× db.r7g.2xlarge running 24/7."

Agent response pattern:

1. Announce reference: **"Loading `references/commitment-pricing-instructions.md` — this is the commitment-pricing workflow."** Naming the path makes the routing decision explicit to the user.
2. Print the script command:

    ```bash
    python3 scripts/commitment_pricing_analyzer.py offline \
      --instance db.r7g.2xlarge --num-instances 2 --region us-west-2
    ```

3. Compute inline (us-west-2 ≈ 1.15× us-east-1):
    - On-demand: 2 × $1.28 × 1.15 × 730 = **$2,149/mo**.
    - 1-year RI All Upfront (~30%): **$1,504/mo** — saves $645/mo, ~30%.
    - 3-year RI All Upfront (~55%): **$967/mo** — saves $1,182/mo, ~55%.
    - 1-year DSP No Upfront — DSP's only payment option (provisioned ceiling up to ~20%): $2,149 × 0.80 ≈ **$1,719/mo** — saves ~$430/mo, ~20%; smaller per-unit discount than the RI options here, but with size-flex (can reshape between r7g/r8g/serverless within commit).
4. Because the user said "running 24/7" on db.r7g.2xlarge (a DSP-eligible family), both RI and DSP apply. Recommend **1-year DSP No Upfront** if the fleet may reshape (size-flex is worth the lower discount), or **3-year RI All Upfront** if the fleet is stable and a 3-year lock is acceptable.

## Troubleshooting

**"Cluster not found".** Wrong cluster ID or region. Verify with `aws rds describe-db-clusters --region <region>`.

**Live RI/DSP fetch returns empty offerings.** Instance types without published offerings, or non-standard regions. Offer offline mode, or direct the user to the AWS Savings Plans console.

**User asks about 3-year DSP.** A 3-year Database Savings Plan does not exist for Aurora — only 1-year. Steer them to 3yr RI if they want a longer commitment. **Aurora serverless caveat**: if the cluster is Aurora serverless, RIs do not apply either — 1yr DSP is the only commitment option available.

**"DSP not available for this family".** Instance family is older than the DSP coverage set. Explain that RI is the only commitment option for that family, and mention migration to a newer family (r7g, r8g, etc.) as a way to unlock DSP flexibility.

**User wants to commit beyond their steady baseline.** Push back — both RI and DSP are use-it-or-lose-it. Recommend committing to the 24/7 baseline and leaving peaks on-demand.

**Aurora serverless with max-capacity=0 planned.** DSP still bills the committed $/hr even during auto-pause. Warn the user before they commit.
