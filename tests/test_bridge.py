"""Package bridge: staged packages are published into the extension folder and matched to
job pages strictly by URL / job id, never by company name alone."""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from core import cover, publish  # noqa: E402


def _package(job_id, url):
    return {"job_id": job_id, "company": "Acme", "role": "PM", "apply_url": url,
            "ats": "lever", "staged_at": "2026-09-19T12:00:00",
            "resume_qa": {"ats_alignment_score": 93}, "cover_letter_data_base64": "eA=="}


class PublishTests(unittest.TestCase):
    def test_publish_and_unpublish_update_index(self):
        with tempfile.TemporaryDirectory() as tmp:
            ext = Path(tmp)
            (ext / "manifest.json").write_text("{}")
            cfg = {"extension_dirs": [str(ext)]}
            publish.publish(_package("a1", "https://jobs.lever.co/acme/11111111-2222-3333-4444-555555555555"), cfg)
            publish.publish(_package("a2", "https://job-boards.greenhouse.io/acme/jobs/7773680003"), cfg)
            index = json.loads((ext / "packages" / "index.json").read_text())["packages"]
            self.assertEqual({e["app_id"] for e in index}, {"a1", "a2"})
            self.assertTrue((ext / "packages" / "a1.json").exists())
            self.assertTrue(index[0]["has_cover_letter"])
            publish.unpublish("a1", cfg)
            index = json.loads((ext / "packages" / "index.json").read_text())["packages"]
            self.assertEqual([e["app_id"] for e in index], ["a2"])

    def test_folders_without_manifest_are_skipped(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(publish.publish(_package("a1", "https://x.test/1234567"),
                                             {"extension_dirs": [tmp]}), [])


class MatchingTests(unittest.TestCase):
    def test_background_matches_only_the_same_job(self):
        source = (ROOT / "extension" / "background.js").read_text()
        start = source.index("function jobTokens")
        end = source.index("async function findPackage")
        cases = [
            ["https://jobs.lever.co/acme/11111111-2222-3333-4444-555555555555",
             "https://jobs.lever.co/acme/11111111-2222-3333-4444-555555555555/apply", True],
            ["https://jobs.lever.co/acme/11111111-2222-3333-4444-555555555555",
             "https://jobs.lever.co/acme/99999999-2222-3333-4444-555555555555/apply", False],
            ["https://jobs.ashbyhq.com/acme/11111111-2222-3333-4444-555555555555",
             "https://jobs.ashbyhq.com/acme/11111111-2222-3333-4444-555555555555/application", True],
            ["https://job-boards.greenhouse.io/acme/jobs/7773680003",
             "https://www.acme.com/careers?gh_jid=7773680003", True],
            ["https://job-boards.greenhouse.io/acme/jobs/7773680003",
             "https://job-boards.greenhouse.io/acme/jobs/7773680004", False],
            ["https://job-boards.greenhouse.io/acme/jobs/7773680003",
             "https://jobs.lever.co/acme-other/careers", False],
        ]
        script = source[start:end] + """
const cases = """ + json.dumps(cases) + """;
console.log(JSON.stringify(cases.map(([apply, page]) => {
  const u = new URL(apply);
  return packageMatches({host: u.host, path: u.pathname.replace(/\\/$/, ''), apply_url: apply}, page);
})));"""
        out = subprocess.run(["node", "-e", script], capture_output=True, text=True, check=True).stdout
        for (apply, page, expected), got in zip(cases, json.loads(out)):
            with self.subTest(page=page):
                self.assertEqual(got, expected)

    def test_live_profile_beats_stale_package_snapshot(self):
        content = (ROOT / "extension" / "content.js").read_text()
        start = content.index("const getProfile")
        self.assertLess(content.index("chrome?.storage?.local", start), content.index("pkg?.profile", start))


class CoverLetterTests(unittest.TestCase):
    def test_placeholders_and_length_fail(self):
        cfg = {"qa": {"forbidden_patterns": ["\\\\href"], "banned_claims": []}}
        template = (ROOT / "examples" / "COVER_LETTER_TEMPLATE.example.tex").read_text()
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "RESULT_cover_letter.tex").write_text(template)
            result = cover.check(Path(tmp), {"company": "Acme"}, cfg)
        self.assertFalse(result["passed"])
        text = " ".join(result["failures"])
        self.assertIn("PLACEHOLDER", text)
        self.assertIn("words", text)
        self.assertNotIn("href", text)  # the template's own comment must not trip the check

    def test_no_letter_means_no_check(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIsNone(cover.check(Path(tmp), {}, {}))


if __name__ == "__main__":
    unittest.main()
