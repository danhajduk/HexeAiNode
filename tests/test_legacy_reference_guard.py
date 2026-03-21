import subprocess
import sys
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


class LegacyReferenceGuardTests(unittest.TestCase):
    def test_active_code_legacy_reference_guard_passes(self):
        result = subprocess.run(
            [sys.executable, "scripts/check_legacy_references.py"],
            cwd=REPO_ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            self.fail(result.stderr or result.stdout)


if __name__ == "__main__":
    unittest.main()
