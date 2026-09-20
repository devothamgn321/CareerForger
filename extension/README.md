# P1 One-Click Autofill Engine — v0.6.16

Jobright-style, one button, whole form in a single pass. Local-only, **no backend**, nothing
about you leaves the machine. The engine is unified: named adapters cover Ashby, Greenhouse,
and Lever, while guarded label/name/autocomplete discovery handles ordinary forms on other ATS
domains. Unsupported closed shadow roots and cross-origin frames are reported, never guessed.

The panel starts as a 44-pixel lightning icon. Click the icon to expand the full panel; click
the minimize control to return it to the icon. Form detection never forces it open.

## What changed from v0.1
- **One click.** No per-field scanning UI. Hit **⚡ Autofill now** and the engine walks the whole
  DOM (including shadow DOM + same-origin iframes), classifies every field, and fills in one pass.
- **Framework-bypass injection** — native setters + input/change + keydown/keyup so React/Vue/Svelte
  forms accept the values.
- **Exact-match typeahead** — school/city pickers select the option that *exactly* equals the value
  (prefix only as fallback), then verify the field took it. This prevents a partial text match from selecting the wrong school or city option.
- **Paste, don't pick.** The per-application package loads from a **paste box**, not a file dialog —
  no native picker anywhere. If the package embeds `resume_data_base64`, the resume uploads itself.
- Section 5 cloud AI co-processor is intentionally **omitted** (kept our no-backend / approval model).
- **Semantic country/auth guards** — phone country, residence, citizenship, work authorization, sponsorship, and related distinctions
  come only from the local canonical profile and are verified after filling.
- **Resume gate in the package** — new staged packages expose QA status, AJOS alignment,
  keyword coverage, page count, and OPAL advisory fit. Explicit QA failure or AJOS alignment
  below 90 blocks autofill.

## Load it (one time)
1. `chrome://extensions` → **Developer mode** ON → **Load unpacked** → select this folder.
2. On install it seeds your profile (`profile.default.json`) into `chrome.storage.local`.
3. Open any supported ATS application page — the **P1 Autofill** sidebar appears top-right.

## Use it (per application)
1. (Optional) Paste the application-package JSON from the pipeline into the box → **Load package**.
   - Without a package, identity + education still fill from your stored profile.
   - With a package, tailored answers (why-company, salary, how-heard) and the resume fill too.
2. Click **⚡ Autofill now**. Watch the log: `✔` filled+verified, `·` skipped/no-value,
   `✘` needs manual attention.
3. **Review the form yourself.** Education is best-effort per block: if the form starts with one
   Education block, only entry #1 fills — click the form's "Add Education", then Autofill again
   (it is idempotent) to fill entry #2.
4. The extension has no submit control and never clicks a portal submit button. After reviewing
   every field, **the candidate clicks the portal native Submit button**.

## Files
manifest.json · background.js (profile seed + messaging) · content.js (engine + sidebar) ·
sidebar.css · profile.default.json (from PDS) · PACKAGE_FORMAT.md


## Universal means guarded coverage, not blind completion

- Named ATS adapters run first.
- Generic DOM discovery uses labels, accessible names, autocomplete, input names/IDs, required
  state, shadow roots, and same-origin frames.
- Every selected option is read back. Unknown or ambiguous controls become `needs_manual`.
- No keyboard "pick the first option" fallback exists; it was removed after a live regression
  proved that it can commit the opposite Yes/No answer.
- Submit buttons are excluded from discovery and the extension contains no submission path.

## Known best-effort areas
- Multi-entry education relies on the form exposing repeat blocks; per-ATS DOM varies.
- Yes/No questions rendered as custom buttons (e.g. Ashby sponsorship / on-site) use a text-match
  click; unusual labels may miss and show `✘` — fill those by hand.
- Cross-origin iframes (rare on these ATS) are out of reach by design.
