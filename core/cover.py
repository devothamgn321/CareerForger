"""Cover-letter QA: deterministic, zero tokens. Runs only when RESULT_cover_letter.tex exists.
Stage embeds RESULT_cover_letter.pdf in package.json, so the extension attaches it."""
import json
import re
from pathlib import Path

from core import qa

MIN_WORDS, MAX_WORDS = 200, 420


def _body_words(tex: str) -> int:
    body = tex.split("Dear", 1)[-1].split("Sincerely", 1)[0]
    body = re.sub(r"\\[a-zA-Z]+\*?(\{[^}]*\})?", " ", body)
    return len(re.findall(r"[A-Za-z0-9][A-Za-z0-9'’.\-/+]*", body))


def check(app_dir: Path, jd: dict, cfg: dict) -> dict | None:
    tex_path = app_dir / "RESULT_cover_letter.tex"
    if not tex_path.exists():
        return None
    raw = tex_path.read_text(errors="ignore")
    tex = re.sub(r"(?m)(?<!\\)%.*$", "", raw)  # LaTeX comments are not letter content
    failures, checks = [], {}
    if "%%" in raw.replace("%%PLACEHOLDER%%", "") and re.search(r"%%[A-Z_]+%%", raw):
        failures.append("unfilled %%PLACEHOLDER%% left in the letter")
    for pat in cfg["qa"]["forbidden_patterns"]:
        if re.search(pat, tex):
            failures.append(f"forbidden pattern: {pat}")
    banned = [b for b in cfg["qa"]["banned_claims"]
              if re.search(r"\b" + re.escape(b.lower()) + r"\b(?!\w|ing)", tex.lower())]
    if banned:
        failures.append(f"BANNED CLAIMS present (Evidence Pack §8): {banned}")
    words = _body_words(tex)
    checks["body_words"] = words
    if not MIN_WORDS <= words <= MAX_WORDS:
        failures.append(f"body is {words} words; keep it {MIN_WORDS}-{MAX_WORDS}")
    company = str(jd.get("company", "")).split("(")[0].strip()
    if company and company.lower() not in tex.lower():
        failures.append(f"company name '{company}' not mentioned")
    pdf, note = qa.compile_latex(tex_path)
    checks["compile"] = note
    if pdf is None:
        failures.append(f"cover letter did not compile: {note}")
    else:
        pages = qa.pdf_page_count(pdf)
        checks["pages"] = pages
        if pages != 1:
            failures.append(f"cover letter is {pages} pages; must be 1")
    result = {"passed": not failures, "failures": failures, "checks": checks}
    (app_dir / "cover_qa.json").write_text(json.dumps(result, indent=2))
    return result
