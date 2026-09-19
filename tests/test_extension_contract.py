import json
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


if __name__ == "__main__":
    unittest.main()

    def test_no_candidate_specific_defaults_in_public_source(self):
        content = (ROOT / "extension" / "content.js").read_text()
        self.assertNotIn("|| 'India'", content)
        self.assertNotIn("'MD', '(US) Maryland'", content)
        self.assertIn("function stateVariants", content)

