"""Dropdown option choice: exact first, word-bounded prefixes, and address rows decided by
city/state/county agreement (never 'the first county'). Runs the real extension code in node."""
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class ChooseOptionTests(unittest.TestCase):
    def test_option_choice_cases(self):
        out = subprocess.run(["node", str(ROOT / "tests" / "js" / "choose_option.js"),
                              str(ROOT / "extension" / "content.js")],
                             capture_output=True, text=True)
        self.assertEqual(out.returncode, 0, out.stdout + out.stderr)


if __name__ == "__main__":
    unittest.main()
