"""QA gate: deterministic checks, zero tokens. Fail -> back to tailoring with reasons."""
import json
import re
import shutil
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path


def compile_latex(tex_path: Path) -> tuple[Path | None, str]:
    if (shutil.which("latexmk") is None and shutil.which("pdflatex") is None
            and shutil.which("tectonic") is None):
        return None, "no latex toolchain on this machine — compile skipped"
    if shutil.which("latexmk"):
        cmd = ["latexmk", "-pdf", "-interaction=nonstopmode", "-halt-on-error", tex_path.name]
    elif shutil.which("pdflatex"):
        cmd = ["pdflatex", "-interaction=nonstopmode", tex_path.name]
    else:
        cmd = ["tectonic", "--keep-logs", "--keep-intermediates", tex_path.name]
    try:
        subprocess.run(cmd, cwd=tex_path.parent, capture_output=True, timeout=120)
    except subprocess.TimeoutExpired:
        return None, "latex compile timed out"
    pdf = tex_path.with_suffix(".pdf")
    return (pdf, "compiled") if pdf.exists() else (None, "compile failed — check .log")


def pdf_page_count(pdf_path: Path) -> int:
    """Page count, most reliable source first: pdfinfo -> latex .log -> raw bytes."""
    if shutil.which("pdfinfo"):
        out = subprocess.run(["pdfinfo", str(pdf_path)], capture_output=True, text=True).stdout
        m = re.search(r"Pages:\s+(\d+)", out)
        if m:
            return int(m.group(1))
    log = pdf_path.with_suffix(".log")
    if log.exists():
        m = re.search(r"Output written on .*\((\d+) pages?", log.read_text(errors="ignore"))
        if m:
            return int(m.group(1))
    data = pdf_path.read_bytes()
    m = re.findall(rb"/Type\s*/Pages\b[^>]*?/Count\s+(\d+)", data)
    if m:
        return max(int(x) for x in m)
    return len(re.findall(rb"/Type\s*/Page\b", data))


def keyword_coverage(tex_text: str, keywords: list[str]) -> tuple[float, list[str]]:
    low = tex_text.lower()
    ignored = {"https", "http", "fair chance", "openai"}

    def _present(kw: str) -> bool:
        kw = kw.strip().lower()
        if not kw:
            return True
        tokens = kw.split()
        if len(tokens) == 1:
            return kw in low
        # Multi-word JD keywords are stopword-stripped bigrams (e.g. "point view",
        # "riders drivers"). Requiring the exact contiguous string rewards keyword
        # stuffing, so count the keyword when every token appears in the resume;
        # natural prose ("point of view", "riders and drivers") then scores honestly.
        return all(tok in low for tok in tokens)

    top = [kw for kw in keywords[:20] if kw.strip().lower() not in ignored]
    missing = [kw for kw in top if not _present(kw)]
    return round(1 - len(missing) / max(len(top), 1), 2), missing


def read_opal_ats_estimate(app_dir: Path) -> tuple[int | None, str]:
    """Read the model's declared OPAL estimate; never present it as externally calibrated."""
    path = app_dir / "RESULT_tailor_meta.json"
    if not path.exists():
        return None, "RESULT_tailor_meta.json missing"
    try:
        meta = json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return None, "RESULT_tailor_meta.json invalid"
    value = meta.get("self_ats_estimate")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None, "self_ats_estimate missing or non-numeric"
    if value < 0 or value > 100:
        return None, "self_ats_estimate outside 0-100"
    return int(round(value)), "internal OPAL estimate (not externally calibrated)"


def ats_alignment_score(keyword_ratio: float, checks: dict) -> int:
    """Transparent internal ATS-alignment score; role-fit/seniority is separate."""
    score = 70 * max(0.0, min(1.0, keyword_ratio))
    score += 6 if checks.get("forbidden_patterns") == "pass" else 0
    score += 6 if checks.get("banned_claims") == "pass" else 0
    score += 6 if checks.get("header_location") == "pass" else 0
    score += 6 if checks.get("compile") == "compiled" else 0
    score += 6 if checks.get("pages") == 1 else 0
    return int(round(score))


def header_location_matches(tex_text: str, job_location: str) -> tuple[bool, str]:
    """Final resume header must use the posting location, not the base's home location."""
    header = tex_text.split(r"\section{SUMMARY}", 1)[0].lower()
    location = str(job_location or "").strip()
    if not location:
        return False, "job location unavailable"
    if re.search(r"\bremote\b", location, flags=re.IGNORECASE):
        return ("remote" in header, "Remote")
    primary = re.split(r"[;/|]", location, maxsplit=1)[0].strip()
    city = primary.split(",", 1)[0].strip()
    if not city or city.lower() in {"united states", "us", "usa"}:
        return True, location
    return (city.lower() in header, city)


def _fill_from_bbox_xml(xml_text: str) -> float | None:
    """Estimate vertical page use from pdftotext's word boxes."""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return None
    page = next((node for node in root.iter() if node.tag.endswith("page")), None)
    if page is None:
        return None
    height = float(page.attrib.get("height", 0))
    bottoms = [
        float(node.attrib["yMax"])
        for node in page.iter()
        if node.tag.endswith("word") and "yMax" in node.attrib
    ]
    if not height or not bottoms:
        return None
    return round(100 * max(bottoms) / height, 1)


def pdf_fill_percent(pdf_path: Path) -> float | None:
    """Return vertical content fill without rasterizing or using vision."""
    if shutil.which("pdftotext") is None:
        return None
    proc = subprocess.run(
        ["pdftotext", "-bbox", str(pdf_path), "-"],
        capture_output=True, text=True, timeout=30,
    )
    return _fill_from_bbox_xml(proc.stdout) if proc.returncode == 0 else None


def run_qa(app_dir: Path, jd: dict, cfg: dict) -> dict:
    tex_path = app_dir / "RESULT_resume.tex"
    tex = tex_path.read_text(errors="ignore")
    checks, failures = {}, []

    for pat in cfg["qa"]["forbidden_patterns"]:
        if re.search(pat, tex):
            failures.append(f"forbidden pattern: {pat}")
    checks["forbidden_patterns"] = "fail" if failures else "pass"

    # word-boundary match so "Data Engineer" (banned title) doesn't hit
    # "Data Engineering Principles" (legitimate coursework)
    banned_hits = [b for b in cfg["qa"]["banned_claims"]
                   if re.search(r"\b" + re.escape(b.lower()) + r"\b(?!\w|ing)", tex.lower())]
    if banned_hits:
        failures.append(f"BANNED CLAIMS present (Evidence Pack §8): {banned_hits}")
    checks["banned_claims"] = "fail" if banned_hits else "pass"

    location_ok, expected_location = header_location_matches(tex, jd.get("location", ""))
    checks["header_location"] = "pass" if location_ok else f"fail (expected {expected_location})"
    if not location_ok:
        failures.append(
            f"resume header location must match job posting: expected {expected_location}")

    cov, missing = keyword_coverage(tex, jd["keywords"])
    checks["keyword_coverage"] = cov
    if cov < cfg["qa"]["min_keyword_coverage"]:
        failures.append(f"keyword coverage {cov} < {cfg['qa']['min_keyword_coverage']}; missing: {missing[:8]}")

    estimate, estimate_note = read_opal_ats_estimate(app_dir)
    checks["opal_role_fit_estimate"] = estimate
    checks["opal_role_fit_note"] = estimate_note

    pdf, compile_msg = compile_latex(tex_path)
    checks["compile"] = compile_msg
    if pdf:
        pages = pdf_page_count(pdf)
        checks["pages"] = pages
        if pages > cfg["qa"]["max_pages"]:
            failures.append(f"{pages} pages > {cfg['qa']['max_pages']}")
        fill = pdf_fill_percent(pdf)
        checks["fill_percent"] = fill if fill is not None else "measurement unavailable"
        if fill is not None:
            minimum = cfg["qa"]["min_fill_percent"]
            maximum = cfg["qa"]["max_fill_percent"]
            if fill < minimum:
                failures.append(f"page fill {fill}% < {minimum}%")
            elif fill > maximum:
                failures.append(f"page fill {fill}% > {maximum}%")
        checks["pdf"] = str(pdf.name)
    elif "skipped" not in compile_msg:
        failures.append(compile_msg)

    alignment = ats_alignment_score(cov, checks)
    checks["ats_alignment_score"] = alignment
    checks["ats_alignment_formula"] = (
        "70% JD keyword coverage + 30% parse/format/truth/location checks")
    minimum_alignment = cfg["qa"]["min_ats_alignment_score"]
    if alignment < minimum_alignment:
        failures.append(
            f"ATS alignment score {alignment} < {minimum_alignment}; return to tailoring")

    return {"passed": not failures, "checks": checks, "failures": failures}
