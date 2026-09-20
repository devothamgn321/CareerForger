# CareerForger

Local-first, human-approved job application system for job discovery, evidence-backed resume
tailoring, deterministic QA, application packaging, and guarded browser autofill—without
fabricated claims or automated submission.

## What it does

CareerForger combines a deterministic Python engine with a local Chrome extension:

```text
job description
  -> normalize and screen
  -> route to a resume family
  -> retrieve evidence
  -> create model-neutral tailoring tickets
  -> compile and QA the resume
  -> stage a reviewed application package
  -> guarded browser autofill
  -> human review and Submit
```

The model is used only for bounded synthesis. State, screening, routing, retrieval, QA,
packaging, filling, and audit history remain deterministic and inspectable.

## Safety model

- The candidate always reviews and clicks Submit.
- Unknown or ambiguous fields remain manual.
- Resume claims must trace to the candidate-controlled Evidence Pack.
- Recurring application facts come from a local Personal Data Sheet/profile.
- No CareerForger backend receives candidate information.
- Login-gated sources, CAPTCHAs, and legal acknowledgements remain human tasks.

## Repository layout

```text
ajos.py                  internal AJOS command-line engine
core/                    ledger, normalize, route, retrieve, tickets, QA, stage, scout, reflect
scripts/                 dashboard and public-board maintenance utilities
tests/                   deterministic regression tests
extension/               P1 Autofill Manifest V3 Chrome extension
docs/ARCHITECTURE.md     complete architecture and technical report
examples/                synthetic package and private-data templates
config.example.json      candidate-neutral configuration template
```

`CareerForger` is the public product/repository name. `AJOS` remains the compatible internal
engine and CLI identifier.

## Technology

- Python 3.10+; Python 3.12 recommended
- SQLite
- Python standard library
- LaTeX via `latexmk`, pdfLaTeX, or Tectonic
- Poppler `pdfinfo`
- Chrome Manifest V3
- Vanilla JavaScript and CSS
- JSON, Markdown, CSV, and self-contained HTML artifacts

No cloud database, vector database, model-provider SDK, Node package tree, or application server
is required by the current architecture.

## Quick start

1. Create private runtime assets outside version control:

   ```bash
   cp config.example.json config.json
   mkdir -p private/bases private/applications private/scouting
   cp examples/PERSONAL_DATA_SHEET.example.md private/PERSONAL_DATA_SHEET.md
   cp examples/EVIDENCE_PACK.example.md private/EVIDENCE_PACK.md
   ```

2. Add your LaTeX chassis and six resume-family bases under `private/`, then update `config.json`.

3. Run the regression suite:

   ```bash
   python3.12 -m unittest discover -v
   ```

4. Inspect CLI commands:

   ```bash
   python3.12 ajos.py
   ```

5. For browser autofill, copy the local profile template and keep it untracked:

   ```bash
   cp extension/profile.default.json extension/profile.local.json
   ```

   Add your private values to `profile.local.json`, load `extension/` as an unpacked Chrome
   extension, and never commit the local profile.

## Current status

Built:

- SQLite state machine, events, evidence statistics, and governed rules
- JD normalization and work-authorization screening
- six-family TF-IDF routing
- evidence retrieval and model-neutral tickets
- deterministic PDF/truth/format/keyword QA
- staged application packages with embedded PDF bytes
- Scouting Policy v2 for public Greenhouse, Lever, and Ashby boards
- read-only approval dashboard generation
- P1 Autofill v0.6.16 with guarded DOM mappings; 33 regression tests

Not built:

- the local DOM-to-application-context bridge described in the architecture report
- automatic application submission, by design
- Gmail/Notion outcome synchronization
- provider-specific model APIs or autonomous task orchestration

## Documentation

- [Complete architecture and technical report](docs/ARCHITECTURE.md)
- [Reusable autofill failure patterns](docs/AUTOFILL_FAILURE_PATTERNS.md)
- [Extension guide](extension/README.md)
- [Application package contract](extension/PACKAGE_FORMAT.md)
- [Security policy](SECURITY.md)

## Private-data boundary

This public repository intentionally excludes real profiles, Personal Data Sheets, Evidence Packs,
resumes, application folders, ledgers, browser profiles, generated PDFs, private references,
credentials, cookies, and tokens. Use the synthetic templates only as schemas.

## Submission boundary

CareerForger prepares, validates, packages, and pre-fills. The human decides whether to apply and
is the only actor who submits.
