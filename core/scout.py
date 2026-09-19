"""Scouting: Greenhouse/Lever/Ashby public job-board JSON APIs -> ranked ingest queue.

Deterministic, stdlib only, zero tokens. Reads pipeline/TARGET_COMPANIES_v1.csv (companies
with a scriptable ATS), fetches each board's public postings API, applies the filter order
from P1_Pipeline_Architecture_v1.md Stage 1 and Scouting Policy v2:
  P1/P0 role queries -> USA -> freshness <=7d -> work-auth hard filter -> repost -> dedup vs ledger
then writes new-posting JD .txt files into pipeline/scouting/jds/ in the same line convention
core/normalize.py already parses, plus a ranked queue manifest for the (future) dashboard.

Company career pages (likely_ats == "careers_page") aren't scriptable via a public JSON API
and are out of scope for this pass -- skipped with a count, not silently dropped.
"""
import csv
import html
import json
import re
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path

from . import normalize, route

USER_AGENT = "ajos-scout/1.0 (personal job search tool; contact via listed company careers page)"
SCRIPTABLE_ATS = {"greenhouse", "lever", "ashby"}

# Order matters: more specific buckets checked before the generic "pm" catch-all.
# tpm/pm require "technical program manager" / "product manager" explicitly, so a bare
# "Program Manager" title (the swap CLAUDE.md rejected 2026-07-16) matches no bucket here.
P1_QUERIES = [
    ("trust_safety", [r"trust\s*(and|&)\s*safety", r"platform integrity", r"content policy",
                       r"content moderation", r"safety product manager", r"integrity.{0,15}product"]),
    ("aipm", [r"\bai\b.{0,20}product manager", r"\bml\b.{0,20}product manager",
              r"machine learning product manager", r"applied ai product",
              r"gen(erative)?[\s-]?ai product manager"]),
    ("tpm", [r"technical program manager", r"technical product manager", r"\btpm\b"]),
    ("productops", [r"product operations", r"product ops\b", r"platform operations",
                     r"program operations manager"]),
    ("gtm_growth", [r"growth product manager", r"growth pm\b", r"growth manager\b", r"growth lead\b",
                     r"product manager.{0,25}(gtm|go-to-market)", r"(gtm|go-to-market).{0,25}product manager"]),
    ("pm", [r"\bproduct manager\b", r"\bproduct owner\b"]),
]

EXCLUDE_TITLE = [
    r"\bintern(ship)?\b", r"\bco-?op\b", r"\bdirector\b", r"\bvp\b", r"\bvice president\b",
    r"\bhead of\b", r"\bchief\b", r"\bsvp\b", r"\bpresident\b", r"\bprincipal\b(?!.{0,15}product manager)",
    r"\bsenior\b", r"\bsr\.?\b", r"\bstaff\b", r"\blead\b",
    r"\bgroup\s+product\s+manager\b", r"\bmanager\s+(ii|iii|iv|2|3|4)\b",
]

US_STATE_ABBR = {
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA", "HI", "ID", "IL", "IN", "IA",
    "KS", "KY", "LA", "ME", "MD", "MA", "MI", "MN", "MS", "MO", "MT", "NE", "NV", "NH", "NJ",
    "NM", "NY", "NC", "ND", "OH", "OK", "OR", "PA", "RI", "SC", "SD", "TN", "TX", "UT", "VT",
    "VA", "WA", "WV", "WI", "WY", "DC",
}
NON_US_MARKERS = [
    "canada", "india", "united kingdom", " uk", "germany", "poland", "ireland", "israel",
    "japan", "china", "mexico", "brazil", "philippines", "singapore", "australia", "france",
    "spain", "netherlands", "romania", "ukraine", "portugal", "toronto", "vancouver",
    "bangalore", "hyderabad", "pune", "gurgaon", "gurugram", "delhi", "mumbai", "chennai",
    "remote - canada", "remote - emea", "remote - apac", "remote - global", "remote, canada",
]

FRESHNESS_MAX_HOURS = 7 * 24
SEEN_JOBS_RETENTION_DAYS = 180

# P0 companies get a deliberately broader PM-adjacent net. Generic Program Manager remains
# excluded everywhere else and routes through the TPM family when admitted here.
P0_QUERIES = [
    ("trust_safety", [
        r"(trust|safety|integrity|content moderation|content policy|risk operations).{0,30}"
        r"(product|program|operations|strategy|manager|lead)",
        r"(product|program|operations|strategy|manager|lead).{0,30}"
        r"(trust|safety|integrity|content moderation|content policy|risk operations)",
    ]),
    ("aipm", [
        r"\b(ai|ml|machine learning|generative ai|genai)\b.{0,30}"
        r"(product|program|strategy|operations).{0,20}(manager|lead|owner)?",
        r"(product|program|strategy|operations).{0,30}"
        r"\b(ai|ml|machine learning|generative ai|genai)\b",
    ]),
    ("tpm", [
        r"\b(program|project|engineering program|systems program) manager\b",
        r"\b(program|project) lead\b",
    ]),
    ("productops", [
        r"\b(product|program|business|platform) operations\b",
        r"\boperations (manager|lead)\b",
    ]),
    ("gtm_growth", [
        r"\b(gtm|go-to-market|growth|commercialization|market strategy|product strategy|"
        r"strategic initiatives|product marketing)\b",
    ]),
    ("pm", [
        r"\b(associate )?product (manager|owner|lead|analyst|strategist|management)\b",
        r"\bplatform product\b",
    ]),
]


class _TextExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []

    def handle_data(self, data):
        self.parts.append(data)


def strip_html(raw: str) -> str:
    """Strip tags; loops up to twice because some boards (Greenhouse) return
    HTML-entity-escaped HTML in their `content` field (double-encoded)."""
    if not raw:
        return ""
    text = raw
    for _ in range(2):
        p = _TextExtractor()
        try:
            p.feed(text)
            text = " ".join(p.parts)
        except Exception:
            text = re.sub(r"<[^>]+>", " ", text)
        text = html.unescape(text)
        if not re.search(r"<[a-zA-Z/][^>]{0,80}>", text):
            break
    text = re.sub(r"[ \t]+", " ", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def _get_json(url: str, timeout: int = 12):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8", errors="ignore"))
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError,
            json.JSONDecodeError, OSError, ValueError):
        return None


def load_companies(csv_path: Path) -> tuple[list[dict], int]:
    """Returns (scriptable companies, count skipped for lacking a scriptable ATS -- e.g.
    likely_ats == 'careers_page' -- so that gap is counted, not silently dropped)."""
    rows = []
    skipped = 0
    with open(csv_path, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            ats = (r.get("likely_ats") or "").strip().lower()
            token = (r.get("board_token_guess") or "").strip()
            if ats in SCRIPTABLE_ATS and token:
                rows.append({"company": r["company"].strip(), "ats": ats, "token": token,
                            "tier": (r.get("tier") or "").strip()})
            else:
                skipped += 1
    return rows, skipped


def fetch_greenhouse(token: str, company: str) -> list[dict] | None:
    """Returns None on fetch failure (wrong token / unreachable), [] if reachable with 0 postings."""
    data = _get_json(f"https://boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true")
    if data is None or "jobs" not in data:
        return None
    out = []
    for j in data["jobs"]:
        out.append({
            "ats": "greenhouse", "board_token": token, "job_id": str(j.get("id", "")),
            "title": j.get("title", ""), "company": company,
            "location": (j.get("location") or {}).get("name", ""),
            "country_hint": None,
            "url": j.get("absolute_url", ""),
            "posted_at": j.get("first_published") or j.get("updated_at"),
            "description_text": strip_html(j.get("content", "")),
        })
    return out


def fetch_lever(token: str, company: str) -> list[dict] | None:
    """Returns None on fetch failure (wrong token / unreachable), [] if reachable with 0 postings."""
    data = _get_json(f"https://api.lever.co/v0/postings/{token}?mode=json")
    if not isinstance(data, list):
        return None
    out = []
    for j in data:
        lists_text = " ".join(strip_html(item.get("content", "")) for item in (j.get("lists") or []))
        body = " ".join(filter(None, [
            j.get("descriptionPlain") or strip_html(j.get("description", "")),
            j.get("openingPlain") or "",
            lists_text,
            j.get("additionalPlain") or "",
        ]))
        out.append({
            "ats": "lever", "board_token": token, "job_id": str(j.get("id", "")),
            "title": j.get("text", ""), "company": company,
            "location": (j.get("categories") or {}).get("location", ""),
            "country_hint": j.get("country"),
            "url": j.get("hostedUrl", "") or j.get("applyUrl", ""),
            "posted_at": j.get("createdAt"),
            "description_text": body.strip(),
        })
    return out


def fetch_ashby(token: str, company: str) -> list[dict] | None:
    """Returns None on fetch failure (wrong token / unreachable), [] if reachable with 0 postings."""
    data = _get_json(f"https://api.ashbyhq.com/posting-api/job-board/{token}")
    if data is None or "jobs" not in data:
        return None
    out = []
    for j in data["jobs"]:
        if j.get("isListed") is False:
            continue
        country = ((j.get("address") or {}).get("postalAddress") or {}).get("addressCountry")
        out.append({
            "ats": "ashby", "board_token": token, "job_id": str(j.get("id", "")),
            "title": j.get("title", ""), "company": company,
            "location": j.get("location", ""),
            "country_hint": country,
            "url": j.get("jobUrl", "") or j.get("applyUrl", ""),
            "posted_at": j.get("publishedAt"),
            "description_text": j.get("descriptionPlain") or strip_html(j.get("descriptionHtml", "")),
        })
    return out


FETCHERS = {"greenhouse": fetch_greenhouse, "lever": fetch_lever, "ashby": fetch_ashby}


def _excluded_title(title: str) -> bool:
    low = title.lower()
    return any(re.search(pat, low) for pat in EXCLUDE_TITLE)


def match_bucket_query(title: str) -> str | None:
    low = title.lower()
    if _excluded_title(title):
        return None
    for bucket, patterns in P1_QUERIES:
        if any(re.search(p, low) for p in patterns):
            return bucket
    return None


def match_p0_query(title: str) -> str | None:
    """Loose PM-adjacent matching used only for explicitly tiered P0 companies."""
    strict = match_bucket_query(title)
    if strict:
        return strict
    if _excluded_title(title):
        return None
    low = title.lower()
    for bucket, patterns in P0_QUERIES:
        if any(re.search(p, low) for p in patterns):
            return bucket
    return None


def match_title(title: str, company_tier: str) -> tuple[str | None, str]:
    if company_tier.upper() == "P0":
        return match_p0_query(title), "p0_loose"
    return match_bucket_query(title), "p1_strict"


def is_us_location(loc: str, country_hint: str | None) -> bool:
    if country_hint:
        # Lever sends ISO codes ("US"); Ashby sends full names ("United States")
        return country_hint.strip().upper() in ("US", "USA", "UNITED STATES", "UNITED STATES OF AMERICA")
    if not loc:
        return False
    low = loc.lower()
    if any(m in low for m in NON_US_MARKERS):
        return False
    if "united states" in low or "usa" in low:
        return True
    if re.search(r"remote\s*-\s*us\b", low) or re.search(r"remote\s*\(us\)", low):
        return True
    m = re.search(r",\s*([A-Za-z]{2})\b", loc)
    if m and m.group(1).upper() in US_STATE_ABBR:
        return True
    if re.search(r"\bremote\b", low):
        return True  # bare "Remote" with no country marker: inclusive, lowest-confidence
    return False


def hours_since(posted_at) -> float | None:
    if posted_at is None or posted_at == "":
        return None
    try:
        if isinstance(posted_at, (int, float)):
            dt = datetime.fromtimestamp(posted_at / 1000, tz=timezone.utc)
        else:
            dt = datetime.fromisoformat(str(posted_at).replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
        return max(0.0, (datetime.now(timezone.utc) - dt).total_seconds() / 3600)
    except (ValueError, TypeError, OverflowError):
        return None


def freshness_tier(hours: float | None) -> int:
    """Policy-v2 bands: minutes, hours, <=24h, <=48h, >48h-7d, then unknown."""
    if hours is None:
        return 5
    if hours <= 1:
        return 0
    if hours <= 6:
        return 1
    if hours <= 24:
        return 2
    if hours <= 48:
        return 3
    return 4


def freshness_band(hours: float | None) -> str:
    return ("unknown" if hours is None else
            "minutes" if hours <= 1 else
            "hours" if hours <= 6 else
            "<=24h" if hours <= 24 else
            "<=48h" if hours <= 48 else
            ">48h-7d")


def job_key(posting: dict) -> str:
    return f"{posting['ats']}:{posting['board_token']}:{posting['job_id']}"


def repost_key(posting: dict) -> str:
    slug = re.sub(r"[^a-z0-9]+", "", posting["title"].lower())
    return f"{posting['company'].lower()}:{slug}"


def load_seen(path: Path) -> dict:
    if path.exists():
        try:
            return json.loads(path.read_text())
        except json.JSONDecodeError:
            return {}
    return {}


def save_seen(path: Path, seen: dict):
    cutoff = time.time() - SEEN_JOBS_RETENTION_DAYS * 86400
    pruned = {k: v for k, v in seen.items() if v.get("_ts", time.time()) >= cutoff}
    path.write_text(json.dumps(pruned, indent=2))


def slug_company(company: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", company.lower())[:24]


def write_jd_file(jds_dir: Path, posting: dict) -> Path:
    fname = f"{slug_company(posting['company'])}_{posting['job_id']}.txt"
    fpath = jds_dir / fname
    body = (
        f"{posting['title']}\n"
        f"{posting['company']}\n"
        f"{posting['location']}\n"
        f"{posting['url']}\n"
        f"Job ID: {posting['job_id']}\n\n"
        f"{posting['description_text']}\n"
    )
    fpath.write_text(body)
    return fpath


def run_scout(cfg: dict, ajos_dir: Path, companies_csv: Path, scouting_dir: Path) -> dict:
    started = time.monotonic()
    jds_dir = scouting_dir / "jds"
    jds_dir.mkdir(parents=True, exist_ok=True)
    seen_path = scouting_dir / "seen_jobs.json"
    seen = load_seen(seen_path)

    companies, skipped_no_api = load_companies(companies_csv)
    funnel = {"fetched": 0, "title_match": 0, "us": 0, "fresh": 0, "work_auth_ok": 0,
              "not_dup_jobid": 0, "final": 0, "companies_scanned": 0, "companies_failed": 0,
              "companies_skipped_no_api": skipped_no_api}

    def fetch_company(c):
        fetcher = FETCHERS[c["ats"]]
        return c, fetcher(c["token"], c["company"])

    all_postings = []
    max_workers = max(1, min(int(cfg.get("scouting", {}).get("max_workers", 12)), 24))
    # map preserves company-list order, so output remains deterministic while network waits overlap.
    with ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="ajos-scout") as pool:
        fetched_companies = pool.map(fetch_company, companies)
    for c, postings in fetched_companies:
        funnel["companies_scanned"] += 1
        if postings is None:
            funnel["companies_failed"] += 1
            continue
        funnel["fetched"] += len(postings)
        for posting in postings:
            posting["_company_tier"] = c["tier"]
        all_postings.extend(postings)
    funnel["fetch_seconds"] = round(time.monotonic() - started, 2)
    funnel["max_workers"] = max_workers

    candidates = []
    soft_reposts = []
    for p in all_postings:
        bucket_guess, match_policy = match_title(p["title"], p.get("_company_tier", ""))
        if not bucket_guess:
            continue
        funnel["title_match"] += 1

        if not is_us_location(p["location"], p["country_hint"]):
            continue
        funnel["us"] += 1

        hrs = hours_since(p["posted_at"])
        if hrs is not None and hrs > FRESHNESS_MAX_HOURS:
            continue
        funnel["fresh"] += 1

        wa = normalize.work_auth_screen(p["title"] + " " + p["description_text"], cfg)
        if not wa["ok"]:
            continue
        funnel["work_auth_ok"] += 1

        jkey = job_key(p)
        if jkey in seen:
            continue
        funnel["not_dup_jobid"] += 1

        p["_bucket_guess"] = bucket_guess
        p["_title_match_policy"] = match_policy
        p["_hours_ago"] = hrs
        p["_freshness_tier"] = freshness_tier(hrs)
        p["_freshness_band"] = freshness_band(hrs)
        p["_job_key"] = jkey
        rkey = repost_key(p)
        if rkey in seen:
            soft_reposts.append(p)
        else:
            candidates.append(p)

    used_fallback = False
    if not candidates and soft_reposts:
        candidates = soft_reposts
        used_fallback = True

    ranked = []
    for p in candidates:
        try:
            routing = route.route(p["description_text"] or p["title"], cfg, ajos_dir)
            p["_bucket"] = routing["bucket"]
            p["_similarity"] = routing["similarity"]
        except Exception:
            p["_bucket"] = p["_bucket_guess"]
            p["_similarity"] = 0.0
        ranked.append(p)

    # Fit is never a gate. Rank by freshness band, then strictly newest first within the band;
    # similarity only breaks ties after freshness.
    ranked.sort(key=lambda p: (
        p["_freshness_tier"],
        p["_hours_ago"] if p["_hours_ago"] is not None else float("inf"),
        -p["_similarity"],
    ))

    queue = []
    now_iso = datetime.now(timezone.utc).isoformat()
    for i, p in enumerate(ranked, 1):
        fpath = write_jd_file(jds_dir, p)
        seen[p["_job_key"]] = {"_ts": time.time(), "first_seen": now_iso,
                                "title": p["title"], "company": p["company"]}
        seen[repost_key(p)] = {"_ts": time.time(), "first_seen": now_iso,
                                "title": p["title"], "company": p["company"]}
        queue.append({
            "rank": i, "company": p["company"], "title": p["title"], "location": p["location"],
            "ats": p["ats"], "bucket_query_guess": p["_bucket_guess"], "bucket_routed": p["_bucket"],
            "company_tier": p.get("_company_tier", ""),
            "title_match_policy": p["_title_match_policy"],
            "freshness_band": p["_freshness_band"],
            "similarity": round(p["_similarity"], 4), "hours_ago": round(p["_hours_ago"], 1)
                if p["_hours_ago"] is not None else None,
            "url": p["url"], "jd_file": str(fpath.relative_to(scouting_dir.parent)),
        })
    funnel["final"] = len(queue)
    funnel["used_repost_fallback"] = used_fallback

    save_seen(seen_path, seen)
    queue_path = scouting_dir / f"queue_{time.strftime('%Y-%m-%d')}.json"
    queue_path.write_text(json.dumps({"generated_at": now_iso, "funnel": funnel, "queue": queue}, indent=2))

    return {"funnel": funnel, "queue": queue, "queue_path": queue_path}
