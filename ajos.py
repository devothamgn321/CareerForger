#!/usr/bin/env python3
"""AJOS CLI — the fast loop. Deterministic stages auto-advance; LLM stages open tickets.

  python3 ajos.py ingest <jd.txt> [--url URL]   discover -> normalize -> route -> retrieve -> tickets
  python3 ajos.py advance <app_id>              validate ticket results -> QA -> stage (or bounce back)
  python3 ajos.py status [app_id]               ledger view / event history
  python3 ajos.py mark <app_id> <state>         manual transitions (submitted, outcome_*, dropped)
  python3 ajos.py chunks                        chunk_stats — the learning loop's raw material
  python3 ajos.py scout                         scan Greenhouse/Lever/Ashby boards -> ranked JD queue
  python3 ajos.py reflect                       generate weekly reflection ticket (slow loop)
  python3 ajos.py reflect apply                 validate RESULT_reflect -> insert proposed rules
  python3 ajos.py rules [approve|reject <id>]   review/govern learned playbook rules
"""
import json
import re
import sys
import time
from pathlib import Path

AJOS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(AJOS_DIR))

from core import ledger, normalize, qa, reflect, retrieve, route, scout, stage, taskpack  # noqa: E402

CONFIG_PATH = AJOS_DIR / "config.json"
if not CONFIG_PATH.exists():
    CONFIG_PATH = AJOS_DIR / "config.example.json"
CFG = json.loads(CONFIG_PATH.read_text())


def make_app_id(jd: dict) -> str:
    slug = re.sub(r"[^a-z0-9]+", "", jd["company"].lower())[:20]
    role = re.sub(r"[^a-z0-9]+", "_", jd["title"].lower()).strip("_")[:30]
    ref = jd.get("job_ref") or time.strftime("%m%d")
    return f"{slug}_{role}_{ref}"


def cmd_ingest(jd_file: str, url: str = ""):
    jd_text = Path(jd_file).read_text(errors="ignore")
    con = ledger.connect(AJOS_DIR / CFG["db_path"])

    jd = normalize.normalize(jd_text, CFG, url)
    app_id = make_app_id(jd)
    print(f"[normalize] {jd['title']} @ {jd['company']} | ats={jd['ats']} | app_id={app_id}")

    # duplicate guard (known failure pattern: duplicate applications diluting signal)
    dups = ledger.similar_company_recent(con, jd["company"])
    dup_note = "none"
    if dups:
        dup_note = "; ".join(f"{d['app_id']}({d['status']})" for d in dups)
        print(f"[dup-guard] WARNING same company in last 90d: {dup_note}")

    recovering_evidence_ready = False
    if not ledger.create_application(
            con, app_id, company=jd["company"], role_title=jd["title"],
            location=jd["location"], url=jd["url"], ats=jd["ats"],
            work_auth_ok=int(jd["work_auth"]["ok"]), jd_path=str(Path(jd_file).resolve())):
        existing = ledger.get_application(con, app_id)
        recovering_evidence_ready = bool(
            existing and existing["status"] == "evidence_ready" and not existing["app_dir"]
        )
        if not recovering_evidence_ready:
            print(f"[dup-guard] BLOCKED: {app_id} already in ledger. Stopping.")
            return
        ledger.log_event(
            con, app_id, "orchestrator", "partial_ingest_recovery",
            "resuming evidence_ready row with no application folder"
        )
        print(f"[recovery] resuming partial ingest for {app_id} from evidence_ready")

    # work-auth hard filter
    if not jd["work_auth"]["ok"]:
        ledger.transition(con, app_id, "rejected_workauth", "normalizer",
                          f"hard-reject patterns: {jd['work_auth']['hard_reject']}")
        print(f"[work-auth] REJECTED: {jd['work_auth']['hard_reject']}")
        return
    if jd["work_auth"]["flags"]:
        print(f"[work-auth] flags (review at approval): {len(jd['work_auth']['flags'])} snippet(s)")

    if not recovering_evidence_ready:
        ledger.transition(con, app_id, "normalized", "normalizer")

    # route
    routing = route.route(jd_text, CFG, AJOS_DIR)
    ledger.set_fields(con, app_id, bucket=routing["bucket"],
                      base_used=routing["base_path"], route_similarity=routing["similarity"])
    if not recovering_evidence_ready:
        ledger.transition(con, app_id, "routed", "router", json.dumps(routing["ranking"]))
    print(f"[route] bucket={routing['bucket']} sim={routing['similarity']} -> {routing['decision']}")
    print(f"        ranking: {routing['ranking']}")

    # retrieve
    retrieval = retrieve.retrieve(jd, (AJOS_DIR / CFG["evidence_pack"]).resolve(), con)
    if not recovering_evidence_ready:
        ledger.transition(con, app_id, "evidence_ready", "retriever",
                          f"sufficiency={retrieval['sufficiency']} gaps={retrieval['gaps'][:5]}")
    print(f"[retrieve] {len(retrieval['selected'])}/{retrieval['total_chunks']} chunks selected | "
          f"sufficiency={retrieval['sufficiency']} | gaps: {', '.join(retrieval['gaps'][:6]) or 'none'}")

    # application folder + tickets
    app_dir = (AJOS_DIR / CFG["applications_dir"]).resolve() / f"{time.strftime('%Y-%m-%d')}_{app_id}"
    app_dir.mkdir(parents=True, exist_ok=True)
    (app_dir / "jd.json").write_text(json.dumps(jd, indent=2))
    (app_dir / "retrieval.json").write_text(json.dumps(retrieval, indent=2))
    t1 = taskpack.write_tailor_ticket(app_dir, app_id, jd, routing, retrieval, jd_text)
    t2 = taskpack.write_answers_ticket(
        app_dir, app_id, jd, retrieval,
        (AJOS_DIR / CFG["personal_data_sheet"]).resolve(), jd_text
    )
    ledger.set_fields(con, app_id, app_dir=str(app_dir))
    ledger.transition(con, app_id, "tailoring", "orchestrator", "tickets opened")
    print(f"[tickets] OPEN -> {t1.name}, {t2.name}\n          in {app_dir}")
    print(f"\nNEXT: have any model execute the tickets, then: python3 ajos.py advance {app_id}")


def cmd_advance(app_id: str):
    con = ledger.connect(AJOS_DIR / CFG["db_path"])
    app = ledger.get_application(con, app_id)
    if not app:
        sys.exit(f"unknown app_id {app_id}")
    app_dir = Path(app["app_dir"])
    jd = json.loads((app_dir / "jd.json").read_text())

    if app["status"] == "tailoring":
        ok, msg, meta = taskpack.validate_tailor_result(app_dir)
        if not ok:
            print(f"[advance] ticket not complete: {msg}")
            return
        ledger.transition(con, app_id, "tailored", "orchestrator", f"meta={meta.get('self_ats_estimate')}")
        # learning loop: record which retrieved chunks the model actually used
        if meta.get("used_chunk_ids"):
            ledger.record_usage(con, meta["used_chunk_ids"])
            print(f"[learn] usage recorded for {len(meta['used_chunk_ids'])} chunks")
        app = ledger.get_application(con, app_id)

    if app["status"] == "tailored":
        result = qa.run_qa(app_dir, jd, CFG)
        (app_dir / "qa_report.json").write_text(json.dumps(result, indent=2))
        for k, v in result["checks"].items():
            print(f"[qa] {k}: {v}")
        if not result["passed"]:
            ledger.transition(con, app_id, "qa_failed", "qa", "; ".join(result["failures"]))
            new = ledger.transition(
                con, app_id, "tailoring", "qa", "bounced back with failure reasons",
                qa_retry_limit=CFG["qa"]["max_qa_retries"],
            )
            (app_dir / "TICKET_tailor.md").write_text(
                (app_dir / "TICKET_tailor.md").read_text()
                + f"\n\n## QA BOUNCE ({time.strftime('%H:%M')})\nFix and rewrite RESULT_resume.tex:\n- "
                + "\n- ".join(result["failures"]))
            print(f"[qa] FAILED -> {new}. Reasons appended to TICKET_tailor.md")
            return
        ledger.transition(con, app_id, "qa_passed", "qa")
        app = ledger.get_application(con, app_id)

    if app["status"] == "qa_passed":
        dups = ledger.similar_company_recent(con, jd["company"])
        dup_note = "; ".join(f"{d['app_id']}({d['status']})" for d in dups if d["app_id"] != app_id) or "none"
        out = stage.stage(app_dir, app_id, jd, CFG, dup_note)
        ledger.transition(con, app_id, "staged", "stager", out["package"])
        print(f"[stage] APPROVAL PACKAGE READY:\n        {out['package']}\n        {out['checklist']}")
        print(f"        You review + click submit, then: python3 ajos.py mark {app_id} submitted")


def cmd_status(app_id: str | None = None):
    con = ledger.connect(AJOS_DIR / CFG["db_path"])
    if app_id:
        app = ledger.get_application(con, app_id)
        print(dict(app) if app else "not found")
        for e in con.execute("SELECT ts, actor, event, detail FROM events WHERE app_id=? ORDER BY id",
                             (app_id,)):
            print(f"  {e['ts']} [{e['actor']}] {e['event']}: {(e['detail'] or '')[:110]}")
    else:
        rows = ledger.list_applications(con)
        if not rows:
            print("ledger empty")
        for r in rows:
            print(f"{r['app_id']:<55} {r['company']:<20} {r['bucket'] or '-':<12} "
                  f"sim={r['route_similarity'] or 0:<7} {r['status']}")


def cmd_mark(app_id: str, state: str):
    con = ledger.connect(AJOS_DIR / CFG["db_path"])
    new = ledger.transition(con, app_id, state, "human")
    print(f"[mark] {app_id} -> {new}")
    # learning loop: positive outcome credits the evidence chunks that resume used
    if new in ("outcome_callback", "outcome_interview", "outcome_offer"):
        app = ledger.get_application(con, app_id)
        meta_p = Path(app["app_dir"]) / "RESULT_tailor_meta.json" if app["app_dir"] else None
        if meta_p and meta_p.exists():
            used = json.loads(meta_p.read_text()).get("used_chunk_ids", [])
            for cid in used:
                con.execute("UPDATE chunk_stats SET times_in_callback=times_in_callback+1 "
                            "WHERE chunk_id=?", (cid,))
            con.commit()
            print(f"[learn] credited {len(used)} chunks for {new}")


def cmd_scout():
    companies_csv = (AJOS_DIR / CFG["target_companies"]).resolve()
    scouting_dir = (AJOS_DIR / CFG["scouting_dir"]).resolve()
    result = scout.run_scout(CFG, AJOS_DIR, companies_csv, scouting_dir)
    f = result["funnel"]
    print(f"[scout] {f['companies_scanned']} companies scanned "
          f"({f['companies_failed']} unreachable, {f['companies_skipped_no_api']} skipped -- "
          f"no scriptable ATS/careers-page scraper) -> {f['fetched']} postings fetched "
          f"in {f.get('fetch_seconds', '?')}s with {f.get('max_workers', 1)} workers")
    print(f"[scout] funnel: title={f['title_match']} -> us={f['us']} -> fresh<=7d={f['fresh']} "
          f"-> work_auth_ok={f['work_auth_ok']} -> new={f['not_dup_jobid']}")
    if f.get("used_repost_fallback"):
        print("[scout] no fresh non-repost survivors — fell back to reposts per filter rules")
    print(f"[scout] {f['final']} new JD(s) written, ranked queue: {result['queue_path']}")
    for q in result["queue"][:15]:
        print(f"  #{q['rank']:<3} {q['company']:<22} {q['title'][:45]:<45} "
              f"bucket={q['bucket_routed']:<12} sim={q['similarity']:<7} "
              f"age_h={q['hours_ago']}  {q['jd_file']}")
    if result["queue"]:
        print(f"\nNEXT: python3 ajos.py ingest <jd_file> --url <url>  (see queue json for full list)")


def cmd_reflect(sub: str | None = None):
    con = ledger.connect(AJOS_DIR / CFG["db_path"])
    if sub == "apply":
        inserted = reflect.apply_result(con, AJOS_DIR)
        print(f"[reflect] {len(inserted)} rule(s) inserted as PROPOSED (inert until approved):")
        for r in inserted:
            print(f"  - {r['rule']}")
        print("Review with: python3 ajos.py rules   |   approve: python3 ajos.py rules approve <id>")
    else:
        path = reflect.generate_ticket(con, AJOS_DIR)
        print(f"[reflect] ticket generated: {path}")
        print(f"NEXT: have any model execute it, then: python3 ajos.py reflect apply")


def cmd_rules(action: str | None = None, rule_id: str | None = None):
    con = ledger.connect(AJOS_DIR / CFG["db_path"])
    if action in ("approve", "reject") and rule_id:
        con.execute("UPDATE playbook_rules SET status=? WHERE rule_id=?",
                    ("approved" if action == "approve" else "rejected", rule_id))
        con.commit()
        ledger.log_event(con, None, "human", f"rule_{action}d", f"rule_id={rule_id}")
        print(f"[rules] #{rule_id} {action}d")
    else:
        for r in con.execute("SELECT rule_id, status, created_at, rule FROM playbook_rules "
                             "ORDER BY rule_id"):
            print(f"#{r['rule_id']} [{r['status']}] ({r['created_at'][:10]}) {r['rule'][:150]}")


def cmd_chunks():
    con = ledger.connect(AJOS_DIR / CFG["db_path"])
    print(f"{'chunk_id':<12} {'section':<12} {'ret':>4} {'used':>5} {'cb':>3}  text")
    for r in con.execute("SELECT * FROM chunk_stats ORDER BY times_retrieved DESC LIMIT 30"):
        print(f"{r['chunk_id']:<12} {r['section']:<12} {r['times_retrieved']:>4} "
              f"{r['times_used']:>5} {r['times_in_callback']:>3}  {r['text_head'][:70]}")


def _export():
    try:
        con = ledger.connect(AJOS_DIR / CFG["db_path"])
        ledger.export_json(con, AJOS_DIR / "ledger_export.json")
    except Exception as e:  # export must never break the pipeline
        print(f"[export] skipped: {e}")


if __name__ == "__main__":
    args = sys.argv[1:]
    if not args:
        print(__doc__)
    elif args[0] == "ingest":
        url = args[args.index("--url") + 1] if "--url" in args else ""
        cmd_ingest(args[1], url)
        _export()
    elif args[0] == "advance":
        cmd_advance(args[1])
        _export()
    elif args[0] == "status":
        cmd_status(args[1] if len(args) > 1 else None)
    elif args[0] == "mark":
        cmd_mark(args[1], args[2])
        _export()
    elif args[0] == "chunks":
        cmd_chunks()
    elif args[0] == "scout":
        cmd_scout()
    elif args[0] == "reflect":
        cmd_reflect(args[1] if len(args) > 1 else None)
        _export()
    elif args[0] == "rules":
        cmd_rules(args[1] if len(args) > 1 else None,
                  args[2] if len(args) > 2 else None)
        _export()
    else:
        print(__doc__)
