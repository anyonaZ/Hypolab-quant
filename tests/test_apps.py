"""Smoke test: every marimo app runs top to bottom in sandbox mode with no cell raising an error.

Cells that wait for a button (mo.stop) are fine; a real exception in any cell fails the test.
Skipped when marimo is not installed. Takes about 30 seconds.
"""
import importlib.util
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
APPS = ["cockpit.py", "dataset_scan.py", "quant_basics.py"]
OK_ERRORS = {"ancestor-stopped", "interruption"}        # waiting for a button is not an error


@unittest.skipIf(importlib.util.find_spec("marimo") is None, "marimo not installed")
class TestApps(unittest.TestCase):
    def test_every_app_runs_without_errors(self):
        for name in APPS:
            with self.subTest(app=name), tempfile.TemporaryDirectory() as home:
                out = Path(home) / "out.html"
                env = dict(os.environ, HYPOLAB_HOME=home)
                r = subprocess.run([sys.executable, "-m", "marimo", "export", "html", str(ROOT / "apps" / name),
                                    "-o", str(out)], env=env, capture_output=True, text=True, timeout=600)
                self.assertEqual(r.returncode, 0, r.stderr[-2000:])
                html = out.read_text()
                names = set(re.findall(r'"ename":\s*"([^"]+)"', html))
                bad = names - OK_ERRORS
                self.assertFalse(bad, f"{name}: cell errors {bad}")
                self.assertNotIn("Traceback (most recent call last)", html)


if __name__ == "__main__":
    unittest.main()
