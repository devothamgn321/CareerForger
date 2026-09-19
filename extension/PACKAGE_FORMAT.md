# Application-package JSON format (spec §16, trimmed)

One `package.json` per application folder under `pipeline/applications/<date>_<company>_<role>/`.

```json
{
  "job_id": "ledger job_id",
  "company": "…",
  "role": "…",
  "apply_url": "…",
  "ats": "ashby | greenhouse | lever | generic",
  "approved": false,
  "resume_filename": "Candidate_Company_Role.pdf",
  "resume_data_base64": "(optional) base64 of the tailored PDF",
  "cover_letter_filename": null,
  "cover_letter_data_base64": null,
  "resume_qa": {
    "passed": true,
    "ats_alignment_score": 94,
    "keyword_coverage": 0.91,
    "opal_role_fit_estimate": 88,
    "pages": 1,
    "fill_percent": 91.2
  },
  "answers": {
    "salary": "researched range for this role+metro",
    "how_heard": "Company careers page",
    "why_company": "drafted from Evidence Pack, approved in batch digest",
    "why_role": "role-specific answer",
    "custom": [{"question": "exact portal question", "answer": "reviewed answer"}]
  }
}
```

Rules: `answers.why_company` and every custom answer are exactly what was shown in the staged
answer bank. Nothing is improvised at fill time. The extension never submits, regardless of the
`approved` value; the human always clicks the portal's native Submit button. New packages with
an explicit failed QA result, missing AJOS alignment, or alignment below 90 are blocked before
autofill. `opal_role_fit_estimate` is advisory and is not the submission gate.
