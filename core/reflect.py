"""Reflection pass — the slow learning loop.

Weekly, global, generated from the WHOLE ledger (events + chunk_stats + outcomes),
never per-application. Deterministic code assembles the evidence; an LLM ticket
proposes rules; a human approves them. Guardrail: a rule does NOTHING until its
status is 'approved' — proposal alone never changes system behavior.
"""
import json
import time
from pathlib import Path

TICKET_TEMPLATE = """# TICKET: WEEKLY REFLECTION — {date}
STATUS: OPEN. Execute by writing `RESULT_reflect_{date}.json` in this folder.

## Contract
1. Read the evidence below. Do NOT invent facts not present here.
2. Output JSON only, schema:
   {{"observations": ["..."],
     "proposed_rules": [{{"rule": "...", "rationale": "...", "evidence": "..."}}]}}
3. Rules must be operational (routing, filtering, retrieval, QA thresholds, outreach) and
   traceable to the evidence. 0 rules is a valid output — do not manufacture insight.
4. Proposed rules are INERT until the human approves them (`ajos.py rules approve <id>`).

## Period
{period_start} → {date}

## Application funnel (current statuses)
{funnel}

## Outcomes recorded this period
{outcomes}

## QA failures and bounces (what the tailoring step keeps getting wrong)
{qa_failures}

## Duplicate/work-auth blocks
{blocks}

## Retrieval health
Top USED chunks (retrieved and actually used in resumes):
{used_chunks}

Dead weight (retrieved repeatedly, never used — candidates for rewriting or retagging):
{dead_chunks}

Chunks credited in callbacks so far:
{callback_chunks}

## Existing rules (do not re-propose)
{existing_rules}
"""


def _fmt(rows, empty="(none)"):
    return "\n".join(f"- {r}" for r in rows) if rows else empty


def generate_ticket(con, ajos_dir: Path) -> Path:
    date = time.strftime("%Y-%m-%d")
    period_start = time.strftime(
        "%Y-%m-%d", time.localtime(time.time() - 7 * 86400))

    funnel = [f"{r['status']}: {r['n']}" for r in con.execute(
        "SELECT status, COUNT(*) n FROM applications GROUP BY status ORDER BY n DESC")]

    outcomes = [f"{r['app_id']}: {r['status']}" for r in con.execute(
        "SELECT app_id, status FROM applications WHERE status LIKE 'outcome_%'")]

    qa_failures = [f"{r['ts']} {r['app_id']}: {(r['detail'] or '')[:140]}" for r in con.execute(
        "SELECT ts, app_id, detail FROM events WHERE event='transition' AND detail LIKE '%qa_failed%' "
        "AND ts >= ? ORDER BY ts DESC LIMIT 20", (period_start,))]

    blocks = [f"{r['ts']} {r['app_id']}: {r['event']}" for r in con.execute(
        "SELECT ts, app_id, event FROM events WHERE event IN "
        "('duplicate_blocked','transition_blocked') OR (event='transition' AND detail LIKE '%rejected_workauth%') "
        "ORDER BY ts DESC LIMIT 20")]

    used = [f"[{r['chunk_id']}] used {r['times_used']}x / retrieved {r['times_retrieved']}x — {r['text_head']}"
            for r in con.execute(
                "SELECT * FROM chunk_stats WHERE times_used > 0 ORDER BY times_used DESC LIMIT 10")]

    dead = [f"[{r['chunk_id']}] retrieved {r['times_retrieved']}x, used 0x — {r['text_head']}"
            for r in con.execute(
                "SELECT * FROM chunk_stats WHERE times_used = 0 AND times_retrieved >= 2 "
                "ORDER BY times_retrieved DESC LIMIT 10")]

    callback = [f"[{r['chunk_id']}] in {r['times_in_callback']} callback(s) — {r['text_head']}"
                for r in con.execute(
                    "SELECT * FROM chunk_stats WHERE times_in_callback > 0 "
                    "ORDER BY times_in_callback DESC LIMIT 10")]

    existing = [f"#{r['rule_id']} [{r['status']}] {r['rule']}" for r in con.execute(
        "SELECT rule_id, status, rule FROM playbook_rules WHERE status != 'rejected'")]

    out_dir = ajos_dir / "reflections"
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"TICKET_reflect_{date}.md"
    path.write_text(TICKET_TEMPLATE.format(
        date=date, period_start=period_start,
        funnel=_fmt(funnel), outcomes=_fmt(outcomes),
        qa_failures=_fmt(qa_failures), blocks=_fmt(blocks),
        used_chunks=_fmt(used), dead_chunks=_fmt(dead),
        callback_chunks=_fmt(callback), existing_rules=_fmt(existing)))
    return path


def apply_result(con, ajos_dir: Path, date: str | None = None) -> list[dict]:
    """Validate RESULT_reflect_<date>.json and insert proposed rules (INERT until approved)."""
    from . import ledger
    date = date or time.strftime("%Y-%m-%d")
    path = ajos_dir / "reflections" / f"RESULT_reflect_{date}.json"
    if not path.exists():
        raise FileNotFoundError(f"{path.name} not found — ticket still open")
    data = json.loads(path.read_text())
    rules = data.get("proposed_rules", [])
    if not isinstance(rules, list):
        raise ValueError("proposed_rules must be a list")
    inserted = []
    for r in rules:
        if not isinstance(r, dict) or not r.get("rule") or not r.get("evidence"):
            raise ValueError(f"malformed rule (need rule+rationale+evidence): {r}")
        # dedup by rule text
        if con.execute("SELECT 1 FROM playbook_rules WHERE rule=?", (r["rule"],)).fetchone():
            continue
        con.execute(
            "INSERT INTO playbook_rules (created_at, source, rule, status) VALUES (?,?,?,?)",
            (ledger.now(), f"reflect_{date}",
             f"{r['rule']} | why: {r.get('rationale','')} | evidence: {r['evidence']}", "proposed"))
        inserted.append(r)
    con.commit()
    ledger.log_event(con, None, "reflect", "rules_proposed",
                     {"date": date, "count": len(inserted)})
    return inserted
