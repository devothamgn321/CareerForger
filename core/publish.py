"""Publish staged packages into the Chrome extension folder(s).

The unpacked P1 Autofill extension can read files inside its own folder, so dropping
`packages/<app_id>.json` + `packages/index.json` there lets the sidebar auto-load the
package for the job page you open. No local server, no copy-paste. Nothing is submitted:
the package keeps approved:false and the human still clicks Submit.
"""
import json
import time
from pathlib import Path
from urllib.parse import urlsplit

DEFAULT_DIRS = ["extension"]
AJOS_DIR = Path(__file__).resolve().parent.parent


def _dirs(cfg: dict) -> list[Path]:
    out = []
    for raw in cfg.get("extension_dirs", DEFAULT_DIRS):
        path = Path(raw).expanduser()
        if not path.is_absolute():
            path = (AJOS_DIR / path).resolve()
        if (path / "manifest.json").exists():
            out.append(path)
    return out


def _entry(package: dict) -> dict:
    parts = urlsplit(package.get("apply_url") or "")
    qa = package.get("resume_qa") or {}
    return {
        "app_id": package["job_id"],
        "company": package.get("company"),
        "role": package.get("role"),
        "apply_url": package.get("apply_url"),
        "host": parts.netloc.lower(),
        "path": parts.path.rstrip("/"),
        "ats": package.get("ats"),
        "staged_at": package.get("staged_at"),
        "ats_alignment_score": qa.get("ats_alignment_score"),
        "has_cover_letter": bool(package.get("cover_letter_data_base64")),
        "file": f"packages/{package['job_id']}.json",
    }


def _write_index(pkg_dir: Path, entries: list[dict]) -> None:
    entries = sorted(entries, key=lambda e: e.get("staged_at") or "", reverse=True)
    body = {"updated_at": time.strftime("%Y-%m-%dT%H:%M:%S"), "packages": entries}
    (pkg_dir / "index.json").write_text(json.dumps(body, indent=2))


def _read_index(pkg_dir: Path) -> list[dict]:
    try:
        return json.loads((pkg_dir / "index.json").read_text()).get("packages", [])
    except (OSError, json.JSONDecodeError):
        return []


def publish(package: dict, cfg: dict) -> list[str]:
    """Copy one package into every extension folder and refresh its index."""
    written = []
    for ext in _dirs(cfg):
        pkg_dir = ext / "packages"
        pkg_dir.mkdir(exist_ok=True)
        (pkg_dir / f"{package['job_id']}.json").write_text(json.dumps(package))
        entries = [e for e in _read_index(pkg_dir) if e.get("app_id") != package["job_id"]]
        entries.append(_entry(package))
        _write_index(pkg_dir, entries)
        written.append(str(pkg_dir))
    return written


def unpublish(app_id: str, cfg: dict) -> None:
    """Drop a package from the auto-load index (after submit/drop). The file is kept."""
    for ext in _dirs(cfg):
        pkg_dir = ext / "packages"
        if not (pkg_dir / "index.json").exists():
            continue
        _write_index(pkg_dir, [e for e in _read_index(pkg_dir) if e.get("app_id") != app_id])
