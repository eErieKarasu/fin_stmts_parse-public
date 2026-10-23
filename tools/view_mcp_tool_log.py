#!/usr/bin/env python3
import argparse
import json
import sys
from datetime import date
from pathlib import Path
from typing import Any, Dict, Iterable, List


def default_log_file() -> Path:
    return Path("logs") / f"mcp_tools_{date.today().strftime('%Y-%m-%d')}.jsonl"


def positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be greater than 0")
    return parsed


def read_records(log_file: Path) -> List[Dict[str, Any]]:
    records: List[Dict[str, Any]] = []
    with log_file.open("r", encoding="utf-8") as file:
        for line_no, line in enumerate(file, start=1):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                record = json.loads(stripped)
            except json.JSONDecodeError as exc:
                print(
                    f"skip invalid JSON line {line_no}: {exc}",
                    file=sys.stderr,
                )
                continue
            if isinstance(record, dict):
                record["_line_no"] = line_no
                records.append(record)
            else:
                print(f"skip non-object JSON line {line_no}", file=sys.stderr)
    return records


def matches_record(
    record: Dict[str, Any],
    *,
    tool: str | None = None,
    session_id: str | None = None,
    status: str | None = None,
) -> bool:
    if tool and record.get("tool") != tool:
        return False
    if session_id and record.get("session_id") != session_id:
        return False
    if status and record.get("status") != status:
        return False
    return True


def filter_records(
    records: Iterable[Dict[str, Any]],
    *,
    tool: str | None = None,
    session_id: str | None = None,
    status: str | None = None,
) -> List[Dict[str, Any]]:
    return [
        record
        for record in records
        if matches_record(
            record,
            tool=tool,
            session_id=session_id,
            status=status,
        )
    ]


def select_records(
    records: List[Dict[str, Any]],
    *,
    limit: int,
    show_all: bool,
) -> List[Dict[str, Any]]:
    if show_all:
        return records
    return records[-limit:]


def format_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, default=str)


def format_record(record: Dict[str, Any]) -> str:
    tool = record.get("tool") or "<unknown>"
    status = record.get("status") or "<unknown>"
    lines = [
        f"=== MCP TOOL {tool} ===",
        f"line_no: {record.get('_line_no', '-')}",
        f"started_at: {record.get('started_at', '-')}",
        f"finished_at: {record.get('finished_at', '-')}",
        f"duration_ms: {record.get('duration_ms', '-')}",
        f"session_id: {record.get('session_id', '-')}",
        f"status: {status}",
        "",
        "--- input ---",
        format_json(record.get("input")),
    ]

    if "output" in record:
        lines.extend(["", "--- output ---", format_json(record.get("output"))])

    if "error" in record:
        lines.extend(["", "--- error ---", format_json(record.get("error"))])

    lines.extend(["", f"=== END MCP TOOL {tool} ==="])
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Render MCP tool JSONL audit logs in a human-readable format.",
    )
    parser.add_argument(
        "log_file",
        nargs="?",
        type=Path,
        default=default_log_file(),
        help="Path to mcp_tools_YYYY-MM-DD.jsonl. Defaults to today's local log.",
    )
    parser.add_argument("--tool", help="Only show records for this MCP tool.")
    parser.add_argument("--session-id", help="Only show records for this session_id.")
    parser.add_argument(
        "--status",
        choices=("success", "error"),
        help="Only show records with this status.",
    )
    parser.add_argument(
        "--latest",
        action="store_true",
        help="Show the latest matching record. This is the default.",
    )
    parser.add_argument(
        "--limit",
        type=positive_int,
        default=1,
        help="Show the latest N matching records. Defaults to 1.",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Show all matching records.",
    )
    return parser


def main(argv: List[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if not args.log_file.exists():
        parser.error(f"log file not found: {args.log_file}")

    records = read_records(args.log_file)
    matched = filter_records(
        records,
        tool=args.tool,
        session_id=args.session_id,
        status=args.status,
    )
    selected = select_records(
        matched,
        limit=1 if args.latest else args.limit,
        show_all=args.all,
    )

    if not selected:
        print("No matching MCP tool log records found.", file=sys.stderr)
        return 1

    print("\n\n".join(format_record(record) for record in selected))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
