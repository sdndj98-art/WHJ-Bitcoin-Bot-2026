"""Independent, zero-token verifier for WHJ agent evidence reports.

This process runs separately from the workers. It checks that each quoted
finding exists verbatim in the referenced repository source and that source
fingerprints have not changed since inventory collection. It never edits
source files, paper ledgers, or trading settings.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_REPORTS = (
    Path("research/agent_office/latest_free_worker_results.json"),
)
DEFAULT_OUTPUT = Path("research/agent_office/evidence_verifier")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def safe_source(root: Path, source_path: str) -> Path | None:
    if not isinstance(source_path, str) or not source_path.strip():
        return None
    candidate = (root / source_path).resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError:
        return None
    return candidate if candidate.is_file() else None


def verify_report(root: Path, report_path: Path) -> dict:
    path = report_path if report_path.is_absolute() else root / report_path
    result = {
        "report": str(path.relative_to(root) if path.is_relative_to(root) else path),
        "status": "passed",
        "findings_checked": 0,
        "issues": [],
    }
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        result["status"] = "failed"
        result["issues"].append({"type": "report_unreadable", "detail": str(exc)})
        return result

    rows = document.get("reports")
    if not isinstance(rows, list):
        result["status"] = "failed"
        result["issues"].append({
            "type": "invalid_report_schema",
            "detail": "Expected a top-level reports array.",
        })
        return result

    for row_index, row in enumerate(rows):
        if not isinstance(row, dict):
            result["issues"].append({
                "type": "invalid_task_report", "task_index": row_index,
                "detail": "Task report must be an object.",
            })
            continue
        findings = row.get("findings", [])
        if not isinstance(findings, list):
            result["issues"].append({
                "type": "invalid_findings", "task_id": row.get("task_id"),
                "detail": "Findings must be an array.",
            })
            continue

        inventory = {
            item.get("path"): item
            for item in row.get("files_inspected", [])
            if isinstance(item, dict) and isinstance(item.get("path"), str)
        }
        for finding_index, finding in enumerate(findings):
            result["findings_checked"] += 1
            location = {
                "task_id": row.get("task_id"),
                "finding_index": finding_index,
            }
            if not isinstance(finding, dict):
                result["issues"].append({
                    **location, "type": "invalid_finding",
                    "detail": "Finding must be an object.",
                })
                continue

            source_path = finding.get("source_path")
            quote = finding.get("evidence_quote")
            source = safe_source(root, source_path)
            if source is None:
                result["issues"].append({
                    **location, "type": "source_missing_or_unsafe",
                    "source_path": source_path,
                    "detail": "Source path is missing, outside the repository, or not a file.",
                })
                continue
            if not isinstance(quote, str) or len(quote.strip()) < 12:
                result["issues"].append({
                    **location, "type": "quote_missing_or_too_short",
                    "source_path": source_path,
                    "detail": "Evidence quote must contain at least 12 non-whitespace characters.",
                })
                continue
            try:
                source_text = source.read_text(encoding="utf-8")
            except (OSError, UnicodeError) as exc:
                result["issues"].append({
                    **location, "type": "source_unreadable",
                    "source_path": source_path, "detail": str(exc),
                })
                continue
            if quote not in source_text:
                result["issues"].append({
                    **location, "type": "quote_not_in_source",
                    "source_path": source_path, "quote": quote,
                    "detail": "Evidence quote does not exist verbatim in the current source.",
                })
                continue

            snapshot = inventory.get(source_path)
            if snapshot and snapshot.get("sha256"):
                actual_hash = sha256_file(source)
                if actual_hash != snapshot["sha256"]:
                    result["issues"].append({
                        **location, "type": "source_changed_since_inventory",
                        "source_path": source_path,
                        "expected_sha256": snapshot["sha256"],
                        "actual_sha256": actual_hash,
                        "detail": "Source changed after the worker recorded its fingerprint.",
                    })

    if result["issues"]:
        result["status"] = "failed"
    return result


def discover_reports(root: Path) -> list[Path]:
    candidates = []
    latest = root / DEFAULT_REPORTS[0]
    if latest.is_file():
        candidates.append(latest)
    run_root = root / "research/agent_office/runs"
    if run_root.is_dir():
        candidates.extend(sorted(run_root.glob("*/free/free_worker_results.json")))
    # Keep paths unique while preserving deterministic order.
    return list(dict.fromkeys(candidates))


def run_verification(root: Path, reports: list[Path] | None = None) -> dict:
    root = root.resolve()
    selected = reports if reports is not None else discover_reports(root)
    results = [verify_report(root, item) for item in selected]
    failed = [item for item in results if item["status"] != "passed"]
    return {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "verifier": "WHJ Independent Evidence Verifier",
        "mode": "local_deterministic_zero_token",
        "reports_checked": len(results),
        "findings_checked": sum(item["findings_checked"] for item in results),
        "status": "passed" if results and not failed else ("failed" if failed else "no_reports"),
        "report_results": results,
        "limitations": [
            "Exact quote matching proves only that the quoted text exists in the source; it does not prove the claim logically follows from that quote.",
            "Only configured WHJ free-worker report files are scanned by default.",
            "The verifier is a separate deterministic process, not an AI semantic fact-checker.",
        ],
    }


def write_outputs(result: dict, output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "latest_report.json").write_text(
        json.dumps(result, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    lines = [
        "# WHJ Independent Evidence Verification",
        "",
        f"- Generated UTC: {result['generated_at_utc']}",
        f"- Status: **{result['status']}**",
        f"- Reports checked: {result['reports_checked']}",
        f"- Exact quotes checked: {result['findings_checked']}",
        "- Execution: local Python; zero model tokens; no network calls",
        "",
        "| Report | Status | Quotes checked | Issues |",
        "|---|---|---:|---:|",
    ]
    for item in result["report_results"]:
        lines.append(
            f"| {item['report']} | **{item['status']}** | "
            f"{item['findings_checked']} | {len(item['issues'])} |"
        )
        for issue in item["issues"]:
            lines.append(
                f"| | {issue['type']} | | {issue.get('source_path', '')} "
                f"{issue.get('detail', '')} |"
            )
    lines += ["", "## Limitations", *[f"- {item}" for item in result["limitations"]], ""]
    (output_dir / "latest_report.md").write_text("\n".join(lines), encoding="utf-8")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Verify WHJ worker evidence without AI or API tokens")
    parser.add_argument("--root", default=".")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT))
    args = parser.parse_args(argv)
    root = Path(args.root).resolve()
    result = run_verification(root)
    output = Path(args.output_dir)
    if not output.is_absolute():
        output = root / output
    write_outputs(result, output)
    print(
        f"WHJ evidence verifier: {result['status']}; "
        f"reports={result['reports_checked']} quotes={result['findings_checked']}"
    )
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
