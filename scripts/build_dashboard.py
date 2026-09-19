#!/usr/bin/env python3
"""Build the bounded AJOS approval-dashboard artifact from portable state."""
import json
from collections import Counter
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
PIPELINE = ROOT / "private"
OUT = ROOT / "output" / "dashboard"


def latest_queue():
    files = sorted((PIPELINE / "scouting").glob("queue_*.json"))
    if not files:
        return {"generated_at": None, "funnel": {}, "queue": []}
    return json.loads(files[-1].read_text())


def action_for(status):
    return {
        "staged": "Review package; human submits",
        "tailoring": "Complete model ticket",
        "needs_manual": "Resolve blocked field or QA issue",
        "submitted": "Await outcome",
        "outcome_callback": "Prepare recruiter response",
        "outcome_interview": "Prepare interview",
        "outcome_offer": "Review offer",
        "outcome_rejected": "Record outcome for reflection",
        "outcome_ghosted": "Record outcome for reflection",
    }.get(status, "Continue deterministic pipeline")


def main():
    ledger = json.loads((ROOT / "ledger_export.json").read_text())
    queue = latest_queue()
    applications = ledger.get("applications", [])
    status_counts = Counter(row["status"] for row in applications)
    terminal_progress = sum(
        status_counts[s] for s in ("outcome_callback", "outcome_interview", "outcome_offer")
    )
    submitted = sum(v for k, v in status_counts.items() if k == "submitted" or k.startswith("outcome_"))
    pending_rules = sum(1 for r in ledger.get("playbook_rules", []) if r["status"] == "proposed")
    generated = datetime.now().astimezone().isoformat(timespec="seconds")

    app_rows = [{
        "company": row.get("company") or "",
        "role": row.get("role_title") or "",
        "bucket": row.get("bucket") or "",
        "status": row.get("status") or "",
        "job_url": row.get("url") or "",
        "ats": row.get("ats") or "",
        "updated_at": row.get("updated_at") or "",
        "action": action_for(row.get("status")),
    } for row in applications]
    status_rows = [
        {"status": status, "applications": count}
        for status, count in sorted(status_counts.items(), key=lambda item: (-item[1], item[0]))
    ]
    summary_rows = [{
        "tracked": len(applications),
        "ready_for_review": status_counts["staged"],
        "submitted": submitted,
        "progressed": terminal_progress,
        "needs_manual": status_counts["needs_manual"],
        "pending_rules": pending_rules,
    }]
    scouting_rows = [{
        "generated_at": queue.get("generated_at") or "not available",
        "fetched": queue.get("funnel", {}).get("fetched", 0),
        "fresh": queue.get("funnel", {}).get("fresh", 0),
        "final": queue.get("funnel", {}).get("final", len(queue.get("queue", []))),
        "companies_scanned": queue.get("funnel", {}).get("companies_scanned", 0),
        "companies_failed": queue.get("funnel", {}).get("companies_failed", 0),
    }]

    artifact = {
        "surface": "dashboard",
        "manifest": {
            "version": 1,
            "surface": "dashboard",
            "title": "AJOS Application Dashboard",
            "description": "Approval-first view of application state, outcomes, and scouting health.",
            "generatedAt": generated,
            "cards": [{
                "id": "pipeline_metrics",
                "description": "Current portable ledger counts.",
                "dataset": "summary",
                "sourceId": "ledger_source",
                "metrics": [
                    {"label": "Tracked", "field": "tracked", "format": "number"},
                    {"label": "Ready for review", "field": "ready_for_review", "format": "number"},
                    {"label": "Submitted", "field": "submitted", "format": "number"},
                    {"label": "Progressed", "field": "progressed", "format": "number"},
                    {"label": "Needs manual", "field": "needs_manual", "format": "number"},
                    {"label": "Proposed rules", "field": "pending_rules", "format": "number"},
                ],
            }],
            "charts": [{
                "id": "status_chart",
                "title": "Applications by status",
                "subtitle": "Staged applications still require the candidate to review and click Submit.",
                "type": "bar",
                "dataset": "status_counts",
                "sourceId": "ledger_source",
                "encodings": {
                    "x": {"field": "status", "type": "nominal", "label": "Status"},
                    "y": {"field": "applications", "type": "quantitative", "label": "Applications"},
                },
            }],
            "tables": [
                {
                    "id": "applications_table",
                    "title": "Application queue",
                    "subtitle": "Current job, package, and outcome state.",
                    "dataset": "applications",
                    "sourceId": "ledger_source",
                    "defaultSort": {"field": "updated_at", "direction": "desc"},
                    "columns": [
                        {"field": "company", "label": "Company", "type": "text"},
                        {"field": "role", "label": "Role", "type": "text"},
                        {"field": "bucket", "label": "Base", "type": "text"},
                        {"field": "status", "label": "Status", "type": "text"},
                        {"field": "job_url", "label": "Job URL", "type": "url"},
                        {"field": "action", "label": "Next action", "type": "text"},
                        {"field": "updated_at", "label": "Updated", "type": "datetime"},
                    ],
                },
                {
                    "id": "scouting_table",
                    "title": "Scouting health",
                    "subtitle": "Latest available scouting manifest; freshness is shown explicitly.",
                    "dataset": "scouting",
                    "sourceId": "scouting_source",
                    "defaultSort": {"field": "generated_at", "direction": "desc"},
                    "columns": [
                        {"field": "generated_at", "label": "Generated", "type": "text"},
                        {"field": "fetched", "label": "Fetched", "type": "number"},
                        {"field": "fresh", "label": "Fresh", "type": "number"},
                        {"field": "final", "label": "Shortlisted", "type": "number"},
                        {"field": "companies_scanned", "label": "Boards scanned", "type": "number"},
                        {"field": "companies_failed", "label": "Failures", "type": "number"},
                    ],
                },
            ],
            "sources": [
                {
                    "id": "ledger_source",
                    "label": "AJOS portable ledger",
                    "path": "ledger_export.json",
                    "query": {
                        "engine": "sqlite",
                        "description": "Current AJOS application, outcome, and proposed-rule state.",
                        "sql": "SELECT * FROM applications ORDER BY updated_at DESC",
                        "tables_used": ["applications", "playbook_rules"],
                    },
                },
                {
                    "id": "scouting_source",
                    "label": "Latest scouting queue",
                    "path": "scouting/queue_latest.json",
                    "query": {
                        "engine": "json_snapshot",
                        "description": "Latest deterministic scouting funnel snapshot.",
                        "sql": "SELECT * FROM scouting_queue ORDER BY generated_at DESC LIMIT 1",
                        "tables_used": ["scouting_queue"],
                    },
                },
            ],
            "blocks": [
                {
                    "id": "heading",
                    "type": "markdown",
                    "body": "# AJOS Application Dashboard\n\nHuman approval remains mandatory before submission. Learned rules remain inert until reviewed and approved.",
                },
                {"id": "metrics", "type": "metric-strip", "cardIds": ["pipeline_metrics"]},
                {"id": "status", "type": "chart", "chartId": "status_chart"},
                {"id": "applications", "type": "table", "tableId": "applications_table"},
                {"id": "scouting", "type": "table", "tableId": "scouting_table"},
                {
                    "id": "sync_note",
                    "type": "markdown",
                    "body": "## Sync status\n\nThe Notion tracker schema is connected and verified. Row-level query/sync was unavailable in the current connector session, so this dashboard does not claim bidirectional synchronization yet.",
                },
            ],
        },
        "snapshot": {
            "version": 1,
            "generatedAt": generated,
            "status": "ready",
            "datasets": {
                "summary": summary_rows,
                "status_counts": status_rows,
                "applications": app_rows,
                "scouting": scouting_rows,
            },
        },
    }
    OUT.mkdir(parents=True, exist_ok=True)
    target = OUT / "artifact.json"
    target.write_text(json.dumps(artifact, indent=2))
    print(target)


if __name__ == "__main__":
    main()
