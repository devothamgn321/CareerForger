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
STOPWORDS.update("""location locations looking seeking join own based hybrid onsite remote
https http www com fair chance ordinance policy statement privacy
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
    # Only rewrite when the URL is provably a Greenhouse-backed shell: an explicit gh_jid
    # parameter anywhere, or a careerpuck job-board URL. A bare "/job/<digits>" on an
    # arbitrary employer domain is NOT evidence of Greenhouse and must pass through untouched.
    mt = re.search(r"[?&]gh_jid=(\d+)", url)
    if not mt and re.search(r"careerpuck\.com", low):
        mt = re.search(r"/job/(\d+)", url)
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


# Scouting notes sometimes say e.g. "no explicit 'us citizens only' language found".
# Those meta-annotations must not trigger a hard reject.
META_NEGATION = re.compile(
    r"no explicit|not found|none found|not present|no blocking|no restrictive|work-auth note|"
    r"no .{0,20}language found")

# Requirement-type restrictions ("security clearance", "US citizen", ...) can be legitimately
# negated by the posting itself: "No security clearance required", "does not require a
# clearance". Sponsorship restrictions are already negative statements ("unable to sponsor"),
# so a nearby "no"/"not" must never cancel them.
REQUIREMENT_TERMS = re.compile(r"clearance|ts/sci|itar|citizen|green card|permanent resident|us persons?")
OPTIONAL_MARKERS = re.compile(r"nice to have|nice-to-have|\ba plus\b|\bpreferred\b|\bbonus\b")
LOCAL_NEGATION = re.compile(
    r"(?:\bno|\bnot|\bwithout|\bnever|n't|does not|do not|is not|isn't)"
    r"(?:\s+(?:require|requires|required|need|needs|an?|any|the|active|current|u\.?s\.?))*\s*$")


def _sentence_bounds(low: str, pos: int) -> tuple[int, int]:
    """Start/end of the sentence containing pos (split on . ; ! ? and newlines)."""
    start = max(low.rfind(ch, 0, pos) for ch in ".;!?\n") + 1
    ends = [i for i in (low.find(ch, pos) for ch in ".;!?\n") if i != -1]
    return start, (min(ends) if ends else len(low))


def _negated(low: str, match: re.Match) -> bool:
    """True only when the hit is (a) inside a scouting meta-note, or (b) a requirement-type
    term directly negated within the SAME sentence ("no security clearance required")."""
    s_start, s_end = _sentence_bounds(low, match.start())
    sentence = low[s_start:s_end]
    if META_NEGATION.search(sentence):
        return True
    if not REQUIREMENT_TERMS.search(match.group(0)):
        return False
    # "Security clearance ... is nice to have" / "a plus" / "preferred" is not a hard requirement.
    if OPTIONAL_MARKERS.search(sentence):
        return True
    before = low[s_start:match.start()]
    after = low[match.end():s_end]
    if LOCAL_NEGATION.search(before[-40:]):
        return True
    # "clearance is not required", "citizenship not required"
    return bool(re.match(r"\s*(?:is\s+)?not\s+(?:required|needed|necessary)", after))


# Built-in restriction patterns are always applied, even when an older private config.json
# only lists a subset. Config patterns are added on top, never subtracted.
DEFAULT_HARD_REJECT = [
    "us citizens? only",
    "u\\.s\\. citizens? only",
    "u\\.?s\\.? citizenship (is )?required",
    "must be an? (u\\.?s\\.? )?citizen",
    "security clearance",
    "active clearance",
    "ts/sci",
    "itar",
    "us persons? only",
    "not able to sponsor",
    "unable to sponsor",
    "no sponsorship",
    "cannot (provide|offer|support) (visa |immigration |employment )?sponsorship",
    "will not (provide |offer )?(visa |immigration )?sponsor",
    "does not (provide |offer )?(visa |immigration )?sponsor",
    "(visa |immigration )?sponsorship (is )?not (available|provided|offered)",
    "without (the need for |requiring |needing )?(current or future |visa |employment |immigration )*sponsorship",
    "(must|will|do|does) not (now or in the future )?require (current or future |visa |employment |immigration )*sponsorship",
    "unrestricted (work |employment )?authori[sz]ation",
    "green card holders? only",
    "permanent resident(s)? only",
]


def work_auth_screen(text: str, cfg: dict) -> dict:
    low = text.lower()
    hard = []
    patterns = list(dict.fromkeys(DEFAULT_HARD_REJECT + cfg.get("work_auth", {}).get("hard_reject_patterns", [])))
    for p in patterns:
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


def extract_keywords(text: str, top_n: int = 40, exclude: set | None = None) -> list[str]:
    # unigrams + bigrams, crude but deterministic; the router and retriever share these
    # Job ID lines are file metadata, not JD content — UUID fragments (e.g. "edc-b") must
    # never become keywords QA scores resumes against
    text = re.sub(r"Job ID:.*", " ", text)
    text = re.sub(r"https?://\S+", " ", text)
    exclude = {e.lower() for e in (exclude or set())}
    words = [w.lower().rstrip(".-/") for w in re.findall(r"[A-Za-z][A-Za-z+#/.-]{1,}", text)]
    words = [w for w in words if w not in STOPWORDS and w not in exclude and len(w) > 2]
    uni = Counter(words)
    bi = Counter(f"{a} {b}" for a, b in zip(words, words[1:])
                 if a not in STOPWORDS and b not in STOPWORDS)
    ranked = [w for w, _ in (uni + Counter({k: v * 2 for k, v in bi.items() if v > 1})).most_common(top_n * 2)]
    return ranked[:top_n]


ROLE_WORDS = re.compile(
    r"\b(manager|engineer|analyst|product|program|project|lead|specialist|associate|director|"
    r"intern|scientist|designer|consultant|architect|developer|strategist|coordinator|owner|"
    r"operations|marketing|researcher|administrator|officer|head|vp|chief|staff|representative|"
    r"recruiter|writer|editor|technician|assistant|advisor|partner|planner)\b", re.I)
LABEL_RE = re.compile(r"^(title|role|position|company|employer|location)\s*[:\-\u2013]\s*(.+)$", re.I)
LABEL_KEYS = {"title": "title", "role": "title", "position": "title",
              "company": "company", "employer": "company", "location": "location"}


def _looks_like_role(line: str) -> bool:
    return bool(ROLE_WORDS.search(line or ""))


def _strip_label(line: str) -> str:
    return re.sub(r"^(location|based in)\s*[:\-\u2013]\s*", "", line or "", flags=re.I).strip()


def _labeled_fields(lines: list[str]) -> dict:
    """Explicit 'Title: ...', 'Company: ...', 'Location: ...' lines win over line order."""
    out = {}
    for ln in lines:
        m = LABEL_RE.match(ln)
        if m:
            out.setdefault(LABEL_KEYS[m.group(1).lower()], m.group(2).strip())
    return out


def _name_tokens(company: str) -> set:
    """Company-name words are not competencies; exclude them from JD keywords."""
    return {w.lower() for w in re.findall(r"[A-Za-z][A-Za-z0-9&.-]+", company or "") if len(w) > 2}


def _keyword_exclusions(company: str, title: str, text: str = "") -> set:
    """Company-name tokens that act only as a name. A token is kept as a keyword when it is
    part of the role title or also appears as an ordinary lowercase word in the JD body
    (e.g. "security" for Abnormal Security, "robotics" in "robotics software")."""
    out = set()
    for tok in _name_tokens(company) - _name_tokens(title):
        if not re.search(rf"(?<![A-Za-z]){re.escape(tok)}(?![A-Za-z])", text):
            out.add(tok)
    return out


def normalize(jd_text: str, cfg: dict, source_url: str = "") -> dict:
    lines = [ln.strip() for ln in jd_text.splitlines()]
    nonempty = [ln for ln in lines if ln]
    labeled = _labeled_fields(nonempty[:12])
    title = nonempty[0] if nonempty else "Unknown Title"
    company = nonempty[1] if len(nonempty) > 1 else "Unknown Company"
    location = nonempty[2] if len(nonempty) > 2 else ""
    # Scout files put the title first. Pasted JDs often lead with the company name instead;
    # swap only when line 2 clearly looks like a role and line 1 clearly does not.
    if _looks_like_role(company) and not _looks_like_role(title):
        title, company = company, title
    title = labeled.get("title", title)
    company = labeled.get("company", company)
    location = labeled.get("location", _strip_label(location))
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
        "keywords": extract_keywords(jd_text, exclude=_keyword_exclusions(company, title, jd_text) | _keyword_exclusions(location, title, jd_text)),
        "length_chars": len(jd_text),
        "remote": bool(re.search(r"\bremote\b", jd_text, re.I)),
    }
