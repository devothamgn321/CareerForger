"""JD normalizer: raw JD text -> structured dict. Deterministic, zero tokens.

Input format = pipeline/scouting/jds/*.txt convention:
  line 1 title, line 2 company, line 3 location, line 4 url, optional 'Job ID:' line,
  then free text. Falls back gracefully on arbitrary pasted JDs.
Work-auth screening: hard-reject and flag regexes from config.json.
"""
import re
from collections import Counter

STOPWORDS = set("""a an and are as at be been by for from has have if in into is it its of on or our
that the their them they this to was we were will with you your not who what how all more can may
about across within us team work working role roles job description years experience including
including strong ability able etc using use used new help both each other than most any also
required requirements preferred qualifications responsibilities skills benefits equal opportunity
employer applicants candidates position company
salary compensation stock insurance bonus equity rsus perks vacation holidays 401k""".split())

# Posting boilerplate and URL/legal tokens are not role competencies. Keeping them in
# the ranked list made QA reward phrases such as "fair chance" and "https" in resumes.
STOPWORDS.update("""https http www com fair chance ordinance policy statement privacy
accommodation accommodations disability disabilities arrest conviction criminal history
law laws lawful eeo affirmative action report form link protected characteristic
openai""".split())

ATS_PATTERNS = {
    "greenhouse": r"greenhouse\.io",
    "lever": r"lever\.co",
    "ashby": r"ashbyhq\.com",
    "workday": r"myworkdayjobs\.com|workday",
    "icims": r"icims\.com",
    "taleo": r"taleo\.net",
}


def detect_ats(text_and_url: str) -> str:
    low = text_and_url.lower()
    for ats, pat in ATS_PATTERNS.items():
        if re.search(pat, low):
            return ats
    return "unknown"


def careerpuck_to_greenhouse_embed(url: str) -> str:
    """AF-017/AF-019: many employers front the Greenhouse application on their OWN domain
    (careerpuck.com, redventures.com, etc.) where P1 tags the page `[generic]` and its Greenhouse
    field-mapping + trusted click never engage. If the URL carries a Greenhouse job id (gh_jid, or a
    careerpuck /job/<id>) and is not already a known ATS host, rebuild the fillable Greenhouse embed:
    boards.greenhouse.io/embed/job_app?for=<board>&token=<jobid>. Returns "" if none can be derived."""
    low = (url or "").lower()
    if not url or any(h in low for h in ("greenhouse.io", "ashbyhq.com", "lever.co")):
        return ""
    mt = re.search(r"gh_jid=(\d+)", url) or re.search(r"/job/(\d+)", url)
    if not mt:
        return ""
    token = mt.group(1)
    mb = re.search(r"careerpuck\.com/job-board/([^/?]+)", url, re.I)
    if mb:
        board = mb.group(1)
    else:
        mh = re.search(r"https?://(?:[^/]*\.)?([^./]+)\.[a-z]{2,}(?:[/:?]|$)", url, re.I)
        board = mh.group(1) if mh else ""
    if not board:
        return ""
    return f"https://boards.greenhouse.io/embed/job_app?for={board}&token={token}"


NEGATION_MARKERS = ["no ", "not ", "without ", "n't", "no explicit", "“", "\""]


def _negated(low: str, match: re.Match, window: int = 80) -> bool:
    """True if a hard-reject hit sits in negated/quoted context, e.g. a scouting
    note reading: no explicit 'us citizens only' language found."""
    before = low[max(0, match.start() - window):match.start()]
    return any(m in before for m in NEGATION_MARKERS)


def work_auth_screen(text: str, cfg: dict) -> dict:
    low = text.lower()
    hard = []
    for p in cfg["work_auth"]["hard_reject_patterns"]:
        m = re.search(p, low)
        if m and not _negated(low, m):
            hard.append(p)
    flags = []
    for p in cfg["work_auth"]["flag_patterns"]:
        for m in re.finditer(p, low):
            start = max(0, m.start() - 90)
            snippet = re.sub(r"\s+", " ", text[start:m.end() + 90]).strip()
            flags.append(snippet)
    return {"hard_reject": hard, "flags": flags[:6], "ok": not hard}


def extract_keywords(text: str, top_n: int = 40) -> list[str]:
    # unigrams + bigrams, crude but deterministic; the router and retriever share these
    # Job ID lines are file metadata, not JD content — UUID fragments (e.g. "edc-b") must
    # never become keywords QA scores resumes against
    text = re.sub(r"Job ID:.*", " ", text)
    text = re.sub(r"https?://\S+", " ", text)
    words = [w.lower() for w in re.findall(r"[A-Za-z][A-Za-z+#/.-]{1,}", text)]
    words = [w for w in words if w not in STOPWORDS and len(w) > 2]
    uni = Counter(words)
    bi = Counter(f"{a} {b}" for a, b in zip(words, words[1:])
                 if a not in STOPWORDS and b not in STOPWORDS)
    ranked = [w for w, _ in (uni + Counter({k: v * 2 for k, v in bi.items() if v > 1})).most_common(top_n * 2)]
    return ranked[:top_n]


def normalize(jd_text: str, cfg: dict, source_url: str = "") -> dict:
    lines = [ln.strip() for ln in jd_text.splitlines()]
    nonempty = [ln for ln in lines if ln]
    title = nonempty[0] if nonempty else "Unknown Title"
    company = nonempty[1] if len(nonempty) > 1 else "Unknown Company"
    location = nonempty[2] if len(nonempty) > 2 else ""
    url = source_url
    for ln in nonempty[:8]:
        if ln.startswith("http"):
            url = ln
            break
    embed = careerpuck_to_greenhouse_embed(url)
    if embed:
        url = embed  # AF-017: fill via the Greenhouse embed, not the careerpuck shell
    m = re.search(r"Job ID:\s*(\S+)", jd_text)
    job_ref = m.group(1) if m else ""

    return {
        "title": title,
        "company": company,
        "location": location,
        "url": url,
        "job_ref": job_ref,
        "ats": detect_ats(jd_text + " " + url),
        "work_auth": work_auth_screen(jd_text, cfg),
        "keywords": extract_keywords(jd_text),
        "length_chars": len(jd_text),
        "remote": bool(re.search(r"\bremote\b", jd_text, re.I)),
    }
