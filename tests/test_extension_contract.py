import json
import shutil
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
EXTENSION = ROOT / "extension"


class ExtensionContractTests(unittest.TestCase):
    def test_public_profile_is_synthetic_and_schema_complete(self):
        profile = json.loads((EXTENSION / "profile.default.json").read_text())
        self.assertEqual(profile["full_name"], "")
        self.assertEqual(profile["email"], "")
        self.assertEqual(profile["address"]["street"], "")
        self.assertEqual(profile["education"], [])
        self.assertIn("work_auth", profile["choices"])
        self.assertIn("sponsorship", profile["choices"])
        self.assertIn("race", profile["eeo"])
        self.assertIn("disability", profile["eeo"])

    def test_unsafe_keyboard_selection_path_is_absent(self):
        content = (EXTENSION / "content.js").read_text()
        background = (EXTENSION / "background.js").read_text()
        self.assertNotIn("TRUSTED_COMBOBOX_KEYBOARD", content)
        self.assertNotIn("TRUSTED_COMBOBOX_KEYBOARD", background)
        self.assertNotIn("trusted-cdp-keyboard", content)
        self.assertNotIn("trusted-cdp-keyboard", background)
        self.assertNotIn("commitComboboxByKeyboard", content)
        self.assertNotIn("ArrowDown", content)

    def test_manifest_and_visible_build_version_match(self):
        manifest = json.loads((EXTENSION / "manifest.json").read_text())
        content = (EXTENSION / "content.js").read_text()
        self.assertEqual(manifest["version"], "0.6.13")
        self.assertIn("P1 Autofill v0.6.13", content)

    def test_short_no_cannot_fuzzy_match_latino(self):
        content = (EXTENSION / "content.js").read_text()
        self.assertIn("if (lw.length <= 3) return false;", content)
        self.assertIn("eeoc[_-]?race", content)

    def test_lever_us_location_and_sponsorship_radios_are_exactly_guarded(self):
        content = (EXTENSION / "content.js").read_text()
        self.assertIn("f: 'located_us_guard'", content)
        self.assertIn("p.choices.located_us || ['Yes']", content)
        self.assertIn("else if (sponsorshipCard)", content)
        self.assertIn("setButtonChoice(sponsorshipCard, p.choices.sponsorship)", content)

    def test_no_candidate_specific_defaults_in_public_source(self):
        content = (ROOT / "extension" / "content.js").read_text()
        self.assertNotIn("|| 'India'", content)
        self.assertNotIn("'MD', '(US) Maryland'", content)
        self.assertIn("function stateVariants", content)

    @unittest.skipUnless(shutil.which("node"), "node is required to execute extension source")
    def test_work_authorization_questions_map_to_the_right_answer_field(self):
        source = (EXTENSION / "content.js").read_text()
        start = source.index("  const ELIGIBILITY_FIELDS")
        end = source.index("  function classify(el, adapterSelectors)")
        cases = json.loads((ROOT / "tests" / "fixtures" / "eligibility_questions.json").read_text())["cases"]
        script = source[start:end] + "\nconst cases = " + json.dumps(cases) + ";\n" + \
            "console.log(JSON.stringify(cases.map(([q]) => eligibilityIntent(q))));"
        out = subprocess.run(["node", "-e", script], capture_output=True, text=True, check=True).stdout
        for (question, expected), got in zip(cases, json.loads(out)):
            with self.subTest(question=question):
                self.assertEqual(got, expected)

    def test_public_profile_has_opt_cpt_field_left_blank(self):
        profile = json.loads((EXTENSION / "profile.default.json").read_text())
        self.assertIn("opt_cpt_status", profile["choices"])
        self.assertEqual(profile["choices"]["opt_cpt_status"], [])


if __name__ == "__main__":
    unittest.main()
