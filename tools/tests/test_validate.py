"""Tests for the .devin-plugin checks in tools/validate.py.

Run: ``python3 -m unittest discover -s tools/tests -v``
"""

import contextlib
import importlib.util
import io
import json
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def load_validate():
    spec = importlib.util.spec_from_file_location("validate", REPO_ROOT / "tools" / "validate.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


METADATA = {"name": "demo", "version": "1.2.0", "description": "Demo plugin."}


class TestDevinManifestParity(unittest.TestCase):
    def setUp(self):
        self.validate = load_validate()
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.validate.REPO_ROOT = Path(self.tmp.name)
        self.plugin = Path(self.tmp.name) / "plugins" / "demo"

    def write(self, rel, data):
        path = self.plugin / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data))

    def errors_for(self, devin, claude=METADATA):
        if claude is not None:
            self.write(".claude-plugin/plugin.json", claude)
        self.write(".codex-plugin/plugin.json", dict(METADATA, author={"name": "x"}, interface={}))
        self.write(".devin-plugin/plugin.json", devin)
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            self.validate.validate_plugin(self.plugin)
        return self.validate.errors

    def test_matching_metadata_passes(self):
        self.assertEqual(self.errors_for(dict(METADATA, skills="./")), [])

    def test_version_mismatch_fails(self):
        errors = self.errors_for(dict(METADATA, version="1.1.0"))
        self.assertEqual(len(errors), 1, errors)
        self.assertIn("'version' in plugins/demo/.devin-plugin/plugin.json does not match "
                      "plugins/demo/.claude-plugin/plugin.json: '1.1.0' != '1.2.0'", errors[0])

    def test_description_mismatch_fails(self):
        errors = self.errors_for(dict(METADATA, description="Stale."))
        self.assertEqual(len(errors), 1, errors)
        self.assertIn("'description' in plugins/demo/.devin-plugin/plugin.json does not match", errors[0])

    def test_missing_version_fails(self):
        errors = self.errors_for({"name": "demo", "description": "Demo plugin."})
        self.assertEqual(len(errors), 1, errors)
        self.assertIn("'version'", errors[0])

    def test_no_claude_manifest_skips_parity(self):
        errors = self.errors_for(dict(METADATA, version="9.9.9"), claude=None)
        self.assertEqual(errors, ["Missing file: plugins/demo/.claude-plugin/plugin.json"])


class TestRepoPlugins(unittest.TestCase):
    def test_every_devin_plugin_passes(self):
        validate = load_validate()
        plugins = sorted(p.parent.parent for p in (REPO_ROOT / "plugins").glob("*/.devin-plugin/plugin.json"))
        self.assertTrue(plugins)
        for plugin in plugins:
            with self.subTest(plugin=plugin.name):
                validate.errors.clear()
                with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                    validate.validate_plugin(plugin)
                self.assertEqual(validate.errors, [])


if __name__ == "__main__":
    unittest.main()
