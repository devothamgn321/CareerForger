#!/usr/bin/env python3
"""Apply a reviewed board-verification result to TARGET_COMPANIES_v1.csv.

Only deterministic changes are made:
- confirmed 404 tokens are demoted to careers_page so scout stops wasting requests;
- candidate rows with status=ok are appended once and marked with the verification date.
"""
import argparse
import csv
import json
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("target_csv", type=Path)
    parser.add_argument("current_report", type=Path)
    parser.add_argument("candidate_csv", type=Path)
    parser.add_argument("candidate_report", type=Path)
    parser.add_argument("--date", required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    with args.target_csv.open(newline="", encoding="utf-8") as source:
        rows = list(csv.DictReader(source))
    fields = ["company", "likely_ats", "board_token_guess", "tier", "notes"]

    current = json.loads(args.current_report.read_text())["results"]
    dead = {item["company"] for item in current if item["status"] == "http_404"}
    demoted = 0
    for row in rows:
        if row["company"] in dead:
            old = f"{row['likely_ats']}:{row['board_token_guess']}"
            row["likely_ats"] = "careers_page"
            note = f"public ATS {old} returned 404 on {args.date}; needs re-discovery"
            row["notes"] = "; ".join(filter(None, [row.get("notes", "").strip(), note]))
            demoted += 1

    with args.candidate_csv.open(newline="", encoding="utf-8") as source:
        candidates = {row["company"]: row for row in csv.DictReader(source)}
    candidate_results = json.loads(args.candidate_report.read_text())["results"]
    existing = {row["company"].casefold() for row in rows}
    added = 0
    for result in candidate_results:
        if result["status"] != "ok" or result["company"].casefold() in existing:
            continue
        row = candidates[result["company"]]
        row["notes"] = f"public ATS verified {args.date}; {result['jobs']} jobs at verification"
        rows.append(row)
        existing.add(result["company"].casefold())
        added += 1

    scriptable = sum(row["likely_ats"] in {"greenhouse", "lever", "ashby"} for row in rows)
    print(f"demote_404={demoted} add_verified={added} total={len(rows)} scriptable={scriptable}")
    if not args.apply:
        print("dry run; pass --apply to write")
        return
    with args.target_csv.open("w", newline="", encoding="utf-8") as output:
        writer = csv.DictWriter(output, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


if __name__ == "__main__":
    main()
