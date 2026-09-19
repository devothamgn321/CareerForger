import json
import tempfile
import unittest
from pathlib import Path

from core.qa import (
    _fill_from_bbox_xml,
    ats_alignment_score,
    keyword_coverage,
    read_opal_ats_estimate,
)


class OpalEstimateTests(unittest.TestCase):
    def test_reads_valid_estimate(self):
        with tempfile.TemporaryDirectory() as tmp:
            app_dir = Path(tmp)
            (app_dir / "RESULT_tailor_meta.json").write_text(
                json.dumps({"self_ats_estimate": 91})
            )
            self.assertEqual(read_opal_ats_estimate(app_dir)[0], 91)

    def test_rejects_missing_or_out_of_range_estimate(self):
        with tempfile.TemporaryDirectory() as tmp:
            app_dir = Path(tmp)
            self.assertIsNone(read_opal_ats_estimate(app_dir)[0])
            (app_dir / "RESULT_tailor_meta.json").write_text(
                json.dumps({"self_ats_estimate": 101})
            )
            self.assertIsNone(read_opal_ats_estimate(app_dir)[0])


class AtsAlignmentTests(unittest.TestCase):
    def test_keyword_coverage_ignores_posting_boilerplate(self):
        ratio, missing = keyword_coverage(
            "AI workflows and internal products",
            ["ai", "workflows", "internal", "products", "openai", "https", "fair chance"],
        )
        self.assertEqual(ratio, 1.0)
        self.assertEqual(missing, [])

    def test_transparent_alignment_formula(self):
        checks = {
            "forbidden_patterns": "pass",
            "banned_claims": "pass",
            "header_location": "pass",
            "compile": "compiled",
            "pages": 1,
        }
        self.assertEqual(ats_alignment_score(0.90, checks), 93)
        self.assertEqual(ats_alignment_score(0.60, checks), 72)


class FillMeasurementTests(unittest.TestCase):
    def test_bbox_fill(self):
        xml = """<?xml version="1.0"?>
        <doc><page width="612" height="792">
          <word xMin="40" yMin="60" xMax="90" yMax="100">Top</word>
          <word xMin="40" yMin="680" xMax="90" yMax="704">Bottom</word>
        </page></doc>"""
        self.assertEqual(_fill_from_bbox_xml(xml), 88.9)

    def test_bad_xml(self):
        self.assertIsNone(_fill_from_bbox_xml("<broken"))


if __name__ == "__main__":
    unittest.main()
