"""Price Sentinel Google Sheets multi-sector staging (no writes).

Examples, from backend directory:

    PYTHONPATH=. python scripts/sheet_sync_preview.py --fixture tests/fixtures/sheets_sync_synthetic.json
    PYTHONPATH=. python scripts/sheet_sync_preview.py --spreadsheet-id "$SHEETS_SOURCE_ID" \
        --service-account-file "$SHEETS_SERVICE_ACCOUNT_FILE" --output /tmp/sentinel-preview.json

The output contains supplier prices: store outside the public repository.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path

from app.services.sheet_sync_dry_run import stage_snapshot


async def execute(args: argparse.Namespace) -> int:
    if args.fixture:
        snapshot = json.loads(Path(args.fixture).read_text(encoding="utf-8"))
    else:
        sid = args.spreadsheet_id or os.environ.get("SHEETS_SOURCE_ID", "")
        secret = args.service_account_file or os.environ.get("SHEETS_SERVICE_ACCOUNT_FILE", "")
        if not sid or not secret:
            raise SystemExit(
                "Missing SHEETS_SOURCE_ID and SHEETS_SERVICE_ACCOUNT_FILE. "
                "Only read-only Google service accounts are supported."
            )
        from app.services.sheet_sync_google import GoogleSheetsReadOnly
        connector = GoogleSheetsReadOnly(sid, secret)
        snapshot = await connector.read_snapshot(with_cell_notes=not args.skip_notes)

    if snapshot.get("title") not in {None, "", "santo graal"}:
        raise SystemExit("Wrong workbook title: refusing to stage")
    report = stage_snapshot(
        snapshot.get("values", {}),
        spreadsheet_id=snapshot.get("spreadsheet_id", ""),
        notes=snapshot.get("notes", {}),
    )
    report["workbook_title"] = snapshot.get("title")
    report["workbook_time_zone"] = snapshot.get("timeZone")
    report["workbook_tabs"] = snapshot.get("all_tab_names", [])
    report["ignored_support_tabs"] = snapshot.get("support_tabs", [])
    report["unknown_tabs"] = snapshot.get("unknown_tabs", [])
    print("Price Sentinel Sheets Sync: DRY-RUN / READ-ONLY")
    print(f"Workbook: {snapshot.get('title', '(synthetic fixture)')}")
    print(f"Candidates staged: {report['candidate_count']}; price commits: 0")
    for sector in report["sector_summary"]:
        print(
            f"{sector['sector']:<13} | products {sector['products']:>4} | "
            f"quotes {sector['quotes']:>4} | excluded {sector['excluded']:>3} | "
            f"blocked {sector['blocked']:>4} | review {sector['review']:>4}"
        )
    if report["missing_sources"]:
        print(f"ALERT: missing/mismatched sources: {report['missing_sources']}")
    if report["warnings"]:
        print(f"Anomalies to review: {len(report['warnings'])}")
    if args.show_samples:
        for candidate in report["candidates"][:args.show_samples]:
            print(f"- {candidate['sector']}/{candidate['source_cell']}: "
                  f"{candidate['status']} ({', '.join(candidate['reasons'])})")
    if args.output:
        output = Path(args.output).expanduser().resolve()
        if output.is_relative_to(Path(__file__).resolve().parents[2]):
            raise SystemExit("Choose an output path OUTSIDE the repository working directory")
        output.parent.mkdir(parents=True, exist_ok=True)
        if output.exists():
            raise SystemExit("Output path already exists: refusing to overwrite")
        output.write_text(json.dumps(report, indent=2, ensure_ascii=False, default=str),
                          encoding="utf-8")
        try:
            output.chmod(0o600)
        except OSError:
            pass
        print(f"Local preview written to: {output}")
    return 1 if report["missing_sources"] else 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Read-only, no price commits")
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--fixture", help="Synthetic JSON snapshot (offline test)")
    source.add_argument("--spreadsheet-id", help="Google Sheets ID (also SHEETS_SOURCE_ID)")
    parser.add_argument("--service-account-file", help="Google JSON credentials file path")
    parser.add_argument("--skip-notes", action="store_true", help="Skip optional Google cell notes")
    parser.add_argument("--output", help="Private JSON report OUTSIDE the repo")
    parser.add_argument("--show-samples", type=int, default=3)
    args = parser.parse_args()
    raise SystemExit(asyncio.run(execute(args)))


if __name__ == "__main__":
    main()
