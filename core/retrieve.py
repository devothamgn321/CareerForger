"""Retrieval planner over the Evidence Pack. The 'agentic RAG' decision layer, right-sized.

- Parses EVIDENCE_PACK_v1.md into section-tagged chunks (facts/bullets/metrics).
- Scores each chunk against JD keywords (weighted overlap).
- Plans per-category quotas (experience / projects / skills / metrics) instead of
  one flat top-k — this is the planner deciding WHAT kind of evidence the
  tailoring step needs.
- Emits a gap list: JD keywords with no evidence hit -> feeds Gate A gap-closing.
- Logs every retrieval to chunk_stats (learning loop: retrieved vs used vs callback).
"""
import hashlib
import re
from pathlib import Path

SECTION_CATEGORY = {
    "1": "identity", "2": "education", "3": "experience", "4": "projects",
    "5": "skills", "6": "leadership", "7": "metrics", "8": "banned",
}
# Planner quotas: how many chunks each category may contribute to the ticket.
QUOTAS = {"experience": 6, "projects": 5, "metrics": 8, "skills": 3,
          "education": 2, "leadership": 2, "identity": 1}


def parse_evidence_pack(path: Path) -> list[dict]:
    chunks = []
    section = "0"
    for raw in path.read_text().splitlines():
        line = raw.strip()
        m = re.match(r"##\s*(\d+)\.", line)
        if m:
            section = m.group(1)
            continue
        if not line or line.startswith("#"):
            continue
        category = SECTION_CATEGORY.get(section, "other")
        if category == "banned":
            continue  # ban list is enforced by QA, never retrieved as evidence
        # split long paragraph lines into sentence-ish chunks; keep bullets whole
        parts = [line] if line.startswith(("-", "*", "**")) else re.split(r"(?<=[.;]) +", line)
        for part in parts:
            part = part.strip("-* ").strip()
            if len(part) < 25:
                continue
            cid = hashlib.md5(part.encode()).hexdigest()[:10]
            chunks.append({"chunk_id": cid, "section": category, "text": part,
                           "text_head": part[:120]})
    return chunks


def score_chunk(chunk_text: str, keywords: list[str]) -> tuple[float, list[str]]:
    low = chunk_text.lower()
    hits = []
    score = 0.0
    for rank, kw in enumerate(keywords):
        if kw in low:
            hits.append(kw)
            score += 1.0 + (len(keywords) - rank) / len(keywords)  # earlier kw = heavier
    return score, hits


def retrieve(jd: dict, evidence_path: Path, con=None) -> dict:
    chunks = parse_evidence_pack(evidence_path)
    keywords = jd["keywords"]
    scored = []
    for c in chunks:
        s, hits = score_chunk(c["text"], keywords)
        if s > 0:
            scored.append({**c, "score": round(s, 2), "matched": hits})
    scored.sort(key=lambda c: -c["score"])

    # planner pass: fill quotas per category
    selected, counts = [], {}
    for c in scored:
        cat = c["section"]
        if counts.get(cat, 0) < QUOTAS.get(cat, 2):
            selected.append(c)
            counts[cat] = counts.get(cat, 0) + 1

    # sufficiency check + gap list
    covered = {kw for c in selected for kw in c["matched"]}
    gaps = [kw for kw in keywords[:20] if kw not in covered]
    sufficiency = round(1 - len(gaps) / max(len(keywords[:20]), 1), 2)

    if con is not None:
        from . import ledger
        ledger.record_retrieval(con, selected)

    return {"selected": selected, "gaps": gaps, "sufficiency": sufficiency,
            "total_chunks": len(chunks), "hit_chunks": len(scored)}
