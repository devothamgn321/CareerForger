# Changelog

## 2026-09-19 — Core hardening (engine + P1 Autofill v0.6.13)

### Fixed
- **Work-authorization screening missed most restriction wording.** A "no", "not", "without", or
  quote anywhere in the 80 characters before a match cancelled the hard reject, so text such as
  "…does not require travel. We are unable to sponsor visas." passed. Negation is now sentence-scoped
  and only applies to requirement-type terms ("No security clearance required"); sponsorship
  restrictions are never cancelled. Added patterns for "without sponsorship", "must not require
  sponsorship", "unrestricted work authorization", "sponsorship is not available", and "cannot
  provide sponsorship". Built-in patterns now apply even when an older private `config.json` lists
  fewer.
- **Arbitrary job links were rewritten into fake Greenhouse links.** Any non-ATS URL containing
  `/job/<number>` became a Greenhouse embed URL. Rewriting now requires a `gh_jid` parameter or a
  careerpuck job-board URL.
- **Title and company were swapped for company-first pasted JDs.** Line order is still honored for
  scout files; a swap happens only when line 2 is clearly a role and line 1 is not. Explicit
  `Title:`, `Company:`, and `Location:` lines take precedence.
- **A clearance marked "nice to have", "preferred", or "a plus" was a hard reject.** Optional
  requirement-type terms are now screened as flags, not rejections.
- **Scouting notes that list banned phrases** (e.g. `"no sponsorship" ... not present`) are
  recognized as annotations and never trigger a reject.
- **Location kept its `Location:` label.**
- **Keywords included company names, location names, filler words, and trailing punctuation**,
  which produced false gaps and distorted keyword coverage. Company words that are also real
  domain words (e.g. "security" for a security company) are kept.
- **`tests/test_normalize.py` never ran** under `python -m unittest discover` (function-style test);
  converted to `unittest.TestCase`.
- **Public extension source contained candidate-specific defaults** (citizenship country and one
  hard-coded US state). State dropdown variants are now derived from the profile's own state.
- Removed a duplicated tail section and dead references from `docs/ARCHITECTURE.md`.

### Tests
- 18 → 29 regression tests.

### Verification
- Unit tests pass on Python 3.10, 3.11, and 3.12.
- Old vs. new normalizer compared on 84 real scouted JDs: title, company, location, URL, and ATS
  unchanged for all 84; one false clearance reject ("nice to have") removed; no new rejects.
- Extension tested in headless Chromium on a mock application form: with a Maryland profile the
  result is unchanged; with California or Texas profiles v0.6.12 wrongly selected Maryland and
  India, v0.6.13 selects the profile's own state and leaves citizenship blank. Submit was never
  triggered.
