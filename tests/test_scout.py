import csv
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core import scout


class ScoutingPolicyV2Tests(unittest.TestCase):
    def test_freshness_ladder_boundaries(self):
        self.assertEqual([scout.freshness_tier(v) for v in (0.5, 5, 20, 40, 120, None)],
                         [0, 1, 2, 3, 4, 5])
        self.assertEqual(scout.freshness_band(120), ">48h-7d")

    def test_p0_admits_loose_pm_adjacent_title_only(self):
        self.assertIsNone(scout.match_bucket_query("Program Manager, Strategic Initiatives"))
        self.assertEqual(scout.match_p0_query("Program Manager, Strategic Initiatives"), "tpm")
        self.assertIsNone(scout.match_p0_query("Software Engineer"))
        self.assertIsNone(scout.match_p0_query("Director, Product Management"))

    def test_senior_titles_never_enter_the_queue(self):
        for title in (
            "Senior Product Manager",
            "Sr. Technical Program Manager",
            "Lead Product Manager",
            "Staff Product Manager",
            "Group Product Manager, Platform",
            "Product Manager II",
        ):
            self.assertIsNone(scout.match_title(title, "P0")[0])
        self.assertEqual(scout.match_title("Product Manager, AI Enablement", "P1")[0], "pm")

    def test_fit_never_filters_and_freshness_controls_order(self):
        postings = [
            self._posting("new-low-fit", 2),
            self._posting("older-high-fit", 5),
            self._posting("buffer", 120),
            self._posting("stale", 169),
        ]
        similarities = {
            "new-low-fit": 0.0,
            "older-high-fit": 0.99,
            "buffer": 0.01,
            "stale": 1.0,
        }

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            companies = root / "companies.csv"
            with companies.open("w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(
                    f, fieldnames=["company", "likely_ats", "board_token_guess", "tier", "notes"])
                writer.writeheader()
                writer.writerow({"company": "TestCo", "likely_ats": "greenhouse",
                                 "board_token_guess": "test", "tier": "P1", "notes": ""})

            def fake_route(text, cfg, ajos_dir):
                return {"bucket": "pm", "similarity": similarities[text]}

            cfg = {"work_auth": {"hard_reject_patterns": [], "flag_patterns": []}}
            with patch.dict(scout.FETCHERS, {"greenhouse": lambda token, company: postings}), \
                    patch.object(scout, "hours_since",
                                 side_effect=lambda posted_at: float(posted_at)), \
                    patch.object(scout.route, "route", side_effect=fake_route):
                result = scout.run_scout(cfg, root, companies, root / "scouting")

        self.assertEqual([q["hours_ago"] for q in result["queue"]], [2.0, 5.0, 120.0])
        self.assertEqual(result["funnel"]["final"], 3)
        self.assertEqual(result["queue"][0]["similarity"], 0.0)
        self.assertEqual(result["queue"][2]["freshness_band"], ">48h-7d")

    @staticmethod
    def _posting(job_id, hours):
        return {
            "ats": "greenhouse",
            "board_token": "test",
            "job_id": job_id,
            "title": "Product Manager",
            "company": "TestCo",
            "location": "New York, NY",
            "country_hint": "US",
            "url": f"https://example.test/{job_id}",
            "posted_at": hours,
            "description_text": job_id,
        }


if __name__ == "__main__":
    unittest.main()
