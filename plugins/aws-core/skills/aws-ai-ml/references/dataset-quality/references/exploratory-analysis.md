# Free-form exploratory analysis (Step 7, the "unsure" branch)

Read this page only when Step 7 of `references/quality-job.md` recorded `intent = explored`: the user is on the BYOD path and is not sure yet what the data must satisfy. `references/results-and-report.md` also sends the "Explore for issues" next step here. Everywhere else the exploratory analysis runs inside the job, as its `exploratory_analysis` operation, and nothing on this page is needed.

Spec-driven evaluation checks the requirements the user knows about.
This pass looks for issues nobody thought to specify — cross-field
inconsistencies, label noise, target leakage, provenance issues,
composition/coverage gaps. Findings surface issues the automated metric
catalog is architecturally unable to detect (semantics, structure,
cross-field logic), so this is the primary place they get raised — the
metric report won't tell the user about them. A finding worth
re-checking on future dataset versions can become a spec requirement.

Here (BYOD, unsure) it runs client-side on a local copy of the data, not
through the dataset quality evaluation API, because the spec does not exist yet. During the job
(Step 12, when included in the plan) the service runs the analysis instead,
as the job's `exploratory_analysis` operation; Step 13 presents its findings
in the same **Exploratory Analysis** block.

Confirm two prerequisites (do this silently — don't re-ask what you
already know):

1. **The user's intent** — take it from Step 1, `data_spec.md`, or
   `use_case_spec.md`. If it's still unclear at this point, ask now.
   This is the overall goal, not the spec — the analysis is looking for
   what the spec would miss.
2. **Local access to the raw file** — by this point in the flow, one of
   the following is true, and you must ensure a local copy exists before
   the analysis begins:
   - **Local file entry** (via Format Validation): file is already local.
     Use it directly.
   - **S3 URI entry**: download the object from the S3 URI to a scratch
     path under the project directory and nowhere else: not `/tmp`, not
     `mktemp`, not the home directory. Download only when the object is
     under 50 MB; otherwise do not run the analysis here, and run it as
     the job's `exploratory_analysis` operation instead (include it in
     the Step 12 plan).
   - **Dataset ARN entry**: resolve the underlying raw file S3 URI by
     reading the hub name and the content name from the ARN and running
     `aws sagemaker describe-hub-content --hub-name <hub> --hub-content-type DataSet --hub-content-name <name>`
     (the hub content record points at the raw S3 object for BYOD
     registrations), then download it under the same bound and to the
     same place.
     For ARNs produced by the dataset-transformation capability (DT),
     the S3 location is also recorded in that capability's manifest at
     `manifests/` — prefer that if Step 0's scan surfaced it.

Then run the analysis as a working data scientist would: read the data,
form hypotheses, test them. Rules:

- Ground every finding in evidence (cite values, row counts, statistics).
- Stay descriptive — report what you found and what it implies. Don't
  prescribe fixes or activate other skills.
- Base every finding on values you actually compute from the file. Do
  not use prior knowledge of the dataset (e.g. published statistics or
  well-known properties of a public dataset with the same name) as
  evidence — the file in front of you may have been modified, filtered,
  or subsampled.
- Sample large datasets (>50k rows) rather than processing everything;
  never process a large file whole on the local machine.

Present findings as a ranked list, most consequential first, framed for
the stated goal:

> **Exploratory Analysis**
>
> 1. **[Finding]** — [evidence and implication]
> 2. ...

If nothing notable, say "Nothing beyond what the metric report will flag
— the data looks fit for purpose." and continue immediately — no need to
wait for acknowledgement on a clean result.

If findings were raised, ⏸ wait for user acknowledgement before continuing
(the user may want to discuss a finding or hand off to
dataset-transformation before proceeding — see below).

If the findings are severe enough that the user wants to fix the data
before evaluation, offer to hand off to dataset-transformation rather
than proceeding.

Do not offer to convert findings into spec requirements, and do not
draft requirements from them: findings are observations, not the
user's requirements, and an agent-authored list tends to be accepted
without the user owning it. The user states their requirements at
Step 10.1 with the findings in view; if they themselves ask for a finding
to become a check, add it — the rule is about who authors, not what is
allowed.

**Routing:** BYOD entries (local file or S3 URI) → Step 8 (Collect the
dataset location to register; the generated notebook registers it after
the plan confirmation). Dataset ARN entries are already registered →
skip Step 8 and go to Step 9 (Validate format).
