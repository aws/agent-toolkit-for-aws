#!/usr/bin/env python3
"""Tests for the x402 policy gate, written as security regression proofs.

Run with no arguments:

    python3 test_x402_policy.py

Stdlib only (unittest) so it runs anywhere the skill runs, with no test
dependency to install.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from unittest import mock
from pathlib import Path

import x402_policy as pol

USDC_BASE_SEPOLIA = "0x036CbD53842c5426634e7929541eC2318f3dCF7e"
MERCHANT = "0x1111111111111111111111111111111111111111"
ATTACKER = "0x2222222222222222222222222222222222222222"
ORIGIN = "https://sandbox.node4all.com"

BASE_POLICY = {
    "max_per_payment_usd": "0.50",
    "allowed_networks": ["eip155:84532"],
    "allowed_assets": {"eip155:84532": [USDC_BASE_SEPOLIA]},
    "allowed_recipients": [MERCHANT],
    "allowed_origins": [ORIGIN],
    "allowed_schemes": ["exact"],
}


def challenge(url: str | None = None, **overrides) -> dict:
    """A well-formed x402 v1 challenge for $0.10 to the approved merchant."""
    accept = {
        "scheme": "exact",
        "network": "eip155:84532",
        "asset": USDC_BASE_SEPOLIA,
        "payTo": MERCHANT,
        "amount": "100000",  # 0.10 USDC at 6 decimals
        "extra": {"nonce": "abc123"},
    }
    accept.update(overrides)
    resource_url = url or f"{ORIGIN}/v1/x402-test"
    return {"x402Version": 1, "resource": {"url": resource_url}, "accepts": [accept]}


class PolicyFileTests(unittest.TestCase):
    """Local payment configuration requires restrictive file protections."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "policy.json"
        self.path.write_text(json.dumps(BASE_POLICY))
        self.path.chmod(0o600)

    def tearDown(self):
        self.tmp.cleanup()

    def test_loads_when_mode_is_600(self):
        self.assertEqual(pol.load_config(self.path)["max_per_payment_usd"], "0.50")

    def test_rejects_group_or_world_readable_policy(self):
        for bad_mode in (0o640, 0o604, 0o666, 0o660):
            self.path.chmod(bad_mode)
            with self.assertRaises(pol.PolicyError) as ctx:
                pol.load_config(self.path)
            self.assertIn("expected 0600", str(ctx.exception))

    def test_rejects_symlink_policy(self):
        link = Path(self.tmp.name) / "link.json"
        link.symlink_to(self.path)
        with self.assertRaises(pol.PolicyError) as ctx:
            pol.load_config(link)
        self.assertIn("symlink", str(ctx.exception))

    def test_missing_policy_denies_rather_than_defaulting_open(self):
        with self.assertRaises(pol.PolicyError):
            pol.load_config(Path(self.tmp.name) / "absent.json")

    def test_rejects_nonpositive_or_missing_cap(self):
        for bad in ({}, {"max_per_payment_usd": "0"}, {"max_per_payment_usd": "-1"}):
            self.path.write_text(json.dumps(bad))
            self.path.chmod(0o600)
            with self.assertRaises(pol.PolicyError):
                pol.load_config(self.path)


class ConfigPrecedenceTests(unittest.TestCase):
    """The merged config must not weaken anything, and should strengthen one thing.

    Resource identifiers and the policy live in one file. The session ID is a
    spending credential, so the file must WIN over the environment: otherwise an
    agent able to set a variable could point the runtime at a larger-budget session
    and the 0600 file would be decorative.
    """

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "config.json"
        self._saved = {k: os.environ.get(k) for k in pol.RESOURCE_ENV.values()}

    def tearDown(self):
        for k, v in self._saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        self.tmp.cleanup()

    def _write(self, resources: dict) -> dict:
        self.path.write_text(json.dumps({"resources": resources, "policy": BASE_POLICY}))
        self.path.chmod(0o600)
        return pol.load_config(self.path)

    def test_config_file_beats_environment(self):
        os.environ["PAYMENT_SESSION_ID"] = "ps-ATTACKER-HUGE"
        cfg = self._write({"payment_session_id": "ps-APPROVED-SMALL"})
        self.assertEqual(pol.resolve_resource(cfg, "payment_session_id"), "ps-APPROVED-SMALL")

    def test_runtime_ignores_environment_selected_policy_file(self):
        trusted = Path(self.tmp.name) / "trusted.json"
        hostile = Path(self.tmp.name) / "hostile.json"
        trusted.write_text(json.dumps({"resources": {}, "policy": BASE_POLICY}))
        trusted.chmod(0o600)
        hostile_policy = dict(BASE_POLICY)
        hostile_policy["max_per_payment_usd"] = "99"
        hostile_policy.pop("allowed_recipients")
        hostile_policy["allow_any_recipient"] = True
        hostile.write_text(json.dumps({"resources": {}, "policy": hostile_policy}))
        hostile.chmod(0o600)

        with (
            mock.patch.object(pol, "runtime_config_path", return_value=trusted),
            mock.patch.dict(
                os.environ,
                {
                    "AGENTS_PAY_CONFIG": str(hostile),
                    "X402_POLICY_FILE": str(hostile),
                },
            ),
        ):
            cfg = pol.load_config()

        self.assertEqual(cfg["max_per_payment_usd"], BASE_POLICY["max_per_payment_usd"])
        self.assertEqual(cfg["allowed_recipients"], BASE_POLICY["allowed_recipients"])
        self.assertNotIn("allow_any_recipient", cfg)

    def test_runtime_config_path_ignores_home_environment(self):
        import pwd

        expected = Path(pwd.getpwuid(os.getuid()).pw_dir) / ".agents-pay" / "config.json"
        with mock.patch.dict(os.environ, {"HOME": self.tmp.name}):
            self.assertEqual(pol.runtime_config_path(), expected)

    def test_environment_is_the_fallback_when_the_file_is_silent(self):
        """Containers and Lambda inject identifiers; that path must still work."""
        os.environ["PAYMENT_SESSION_ID"] = "ps-FROM-ENV"
        cfg = self._write({})
        self.assertEqual(pol.resolve_resource(cfg, "payment_session_id"), "ps-FROM-ENV")

    def test_missing_everywhere_resolves_to_none(self):
        os.environ.pop("PAYMENT_SESSION_ID", None)
        cfg = self._write({})
        self.assertIsNone(pol.resolve_resource(cfg, "payment_session_id"))

    def test_policy_section_is_read_from_the_nested_shape(self):
        cfg = self._write({"user_id": "alice"})
        self.assertEqual(cfg["max_per_payment_usd"], "0.50")
        self.assertEqual(pol.resolve_resource(cfg, "user_id"), "alice")

    def test_flat_legacy_policy_file_still_loads(self):
        """An existing policy.json must keep working, not fail open or fail loudly."""
        self.path.write_text(json.dumps(BASE_POLICY))
        self.path.chmod(0o600)
        cfg = pol.load_config(self.path)
        self.assertEqual(cfg["max_per_payment_usd"], "0.50")

    def test_earlier_cap_key_is_still_honoured(self):
        legacy = dict(BASE_POLICY)
        legacy["max_amount_usd"] = legacy.pop("max_per_payment_usd")
        self.path.write_text(json.dumps(legacy))
        self.path.chmod(0o600)
        cfg = pol.load_config(self.path)
        self.assertEqual(pol.per_payment_cap(cfg), "0.50")

    def test_config_file_permissions_remain_enforced_with_resource_identifiers(self):
        """The config remains protected after resource identifiers are added."""
        self._write({"payment_session_id": "ps-1"})
        for bad in (0o640, 0o666):
            self.path.chmod(bad)
            with self.assertRaises(pol.PolicyError):
                pol.load_config(self.path)

    def test_missing_per_payment_cap_refuses_rather_than_paying_unbounded(self):
        no_cap = {k: v for k, v in BASE_POLICY.items() if k != "max_per_payment_usd"}
        with self.assertRaises(pol.PolicyError) as ctx:
            pol.select_accept_entry(challenge(), no_cap)
        self.assertIn("per-payment ceiling", str(ctx.exception))


class RecipientAndValueTests(unittest.TestCase):
    """Untrusted payment challenges cannot control recipient or value."""

    def test_amount_above_ceiling_is_refused(self):
        # 5.00 USDC against a 0.50 cap.
        with self.assertRaises(pol.PolicyError):
            pol.select_accept_entry(challenge(amount="5000000"), BASE_POLICY)

    def test_amount_at_ceiling_is_allowed(self):
        entry = pol.select_accept_entry(challenge(amount="500000"), BASE_POLICY)
        self.assertEqual(entry["payTo"], MERCHANT)

    def test_zero_and_negative_amounts_are_refused(self):
        for bad in ("0", "-100000"):
            with self.assertRaises(pol.PolicyError):
                pol.select_accept_entry(challenge(amount=bad), BASE_POLICY)

    def test_unapproved_network_is_refused(self):
        with self.assertRaises(pol.PolicyError):
            pol.select_accept_entry(challenge(network="eip155:1"), BASE_POLICY)

    def test_wrong_asset_contract_is_refused(self):
        with self.assertRaises(pol.PolicyError):
            pol.select_accept_entry(challenge(asset=ATTACKER), BASE_POLICY)

    def test_unapproved_scheme_is_refused(self):
        with self.assertRaises(pol.PolicyError):
            pol.select_accept_entry(challenge(scheme="upto"), BASE_POLICY)

    def test_explicitly_empty_scheme_list_refuses_every_payment(self):
        policy = dict(BASE_POLICY)
        policy["allowed_schemes"] = []
        with self.assertRaises(pol.PolicyError) as ctx:
            pol.select_accept_entry(challenge(), policy)
        self.assertIn("allows no schemes", str(ctx.exception))

    def test_absent_scheme_list_uses_the_exact_scheme_default(self):
        policy = dict(BASE_POLICY)
        policy.pop("allowed_schemes")
        self.assertEqual(pol.select_accept_entry(challenge(), policy)["scheme"], "exact")

    def test_null_amount_uses_max_amount_required(self):
        entry = pol.select_accept_entry(
            challenge(amount=None, maxAmountRequired="100000"),
            BASE_POLICY,
        )
        self.assertEqual(entry["maxAmountRequired"], "100000")

    def test_conflicting_amount_fields_are_refused(self):
        for amount, maximum in (("1", "50000000"), ("50000000", "1")):
            with self.subTest(amount=amount, maxAmountRequired=maximum):
                with self.assertRaises(pol.PolicyError):
                    pol.select_accept_entry(
                        challenge(amount=amount, maxAmountRequired=maximum),
                        BASE_POLICY,
                    )

    def test_equal_amount_fields_are_allowed(self):
        entry = pol.select_accept_entry(
            challenge(amount="100000", maxAmountRequired="100000"),
            BASE_POLICY,
        )
        self.assertEqual(entry["amount"], entry["maxAmountRequired"])

    def test_checksum_capitalization_still_matches(self):
        entry = pol.select_accept_entry(challenge(asset=USDC_BASE_SEPOLIA.lower()), BASE_POLICY)
        self.assertIsNotNone(entry)

    def test_does_not_blindly_take_first_accepts_entry(self):
        """A compliant later entry must win over a hostile first entry."""
        ch = challenge()
        hostile = dict(ch["accepts"][0])
        hostile["amount"] = "5000000"          # $5.00, over the $0.50 ceiling
        ch["accepts"] = [hostile, ch["accepts"][0]]
        self.assertEqual(pol.select_accept_entry(ch, BASE_POLICY)["amount"], "100000")

    def test_missing_required_fields_are_refused(self):
        for field in ("scheme", "network", "asset", "payTo"):
            ch = challenge()
            del ch["accepts"][0][field]
            with self.assertRaises(pol.PolicyError):
                pol.select_accept_entry(ch, BASE_POLICY)

    def test_refusal_message_does_not_echo_challenge_values(self):
        """A uniform refusal stops a publisher probing the policy field by field."""
        with self.assertRaises(pol.PolicyError) as ctx:
            pol.select_accept_entry(challenge(asset=ATTACKER, amount="5000000"), BASE_POLICY)
        message = str(ctx.exception)
        self.assertNotIn(ATTACKER, message)
        self.assertNotIn("5000000", message)


class SingleTenantUserIdTests(unittest.TestCase):
    """The payer identity is generated once at init and read from the config after.

    One installation = one payer. Requiring --user-id at every step invited a
    mismatch between create-instrument and new-session, which yields a session that
    cannot spend the instrument — a confusing failure with no clear error.
    """

    @classmethod
    def setUpClass(cls):
        import importlib.util

        spec = importlib.util.spec_from_file_location(
            "agents_pay_admin", Path(__file__).resolve().parent / "agents_pay_admin.py"
        )
        cls.admin = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.admin)

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "config.json"
        self._saved = os.environ.pop("PAYMENT_USER_ID", None)

    def tearDown(self):
        if self._saved is not None:
            os.environ["PAYMENT_USER_ID"] = self._saved
        self.tmp.cleanup()

    def test_generated_id_is_opaque(self):
        """It reaches the payments API and the wallet, so it must not leak host or login."""
        generated = self.admin.generate_user_id()
        self.assertTrue(generated.startswith("agents-pay-"))
        self.assertGreater(len(generated), len("agents-pay-") + 8)
        for leak in (os.environ.get("USER", "\0"), os.uname().nodename):
            self.assertNotIn(leak, generated)

    def test_generated_ids_differ_between_installations(self):
        self.assertNotEqual(self.admin.generate_user_id(), self.admin.generate_user_id())

    def test_resolves_from_the_config(self):
        self.path.write_text(json.dumps({"resources": {"user_id": "agents-pay-abc"}, "policy": {}}))
        self.assertEqual(self.admin.resolve_user_id(None, self.path), "agents-pay-abc")

    def test_explicit_flag_wins(self):
        self.path.write_text(json.dumps({"resources": {"user_id": "agents-pay-abc"}, "policy": {}}))
        self.assertEqual(self.admin.resolve_user_id("override", self.path), "override")

    def test_environment_is_the_last_resort(self):
        os.environ["PAYMENT_USER_ID"] = "from-env"
        self.assertEqual(self.admin.resolve_user_id(None, self.path), "from-env")

    def test_absent_everywhere_returns_none(self):
        self.assertIsNone(self.admin.resolve_user_id(None, self.path))

    def test_admin_calls_are_attributed_to_the_skill(self):
        import inspect

        self.assertEqual(self.admin.AGENT_NAME, "aws-agents-pay")
        for command in (self.admin.cmd_create_instrument, self.admin.cmd_new_session):
            self.assertIn("agent_name=AGENT_NAME", inspect.getsource(command))

    def test_runtime_calls_are_attributed_to_the_skill(self):
        import inspect
        import x402_fetch

        self.assertEqual(x402_fetch.AGENT_NAME, "openclaw-aws-agents-pay")
        source = inspect.getsource(x402_fetch)
        self.assertEqual(source.count("agent_name=AGENT_NAME"), 3)

    def test_admin_config_path_preserves_operator_override(self):
        env_path = str(self.path.with_name("from-env.json"))
        explicit_path = str(self.path.with_name("from-flag.json"))
        with mock.patch.dict(os.environ, {"AGENTS_PAY_CONFIG": env_path}):
            self.assertEqual(self.admin.admin_config_path(None), Path(env_path))
            self.assertEqual(
                self.admin.admin_config_path(explicit_path),
                Path(explicit_path),
            )


class RecipientValidationTests(unittest.TestCase):
    """Recipient mode is explicit, exclusive, and fail-closed by default."""

    def test_unknown_recipient_is_refused(self):
        with self.assertRaises(pol.PolicyError):
            pol.select_accept_entry(challenge(payTo=ATTACKER), BASE_POLICY)

    def test_known_recipient_is_accepted(self):
        entry = pol.select_accept_entry(challenge(payTo=MERCHANT), BASE_POLICY)
        self.assertEqual(entry["payTo"], MERCHANT)

    def test_missing_recipient_allowlist_denies_by_default(self):
        policy = dict(BASE_POLICY)
        policy.pop("allowed_recipients")
        with self.assertRaises(pol.PolicyError) as ctx:
            pol.select_accept_entry(challenge(payTo=MERCHANT), policy)
        self.assertIn("allows no recipients", str(ctx.exception))

    def test_recipient_match_is_case_insensitive(self):
        policy = dict(BASE_POLICY)
        policy["allowed_recipients"] = [MERCHANT.upper()]
        entry = pol.select_accept_entry(challenge(payTo=MERCHANT.lower()), policy)
        self.assertEqual(entry["payTo"], MERCHANT.lower())

    def test_allow_any_recipient_accepts_an_unlisted_payee(self):
        policy = dict(BASE_POLICY)
        policy.pop("allowed_recipients")
        policy["allow_any_recipient"] = True
        entry = pol.select_accept_entry(challenge(payTo=ATTACKER), policy)
        self.assertEqual(entry["payTo"], ATTACKER)

    def test_recipient_modes_are_mutually_exclusive(self):
        for value in (True, False):
            with self.subTest(allow_any_recipient=value):
                policy = dict(BASE_POLICY)
                policy["allow_any_recipient"] = value
                with self.assertRaises(pol.PolicyError) as ctx:
                    pol.select_accept_entry(challenge(), policy)
                self.assertIn("mutually exclusive", str(ctx.exception))

    def test_allow_any_recipient_requires_a_boolean(self):
        policy = dict(BASE_POLICY)
        policy.pop("allowed_recipients")
        policy["allow_any_recipient"] = "true"
        with self.assertRaises(pol.PolicyError) as ctx:
            pol.select_accept_entry(challenge(), policy)
        self.assertIn("must be a boolean", str(ctx.exception))

    def test_allow_any_recipient_keeps_other_policy_checks(self):
        policy = dict(BASE_POLICY)
        policy.pop("allowed_recipients")
        policy["allow_any_recipient"] = True
        for kwargs in (
            {"network": "eip155:1"},
            {"asset": ATTACKER},
            {"scheme": "upto"},
            {"amount": "500001"},
        ):
            with self.subTest(**kwargs):
                with self.assertRaises(pol.PolicyError):
                    pol.select_accept_entry(challenge(payTo=ATTACKER, **kwargs), policy)

    def test_network_asset_and_scheme_are_still_validated_for_known_recipient(self):
        for kwargs in ({"network": "eip155:1"}, {"asset": ATTACKER}, {"scheme": "upto"}):
            with self.subTest(**kwargs):
                with self.assertRaises(pol.PolicyError):
                    pol.select_accept_entry(challenge(payTo=MERCHANT, **kwargs), BASE_POLICY)


class AdminRecipientModeTests(unittest.TestCase):
    """The human-facing CLI writes exactly one recipient authorization mode."""

    @classmethod
    def setUpClass(cls):
        import importlib.util

        spec = importlib.util.spec_from_file_location(
            "agents_pay_admin_recipient_tests",
            Path(__file__).resolve().parent / "agents_pay_admin.py",
        )
        cls.admin = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.admin)

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "config.json"

    def tearDown(self):
        self.tmp.cleanup()

    def _run(self, *arguments):
        from contextlib import redirect_stderr, redirect_stdout
        from io import StringIO

        argv = [
            "agents_pay_admin.py",
            "init-config",
            "--path",
            str(self.path),
            *arguments,
        ]
        with (
            mock.patch.object(sys, "argv", argv),
            redirect_stdout(StringIO()),
            redirect_stderr(StringIO()),
        ):
            return self.admin.main()

    def test_recipient_flag_writes_an_allowlist(self):
        self.assertEqual(self._run("--recipient", MERCHANT), 0)
        policy = json.loads(self.path.read_text())["policy"]
        self.assertEqual(policy["allowed_recipients"], [MERCHANT])
        self.assertNotIn("allow_any_recipient", policy)

    def test_allow_any_recipient_writes_explicit_mode(self):
        self.assertEqual(self._run("--allow-any-recipient"), 0)
        policy = json.loads(self.path.read_text())["policy"]
        self.assertIs(policy["allow_any_recipient"], True)
        self.assertNotIn("allowed_recipients", policy)

    def test_recipient_modes_cannot_be_combined(self):
        with self.assertRaises(SystemExit) as ctx:
            self._run("--recipient", MERCHANT, "--allow-any-recipient")
        self.assertEqual(ctx.exception.code, 2)
        self.assertFalse(self.path.exists())

    def test_one_recipient_mode_is_required(self):
        with self.assertRaises(SystemExit) as ctx:
            self._run()
        self.assertEqual(ctx.exception.code, 2)
        self.assertFalse(self.path.exists())


class OptionalOriginTests(unittest.TestCase):
    """Origin allowlisting is optional; baseline URL protections remain required."""

    def _policy(self, origins=None):
        p = dict(BASE_POLICY)
        if origins is None:
            p.pop("allowed_origins", None)
        else:
            p["allowed_origins"] = origins
        return p

    def test_no_origin_list_allows_any_public_https_site(self):
        decision = pol.authorize_payment("https://example.com/paid", challenge(url="https://example.com/paid"), self._policy())
        self.assertEqual(decision["origin"], "https://example.com")

    def test_an_origin_list_still_pins_when_provided(self):
        with self.assertRaises(pol.PolicyError) as ctx:
            pol.authorize_payment("https://example.com/paid", challenge(url="https://example.com/paid"), self._policy([ORIGIN]))
        self.assertIn("allowed_origins", str(ctx.exception))

    def test_mandatory_ssrf_controls_apply_even_with_no_origin_list(self):
        """Dropping the preference must not drop the requirements."""
        for url in ("http://example.com/x", "https://user:pw@example.com/x"):
            with self.subTest(url=url):
                with self.assertRaises(pol.PolicyError):
                    pol.authorize_payment(url, challenge(), self._policy())
        for addr in ("169.254.169.254", "127.0.0.1", "100.64.0.1"):
            with self.subTest(addr=addr):
                with self.assertRaises(pol.PolicyError):
                    pol.assert_public_ip(addr)


class SsrfTests(unittest.TestCase):
    """Arbitrary URL fetching must not enable server-side request forgery."""

    def test_non_https_schemes_are_refused(self):
        for url in ("http://example.com/x", "file:///etc/passwd", "gopher://h/1"):
            with self.assertRaises(pol.PolicyError):
                pol.assert_public_https_url(url)

    def test_embedded_credentials_are_refused(self):
        with self.assertRaises(pol.PolicyError):
            pol.assert_public_https_url("https://user:pw@example.com/x")

    def test_internal_addresses_are_refused(self):
        internal = [
            "127.0.0.1",          # loopback
            "10.0.0.1",           # RFC1918
            "192.168.1.1",        # RFC1918
            "172.16.0.1",         # RFC1918
            "169.254.169.254",    # cloud metadata
            "100.64.0.1",         # CGNAT — not caught by is_private
            "224.0.0.1",          # multicast — not caught by is_private
            "0.0.0.0",            # unspecified
            "::1",                # v6 loopback
            "fd00::1",            # v6 unique-local
            "fe80::1",            # v6 link-local
            "::ffff:127.0.0.1",   # v4-mapped loopback
        ]
        for addr in internal:
            with self.subTest(addr=addr):
                with self.assertRaises(pol.PolicyError):
                    pol.assert_public_ip(addr)

    def test_public_addresses_are_allowed(self):
        for addr in ("93.184.216.34", "1.1.1.1", "2606:4700:4700::1111"):
            with self.subTest(addr=addr):
                pol.assert_public_ip(addr)  # must not raise

    def test_origin_must_be_allowlisted(self):
        """A resolvable but unapproved origin is refused by the allowlist.

        Uses example.com because it actually resolves — otherwise the DNS check
        fires first and we would not be testing the allowlist at all.
        """
        with self.assertRaises(pol.PolicyError) as ctx:
            pol.authorize_payment("https://example.com/x", challenge(), BASE_POLICY)
        self.assertIn("allowed_origins", str(ctx.exception))


class IdempotencyTests(unittest.TestCase):
    """Payment retries use stable idempotency keys."""

    def setUp(self):
        self._saved = os.environ.get("PAYMENT_SESSION_ID")
        os.environ["PAYMENT_SESSION_ID"] = "sess-1"

    def tearDown(self):
        if self._saved is None:
            os.environ.pop("PAYMENT_SESSION_ID", None)
        else:
            os.environ["PAYMENT_SESSION_ID"] = self._saved

    def _token(self, url=f"{ORIGIN}/v1/x402-test", **overrides):
        ch = challenge(**overrides)
        return pol.derive_client_token(url, ch["accepts"][0], ch)

    def test_same_purchase_yields_same_token(self):
        """This is what makes a retry replay one authorization instead of two."""
        self.assertEqual(self._token(), self._token())

    def test_token_survives_a_rotating_publisher_nonce(self):
        """The retry path re-fetches the 402, so the nonce may be fresh each time.

        Mixing the nonce into the token would give every attempt a different
        token — converting the retry this function protects into a second real
        payment, and letting a hostile publisher force double charges by
        rotating nonces. Two separately fetched challenges for the same purchase
        must derive the SAME token.
        """
        first = self._token(extra={"nonce": "server-nonce-1"})
        second = self._token(extra={"nonce": "server-nonce-2"})
        self.assertEqual(first, second)

    def test_token_ignores_an_absent_nonce(self):
        ch = challenge()
        del ch["accepts"][0]["extra"]
        without = pol.derive_client_token(f"{ORIGIN}/v1/x402-test", ch["accepts"][0], ch)
        self.assertEqual(without, self._token())

    def test_explicit_purchase_id_distinguishes_deliberate_repeat_buys(self):
        ch = challenge()
        base = pol.derive_client_token(f"{ORIGIN}/v1/x402-test", ch["accepts"][0], ch)
        first = pol.derive_client_token(f"{ORIGIN}/v1/x402-test", ch["accepts"][0], ch, "order-1")
        second = pol.derive_client_token(f"{ORIGIN}/v1/x402-test", ch["accepts"][0], ch, "order-2")
        self.assertNotEqual(first, second)
        self.assertNotEqual(base, first)

    def test_token_is_stable_across_process_restart(self):
        """Derived, not random — so a restart mid-purchase cannot double-charge."""
        expected = self._token()
        for _ in range(5):
            self.assertEqual(self._token(), expected)

    def test_different_amount_yields_different_token(self):
        self.assertNotEqual(self._token(), self._token(amount="200000"))

    def test_conflicting_amount_aliases_cannot_change_the_signed_value_or_token(self):
        ch = challenge(amount="1", maxAmountRequired="50000000")
        with self.assertRaises(pol.PolicyError):
            pol.derive_client_token(
                f"{ORIGIN}/v1/x402-test",
                ch["accepts"][0],
                ch,
            )

    def test_different_recipient_yields_different_token(self):
        self.assertNotEqual(self._token(), self._token(payTo=ATTACKER))

    def test_different_resource_yields_different_token(self):
        self.assertNotEqual(self._token(), self._token(url=f"{ORIGIN}/v1/other"))

    def test_different_session_yields_different_token(self):
        first = self._token()
        os.environ["PAYMENT_SESSION_ID"] = "sess-2"
        self.assertNotEqual(first, self._token())

    def test_authorization_token_uses_config_session_over_environment(self):
        """The protected config session is the spend boundary, so it keys retries."""
        policy = dict(BASE_POLICY)
        policy["_resources"] = {"payment_session_id": "sess-approved-small"}
        os.environ["PAYMENT_SESSION_ID"] = "sess-attacker-huge"
        ch = challenge()

        decision = pol.authorize_payment(f"{ORIGIN}/v1/x402-test", ch, policy)
        expected = pol.derive_client_token(
            f"{ORIGIN}/v1/x402-test",
            ch["accepts"][0],
            ch,
            session_id="sess-approved-small",
        )
        env_based = pol.derive_client_token(
            f"{ORIGIN}/v1/x402-test",
            ch["accepts"][0],
            ch,
            session_id="sess-attacker-huge",
        )

        self.assertEqual(decision["client_token"], expected)
        self.assertNotEqual(decision["client_token"], env_based)


class PolicyDirectoryTests(unittest.TestCase):
    """The directory matters as much as the file.

    Write access to the containing directory lets another principal rename a
    wider policy into place, which checks on the original inode cannot detect.
    """

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name) / "cfg"
        self.dir.mkdir(mode=0o700)
        self.path = self.dir / "policy.json"
        self.path.write_text(json.dumps(BASE_POLICY))
        self.path.chmod(0o600)

    def tearDown(self):
        self.dir.chmod(0o700)  # so cleanup can remove it
        self.tmp.cleanup()

    def test_loads_from_a_0700_directory(self):
        self.assertTrue(pol.load_config(self.path))

    def test_refuses_a_group_or_world_writable_directory(self):
        for bad_mode in (0o777, 0o722, 0o770):
            self.dir.chmod(bad_mode)
            with self.subTest(mode=oct(bad_mode)):
                with self.assertRaises(pol.PolicyError) as ctx:
                    pol.load_config(self.path)
                self.assertIn("writable", str(ctx.exception))


class SignerInputTests(unittest.TestCase):
    """The signer receives only the policy-approved challenge.

    Validating a challenge and then forwarding the publisher's raw response to
    the signer would mean approving one document and signing another. These
    assert on what the signer receives, not only on what the gate returns.
    """

    @classmethod
    def setUpClass(cls):
        try:
            import x402_fetch  # noqa: F401
        except ImportError as e:  # pragma: no cover
            raise unittest.SkipTest(f"x402_fetch unavailable: {e}")

    def test_signer_receives_only_the_vetted_entry(self):
        """A hostile accepts[0] must never reach the signer."""
        hostile = {
            "scheme": "exact", "network": "eip155:1", "asset": ATTACKER,
            "payTo": ATTACKER, "amount": "50000000",
        }
        compliant = {
            "scheme": "exact", "network": "eip155:84532", "asset": USDC_BASE_SEPOLIA,
            "payTo": MERCHANT, "amount": "100000",
        }
        ch = {"x402Version": 2, "accepts": [hostile, compliant]}

        decision = pol.authorize_payment(f"{ORIGIN}/v1/x402-test", ch, BASE_POLICY)
        # This mirrors exactly what x402_fetch hands to generate_payment_header.
        forwarded = json.loads(
            json.dumps({"x402Version": decision["x402_version"], "accepts": [decision["accept"]]})
        )

        self.assertEqual(len(forwarded["accepts"]), 1, "signer must see exactly one option")
        self.assertEqual(forwarded["accepts"][0], compliant)
        blob = json.dumps(forwarded)
        self.assertNotIn(ATTACKER, blob)
        self.assertNotIn("eip155:1\"", blob)
        self.assertNotIn("50000000", blob)

    def test_signer_receives_only_the_canonical_validated_amount(self):
        for version, expected_key, removed_key in (
            (1, "maxAmountRequired", "amount"),
            (2, "amount", "maxAmountRequired"),
        ):
            with self.subTest(version=version):
                ch = challenge(amount="100000", maxAmountRequired="100000")
                ch["x402Version"] = version
                decision = pol.authorize_payment(
                    f"{ORIGIN}/v1/x402-test",
                    ch,
                    BASE_POLICY,
                )
                accepted = decision["accept"]
                self.assertEqual(accepted[expected_key], "100000")
                self.assertNotIn(removed_key, accepted)
                self.assertEqual(decision["amount_base_units"], "100000")

    def test_runtime_hands_the_signer_only_the_canonical_amount(self):
        import types

        import httpx
        import x402_fetch as fetch

        url = f"{ORIGIN}/v1/x402-test"
        ch = challenge(amount="100000", maxAmountRequired="100000")
        ch["x402Version"] = 2
        policy = {
            **BASE_POLICY,
            "_resources": {
                "payment_manager_arn": "arn:aws:bedrock-agentcore:us-west-2:111111111111:payment-manager/test",
                "payment_instrument_id": "instrument-1",
                "payment_session_id": "session-1",
                "user_id": "user-1",
            },
        }
        captured: list[dict] = []

        class PaymentManager:
            def __init__(self, **_kwargs):
                pass

            def generate_payment_header(self, **kwargs):
                captured.append(json.loads(kwargs["payment_required_request"]["body"]))
                return {"PAYMENT-SIGNATURE": "proof"}

        payments_module = types.ModuleType("bedrock_agentcore.payments")
        payments_module.PaymentManager = PaymentManager
        agentcore_module = types.ModuleType("bedrock_agentcore")
        agentcore_module.payments = payments_module
        challenge_response = httpx.Response(
            402,
            json=ch,
            request=httpx.Request("GET", url),
        )
        challenge_response.read_body = challenge_response.content
        paid_response = httpx.Response(
            200,
            content=b"paid",
            headers={"content-type": "text/plain"},
            request=httpx.Request("GET", url),
        )
        paid_response.read_body = paid_response.content
        responses = [challenge_response, paid_response]

        with (
            mock.patch.object(fetch.pol, "load_config", return_value=policy),
            mock.patch.object(fetch.pol, "assert_public_https_url", return_value=ORIGIN),
            mock.patch.object(fetch, "_get", side_effect=responses),
            mock.patch.dict(
                sys.modules,
                {
                    "bedrock_agentcore": agentcore_module,
                    "bedrock_agentcore.payments": payments_module,
                },
            ),
        ):
            result = json.loads(fetch.x402_fetch(url))

        self.assertTrue(result["paid"], result)
        self.assertEqual(len(captured), 1)
        accepted = captured[0]["accepts"][0]
        self.assertEqual(accepted["amount"], "100000")
        self.assertNotIn("maxAmountRequired", accepted)

    def test_fetch_does_not_forward_publisher_headers_or_body(self):
        """The raw 402 must not be passed through to the signer."""
        import inspect

        import x402_fetch as fetch

        src = inspect.getsource(fetch.x402_fetch)
        self.assertIn("vetted_challenge", src)
        self.assertIn('"body": vetted_challenge', src)
        # The publisher's own headers/body must not reach the signer call.
        self.assertNotIn("dict(response.headers)", src)
        self.assertNotIn('"body": _body_text(response)', src)

    def test_compressed_responses_are_refused(self):
        """A decompression bomb must not be able to blow past the size cap."""
        import inspect

        import x402_fetch as fetch

        src = inspect.getsource(fetch._get)
        self.assertIn('"Accept-Encoding": "identity"', src)
        # The cap must be checked BEFORE the buffer grows.
        self.assertIn("if len(body) + len(chunk) > MAX_BODY_BYTES", src)

    def test_body_limit_env_var_cannot_disable_the_cap(self):
        import x402_fetch as fetch

        self.assertGreaterEqual(fetch.MAX_BODY_BYTES, 1024)
        for bad in ("0", "-1", "abc", ""):
            with self.subTest(value=bad):
                with mock.patch.dict(os.environ, {"X402_BODY_LIMIT_BYTES": bad}):
                    self.assertEqual(
                        fetch._bounded_env("X402_BODY_LIMIT_BYTES", 256.0, 1.0, 1000.0),
                        256.0,
                    )


class TransientSettlementTests(unittest.TestCase):
    """Base Sepolia settlement can be intermittently transient.

    The proof is valid but the paid retry still returns 402. Without a retry that
    surfaces as a failed fetch for a payment the user already made. Safe only because
    the same derived client_token is replayed, so ProcessPayment stays idempotent.
    """

    @classmethod
    def setUpClass(cls):
        try:
            import x402_fetch  # noqa: F401
        except ImportError as e:  # pragma: no cover
            raise unittest.SkipTest(f"x402_fetch unavailable: {e}")

    def test_retry_cap_is_bounded(self):
        """A bad env value must not produce an unbounded payment loop."""
        import x402_fetch as fetch

        self.assertGreaterEqual(fetch.MAX_PAYMENT_ATTEMPTS, 1)
        self.assertLessEqual(fetch.MAX_PAYMENT_ATTEMPTS, 10)
        for bad in ("0", "-1", "abc", "99999"):
            with self.subTest(value=bad):
                with mock.patch.dict(os.environ, {"X402_MAX_PAYMENT_ATTEMPTS": bad}):
                    self.assertEqual(
                        fetch._bounded_env("X402_MAX_PAYMENT_ATTEMPTS", 5, 1, 10),
                        5,
                    )

    def test_the_same_token_is_reused_across_attempts(self):
        """This is what makes the retry safe rather than a double-charge."""
        import inspect

        import x402_fetch as fetch

        src = inspect.getsource(fetch.x402_fetch)
        # The decision (which derives the token) is made once, BEFORE the attempt
        # loop, so every attempt replays the same authorization.
        self.assertLess(src.index("pol.authorize_payment"), src.index("for attempt in range"))
        self.assertEqual(src.count("pol.authorize_payment"), 1)

    def test_exhausted_retries_report_no_double_charge(self):
        import inspect

        import x402_fetch as fetch

        src = inspect.getsource(fetch.x402_fetch)
        self.assertIn("no double charge", src)
        self.assertIn('"paid": False', src)


class SafeMethodTests(unittest.TestCase):
    """Method support without opening an exfiltration channel.

    The fetch tool takes any method. Paid retrieval needs GET/HEAD; a body-bearing verb
    would let the agent push agent-chosen data to an arbitrary origin, which the
    policy gate does not validate because it checks the URL, not a body.
    """

    @classmethod
    def setUpClass(cls):
        try:
            import x402_fetch  # noqa: F401
        except ImportError as e:  # pragma: no cover
            raise unittest.SkipTest(f"x402_fetch unavailable: {e}")

    def test_body_bearing_methods_are_refused(self):
        import x402_fetch as fetch

        for method in ("POST", "PUT", "PATCH", "DELETE"):
            with self.subTest(method=method):
                with self.assertRaises(fetch.PaymentBlocked):
                    fetch._get("https://example.com/x", method=method)

    def test_get_and_head_are_allowed(self):
        import x402_fetch as fetch

        self.assertEqual(fetch._ALLOWED_METHODS, ("GET", "HEAD"))

    def test_method_is_case_insensitive(self):
        import x402_fetch as fetch

        with self.assertRaises(fetch.PaymentBlocked):
            fetch._get("https://example.com/x", method="post")


class HarnessCliTests(unittest.TestCase):
    """The CLI is the interface a harness actually uses, so its contract is tested.

    Claude Code, Codex, Cursor, Kiro and OpenClaw run shell commands — they do not
    import Python and build an agent object. Exit codes matter because a harness
    branches on them without parsing JSON.
    """

    @classmethod
    def setUpClass(cls):
        cls.cli = Path(__file__).resolve().parent / "x402_fetch_cli.py"
        if not cls.cli.exists():  # pragma: no cover
            raise unittest.SkipTest("CLI not present")

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cfg = Path(self.tmp.name) / "config.json"
        self.cfg.write_text(json.dumps({"resources": {}, "policy": BASE_POLICY}))
        self.cfg.chmod(0o600)
        self.env = dict(os.environ)
        for k in pol.RESOURCE_ENV.values():
            self.env.pop(k, None)

    def tearDown(self):
        self.tmp.cleanup()

    def _run(self, *args):
        import subprocess

        scripts = self.cli.parent
        bootstrap = """
import runpy
import sys
from pathlib import Path

scripts = Path(sys.argv.pop(1))
config = Path(sys.argv.pop(1))
cli = scripts / "x402_fetch_cli.py"
sys.path.insert(0, str(scripts))
import x402_policy
x402_policy.runtime_config_path = lambda: config
sys.argv = [str(cli), *sys.argv[1:]]
runpy.run_path(str(cli), run_name="__main__")
"""
        return subprocess.run(
            [
                sys.executable,
                "-c",
                bootstrap,
                str(scripts),
                str(self.cfg),
                *args,
            ],
            capture_output=True, text=True, env=self.env, timeout=120,
        )

    def test_refusal_exits_2_not_1(self):
        """A refusal is a decision, not a fault — a harness must be able to tell."""
        r = self._run("https://169.254.169.254/latest/meta-data/")
        self.assertEqual(r.returncode, 2)
        self.assertTrue(json.loads(r.stdout)["refused"])

    def test_status_reports_unusable_without_a_session(self):
        r = self._run("--status")
        self.assertEqual(r.returncode, 2)
        self.assertFalse(json.loads(r.stdout)["usable"])

    def test_output_is_a_single_json_object_on_stdout(self):
        """Harnesses parse stdout; diagnostics must not contaminate it."""
        r = self._run("https://169.254.169.254/")
        json.loads(r.stdout)  # raises if not exactly one JSON document

    def test_no_url_and_no_flag_is_a_usage_error(self):
        self.assertEqual(self._run().returncode, 1)

    def test_needs_no_framework_import(self):
        """The CLI must not depend on Strands, LangGraph, or any agent framework."""
        src = self.cli.read_text()
        for framework in ("strands", "langgraph", "langchain", "from agents import", "crewai"):
            self.assertNotIn(framework, src.lower())


class BrowserHandleTests(unittest.TestCase):
    """Browser payments use an opaque, single-purpose handle."""

    @classmethod
    def setUpClass(cls):
        try:
            import x402_fetch  # noqa: F401
        except ImportError as e:  # pragma: no cover
            raise unittest.SkipTest(f"x402_fetch unavailable: {e}")

    def setUp(self):
        import time

        import x402_fetch as fetch

        self.fetch = fetch
        fetch._PROOF_VAULT.clear()
        self.handle = "x402h_unittest"
        fetch._PROOF_VAULT[self.handle] = {
            "header": {"PAYMENT-SIGNATURE": "PROOF_BYTES_THAT_MUST_NOT_LEAK"},
            "origin": ORIGIN,
            "path": "/v1/x402-test",
            "expires_at": time.monotonic() + 90,
        }

    def tearDown(self):
        self.fetch._PROOF_VAULT.clear()

    def test_handle_is_bound_to_the_origin(self):
        with self.assertRaises(self.fetch.PaymentBlocked):
            self.fetch.attach_browser_payment(self.handle, "https://evil.example.com/v1/x402-test")

    def test_handle_is_bound_to_the_resource_path(self):
        with self.assertRaises(self.fetch.PaymentBlocked):
            self.fetch.attach_browser_payment(self.handle, f"{ORIGIN}/some/other/path")

    def test_handle_redeems_once_then_is_consumed(self):
        header = self.fetch.attach_browser_payment(self.handle, f"{ORIGIN}/v1/x402-test")
        self.assertIn("PAYMENT-SIGNATURE", header)
        with self.assertRaises(self.fetch.PaymentBlocked):
            self.fetch.attach_browser_payment(self.handle, f"{ORIGIN}/v1/x402-test")

    def test_expired_handle_is_refused(self):
        import time

        self.fetch._PROOF_VAULT[self.handle]["expires_at"] = time.monotonic() - 1
        with self.assertRaises(self.fetch.PaymentBlocked):
            self.fetch.attach_browser_payment(self.handle, f"{ORIGIN}/v1/x402-test")

    def test_unknown_handle_is_refused(self):
        with self.assertRaises(self.fetch.PaymentBlocked):
            self.fetch.attach_browser_payment("x402h_nope", f"{ORIGIN}/v1/x402-test")

    def test_handle_is_not_derived_from_the_proof(self):
        """A handle must carry no information about the proof it references."""
        self.assertTrue(self.handle.startswith("x402h_"))
        self.assertNotIn("PROOF", self.handle.upper())

    def test_model_facing_output_never_contains_the_proof(self):
        """prepare_browser_payment returns a handle + receipt, never proof bytes."""
        import inspect

        src = inspect.getsource(self.fetch.prepare_browser_payment)
        # The proof goes into the vault, and only the handle is serialized out.
        self.assertIn('"header": payment_header,     # stays here; never returned', src)
        self.assertIn('"handle": handle', src)
        self.assertNotIn('"header": payment_header}', src)
        self.assertNotIn("json.dumps(payment_header", src)


class SessionStatusTests(unittest.TestCase):
    """Feature parity with the plugin's `get_payment_session_status` (read-only)."""

    @classmethod
    def setUpClass(cls):
        try:
            import x402_fetch  # noqa: F401
        except ImportError as e:  # pragma: no cover
            raise unittest.SkipTest(f"x402_fetch unavailable: {e}")

    def test_reports_unusable_and_names_the_human_step(self):
        import x402_fetch as fetch

        saved = os.environ.pop("PAYMENT_SESSION_ID", None)
        try:
            result = json.loads(fetch.payment_session_status())
            self.assertFalse(result["usable"])
            # Must not imply the agent can fix it itself.
            self.assertIn("operator", result["next_step"].lower())
        finally:
            if saved is not None:
                os.environ["PAYMENT_SESSION_ID"] = saved

    def test_status_is_read_only(self):
        """It must not be able to create or extend a session."""
        import inspect

        import x402_fetch as fetch

        src = inspect.getsource(fetch.payment_session_status)
        for mutator in ("create_payment_session", "CreatePaymentSession", "update_", "delete_"):
            self.assertNotIn(mutator, src)

    def test_unknown_sdk_status_is_not_reported_as_usable(self):
        import types

        import x402_fetch as fetch

        class PaymentManager:
            def __init__(self, **_kwargs):
                pass

            def get_payment_session(self, **_kwargs):
                return {"state": "MAYBE_ACTIVE"}

        payments_module = types.ModuleType("bedrock_agentcore.payments")
        payments_module.PaymentManager = PaymentManager
        agentcore_module = types.ModuleType("bedrock_agentcore")
        agentcore_module.payments = payments_module
        policy = {
            "_resources": {
                "payment_session_id": "session-1",
                "payment_manager_arn": "arn:aws:bedrock-agentcore:region:account:payment-manager/pm-1",
            }
        }

        with mock.patch.object(fetch.pol, "load_config", return_value=policy):
            with mock.patch.dict(
                sys.modules,
                {
                    "bedrock_agentcore": agentcore_module,
                    "bedrock_agentcore.payments": payments_module,
                },
            ):
                result = json.loads(fetch.payment_session_status())

        self.assertFalse(result["usable"])
        self.assertEqual(result["status"], "unknown")


class DnsPinningTests(unittest.TestCase):
    """DNS rebinding must not reopen the SSRF window.

    These live here rather than in a separate file so the whole security surface
    runs in one command. They import x402_fetch, which needs httpx.
    """

    @classmethod
    def setUpClass(cls):
        try:
            import x402_fetch  # noqa: F401
        except ImportError as e:  # pragma: no cover - environment without httpx
            raise unittest.SkipTest(f"x402_fetch unavailable: {e}")

    def test_pin_is_not_implemented_by_patching_a_global(self):
        """Patching socket.getaddrinfo is racy: a concurrent fetch can unpin."""
        import socket

        import x402_fetch as fetch

        before = socket.getaddrinfo
        transport = fetch._PinnedResolverTransport("93.184.216.34", verify=fetch._ssl_context())
        self.assertIs(socket.getaddrinfo, before, "must not mutate socket.getaddrinfo")
        self.assertEqual(type(transport._pool._network_backend).__name__, "_PinnedBackend")

    def test_connect_ignores_the_requested_host(self):
        """A rebind between resolve and connect cannot change the destination."""
        import inspect

        import x402_fetch as fetch

        transport = fetch._PinnedResolverTransport("93.184.216.34", verify=fetch._ssl_context())
        src = inspect.getsource(transport._pool._network_backend.connect_tcp)
        self.assertIn("self._pinned, port", src)

    def test_internal_pin_is_refused_at_connect_time(self):
        import x402_fetch as fetch

        transport = fetch._PinnedResolverTransport("169.254.169.254", verify=fetch._ssl_context())
        with self.assertRaises(pol.PolicyError):
            transport._pool._network_backend.connect_tcp("anything.test", 443)

    def test_tls_context_never_disables_verification(self):
        import ssl

        import x402_fetch as fetch

        ctx = fetch._ssl_context()
        self.assertTrue(ctx.check_hostname)
        self.assertEqual(ctx.verify_mode, ssl.CERT_REQUIRED)


class AuthorizeTests(unittest.TestCase):
    """End-to-end gate behavior."""

    def test_approved_payment_returns_full_decision(self):
        decision = pol.authorize_payment(f"{ORIGIN}/v1/x402-test", challenge(), BASE_POLICY)
        self.assertEqual(decision["amount_usd"], "0.1")
        self.assertEqual(decision["accept"]["payTo"], MERCHANT)
        self.assertEqual(decision["origin"], ORIGIN)
        self.assertEqual(decision["x402_version"], 1)
        self.assertEqual(len(decision["client_token"]), 64)
        # x402 v2 requires resource in the signed payload for URL binding
        self.assertEqual(decision["resource"], {"url": f"{ORIGIN}/v1/x402-test"})

    def test_resource_none_when_challenge_omits_it(self):
        ch = challenge()
        del ch["resource"]
        decision = pol.authorize_payment(f"{ORIGIN}/v1/x402-test", ch, BASE_POLICY)
        self.assertIsNone(decision["resource"])

    def test_resource_url_mismatch_is_refused(self):
        ch = challenge()
        ch["resource"] = {"url": "https://attacker.example/evil"}
        with self.assertRaises(pol.PolicyError):
            pol.authorize_payment(f"{ORIGIN}/v1/x402-test", ch, BASE_POLICY)

    def test_resource_extra_fields_are_stripped(self):
        ch = challenge()
        ch["resource"] = {"url": f"{ORIGIN}/v1/x402-test", "injected": "payload", "nested": {"x": 1}}
        decision = pol.authorize_payment(f"{ORIGIN}/v1/x402-test", ch, BASE_POLICY)
        self.assertEqual(decision["resource"], {"url": f"{ORIGIN}/v1/x402-test"})

    def test_resource_non_dict_is_ignored(self):
        ch = challenge()
        ch["resource"] = "not-a-dict"
        decision = pol.authorize_payment(f"{ORIGIN}/v1/x402-test", ch, BASE_POLICY)
        self.assertIsNone(decision["resource"])

    def test_resource_non_string_url_is_ignored(self):
        ch = challenge()
        ch["resource"] = {"url": 12345}
        decision = pol.authorize_payment(f"{ORIGIN}/v1/x402-test", ch, BASE_POLICY)
        self.assertIsNone(decision["resource"])

    def test_non_dict_challenge_is_refused(self):
        for bad in ("[]", None, 5, []):
            with self.assertRaises(pol.PolicyError):
                pol.authorize_payment(f"{ORIGIN}/x", bad, BASE_POLICY)

    def test_base_unit_conversion(self):
        self.assertEqual(pol.base_units_to_usd("1000000"), pol.Decimal("1"))
        self.assertEqual(pol.base_units_to_usd("1"), pol.Decimal("0.000001"))

    def test_fractional_base_units_are_refused(self):
        with self.assertRaises(pol.PolicyError):
            pol.base_units_to_usd("100.5")

    def test_only_canonical_integer_amounts_are_accepted(self):
        """A publisher must not express an amount in an exotic encoding.

        Decimal() alone parses all of these. They are rejected so an amount can
        never read as one value to the code and another to a human reading logs.
        """
        for bad in (
            "1E+7",        # scientific notation
            "Infinity",    # not finite
            "NaN",         # not a number
            "1_000_000",   # underscore separators
            "500000.0",    # trailing fraction
            "  500000  ",  # surrounding whitespace
            "+500000",     # explicit sign
            "0x7A120",     # hex
            "",            # empty
            "-500000",     # negative
        ):
            with self.subTest(amount=bad):
                with self.assertRaises(pol.PolicyError):
                    pol.base_units_to_usd(bad)

    def test_canonical_amounts_still_work(self):
        self.assertEqual(pol.base_units_to_usd("500000"), pol.Decimal("0.5"))
        self.assertEqual(pol.base_units_to_usd(500000), pol.Decimal("0.5"))

    def test_exotic_amount_in_a_challenge_is_refused_not_paid(self):
        """The gate must refuse such a challenge outright, not coerce the value."""
        for bad in ("1E+7", "Infinity", "500000.0"):
            with self.subTest(amount=bad):
                with self.assertRaises(pol.PolicyError):
                    pol.select_accept_entry(challenge(amount=bad), BASE_POLICY)


if __name__ == "__main__":
    unittest.main(verbosity=2)
