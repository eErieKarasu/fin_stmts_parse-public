#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import sys
import time
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any, Sequence
from urllib.parse import urlparse

PROJECT_ROOT = Path(__file__).resolve().parents[1]
APPS_DIR = PROJECT_ROOT / "apps"
FIN_PARSE_APP_DIR = APPS_DIR / "fin_stmts_parse"

for path in (PROJECT_ROOT, APPS_DIR, FIN_PARSE_APP_DIR):
    path_str = str(path.resolve())
    if path_str not in sys.path:
        sys.path.insert(0, path_str)

from psycopg import connect, sql
from psycopg.rows import dict_row
from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.syntax import Syntax
from rich.table import Table
from rich.text import Text

from fin_stmts_parse.utils.read_yaml import load_env_config


DEFAULT_ENV = os.getenv("RUNNING_ENV", "local")
DEFAULT_SCHEMA = "public"
DEFAULT_PREVIEW_LIMIT = 20
DEFAULT_MAX_CELL_WIDTH = 48
READ_ONLY_PREFIXES = ("select", "show", "explain", "values", "table")

console = Console()


@dataclass(frozen=True)
class DbSettings:
    env: str
    dsn: str
    configured_tables: dict[str, str]


@dataclass(frozen=True)
class QueryResult:
    columns: list[str]
    rows: list[dict[str, Any]]
    rowcount: int
    elapsed_ms: float
    read_only: bool


def load_db_settings(env: str, dsn_override: str | None) -> DbSettings:
    config = load_env_config(env)
    postgres_config = config.get("postgres", {}) or {}
    dsn = str(dsn_override or postgres_config.get("dsn") or "").strip()
    if not dsn:
        raise ValueError(f"postgres.dsn is not configured for env={env}")

    table_names = postgres_config.get("table_names")
    if not isinstance(table_names, dict):
        table_names = {}

    configured_tables = {
        str(statement_type).strip(): str(table_name).strip()
        for statement_type, table_name in table_names.items()
        if str(statement_type).strip() and str(table_name).strip()
    }
    return DbSettings(env=env, dsn=dsn, configured_tables=configured_tables)


def parse_table_reference(table_ref: str, default_schema: str = DEFAULT_SCHEMA) -> tuple[str, str]:
    normalized = str(table_ref or "").strip()
    if not normalized:
        raise ValueError("table name is required")

    parts = normalized.split(".", maxsplit=1)
    if len(parts) == 1:
        return default_schema, parts[0]

    schema_name = parts[0].strip()
    table_name = parts[1].strip()
    if not schema_name or not table_name:
        raise ValueError(f"invalid table reference: {table_ref}")
    return schema_name, table_name


def compact_cell_value(value: Any, max_width: int) -> str:
    if value is None:
        return "NULL"

    text = str(value)
    if text == "":
        return "<empty>"

    text = text.replace("\r\n", "\n").replace("\r", "\n").replace("\n", " | ")
    if max_width > 3 and len(text) > max_width:
        return text[: max_width - 3] + "..."
    return text


def render_cell(value: Any, max_width: int) -> Text:
    compact = compact_cell_value(value, max_width=max_width)
    if value is None:
        return Text(compact, style="dim italic")
    if value == "":
        return Text(compact, style="yellow")
    return Text(compact)


def is_numeric_column(rows: Sequence[dict[str, Any]], column: str) -> bool:
    numeric_types = (int, float, Decimal)
    values = [row.get(column) for row in rows]
    concrete_values = [value for value in values if value is not None]
    return bool(concrete_values) and all(isinstance(value, numeric_types) for value in concrete_values)


def is_read_only_sql(sql_text: str) -> bool:
    normalized = str(sql_text or "").lstrip().lower()
    return normalized.startswith(READ_ONLY_PREFIXES)


def format_connection_summary(dsn: str) -> str:
    parsed = urlparse(dsn)
    host = parsed.hostname or "localhost"
    port = parsed.port or 5432
    database = parsed.path.lstrip("/") or "-"
    user = parsed.username or "-"
    return "\n".join(
        (
            f"host={host}",
            f"port={port}",
            f"database={database}",
            f"user={user}",
        )
    )


def print_connection_panel(settings: DbSettings) -> None:
    configured = ", ".join(
        f"{statement_type}:{table_name}"
        for statement_type, table_name in sorted(settings.configured_tables.items())
    ) or "-"
    body = "\n".join(
        (
            f"env={settings.env}",
            format_connection_summary(settings.dsn),
            f"configured_tables={configured}",
        )
    )
    console.print(Panel.fit(body, title="Postgres", border_style="cyan"))


def print_sql_panel(sql_text: str) -> None:
    console.print(
        Panel(
            Syntax(sql_text.strip() or "-- empty sql --", "sql", word_wrap=True, line_numbers=False),
            title="SQL",
            border_style="blue",
        )
    )


def render_rows(
    title: str,
    columns: Sequence[str],
    rows: Sequence[dict[str, Any]],
    *,
    max_width: int,
    vertical: bool = False,
) -> None:
    if not rows:
        console.print(Panel.fit("No rows returned.", title=title, border_style="yellow"))
        return

    use_vertical = vertical or (len(columns) > 8 and len(rows) <= 10)
    if use_vertical:
        render_vertical_rows(title, columns, rows, max_width=max_width)
        return

    table = Table(title=title, box=box.ROUNDED, header_style="bold cyan", row_styles=["none", "dim"])
    for column in columns:
        justify = "right" if is_numeric_column(rows, column) else "left"
        table.add_column(str(column), overflow="fold", max_width=max_width, justify=justify)

    for row in rows:
        table.add_row(*(render_cell(row.get(column), max_width=max_width) for column in columns))

    console.print(table)


def render_vertical_rows(
    title: str,
    columns: Sequence[str],
    rows: Sequence[dict[str, Any]],
    *,
    max_width: int,
) -> None:
    for index, row in enumerate(rows, start=1):
        table = Table(
            title=f"{title} #{index}",
            box=box.SIMPLE_HEAVY,
            header_style="bold cyan",
            show_header=True,
            row_styles=["none", "dim"],
        )
        table.add_column("column", style="bold")
        table.add_column("value", overflow="fold", max_width=max_width)
        for column in columns:
            table.add_row(str(column), render_cell(row.get(column), max_width=max_width))
        console.print(table)


def execute_sql(
    dsn: str,
    statement: Any,
    *,
    params: Sequence[Any] | None = None,
    read_only: bool,
) -> QueryResult:
    started = time.perf_counter()
    with connect(dsn, row_factory=dict_row) as conn:
        with conn.cursor() as cursor:
            cursor.execute(statement, params)
            columns = [
                description.name if hasattr(description, "name") else description[0]
                for description in (cursor.description or [])
            ]
            rows = cursor.fetchall() if columns else []
            conn.commit()
    elapsed_ms = (time.perf_counter() - started) * 1000
    rowcount = len(rows) if columns else 0
    return QueryResult(
        columns=columns,
        rows=rows,
        rowcount=rowcount,
        elapsed_ms=elapsed_ms,
        read_only=read_only,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Readable PostgreSQL CLI for this repository.",
    )
    parser.add_argument(
        "--env",
        default=DEFAULT_ENV,
        help="Config env name. Defaults to RUNNING_ENV or 'local'.",
    )
    parser.add_argument(
        "--dsn",
        help="Override postgres DSN instead of loading it from config.",
    )
    parser.add_argument(
        "--schema",
        default=DEFAULT_SCHEMA,
        help="Default schema for table commands. Defaults to public.",
    )
    parser.add_argument(
        "--max-cell-width",
        type=int,
        default=DEFAULT_MAX_CELL_WIDTH,
        help="Maximum rendered width per cell before truncation.",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    tables_parser = subparsers.add_parser("tables", help="List tables.")
    tables_parser.add_argument(
        "--all-schemas",
        action="store_true",
        help="Include non-system schemas instead of only the selected schema.",
    )

    describe_parser = subparsers.add_parser("describe", help="Describe a table.")
    describe_parser.add_argument("table", help="Table name, optionally schema-qualified.")

    preview_parser = subparsers.add_parser("preview", help="Preview rows from a table.")
    preview_parser.add_argument("table", help="Table name, optionally schema-qualified.")
    preview_parser.add_argument(
        "--limit",
        type=int,
        default=DEFAULT_PREVIEW_LIMIT,
        help=f"Number of rows to preview. Defaults to {DEFAULT_PREVIEW_LIMIT}.",
    )
    preview_parser.add_argument(
        "--vertical",
        action="store_true",
        help="Render each row vertically.",
    )

    sql_parser = subparsers.add_parser("sql", help="Execute arbitrary SQL.")
    sql_input_group = sql_parser.add_mutually_exclusive_group(required=True)
    sql_input_group.add_argument(
        "-q",
        "--query",
        help="Inline SQL statement to execute.",
    )
    sql_input_group.add_argument(
        "-f",
        "--file",
        help="Read SQL statement from a file.",
    )
    sql_parser.add_argument(
        "--vertical",
        action="store_true",
        help="Render result rows vertically.",
    )

    return parser


def handle_tables(args: argparse.Namespace, settings: DbSettings) -> int:
    if args.all_schemas:
        sql_text = """
SELECT
    schemaname AS schema_name,
    tablename AS table_name,
    tableowner AS owner,
    hasindexes AS has_indexes,
    rowsecurity AS row_security,
    pg_size_pretty(pg_total_relation_size(format('%%I.%%I', schemaname, tablename))) AS total_size
FROM pg_tables
WHERE schemaname NOT IN ('pg_catalog', 'information_schema')
ORDER BY schemaname, tablename
""".strip()
        params: Sequence[Any] | None = None
    else:
        sql_text = """
SELECT
    schemaname AS schema_name,
    tablename AS table_name,
    tableowner AS owner,
    hasindexes AS has_indexes,
    rowsecurity AS row_security,
    pg_size_pretty(pg_total_relation_size(format('%%I.%%I', schemaname, tablename))) AS total_size
FROM pg_tables
WHERE schemaname = %s
ORDER BY schemaname, tablename
""".strip()
        params = (args.schema,)

    result = execute_sql(
        settings.dsn,
        sql_text,
        params=params,
        read_only=True,
    )
    configured_lookup = {
        table_name: statement_type
        for statement_type, table_name in settings.configured_tables.items()
    }
    rows = [
        {
            "schema": row["schema_name"],
            "table": row["table_name"],
            "owner": row["owner"],
            "size": row["total_size"],
            "indexed": "Y" if row["has_indexes"] else "N",
            "row_security": "Y" if row["row_security"] else "N",
            "configured_as": configured_lookup.get(row["table_name"], ""),
        }
        for row in result.rows
    ]
    print_connection_panel(settings)
    print_sql_panel(sql_text if params is None else f"{sql_text}\n-- params: schema={args.schema}")
    console.print(f"[bold green]Returned {len(rows)} table(s) in {result.elapsed_ms:.1f} ms[/bold green]")
    render_rows("Tables", list(rows[0].keys()) if rows else [], rows, max_width=args.max_cell_width)
    return 0


def handle_describe(args: argparse.Namespace, settings: DbSettings) -> int:
    schema_name, table_name = parse_table_reference(args.table, default_schema=args.schema)
    sql_text = """
SELECT
    ordinal_position AS position,
    column_name,
    data_type,
    is_nullable,
    COALESCE(column_default, '') AS default_value
FROM information_schema.columns
WHERE table_schema = %s
  AND table_name = %s
ORDER BY ordinal_position
""".strip()
    result = execute_sql(
        settings.dsn,
        sql_text,
        params=(schema_name, table_name),
        read_only=True,
    )
    rows = [
        {
            "position": row["position"],
            "column": row["column_name"],
            "type": row["data_type"],
            "nullable": row["is_nullable"],
            "default": row["default_value"],
        }
        for row in result.rows
    ]
    print_connection_panel(settings)
    print_sql_panel(f"{sql_text}\n-- params: schema={schema_name}, table={table_name}")
    console.print(
        f"[bold green]Returned {len(rows)} column(s) in {result.elapsed_ms:.1f} ms[/bold green]"
    )
    render_rows(
        f"Describe {schema_name}.{table_name}",
        ["position", "column", "type", "nullable", "default"],
        rows,
        max_width=args.max_cell_width,
    )
    return 0


def handle_preview(args: argparse.Namespace, settings: DbSettings) -> int:
    schema_name, table_name = parse_table_reference(args.table, default_schema=args.schema)
    statement = sql.SQL("SELECT * FROM {}.{} LIMIT %s").format(
        sql.Identifier(schema_name),
        sql.Identifier(table_name),
    )
    sql_preview = f'SELECT * FROM "{schema_name}"."{table_name}" LIMIT {args.limit}'
    result = execute_sql(
        settings.dsn,
        statement,
        params=(args.limit,),
        read_only=True,
    )
    print_connection_panel(settings)
    print_sql_panel(sql_preview)
    console.print(
        f"[bold green]Returned {result.rowcount} row(s) in {result.elapsed_ms:.1f} ms[/bold green]"
    )
    render_rows(
        f"Preview {schema_name}.{table_name}",
        result.columns,
        result.rows,
        max_width=args.max_cell_width,
        vertical=args.vertical,
    )
    return 0


def read_sql_text(query: str | None, file_path: str | None) -> str:
    if query is not None:
        sql_text = query
    elif file_path is not None:
        sql_text = Path(file_path).read_text(encoding="utf-8")
    else:
        raise ValueError("either query or file_path must be provided")

    normalized = sql_text.strip()
    if not normalized:
        raise ValueError("sql text is empty")
    return normalized


def handle_sql(args: argparse.Namespace, settings: DbSettings) -> int:
    sql_text = read_sql_text(args.query, args.file)
    result = execute_sql(
        settings.dsn,
        sql_text,
        read_only=is_read_only_sql(sql_text),
    )
    print_connection_panel(settings)
    print_sql_panel(sql_text)
    if result.columns:
        console.print(
            f"[bold green]Returned {result.rowcount} row(s) in {result.elapsed_ms:.1f} ms[/bold green]"
        )
        render_rows(
            "SQL Result",
            result.columns,
            result.rows,
            max_width=args.max_cell_width,
            vertical=args.vertical,
        )
    else:
        action = "Read-only statement finished" if result.read_only else "Statement committed"
        console.print(
            Panel.fit(
                f"{action} in {result.elapsed_ms:.1f} ms",
                title="Execution",
                border_style="green",
            )
        )
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    settings = load_db_settings(args.env, args.dsn)

    if args.command == "tables":
        return handle_tables(args, settings)
    if args.command == "describe":
        return handle_describe(args, settings)
    if args.command == "preview":
        return handle_preview(args, settings)
    if args.command == "sql":
        return handle_sql(args, settings)
    parser.error(f"unsupported command: {args.command}")
    return 2


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        console.print(Panel.fit(str(exc), title="Error", border_style="red"))
        raise SystemExit(1) from exc
