#!/usr/bin/env python3
"""Verify Greenhouse, Lever, and Ashby board tokens without exposing job payloads.

Writes a compact JSON report containing only company/token/status/job-count. It never stores
descriptions or raw board responses.
"""
import argparse
import csv
import json
import subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

URLS = {
    "greenhouse": "https://boards-api.greenhouse.io/v1/boards/{token}/jobs",
    "lever": "https://api.lever.co/v0/postings/{token}?mode=json",
    "ashby": "https://api.ashbyhq.com/posting-api/job-board/{token}",
}
USER_AGENT = "ajos-board-verifier/1.0"


def verify(row: dict, timeout: int) -> dict:
    ats = row["likely_ats"].strip().lower()
    token = row["board_token_guess"].strip()
    result = {
        "company": row["company"].strip(),
        "ats": ats,
        "token": token,
        "tier": row.get("tier", "").strip(),
    }
    if ats not in URLS or not token:
        return {**result, "status": "not_scriptable", "jobs": None}
    try:
        completed = subprocess.run(
            ["curl", "-fsSL", "--max-time", str(timeout), "-A", USER_AGENT,
             URLS[ats].format(token=token)],
            capture_output=True, text=True, timeout=timeout + 2, check=False,
        )
        if completed.returncode:
            return {**result, "status": f"curl_{completed.returncode}", "jobs": None}
        data = json.loads(completed.stdout)
        jobs = data if isinstance(data, list) else data.get("jobs") if isinstance(data, dict) else None
        if not isinstance(jobs, list):
            return {**result, "status": "invalid_payload", "jobs": None}
        return {**result, "status": "ok", "jobs": len(jobs)}
    except (subprocess.TimeoutExpired, OSError, ValueError, json.JSONDecodeError) as exc:
        return {**result, "status": type(exc).__name__.lower(), "jobs": None}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("csv_path", type=Path)
    parser.add_argument("--output", type=Path, default=Path("board_verification.json"))
    parser.add_argument("--workers", type=int, default=12)
    parser.add_argument("--timeout", type=int, default=12)
    args = parser.parse_args()

    with args.csv_path.open(newline="", encoding="utf-8") as source:
        rows = list(csv.DictReader(source))
    results = []
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = [pool.submit(verify, row, args.timeout) for row in rows]
        for future in as_completed(futures):
            results.append(future.result())
    results.sort(key=lambda item: (item["status"], item["company"].lower()))
    summary = {}
    for item in results:
        summary[item["status"]] = summary.get(item["status"], 0) + 1
    payload = {"source": str(args.csv_path.resolve()), "summary": summary, "results": results}
    args.output.write_text(json.dumps(payload, indent=2))
    print(json.dumps(summary, sort_keys=True))
    for item in results:
        if item["status"] not in ("ok", "not_scriptable"):
            print(f"{item['status']}: {item['company']} [{item['ats']}:{item['token']}]")


if __name__ == "__main__":
    main()
