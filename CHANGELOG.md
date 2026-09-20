# Changelog

## 2026-09-19 — Package bridge (P1 Autofill v0.6.17)

### Added
- **Auto-load.** `advance` publishes each staged package into `extension/packages/` with an
  `index.json`. The sidebar asks the background worker for the package whose apply URL or job id
  matches the open page and loads it without copy-paste; Run autofill attaches the tailored resume
  and cover letter. Matching never uses company name alone, so a wrong resume cannot be attached.
  `ajos.py publish <app_id>` re-sends a package; `mark` (submitted, dropped, outcomes) removes it.
  Controlled by `publish_to_extension` and `extension_dirs` in the config.
- **Cover letters.** `examples/COVER_LETTER_TEMPLATE.example.tex` plus deterministic QA in
  `core/cover.py` (placeholders filled, 200–420 body words, company named, forbidden patterns,
  banned claims, compiles to one page). `advance` runs it before staging when
  `RESULT_cover_letter.tex` exists.
- `tests/test_bridge.py`: publish/unpublish, URL/job-id matching, cover-letter QA.

### Fixed
- The live profile in `chrome.storage` now wins over the snapshot embedded in a package, so older
  packages cannot re-apply stale answers.
- Ledger paths that no longer exist (moved workspace) fall back to the folder under
  `applications_dir`.
- Cover-letter filenames drop descriptors in parentheses, matching resume filenames.

## 2026-09-19 — Profile template and guide

### Added
- `extension/PROFILE_GUIDE.md`: every profile field, the question it answers, and accepted options.
- `extension/profile.example.json`: a fictional filled-in profile showing the format.
- The blank `profile.default.json` now lists every field the engine reads (`gpa`,
  `sponsorship_explanation`, `immediate_sponsorship_explanation`, `choices.onsite`,
  `eeo.sexual_orientation`).
- Test: the shipped template stays blank and the example matches its fields.

### Fixed
- The sidebar's profile recovery path now reads `profile.local.json` before the blank default,
  matching the background seeding.

## 2026-09-19 — P1 Autofill v0.6.16: free-text sponsorship and GPA

### Fixed
- **"If so, please explain" sponsorship questions** rendered as text boxes were skipped. They now fill
  from `sponsorship_explanation` / `immediate_sponsorship_explanation` in the profile (blank by
  default, so they stay manual).
- **GPA text fields** were detected but never filled. They now use `gpa`, or the first education
  entry's `gpa`.

## 2026-09-19 — P1 Autofill v0.6.15: STEM OPT answers from the profile

### Changed
- **STEM OPT extension, E-Verify, and I-983 questions** now have their own field, `choices.stem_opt`.
  When a profile sets it (for example `["Yes"]` for a candidate in a STEM-designated degree who
  will use the extension), those prompts are answered from it. The public default is empty, so they
  stay blank for human review as before. "Are you currently on STEM OPT?" and "authorized for any
  employer without restriction" are always left for the human.

## 2026-09-19 — P1 Autofill v0.6.14: manual stop

### Added
- **Stop autofill.** A red "Stop autofill (Esc)" button in the panel and a stop icon in the header
  (also shown when the panel is collapsed) appear while a run is active. Pressing Esc does the same.
  Previously a run could not be interrupted until every pass finished. Stopping interrupts pending
  waits and all fill loops; fields already filled are kept and the run is marked for manual review.
  Submit is never clicked.

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
- **Work-authorization questions could be answered falsely.** "Are you authorized to work in the
  U.S. without company sponsorship?" was answered **Yes** for a candidate who needs sponsorship,
  because "in the U.S." between the words broke the match. Every question containing "sponsor"
  also received the future-sponsorship answer, so the profile's separate "no immediate
  sponsorship" answer was never used. A single `eligibilityIntent()` classifier now decides the
  meaning of every work-authorization prompt (future sponsorship, immediate sponsorship,
  authorized without sponsorship, OPT/CPT status, proof of eligibility) for dropdowns, buttons,
  and the eligibility guard alike. Prompts that are legally ambiguous for F-1/OPT candidates
  ("any employer without restriction", STEM OPT / E-Verify / I-983 support) are always left for
  the human. Added an `opt_cpt_status` profile choice, blank by default (left for review).
- **Two extension tests never ran** because they were placed after the `unittest.main()` block.
- Removed a duplicated tail section and dead references from `docs/ARCHITECTURE.md`.

### Tests
- 18 → 32 regression tests (the earlier count of 29 included one test that was not actually running).

### Verification
- Unit tests pass on Python 3.10, 3.11, and 3.12.
- Old vs. new normalizer compared on 84 real scouted JDs: title, company, location, URL, and ATS
  unchanged for all 84; one false clearance reject ("nice to have") removed; no new rejects.
- Extension tested in headless Chromium on a mock application form: with a Maryland profile the
  result is unchanged; with California or Texas profiles v0.6.12 wrongly selected Maryland and
  India, v0.6.13 selects the profile's own state and leaves citizenship blank. Submit was never
  triggered.
- Work-authorization check in headless Chromium with the candidate's real answer set: 24 dropdown
  prompts and 5 button-style prompts. v0.6.12 answered 8 of 24 dropdowns and 3 of 5 button
  questions wrong or blank, including "authorized to work without sponsorship" = Yes.
  v0.6.13: 0 wrong; ambiguous prompts left blank; Submit never triggered.
