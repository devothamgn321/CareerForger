"""Router: which of the 6 P1 bases fits this JD best. Pure TF-IDF cosine, zero tokens.

HONESTY NOTE: the score is corpus-relative similarity, not an ATS score.
It ranks bases against each other reliably; the absolute value is calibrated
over time by the learning loop (predicted vs. OPAL outcome, events table).
"""
import math
import re
from collections import Counter
from pathlib import Path

from .normalize import STOPWORDS


def strip_latex(tex: str) -> str:
    tex = re.sub(r"%.*", " ", tex)
    tex = re.sub(r"\\[a-zA-Z]+\*?(\[[^\]]*\])?", " ", tex)  # commands
    tex = re.sub(r"[{}\\$&_^~]", " ", tex)
    return tex


def tokens(text: str) -> list[str]:
    words = [w.lower() for w in re.findall(r"[A-Za-z][A-Za-z+#/.-]{1,}", text)]
    return [w for w in words if w not in STOPWORDS and len(w) > 2]


def tfidf_vectors(docs: dict[str, str]) -> dict[str, dict[str, float]]:
    tf = {name: Counter(tokens(text)) for name, text in docs.items()}
    df = Counter()
    for counts in tf.values():
        df.update(counts.keys())
    n = len(docs)
    vecs = {}
    for name, counts in tf.items():
        total = sum(counts.values()) or 1
        vecs[name] = {t: (c / total) * math.log(1 + n / df[t]) for t, c in counts.items()}
    return vecs


def cosine(a: dict, b: dict) -> float:
    common = set(a) & set(b)
    num = sum(a[t] * b[t] for t in common)
    den = math.sqrt(sum(v * v for v in a.values())) * math.sqrt(sum(v * v for v in b.values()))
    return num / den if den else 0.0


def route(jd_text: str, cfg: dict, ajos_dir: Path) -> dict:
    docs = {"__jd__": jd_text}
    for bucket, rel in cfg["bases"].items():
        p = (ajos_dir / rel).resolve()
        docs[bucket] = strip_latex(p.read_text(errors="ignore"))
    vecs = tfidf_vectors(docs)
    jd_vec = vecs.pop("__jd__")
    scores = {b: round(cosine(jd_vec, v), 4) for b, v in vecs.items()}
    ranked = sorted(scores.items(), key=lambda kv: -kv[1])
    best_bucket, best = ranked[0]
    fast = best >= cfg["routing"]["fast_path_similarity"]
    return {
        "bucket": best_bucket,
        "base_path": cfg["bases"][best_bucket],
        "similarity": best,
        "fast_path": fast,
        "ranking": ranked,
        "decision": ("fast path: base usable with light tailoring" if fast
                     else "full OPAL tailoring required"),
    }
