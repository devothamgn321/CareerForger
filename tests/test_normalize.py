import json
import unittest
from pathlib import Path

from core.normalize import careerpuck_to_greenhouse_embed, extract_keywords, normalize, work_auth_screen

CFG = json.loads((Path(__file__).resolve().parents[1] / "config.example.json").read_text())
# An older private config that predates the expanded pattern list must still be protected.
OLD_CFG = {"work_auth": {"hard_reject_patterns": ["no sponsorship"], "flag_patterns": []}}


class KeywordTests(unittest.TestCase):
    def test_keywords_exclude_urls_and_legal_boilerplate(self):
        text = """Product Manager
OpenAI
San Francisco
https://jobs.example.com/role
Build AI workflows and internal products.
Qualified applicants are considered under the Fair Chance Ordinance.
See https://example.com/privacy-policy."""
        keywords = extract_keywords(text)
        self.assertNotIn("https", keywords)
        self.assertNotIn("fair chance", keywords)
        self.assertNotIn("openai", keywords)
        self.assertIn("workflows", keywords)

    def test_keywords_drop_company_location_filler_and_punctuation(self):
        jd = normalize("Associate Product Manager\nAcme Robotics\nPittsburgh, PA\n"
                       "We are looking for someone to own the platform. SQL, Python, experimentation.", CFG)
        kws = jd["keywords"]
        for noise in ("acme", "robotics", "pittsburgh", "looking", "own", "platform."):
            self.assertNotIn(noise, kws)
        for real in ("platform", "sql", "python", "experimentation", "product"):
            self.assertIn(real, kws)


    def test_company_word_used_as_a_domain_word_is_kept(self):
        jd = normalize("Product Manager\nAbnormal Security\nRemote\n"
                       "Own identity security and customer security workflows.", CFG)
        self.assertIn("security", jd["keywords"])
        self.assertNotIn("abnormal", jd["keywords"])


class FieldParsingTests(unittest.TestCase):
    def test_scout_order_title_first_is_kept(self):
        jd = normalize("Technical Program Manager\nZoox\nFoster City, CA\nText.", CFG)
        self.assertEqual((jd["title"], jd["company"]), ("Technical Program Manager", "Zoox"))

    def test_company_first_paste_is_swapped(self):
        jd = normalize("Acme Robotics\nAssociate Product Manager, Autonomy\nLocation: Pittsburgh, PA\nText.", CFG)
        self.assertEqual(jd["title"], "Associate Product Manager, Autonomy")
        self.assertEqual(jd["company"], "Acme Robotics")
        self.assertEqual(jd["location"], "Pittsburgh, PA")

    def test_explicit_labels_win(self):
        jd = normalize("Great opportunity\nCompany: Example Co\nTitle: Data Analyst\nLocation: Remote", CFG)
        self.assertEqual((jd["title"], jd["company"], jd["location"]), ("Data Analyst", "Example Co", "Remote"))


class UrlTests(unittest.TestCase):
    def test_generic_job_url_is_not_rewritten_to_greenhouse(self):
        jd = normalize("Product Manager\nExample Co\nNYC\nText", CFG, "https://example.com/job/1")
        self.assertEqual(jd["url"], "https://example.com/job/1")
        self.assertNotEqual(jd["ats"], "greenhouse")

    def test_greenhouse_shells_are_still_rewritten(self):
        self.assertEqual(careerpuck_to_greenhouse_embed("https://www.careerpuck.com/job-board/acme/job/123"),
                         "https://boards.greenhouse.io/embed/job_app?for=acme&token=123")
        self.assertEqual(careerpuck_to_greenhouse_embed("https://acme.com/careers?gh_jid=555"),
                         "https://boards.greenhouse.io/embed/job_app?for=acme&token=555")


class WorkAuthTests(unittest.TestCase):
    RESTRICTIONS = [
        "This role does not require travel. We are unable to sponsor visas.",
        "No relocation assistance. Must be a US citizen.",
        "Applicants must not require sponsorship now or in the future.",
        'We are an "equal opportunity" employer. Active clearance required.',
        "Candidates must be authorized to work in the US without sponsorship.",
        "We will not sponsor H-1B.",
        "Candidates must have unrestricted work authorization.",
        "Visa sponsorship is not available for this role.",
        "We cannot provide visa sponsorship.",
    ]
    NON_RESTRICTIONS = [
        "No security clearance required.",
        "This role does not require a security clearance.",
        "We sponsor visas for this role.",
        'Scouting note: no explicit "us citizens only" language found.',
        'Work-auth note: Standard sponsorship question, no blocking language ("no sponsorship"/'
        '"citizens only"/"clearance required" not present).',
        "We offer H-1B sponsorship and relocation.",
        'Nice to haves:\n- Security Clearance: active Secret or TS/SCI is "nice to have"',
        "An active security clearance is a plus.",
    ]

    def test_restrictions_hard_reject(self):
        for text in self.RESTRICTIONS:
            with self.subTest(text=text):
                self.assertTrue(work_auth_screen(text, CFG)["hard_reject"])

    def test_negated_requirements_and_sponsoring_employers_pass(self):
        for text in self.NON_RESTRICTIONS:
            with self.subTest(text=text):
                self.assertEqual(work_auth_screen(text, CFG)["hard_reject"], [])

    def test_older_private_config_still_gets_builtin_patterns(self):
        self.assertTrue(work_auth_screen("We are unable to sponsor visas.", OLD_CFG)["hard_reject"])
