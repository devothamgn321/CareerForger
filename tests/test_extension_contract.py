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
        # ArrowDown may OPEN a React Select (keyboard opening cannot hit the wrong control),
        # but selection must never be blind keyboard stepping: no Enter/ArrowDown pair that
        # commits whatever option happens to be highlighted.
        self.assertIn("openComboboxByKeyboard", content)
        opener = content[content.index("async function openComboboxByKeyboard"):]
        opener = opener[:opener.index("async function waitForComboboxOptions")]
        self.assertNotIn("Enter", opener)
        for line in content.splitlines():
            if "ArrowDown" in line:
                self.assertNotIn("Enter", line)

    def test_manifest_and_visible_build_version_match(self):
        manifest = json.loads((EXTENSION / "manifest.json").read_text())
        content = (EXTENSION / "content.js").read_text()
        self.assertEqual(manifest["version"], "0.6.23")
        self.assertIn("P1 Autofill v0.6.23", content)

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
        # STEM OPT eligibility is candidate-specific: blank means "leave for the human".
        self.assertEqual(profile["choices"]["stem_opt"], [])

    def test_manual_stop_control_exists_and_interrupts_waits(self):
        content = (EXTENSION / "content.js").read_text()
        self.assertIn('id="p1f-stop"', content)
        self.assertIn('id="p1f-stop-head"', content)
        self.assertIn("e.key === 'Escape' && e.isTrusted", content)
        self.assertIn("if (err instanceof StopRequested) throw err;", content)
        # Waits must be interruptible, and the per-field catch must not swallow a stop.
        self.assertIn("if (RUN.stopped) { reject(new StopRequested()); return; }", content)

    def test_public_profiles_hold_no_real_data(self):
        blank = json.loads((EXTENSION / "profile.default.json").read_text())
        example = json.loads((EXTENSION / "profile.example.json").read_text())
        # The example documents every field the template has, and nothing else.
        self.assertEqual(set(blank) - {"_source"}, set(example) - {"_source"})
        self.assertEqual(set(blank["choices"]), set(example["choices"]))
        self.assertEqual(set(blank["eeo"]), set(example["eeo"]))
        # The shipped template is blank: nothing gets typed into a real form by accident.
        def values(node):
            if isinstance(node, dict):
                for key, value in node.items():
                    if not key.startswith("_") and key != "never_auto_answer":
                        yield from values(value)
            elif isinstance(node, list):
                for item in node:
                    yield from values(item)
            else:
                yield node
        self.assertTrue(all(v in ("", None) for v in values(blank)))
        self.assertIn("example.com", example["email"])
        self.assertIn("profile.local.json", (ROOT / ".gitignore").read_text())


if __name__ == "__main__":
    unittest.main()
