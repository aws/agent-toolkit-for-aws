"""Tests for skills/claude-to-bedrock/references/process_export.py.

The script runs in a subprocess with HOME and USERPROFILE pointed at a temp dir
(it writes a scratch folder under ~, which is USERPROFILE on Windows). The
encoding tests force a non-UTF-8 locale to reproduce the Windows default-
encoding crash on any OS (no -I here: it would ignore the locale variables).
The collision test runs in UTF-8 mode so it can only fail on the collision.
"""
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import unittest
import zipfile

SCRIPT = (pathlib.Path(__file__).resolve().parent.parent
          / "skills" / "claude-to-bedrock" / "references" / "process_export.py")


def make_export(downloads, conversations, part="000"):
    with zipfile.ZipFile(downloads / f"conversations-{part}.zip", "w") as zf:
        zf.writestr("conversations.json", json.dumps(conversations, ensure_ascii=False))


def conv(uuid, name, created, text):
    return {
        "uuid": uuid,
        "name": name,
        "created_at": created,
        "summary": "",
        "chat_messages": [
            {"sender": "human", "text": text},
            {"sender": "assistant", "content": [{"type": "text", "text": "ok " + text}]},
        ],
    }


class ProcessExportTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = pathlib.Path(self.tmp.name)
        self.home, self.downloads, self.out = root / "home", root / "dl", root / "out"
        for d in (self.home, self.downloads):
            d.mkdir()

    def tearDown(self):
        self.tmp.cleanup()

    def run_script(self, force_ascii_locale=True):
        env = dict(os.environ, HOME=str(self.home), USERPROFILE=str(self.home),
                   PYTHONIOENCODING="utf-8")
        if force_ascii_locale:
            env.update(LC_ALL="C", LANG="C", PYTHONUTF8="0", PYTHONCOERCECLOCALE="0")
        utf8 = "utf8=0" if force_ascii_locale else "utf8=1"
        return subprocess.run(
            [sys.executable, "-X", utf8, str(SCRIPT), str(self.downloads), str(self.out)],
            env=env, capture_output=True, text=True, encoding="utf-8")

    def test_non_ascii_text_survives(self):
        text = "Résumé 日本語 🚀 naïve"
        make_export(self.downloads, [conv("u1", "Café plans 🚀", "2026-10-01T10:00:00Z", text)])
        r = self.run_script()
        self.assertEqual(r.returncode, 0, r.stderr)
        combined = (self.out / "COMBINED-1p-history.md").read_text(encoding="utf-8")
        self.assertIn(text, combined)
        self.assertIn("Café plans 🚀", (self.out / "GLOBAL-INSTRUCTIONS.txt").read_text(encoding="utf-8"))

    def test_same_date_and_title_do_not_overwrite(self):
        make_export(self.downloads, [
            conv("u1", "Standup", "2026-10-01T09:00:00Z", "first"),
            conv("u2", "Standup", "2026-10-01T17:00:00Z", "second"),
        ])
        r = self.run_script(force_ascii_locale=False)
        self.assertEqual(r.returncode, 0, r.stderr)
        per_conv = sorted(p for p in self.out.glob("*.md") if p.name != "COMBINED-1p-history.md")
        self.assertEqual(len(per_conv), 2, [p.name for p in per_conv])
        bodies = "".join(p.read_text(encoding="utf-8") for p in per_conv)
        self.assertIn("first", bodies)
        self.assertIn("second", bodies)

    def test_dedupes_across_parts_and_skips_html_403_pages(self):
        c = conv("u1", "Dup", "2026-10-01T09:00:00Z", "hello")
        make_export(self.downloads, [c], part="000")
        make_export(self.downloads, [c], part="001")
        (self.downloads / "conversations-002.zip").write_text("<!DOCTYPE html>403", encoding="utf-8")
        r = self.run_script()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("found 1 conversations", r.stdout)
        self.assertIn("conversations-002.zip is not a valid zip", r.stdout)


if __name__ == "__main__":
    unittest.main()
