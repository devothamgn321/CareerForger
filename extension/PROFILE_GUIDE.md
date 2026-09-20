# Profile guide

P1 Autofill fills forms only from **your own local profile**. The public repo ships a blank template
and a fictional example. No real candidate data is committed.

| File | What it is | Commit it? |
|---|---|---|
| `profile.default.json` | Blank template. Every field empty. | Yes (leave it blank) |
| `profile.example.json` | Fictional "Alex Example" showing the format. Never loaded by the extension. | Yes |
| `profile.local.json` | **Your** data. Loaded first if it exists. | **No**, it is git-ignored |

## Setup

```bash
cp extension/profile.default.json extension/profile.local.json
# fill in profile.local.json, then load extension/ as an unpacked extension in Chrome
```

After editing `profile.local.json`, raise its `_profile_version` by 1 and reload the extension so
Chrome picks up the change.

## Rules

- **Blank means "leave it for me".** An empty string `""` or empty list `[]` is never guessed. The field
  is left for you to answer by hand.
- **Lists are option labels, in order of preference.** Forms word options differently, so list the
  variants you accept. The first one that matches an option on the page is picked.
  Example: `"visa_status": ["F-1 OPT", "F-1 Student", "F-1"]`.
- **Yes/No questions** take `["Yes"]` or `["No"]`.
- The extension never clicks Submit.

## Identity and contact (text)

| Field | Example | Notes |
|---|---|---|
| `first_name`, `last_name`, `full_name` | `Alex`, `Example`, `Alex Example` | |
| `email`, `phone` | `alex@example.com`, `555-010-0000` | |
| `phone_country`, `phone_country_code` | `United States`, `+1` | For country-code dropdowns |
| `address.street/apartment/city/state/zip/country` | `Illinois` or `IL` | State accepts full name or 2-letter code |
| `citizenship_country` | `Canada` | Blank = left for you |
| `linkedin`, `portfolio`, `github` | full URLs | |
| `current_company` | `Example Corp` | |
| `earliest_start` | `January 2027` | |
| `gpa` | `3.70` | Used for "What is your GPA?" text boxes. Falls back to `education[0].gpa` |

## Work authorization (`choices`)

| Field | Question it answers | Typical options |
|---|---|---|
| `work_auth` | Are you legally authorized to work in the US? | `["Yes"]` / `["No"]` |
| `located_us` | Are you currently located in the US? | `["Yes"]` / `["No"]` |
| `authorized_without_sponsorship` | Authorized to work **without** sponsorship? | `["Yes"]` / `["No"]` |
| `sponsorship` | Will you now **or in the future** require sponsorship (H-1B)? | `["Yes"]` / `["No"]` |
| `immediate_sponsorship` | Do you require sponsorship **to start** / now? | `["Yes"]` / `["No"]` |
| `opt_cpt_status` | Are you on F-1 OPT or CPT? | `["Yes"]` / `["No"]` |
| `stem_opt` | Eligible for STEM OPT extension / need E-Verify employer / need I-983? | `["Yes"]` / `["No"]` |
| `visa_status` | Current visa status dropdown | e.g. `["F-1 OPT", "F-1"]`, `["H-1B"]`, `["Green Card"]`, `["US Citizen"]` |
| `us_citizen`, `permanent_resident` | Citizen? Green card? | `["Yes"]` / `["No"]` |
| `security_clearance` | Active clearance? | e.g. `["No", "None"]` |
| `relocate`, `onsite` | Willing to relocate / work on-site? | `["Yes"]` / `["No"]` |
| `company_referral` | Were you referred? | `["Yes"]` / `["No"]` |
| `sms_updates` | Opt in to text messages? | `["Yes"]` / `["No"]` |
| `how_heard` | How did you hear about us? | e.g. `["Company careers page", "LinkedIn", "Other"]` |

Free-text versions ("If so, please explain"):

| Field | Used for |
|---|---|
| `sponsorship_explanation` | "Will you now or in the future require sponsorship? Please explain." |
| `immediate_sponsorship_explanation` | "Do you require sponsorship to begin employment? Please explain." |

Always left for you, whatever the profile says: "authorized for **any employer without restriction**"
and "are you **currently on** STEM OPT".

## Voluntary self-identification (`eeo`)

All optional. Leave any list empty to answer by hand. Use the wording your target forms use.

| Field | Example options |
|---|---|
| `gender` | `["Female", "Woman"]`, `["Male", "Man"]`, `["Decline to self-identify"]` |
| `race` | `["Asian"]`, `["Black or African American"]`, `["White"]`, `["Two or More Races"]`, `["Decline to self-identify"]` |
| `hispanic` | `["No", "Not Hispanic or Latino"]`, `["Yes"]`, `["Decline to self-identify"]` |
| `sexual_orientation`, `lgbtq_identity` | `["I don't wish to answer"]` or your own wording |
| `veteran` | `["I am not a protected veteran"]`, `["I identify as one or more of the classifications of protected veteran"]`, `["I don't wish to answer"]` |
| `disability` | `["No, I do not have a disability"]`, `["Yes, I have a disability"]`, `["I don't wish to answer"]` |

## Education (`education`, newest first)

| Field | Example |
|---|---|
| `school` | `["Example State University", "Other"]` (list variants; add `"Other"` as a last resort) |
| `degree` | `["Master of Science (M.S.)", "Master's Degree"]` |
| `major` | `["Computer Science", "Engineering, General"]` |
| `start_month`, `start_year`, `end_month`, `end_year` | `August`, `2025`, `December`, `2026` |
| `still_student` | `true` / `false` |
| `gpa` | `3.70` |
