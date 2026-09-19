"""Prompt-pack generator: model-agnostic LLM tickets.

An LLM step = a TICKET_*.md file in the application folder. ANY model
(Claude, ChatGPT, Antigravity, future) executes it by writing the RESULT_*
file the ticket names. `ajos.py advance` validates the result and moves the
state machine. No API key required; drop-in API automation later.
"""
import json
from pathlib import Path

TAILOR_TEMPLATE = """# TICKET: TAILOR RESUME — {app_id}
STATUS: OPEN. Execute this ticket by writing `RESULT_resume.tex` in this folder.

## Role
{title} @ {company} ({location}) — bucket: {bucket}, base similarity {similarity} ({decision})

## Contract (non-negotiable)
1. Start from the base resume: `{base_path}` (frozen chassis — do NOT change preamble/format).
2. Exactly 1 page when compiled. 85–97% page fill. No hyperlinks (\\href banned), no brackets.
3. TRUTHFULNESS: every claim must trace to the Evidence Pack lines quoted below.
   Numbers ONLY from the metrics bank. The §8 ban list is absolute.
4. Natural keyword integration from the JD keyword list — no stuffing.
5. The contact header location MUST match the job posting location shown above.
   Never leave the base resume location unless it matches the job location or the configured remote-location policy.
6. HARD GUARDRAIL: AJOS deterministic ATS alignment must reach >=90 after QA. A
   years-of-experience gap is NOT an automatic rejection: maximize transferable evidence,
   title/keyword alignment, project selection, and defensible scope, then tailor and compete.
   Keep every claim interview-defensible. The separate `self_ats_estimate` is an advisory
   OPAL role-fit estimate and must never be inflated to clear the deterministic gate. If
   alignment would require fabricating a mandatory credential, clearance, license, work
   authorization, or years of experience, record that structural blocker in `changes`.
7. Write the finished LaTeX to `RESULT_resume.tex` in this folder. Also write
   `RESULT_tailor_meta.json`: {{"used_chunk_ids": [...], "changes": ["..."], "self_ats_estimate": 0-100}}
   — used_chunk_ids MUST list which evidence chunks below you actually used (learning loop input).
   A below-90 deterministic result is a revision request, not permission to abandon the application.

## JD keywords (ranked)
{keywords}

## Evidence gaps the retriever found (address via Gate A: rewording > evidence > defensible project; NEVER invent)
{gaps}

## Selected evidence (chunk_id | section | text)
{evidence}

## Full JD
{jd_text}
"""

ANSWERS_TEMPLATE = """# TICKET: APPLICATION ANSWERS — {app_id}
STATUS: OPEN. Execute by writing `RESULT_answers.md` in this folder.

## Task
Draft answers for the application form's free-text questions, skills section, and
any "why us" boxes for {title} @ {company}.

## Contract
1. Facts ONLY from the Personal Data Sheet and Evidence Pack excerpts below. Work-auth
   answers verbatim from the PDS. Never infer or simplify immigration or sponsorship facts.
2. If the actual form questions are unknown, produce the standard bank: why-this-company
   (3-4 sentences, from the JD), why-this-role, top-5 skills list matched to JD keywords,
   salary expectation policy line, availability/notice, relocation stance.
3. THINK BEFORE WRITING. For every motivation, fit, accomplishment, challenge, or
   "tell us about yourself" question:
   - identify the question's real evaluation criterion;
   - compare ALL supplied evidence excerpts and select the strongest directly relevant,
     interview-defensible accomplishment, not merely the first matching keyword;
   - use: context/problem -> the candidate's action and judgment -> verified result ->
     explicit bridge to this role/company;
   - prefer one specific accomplishment with a supported metric over a generic list;
   - do not reuse the same accomplishment mechanically when another example is stronger.
4. "Why this company?" must combine one verified current company-specific fact, one
   relevant candidate accomplishment, and a concrete contribution they can make in this role.
   Never use generic praise, invent product usage, or claim personal connections. If no
   verified company fact is supplied, write `RESEARCH_REQUIRED` rather than guessing.
5. Salary answers follow the PDS dynamic policy and require current external market evidence
   for the exact role and region. Never fabricate a range.
6. Under 120 words per answer unless the portal imposes a shorter limit. No em-dash stuffing,
   "passionate about", unsupported superlatives, biography dumps, or keyword stuffing.
7. Cross-answer consistency is mandatory: dates, employer, location, work authorization,
   project status, metrics, and resume claims must agree with the staged resume and PDS.
8. Output format: `## Q: <question>` then the answer. These are STAGED for human review —
   never submitted automatically.

## JD keywords
{keywords}

## PDS core (verbatim source)
{pds_excerpt}

## Evidence excerpts
{evidence}

## Full JD
{jd_text}
"""


def write_tailor_ticket(app_dir: Path, app_id: str, jd: dict, routing: dict,
                        retrieval: dict, jd_text: str) -> Path:
    evidence_lines = "\n".join(
        f"- `{c['chunk_id']}` | {c['section']} | {c['text']}" for c in retrieval["selected"])
    ticket = TAILOR_TEMPLATE.format(
        app_id=app_id, title=jd["title"], company=jd["company"], location=jd["location"],
        bucket=routing["bucket"], similarity=routing["similarity"], decision=routing["decision"],
        base_path=routing["base_path"], keywords=", ".join(jd["keywords"]),
        gaps=", ".join(retrieval["gaps"]) or "(none — full coverage)",
        evidence=evidence_lines, jd_text=jd_text.strip())
    path = app_dir / "TICKET_tailor.md"
    path.write_text(ticket)
    return path


def write_answers_ticket(app_dir: Path, app_id: str, jd: dict, retrieval: dict,
                         pds_path: Path, jd_text: str) -> Path:
    pds = pds_path.read_text(errors="ignore")
    evidence_lines = "\n".join(f"- {c['text']}" for c in retrieval["selected"][:12])
    ticket = ANSWERS_TEMPLATE.format(
        app_id=app_id, title=jd["title"], company=jd["company"],
        keywords=", ".join(jd["keywords"][:25]),
        pds_excerpt=pds, evidence=evidence_lines, jd_text=jd_text.strip())
    path = app_dir / "TICKET_answers.md"
    path.write_text(ticket)
    return path


def validate_tailor_result(app_dir: Path) -> tuple[bool, str, dict]:
    tex = app_dir / "RESULT_resume.tex"
    meta_p = app_dir / "RESULT_tailor_meta.json"
    if not tex.exists():
        return False, "RESULT_resume.tex missing — ticket still open", {}
    meta = {}
    if meta_p.exists():
        try:
            meta = json.loads(meta_p.read_text())
        except json.JSONDecodeError:
            return False, "RESULT_tailor_meta.json is invalid JSON", {}
    if len(tex.read_text(errors="ignore")) < 1000:
        return False, "RESULT_resume.tex suspiciously short", meta
    return True, "ok", meta
