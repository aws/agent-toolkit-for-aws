# Local DAG Validation with `test-dags` (Phase 6)

SKILL.md Phase 6 decides whether validation runs, which images to check, and
what to warn if it is skipped. How to set up the repo, build an image, run
`test-dags`, and read its exit code and report is in the repo README section
[Validate DAGs before an Amazon MWAA upgrade](https://github.com/aws/amazon-mwaa-docker-images#validate-dags-before-an-amazon-mwaa-upgrade).
Fetch that section every time and follow it as written. Do not work from a
remembered copy, because the command and its options can change.

For each image row in the plan:

1. **Skip when it cannot run.** Log `SKIP` with the reason, and give the
   SKILL.md Phase 6 skip warning, when no container runtime is available, the
   user declines, or the repo or README does not support the target version or
   this host.
2. **Use a current clone.** Clone or `git pull` the repo first. Before running,
   confirm that the version folder supports `test-dags` as the README
   describes. If it does not, log `SKIP`. Never run `test-dags` against a
   version folder that lacks it: an older `run.sh` starts the full Airflow
   stack for a command it does not know.
3. **Pass the right inputs.** The DAGs are the set deployed at that jump
   (SKILL.md Phase 6). Use that jump's requirements file, plugins and startup
   script, and write a separate report file for each image. Build and run for
   `linux/amd64`, the architecture MWAA environments run on, because
   requirements resolve to different wheels per architecture. If the host
   cannot build or emulate `linux/amd64`, log `SKIP`.
4. **Decide from the exit code and the report, as the README defines them,
   never from the console output.** Record `DONE` only when the README says the
   check passed and every DAG ID the plan expects at that jump appears in the
   report's DAG list. A run that found none or only some of them is not
   `DONE`: log `SKIP` and name the missing DAGs (a wrong DAG folder also passes
   with nothing checked). A check that did not finish is never `DONE`. Send DAG and
   plugin import errors to Phase 5 and requirement failures back to the pins,
   then re-run. Record warnings as advisory plan items. Tell the user about
   anything the README says the check did not cover, such as files it skipped.
5. **Save progress** for each image row: `DONE` (with the report path),
   `SKIP` (with the reason), or `SKIP` with the reason
   `check did not finish: <error>`. Update `Last updated`.
