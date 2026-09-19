# Sanitized Autofill Failure Patterns

These patterns were derived from live ATS regressions. Candidate-specific
values and company/application details are intentionally omitted.

## AF-P01 — Missing ATS-specific fields

Generic matching may miss employer or location controls with nonstandard
labels. Add the smallest adapter selector and a fixture.

## AF-P02 — Host CSS leakage

Host-page CSS can distort an extension sidebar. Explicitly reset sizing,
line-height, wrapping, buttons, and form-control styles.

## AF-P03 — Combined legal-name field

A visible combined-name label must override misleading internal identifiers.
Always re-read the exact legal name after asynchronous portal behavior.

## AF-P04 — Portal-native resume parser overwrite

An optional `Autofill from resume` control may parse the PDF and overwrite
canonical fields. Target only the required resume attachment control.

## AF-P05 — Framework consumes file input

React may accept the upload and clear `input.files`. Verify the visible exact
filename and an attachment action such as Remove or Replace.

## AF-P06 — Non-idempotent rerun

Blindly clicking choices can toggle correct answers off. Check selected state
before activation and run eligibility invariants after every pass.

## AF-P07 — Greedy substring classification

Generic patterns can match substrings inside unrelated questions. Use word
boundaries and exact high-risk question overrides.

## AF-P08 — Extension reload orphaning

Reloading an unpacked extension can invalidate scripts on already-open pages.
Refresh the application page after every extension reload.

## AF-P09 — Package transport failure

Large clipboard payloads can be truncated or pasted into the wrong window.
Use schema validation, checksums, and a supported transport channel.

## AF-P10 — Typeahead text not committed

Typing text is not equivalent to selecting a suggestion. Preserve proper case,
wait for the active listbox, choose an exact option, and verify hidden/visible
selection state.

## AF-P11 — Overlay blocks portal controls

Default to a 44-pixel icon. Expand only on explicit human click and constrain pointer capture to
the visible extension footprint.

## AF-P12 — Open-menu text creates false verification

Never verify a dropdown from menu text. Read only the committed selected-value node after the
framework settles.

## AF-P13 — Cross-dropdown option leakage

A trusted option click must prove the hit belongs to the intended control, re-resolve current
coordinates, click an exact visible option, and verify that exact control afterward.

## AF-P14 — Short-answer substring collision

Yes/No values require exact matching. Fuzzy matching must never let `No` match `Latino` or other
longer text.

## AF-P15 — Token inside an unrelated word

Apartment, apt, and unit classifiers require word boundaries. A token such as `unit` must not
match `opportunity`.

## AF-P16 — ATS radio groups need question-level identity

Ashby and Lever radios must be resolved as complete question groups and verified from their final
checked state. Work authorization, sponsorship, demographics, relocation/onsite willingness, and
current-location facts remain distinct mappings.

## Required learning loop

Every confirmed failure must produce:

1. a reproducible fixture;
2. root-cause note;
3. minimal deterministic patch;
4. regression test;
5. adapter/version update;
6. post-fill read-back proof.
