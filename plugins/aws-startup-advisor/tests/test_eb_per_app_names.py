"""Elastic Beanstalk names for a design with several Heroku apps.

`beanstalk.tf` used to name every app's application `var.project_name` and every environment
`${var.project_name}-<process_type>`. Two Heroku apps on Elastic Beanstalk in one Terraform root then
asked for the same application, environments and instance role: `terraform apply` cannot create the
second, and a staging and a production app resolve to the same environments (a "staging" deploy lands
in production). generate-terraform.md § "EB name resolution" now gives each app its own names when
there are two or more, and keeps today's names for one.

These tests pin that section: a reference implementation of its slug rule (the same shortening a
reader would apply), the template tokens that carry it, and the checker rule that catches a root which
still has duplicates.
"""
from __future__ import annotations

import importlib.util
import json
import re
import sys
import tempfile
import unittest
from pathlib import Path

PLUGIN = Path(__file__).resolve().parent.parent
GENERATE = PLUGIN / "skills/heroku-to-aws/references/phases/generate"
TERRAFORM = (GENERATE / "generate-terraform.md").read_text(encoding="utf-8")
DOCS = (GENERATE / "generate-docs.md").read_text(encoding="utf-8")
EB_ENV_MAX = 40
IAM_ROLE_MAX = 64


def eb_suffixes(project_name: str, apps: dict[str, list[str]]) -> dict[str, str]:
    """Reference for generate-terraform.md § EB name resolution. apps: Heroku app -> its EB process types.

    Returns the `<eb_app_suffix>` per app: "" with one EB app, "-<slug>" with two or more."""
    eb_apps = sorted(apps)
    if len(eb_apps) < 2:
        return {app: "" for app in eb_apps}
    longest = max(len(process) for processes in apps.values() for process in processes)
    room = EB_ENV_MAX - len(project_name) - 1 - 1 - longest
    if room < 3:
        raise ValueError("project name or process type too long for per-app names")
    def clean(app: str) -> str:
        return re.sub(r"[^a-z0-9]+", "-", app.lower()).strip("-") or "app"

    naturals = {app: clean(app)[:room].rstrip("-") for app in eb_apps}
    suffixes: dict[str, str] = {}
    assigned: set[str] = set()
    for app in eb_apps:
        slug = naturals[app]
        if slug in assigned:
            others = {naturals[other] for other in eb_apps if other != app}
            n = 1
            while slug in assigned or slug in others or n == 1:
                n += 1
                keep = room - len(str(n)) - 1
                if keep < 1:
                    raise ValueError("project name or process type too long for per-app names")
                slug = clean(app)[:keep].rstrip("-") + "-" + str(n)
        assigned.add(slug)
        suffixes[app] = "-" + slug
    return suffixes


def load_validator():
    path = PLUGIN / "skills/tf-best-practices/scripts/validate-migration-artifacts.py"
    spec = importlib.util.spec_from_file_location("validate_migration_artifacts_eb_names", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # the validator's dataclasses resolve their module by name
    spec.loader.exec_module(module)
    return module


class EbNameRuleTests(unittest.TestCase):
    def test_one_eb_app_keeps_todays_names(self) -> None:
        self.assertEqual(eb_suffixes("shop", {"only-app": ["web", "worker"]}), {"only-app": ""})
        self.assertEqual(eb_suffixes("shop", {}), {})

    def test_the_specs_examples_are_what_the_rule_produces(self) -> None:
        # the table in § EB name resolution
        self.assertEqual(
            eb_suffixes("shop", {"shop-staging": ["web", "worker"], "shop-production": ["web", "worker"]}),
            {"shop-production": "-shop-production", "shop-staging": "-shop-staging"},
        )
        long_app = "acme-platform-production-api-service"
        self.assertEqual(
            eb_suffixes("acme-platform-prod", {long_app: ["web", "scheduler"], "other": ["web"]})[long_app],
            "-acme-platfo",
        )
        self.assertEqual(
            eb_suffixes("acme-platform-prod", {"billing-service-eu": ["web", "scheduler"], "billing-service-us": ["web", "scheduler"]}),
            {"billing-service-eu": "-billing-ser", "billing-service-us": "-billing-s-2"},
        )
        for row in ("`shop-shop-staging`", "`shop-shop-production`", "`acme-platform-prod-acme-platfo`", "`billing-s-2`"):
            self.assertIn(row.replace("`billing-s-2`", "billing-s-2"), TERRAFORM)

    def test_every_name_fits_ebs_and_iams_limits_and_is_unique(self) -> None:
        cases = [
            ("shop", {f"service-{i:02d}-with-a-rather-long-heroku-app-name": ["web", "worker"] for i in range(12)}),
            ("a", {"x" * 60: ["web"], "x" * 61: ["web"], "x" * 62: ["web"]}),
            ("acme-platform-prod", {"billing-service-eu": ["web", "scheduler"], "billing-service-us": ["web", "scheduler"], "billing-service-ap": ["web"]}),
            ("p", {"My_App.Name": ["web"], "my-app-name": ["web"], "MY APP NAME": ["web"]}),
            ("shop", {"---": ["web"], "!!!": ["web"]}),
        ]
        for project, apps in cases:
            with self.subTest(project=project, apps=len(apps)):
                suffixes = eb_suffixes(project, apps)
                names: list[str] = []
                for app, suffix in suffixes.items():
                    application = project + suffix
                    for process in apps[app]:
                        environment = f"{application}-{process}"
                        self.assertLessEqual(len(environment), EB_ENV_MAX, environment)
                        self.assertRegex(environment, r"^[a-z0-9][a-z0-9-]*[a-z0-9]$")
                        names.append(environment)
                    self.assertLessEqual(len(application + "-eb-instance"), IAM_ROLE_MAX)
                    # an environment is its application, a dash and the process type
                    self.assertTrue(f"{application}-{apps[app][0]}".startswith(application + "-"))
                self.assertEqual(len(names), len(set(names)), "two environments share a name")
                self.assertEqual(len({s for s in suffixes.values()}), len(suffixes), "two apps share a suffix")

    def test_a_rebuilt_slug_that_collides_is_rebuilt_again(self) -> None:
        # `hello-2` truncates to `hello` (taken by `hello`), is rebuilt to `hell-2`, and `hell-2` already
        # owns that slug, so the rebuild must continue to `hell-3`.
        project = "a" * 29  # room = 40 - 29 - 1 - 1 - len("web") = 6
        suffixes = eb_suffixes(project, {"hell-2": ["web"], "hello": ["web"], "hello-2": ["web"]})
        self.assertEqual(suffixes, {"hell-2": "-hell-2", "hello": "-hello", "hello-2": "-hell-3"})
        self.assertEqual(len(set(suffixes.values())), 3)

    def test_a_later_natural_slug_cannot_equal_an_earlier_rebuilt_one(self) -> None:
        # The rebuilt slug must also avoid the natural slug of an app that is assigned later.
        for project, apps in (
            ("a" * 29, {"hello": ["web"], "hellos": ["web"], "hell-2": ["web"], "hello-2": ["web"], "helloa": ["web"]}),
            ("a" * 28, {"abcdef": ["web"], "abcdefg": ["web"], "abcdefh": ["web"], "abcd-2": ["web"]}),
        ):
            with self.subTest(apps=sorted(apps)):
                suffixes = eb_suffixes(project, apps)
                self.assertEqual(len(set(suffixes.values())), len(suffixes), suffixes)

    def test_slugs_are_unique_or_refused_for_many_generated_app_sets(self) -> None:
        import random
        rng = random.Random(632)
        alphabet = "ab-12"
        refused = unique = 0
        for _ in range(3000):
            # project lengths up to 33 leave room 3..36 for a 3-letter process type, so the tightest rooms
            # (where a rebuild cannot fit and generation must halt) are reached as well as the roomy ones
            project = "p" * rng.randint(1, 33)
            apps = {"".join(rng.choice(alphabet) for _ in range(rng.randint(1, 9))): ["web"] for _ in range(rng.randint(2, 12))}
            if len(apps) < 2:
                continue
            try:
                suffixes = eb_suffixes(project, apps)
            except ValueError:
                refused += 1
                continue
            unique += 1
            self.assertEqual(len(set(suffixes.values())), len(suffixes), (project, sorted(apps), suffixes))
            for app, suffix in suffixes.items():
                self.assertLessEqual(len(f"{project}{suffix}-web"), EB_ENV_MAX, (project, app, suffix))
                self.assertRegex(f"{project}{suffix}-web", r"^[a-z0-9][a-z0-9-]*[a-z0-9]$")
        self.assertGreater(unique, 1500, "the generator should mostly produce valid sets")
        self.assertGreater(refused, 0, "tight rooms should be refused, not silently collided")

    def test_a_project_or_process_name_too_long_for_per_app_names_is_refused(self) -> None:
        with self.assertRaises(ValueError):
            eb_suffixes("a-very-long-project-name-here", {"a": ["web"], "b": ["a-long-process-type-name"]})


class EbNameTemplateTests(unittest.TestCase):
    def test_every_name_in_beanstalk_tf_and_pipeline_tf_carries_the_app_suffix(self) -> None:
        section = TERRAFORM.split("## Step 6.5", 1)[1].split("\n## Step ", 1)[0]
        # no hard-coded shared form is left for the resources that collide between two apps
        for shared in (
            '  name        = var.project_name\n',
            '"${var.project_name}-<process_type>"',
            '"${var.project_name}-eb-profile"',
            '"${var.project_name}-eb-instance"',
            '"${var.project_name}-deploy"',
            '"${var.project_name}-codepipeline"',
            '"${var.project_name}-codepipeline-policy"',
        ):
            self.assertNotIn(shared, section, shared)
        for suffixed in (
            '"${var.project_name}<eb_app_suffix>"',
            '"${var.project_name}<eb_app_suffix>-<process_type>"',
            '"${var.project_name}<eb_app_suffix>-eb-profile"',
            '"${var.project_name}<eb_app_suffix>-eb-instance"',
            '"${var.project_name}<eb_app_suffix>-deploy"',
            '"${var.project_name}<eb_app_suffix>-codepipeline"',
            '"${var.project_name}<eb_app_suffix>-codepipeline-policy"',
        ):
            self.assertIn(suffixed, section, suffixed)

    def test_slug_step_keeps_rebuilding_until_unique_and_can_halt(self) -> None:
        section = TERRAFORM.split("### EB name resolution", 1)[1].split("### `beanstalk.tf`", 1)[0]
        for text in (
            "neither already assigned to an earlier app nor the natural slug of any other app",
            "keep incrementing n", "drops below 1, halt with the message from step 1",
        ):
            self.assertIn(text, section, text)

    def test_pipeline_policy_names_the_application_not_the_terraform_label(self) -> None:
        # The policy authorized application/<app_name>, the Terraform resource label (shop_staging), which
        # is never the Elastic Beanstalk application name. It now references the resource's own name.
        policy = TERRAFORM.split("### `pipeline.tf`", 1)[1].split("**CodePipeline rules:**", 1)[0]
        for kind in ("application", "applicationversion", "environment"):
            self.assertRegex(
                policy,
                rf":{kind}/\$\{{aws_elastic_beanstalk_application\.<app_name>\.name\}}",
                kind,
            )
        self.assertNotRegex(policy, r"elasticbeanstalk:\$\{[^\"]*\}:\$\{[^\"]*\}:(application|applicationversion|environment)/<app_name>")

    def test_per_app_mode_emits_one_deploy_workflow_per_app(self) -> None:
        section = TERRAFORM.split("### `.github/workflows/deploy-eb.yml`", 1)[1].split("### `pipeline.tf`", 1)[0]
        for text in (
            "One file per EB app in per-app mode",
            "`.github/workflows/deploy-eb-<eb_app_slug>.yml` for each EB app",
            "Emit one workflow per EB app, never one per EB environment",
            "`workflow_dispatch:` only",
        ):
            self.assertIn(text, section, text)
        # the file lists and the checker agree
        front = TERRAFORM.split("---\n", 2)[1]
        self.assertIn(".github/workflows/deploy-eb-*.yml", front)
        for doc in ("generate.md", "generate-assemble.md"):
            text = (GENERATE / doc).read_text(encoding="utf-8")
            self.assertIn("deploy-eb-<", text, doc)

    def test_deploy_workflow_names_the_ebs_application_not_the_heroku_app(self) -> None:
        # main set EB_APPLICATION_NAME to the Heroku app name while Terraform created `var.project_name`
        deploy = TERRAFORM.split("### `.github/workflows/deploy-eb.yml`", 1)[1].split("```yaml\n", 1)[1].split("\n```", 1)[0]
        self.assertIn("EB_APPLICATION_NAME: <eb_application_name>", deploy)
        self.assertNotIn("EB_APPLICATION_NAME: <app_name>", deploy)

    def test_name_resolution_states_both_modes_and_the_invariant_deploys_rely_on(self) -> None:
        section = TERRAFORM.split("### EB name resolution", 1)[1].split("### `beanstalk.tf`", 1)[0]
        for text in (
            "exactly one EB app", "two or more", "`<eb_app_suffix>` is empty",
            "In both modes an environment's name is its application's name, a dash, and the process type",
            "at most 40 characters", "halt and tell the user",
        ):
            self.assertIn(text, section, text)

    def test_the_guide_defers_to_name_resolution_instead_of_assuming_project_name(self) -> None:
        self.assertIn("§ EB name resolution", DOCS)
        self.assertNotIn("`var.project_name`, not the Heroku app name |", DOCS)
        self.assertNotIn("`web` environment (`${project_name}-web`)", DOCS)


class EbDuplicateNameCheckTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.validator = load_validator()
        cls.policy, _ = cls.validator._dependencies()

    def rules(self, text: str) -> list[str]:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            (root / "terraform").mkdir()
            (root / "terraform/main.tf").write_text(text, encoding="utf-8")
            findings: list = []
            resources = self.validator._resources(root, self.policy, findings)
            self.validator._eb_duplicate_names(resources, self.policy, findings)
            return [item.rule for item in findings]

    @staticmethod
    def render(app: str, suffix: str, process: str = "web") -> str:
        label = app.replace("-", "_")
        return f"""
resource "aws_elastic_beanstalk_application" "{label}" {{
  name = "${{var.project_name}}{suffix}"
}}
resource "aws_elastic_beanstalk_environment" "{label}_{process}" {{
  name        = "${{var.project_name}}{suffix}-{process}"
  application = aws_elastic_beanstalk_application.{label}.name
}}
resource "aws_iam_instance_profile" "eb_{label}" {{
  name = "${{var.project_name}}{suffix}-eb-profile"
}}
resource "aws_iam_role" "eb_instance_{label}" {{
  name = "${{var.project_name}}{suffix}-eb-instance"
}}
"""

    def test_two_apps_with_the_shared_names_are_reported_once_per_colliding_resource(self) -> None:
        text = self.render("shop-staging", "") + self.render("shop-production", "")
        self.assertEqual(self.rules(text).count("eb_duplicate_name"), 4)

    def test_per_app_names_pass(self) -> None:
        text = self.render("shop-staging", "-shop-staging") + self.render("shop-production", "-shop-production")
        self.assertEqual(self.rules(text), [])

    def test_one_app_with_several_process_types_is_not_a_duplicate(self) -> None:
        text = self.render("shop", "") + (
            'resource "aws_elastic_beanstalk_environment" "shop_worker" {\n  name = "${var.project_name}-worker"\n}\n'
        )
        self.assertEqual(self.rules(text), [])

    def test_the_spec_template_rendered_for_two_apps_in_each_mode(self) -> None:
        section = TERRAFORM.split("### `beanstalk.tf`", 1)[1].split("```hcl\n", 1)[1].split("\n```", 1)[0]
        policy = self.policy
        env_header = 'resource "aws_elastic_beanstalk_environment" "<app_name>_<process_type>" '
        template = ""
        for header in (
            'resource "aws_elastic_beanstalk_application" "<app_name>" ',
            env_header,
            'resource "aws_iam_instance_profile" "eb_<app_name>" ',
            'resource "aws_iam_role" "eb_instance_<app_name>" ',
        ):
            start = section.index(header)
            body, _ = policy._extract_braced_block(section, section.index("{", start))
            template += header + body + "\n"

        def render(app: str, suffix: str) -> str:
            return (template.replace("<eb_app_suffix>", suffix).replace("<app_name>", app.replace("-", "_"))
                    .replace("<heroku_app>", app).replace("<process_type>", "web"))

        shared = render("shop-staging", "") + render("shop-production", "")
        per_app = render("shop-staging", "-shop-staging") + render("shop-production", "-shop-production")
        self.assertIn("eb_duplicate_name", self.rules(shared))
        self.assertEqual(self.rules(per_app), [])

    def test_validate_reports_the_rule_and_lists_the_check(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            (root / "terraform").mkdir()
            (root / "terraform/main.tf").write_text(self.render("a", "") + self.render("b", ""), encoding="utf-8")
            report = self.validator.validate(root)
        self.assertIn("eb_duplicate_names", report["checks_run"])
        self.assertEqual(report["artifact_status"], "ARTIFACTS_FAIL")
        self.assertIn("eb_duplicate_name", {item["rule"] for item in report["findings"]})


if __name__ == "__main__":
    unittest.main()
