# Security and privacy

CareerForger processes sensitive employment and identity data. The public repository contains only
candidate-neutral code, synthetic templates, and public-safe documentation.

## Never commit

- real profiles, Personal Data Sheets, or Evidence Packs;
- resumes, cover letters, application folders, or staged packages;
- SQLite ledgers or portable ledger exports;
- browser profiles, cookies, session data, credentials, or tokens;
- private documents or generated PDFs.

## Submission boundary

The extension must not contain or invoke a Submit path. CareerForger may prepare and pre-fill an
application, but a human must review the portal and click its native Submit button.

## Reporting a vulnerability

Do not open a public issue containing personal data, application data, credentials, or live portal
captures. Contact the repository owner privately with a minimal, sanitized reproduction.
