"""Staging: build the human-approval package. Emits package.json in the SAME format
the existing Chrome extension consumes (approved:false gate — Phase A, human clicks submit)."""
import base64
import json
import re
import shutil
import time
from pathlib import Path

CHECKLIST = """# APPROVAL CHECKLIST — {app_id}
Generated {ts}. NOTHING here has been submitted. You click submit.

- [ ] Resume PDF opens, 1 page, no typos, fill looks 85–97%
- [ ] Claims spot-check: every metric traces to Evidence Pack §7
- [ ] RESULT_answers.md reviewed — work-auth answers verbatim from PDS
- [ ] Work-auth flags from JD reviewed: {wa_flags}
- [ ] Company/role not already applied (ledger dup guard passed: {dup_note})
- [ ] Open {url} -> extension pre-fills from package.json (incl. resume) -> verify parsed fields vs resume -> SUBMIT
- [ ] If the portal blocks the extension: drag the PDF from ~/Downloads ({export_note})
- [ ] After submit: `python3 ajos.py mark {app_id} submitted`
"""


def _resume_filename(jd: dict, filename_prefix: str = "Candidate") -> str:
    company = re.split(r"[(—–-]", jd["company"])[0]  # cut descriptors after ( or dash
    company = re.sub(r"[^A-Za-z0-9]", "", company)[:20]
    role = re.sub(r"[^A-Za-z0-9]", "", jd["title"])[:35]
    prefix = re.sub(r"[^A-Za-z0-9_-]", "_", filename_prefix).strip("_") or "Candidate"
    return f"{prefix}_{company}_{role}.pdf"


def _parse_answers(path: Path) -> dict:
    """Convert reviewed RESULT_answers.md into deterministic package fields."""
    if not path.exists():
        return {"custom": []}
    text = path.read_text(errors="ignore")
    matches = list(re.finditer(r"^## Q:\s*(.+?)\s*$", text, flags=re.MULTILINE))
    custom = []
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        answer = text[match.end():end].strip()
        if answer:
            custom.append({"question": match.group(1).strip(), "answer": answer})
    result = {"custom": custom}
    for item in custom:
        question = item["question"].lower()
        if "salary" in question or "compensation" in question:
            result["salary"] = item["answer"]
        elif "how did you hear" in question:
            result["how_heard"] = item["answer"]
        elif question.startswith("why ") and "role" not in question:
            result["why_company"] = item["answer"]
        elif "why this role" in question or "why are you interested in this role" in question:
            result["why_role"] = item["answer"]
    return result


def stage(app_dir: Path, app_id: str, jd: dict, cfg: dict, dup_note: str = "none") -> dict:
    pdf = app_dir / "RESULT_resume.pdf"
    if not pdf.exists():
        cand = sorted(app_dir.glob("*.pdf"), key=lambda p: p.stat().st_mtime, reverse=True)
        if not cand:
            raise FileNotFoundError("no PDF in application folder — QA must run first")
        pdf = cand[0]

    answers_path = app_dir / "RESULT_answers.md"
    qa_report_path = app_dir / "qa_report.json"
    qa_report = {}
    if qa_report_path.exists():
        try:
            qa_report = json.loads(qa_report_path.read_text())
        except (OSError, json.JSONDecodeError):
            qa_report = {}
    qa_checks = qa_report.get("checks", {})
    filename_prefix = re.sub(
        r"[^A-Za-z0-9_-]", "_",
        cfg.get("candidate_filename_prefix", "Candidate")
    ).strip("_") or "Candidate"
    package = {
        "job_id": app_id,
        "company": jd["company"],
        "role": jd["title"],
        "job_location": jd.get("location"),
        "apply_url": jd["url"],
        "ats": jd["ats"],
        "approved": False,
        "resume_filename": _resume_filename(jd, filename_prefix),
        "resume_data_base64": base64.b64encode(pdf.read_bytes()).decode(),
        "answers_file": answers_path.name,
        "answers": _parse_answers(answers_path),
        "resume_qa": {
            "passed": qa_report.get("passed") is True,
            "ats_alignment_score": qa_checks.get("ats_alignment_score"),
            "keyword_coverage": qa_checks.get("keyword_coverage"),
            "opal_role_fit_estimate": qa_checks.get("opal_role_fit_estimate"),
            "pages": qa_checks.get("pages"),
            "fill_percent": qa_checks.get("fill_percent"),
        },
        "staged_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    # Embed the canonical local autofill profile in each package. This keeps form
    # execution deterministic even when an ATS runs the content script in a context
    # where chrome.storage is unavailable. The package is local and already contains
    # the candidate's resume, so this does not introduce a new data boundary.
    profile_dir = Path(cfg.get("pipeline_dir", ".")) / "extension"
    profile_path = profile_dir / "profile.local.json"
    if not profile_path.exists():
        profile_path = profile_dir / "profile.default.json"
    if profile_path.exists():
        package["profile"] = json.loads(profile_path.read_text())
    cover = app_dir / "RESULT_cover_letter.pdf"
    if cover.exists():
        company_slug = re.sub(r"[^A-Za-z0-9]", "", re.split(r"[(—–-]", jd["company"])[0])[:20]
        package["cover_letter_filename"] = (
            f"{filename_prefix}_{company_slug}_Cover_Letter.pdf")
        package["cover_letter_data_base64"] = base64.b64encode(cover.read_bytes()).decode()
    else:
        package["cover_letter_filename"] = None
        package["cover_letter_data_base64"] = None
    (app_dir / "package.json").write_text(json.dumps(package, indent=2))
    # Bridge: make the package visible to the extension so the sidebar auto-loads it.
    published = []
    if cfg.get("publish_to_extension"):
        from core import publish as _publish
        published = _publish.publish(package, cfg)

    # friction fix: drop a properly-named copy of the PDF in ~/Downloads so
    # portals the extension can't inject into are a drag-and-drop away
    export_note = "extension uploads resume from package.json"
    try:
        export_dir = Path(cfg.get("staging_export_dir", "~/Downloads")).expanduser()
        export_dir.mkdir(parents=True, exist_ok=True)
        exported = export_dir / package["resume_filename"]
        shutil.copy2(pdf, exported)
        export_note = f"PDF copy ready in {export_dir.name}/: {package['resume_filename']}"
    except OSError:
        pass  # non-fatal: package.json still carries the resume

    wa = jd.get("work_auth", {})
    (app_dir / "CHECKLIST.md").write_text(CHECKLIST.format(
        app_id=app_id, ts=package["staged_at"],
        wa_flags="; ".join(wa.get("flags", [])[:3]) or "none found",
        dup_note=dup_note, url=jd["url"], export_note=export_note))
    return {"package": str(app_dir / "package.json"), "checklist": str(app_dir / "CHECKLIST.md"),
            "published": published}
