import json
import tempfile
import unittest
from pathlib import Path

from core.stage import _parse_answers, stage


class StagePackageTests(unittest.TestCase):
    def test_answer_bank_becomes_canonical_and_custom_answers(self):
        content = """# RESULT
## Q: Why Acme?
Because the role joins platform delivery and AI evaluation.

## Q: Why this role?
It matches my technical program experience.

## Q: Salary expectations
Open to the posted range.
"""
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "RESULT_answers.md"
            path.write_text(content)
            parsed = _parse_answers(path)
        self.assertEqual(parsed["why_company"],
                         "Because the role joins platform delivery and AI evaluation.")
        self.assertEqual(parsed["why_role"], "It matches my technical program experience.")
        self.assertEqual(parsed["salary"], "Open to the posted range.")
        self.assertEqual(len(parsed["custom"]), 3)

    def test_missing_answers_is_explicitly_empty(self):
        self.assertEqual(_parse_answers(Path("/does/not/exist")), {"custom": []})

    def test_stage_exposes_resume_qa_contract(self):
        with tempfile.TemporaryDirectory() as td:
            app_dir = Path(td) / "app"
            app_dir.mkdir()
            (app_dir / "RESULT_resume.pdf").write_bytes(b"%PDF-1.4\n%%EOF")
            (app_dir / "qa_report.json").write_text(json.dumps({
                "passed": True,
                "checks": {
                    "ats_alignment_score": 94,
                    "keyword_coverage": 0.91,
                    "opal_role_fit_estimate": 88,
                    "pages": 1,
                    "fill_percent": 91.2,
                },
            }))
            result = stage(
                app_dir,
                "acme_pm_1",
                {
                    "company": "Acme",
                    "title": "Product Manager",
                    "location": "New York, NY",
                    "url": "https://example.com/jobs/1",
                    "ats": "generic",
                    "work_auth": {},
                },
                {"staging_export_dir": str(Path(td) / "exports")},
            )
            package = json.loads(Path(result["package"]).read_text())
        self.assertEqual(package["resume_qa"]["ats_alignment_score"], 94)
        self.assertEqual(package["resume_qa"]["keyword_coverage"], 0.91)
        self.assertTrue(package["resume_qa"]["passed"])


if __name__ == "__main__":
    unittest.main()
