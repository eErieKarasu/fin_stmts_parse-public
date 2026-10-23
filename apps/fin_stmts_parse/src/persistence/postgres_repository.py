from __future__ import annotations

import re
from dataclasses import replace
from typing import Any, Dict, Iterable, List

from fin_stmts_parse.src.persistence.contracts import (
    MARKDOWN_REPORT_STATUS,
    FinancialStatementFactRow,
    FinancialStatementFactSource,
)


_VALID_TABLE_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_STATEMENT_TYPES = ("balance", "profit", "cashflow")
_STANDARD_REPORT_STATUSES = ("0", "1")
_TABLE_COLUMN_DEFINITIONS = (
    "session_id varchar NOT NULL",
    "company_name varchar NOT NULL",
    "item_name varchar NOT NULL",
    "fns_cycle varchar NOT NULL",
    "fns_year varchar NOT NULL",
    "report_cycle_type varchar NOT NULL",
    "report_type varchar NOT NULL",
    "begin_amt varchar",
    "end_amt varchar",
    "report_status varchar NOT NULL",
    "stat_date varchar NOT NULL",
    "file_name varchar NOT NULL",
    "extension_field varchar NOT NULL",
    "stat_is_audit varchar NOT NULL",
)


class PostgresFinancialStatementRepository:
    def __init__(self, config: Dict[str, Any] | None = None, logger: Any = None):
        postgres_config = (config or {}).get("postgres", {})
        self.dsn = str(postgres_config.get("dsn") or "").strip()
        table_names = postgres_config.get("table_names")
        if not isinstance(table_names, dict):
            table_names = {}
        self.table_names = {
            statement_type: str(table_names.get(statement_type) or "").strip()
            for statement_type in _STATEMENT_TYPES
        }
        self.logger = logger

    def replace_session_snapshot(
        self,
        session_id: str,
        rows: Iterable[FinancialStatementFactRow],
        *,
        report_status: str | None = None,
        target_sources: Iterable[FinancialStatementFactSource] | None = None,
    ) -> None:
        normalized_session_id = str(session_id or "").strip()
        if not normalized_session_id:
            return
        if not self.dsn:
            raise RuntimeError("postgres.dsn 未配置")

        table_names = self._validated_table_names()
        prepared_rows, replace_targets = self._prepare_rows_and_targets(
            rows,
            report_status=report_status,
            target_sources=target_sources,
        )
        self._validate_standard_rows(prepared_rows)
        if not replace_targets:
            return
        rows_by_statement_type = self._group_rows_by_statement_type(prepared_rows)
        columns = FinancialStatementFactRow.db_columns()
        column_sql = ", ".join(columns)
        placeholders = ", ".join(["%s"] * len(columns))

        with self._connect() as conn:
            with conn.cursor() as cursor:
                self._ensure_tables_exist(cursor, table_names)
                for statement_type, file_name, target_status, report_type in replace_targets:
                    cursor.execute(
                        f"DELETE FROM {table_names[statement_type]} "
                        f"WHERE session_id = %s AND file_name = %s "
                        f"AND report_status = %s AND report_type = %s",
                        (
                            normalized_session_id,
                            file_name,
                            target_status,
                            report_type,
                        ),
                    )
                for statement_type in _STATEMENT_TYPES:
                    statement_rows = rows_by_statement_type[statement_type]
                    if not statement_rows:
                        continue
                    cursor.executemany(
                        f"INSERT INTO {table_names[statement_type]} ({column_sql}) VALUES ({placeholders})",
                        [row.to_db_tuple() for row in statement_rows],
                    )
            conn.commit()

    def replace_file_markdown(
        self,
        *,
        session_id: str,
        file_name: str,
        rows: Iterable[FinancialStatementFactRow],
    ) -> None:
        normalized_session_id = str(session_id or "").strip()
        normalized_file_name = str(file_name or "").strip()
        if not normalized_session_id or not normalized_file_name:
            return
        if not self.dsn:
            raise RuntimeError("postgres.dsn 未配置")

        prepared_rows = list(rows)
        if not prepared_rows:
            return
        self._validate_markdown_rows(
            prepared_rows,
            session_id=normalized_session_id,
            file_name=normalized_file_name,
        )

        table_names = self._validated_table_names()
        rows_by_statement_type = self._group_rows_by_statement_type(prepared_rows)
        columns = FinancialStatementFactRow.db_columns()
        column_sql = ", ".join(columns)
        placeholders = ", ".join(["%s"] * len(columns))
        lock_key = f"{normalized_session_id}\x1f{normalized_file_name}"

        with self._connect() as conn:
            with conn.cursor() as cursor:
                self._ensure_tables_exist(cursor, table_names)
                cursor.execute(
                    "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                    (lock_key,),
                )
                self._ensure_markdown_unique_indexes(cursor, table_names)
                for statement_type in _STATEMENT_TYPES:
                    cursor.execute(
                        f"DELETE FROM {table_names[statement_type]} "
                        f"WHERE session_id = %s AND file_name = %s "
                        f"AND report_status = %s",
                        (
                            normalized_session_id,
                            normalized_file_name,
                            MARKDOWN_REPORT_STATUS,
                        ),
                    )
                for statement_type in _STATEMENT_TYPES:
                    statement_rows = rows_by_statement_type[statement_type]
                    if not statement_rows:
                        continue
                    cursor.executemany(
                        f"INSERT INTO {table_names[statement_type]} "
                        f"({column_sql}) VALUES ({placeholders})",
                        [row.to_db_tuple() for row in statement_rows],
                    )
            conn.commit()

    def _prepare_rows_and_targets(
        self,
        rows: Iterable[FinancialStatementFactRow],
        *,
        report_status: str | None,
        target_sources: Iterable[FinancialStatementFactSource] | None = None,
    ) -> tuple[List[FinancialStatementFactRow], List[tuple[str, str, str, str]]]:
        prepared: List[FinancialStatementFactRow] = []
        group_to_name: dict[str, str] = {}
        used_names: set[str] = set()

        for index, row in enumerate(rows):
            group_key = row.source_group_key or f"__row_{index}"
            if group_key not in group_to_name:
                group_to_name[group_key] = self._pick_unique_file_name(
                    row.file_name,
                    used_names,
                )
            prepared.append(
                replace(
                    row,
                    file_name=group_to_name[group_key],
                )
            )

        replace_targets = self._resolve_standard_replace_targets(
            rows=prepared,
            group_to_name=group_to_name,
            used_names=used_names,
            report_status=report_status,
            target_sources=target_sources,
        )
        return prepared, replace_targets

    @staticmethod
    def _ensure_tables_exist(cursor: Any, table_names: Dict[str, str]) -> None:
        column_sql = ", ".join(_TABLE_COLUMN_DEFINITIONS)
        for statement_type in _STATEMENT_TYPES:
            table_name = table_names[statement_type]
            cursor.execute(
                f"CREATE TABLE IF NOT EXISTS {table_name} ({column_sql})",
            )
            # Keep None/""/"0.0" distinct in PostgreSQL by allowing NULL in amount columns.
            cursor.execute(
                f"ALTER TABLE {table_name} ALTER COLUMN begin_amt DROP NOT NULL",
            )
            cursor.execute(
                f"ALTER TABLE {table_name} ALTER COLUMN end_amt DROP NOT NULL",
            )
            cursor.execute(
                f"CREATE INDEX IF NOT EXISTS idx_{table_name}_session_id "
                f"ON {table_name} (session_id)",
            )
            cursor.execute(
                f"CREATE INDEX IF NOT EXISTS idx_{table_name}_session_id_file_name "
                f"ON {table_name} (session_id, file_name)",
            )
            cursor.execute(
                f"CREATE INDEX IF NOT EXISTS idx_{table_name}_snapshot "
                f"ON {table_name} "
                f"(session_id, file_name, report_status, report_type)",
            )

    @staticmethod
    def _ensure_markdown_unique_indexes(
        cursor: Any,
        table_names: Dict[str, str],
    ) -> None:
        for statement_type in _STATEMENT_TYPES:
            table_name = table_names[statement_type]
            cursor.execute(
                f"WITH ranked AS ("
                f"SELECT ctid, ROW_NUMBER() OVER ("
                f"PARTITION BY session_id, file_name, report_status, report_type "
                f"ORDER BY stat_date DESC, ctid DESC"
                f") AS row_number "
                f"FROM {table_name} WHERE report_status = %s"
                f") "
                f"DELETE FROM {table_name} AS target USING ranked "
                f"WHERE target.ctid = ranked.ctid AND ranked.row_number > 1",
                (MARKDOWN_REPORT_STATUS,),
            )
            cursor.execute(
                f"CREATE UNIQUE INDEX IF NOT EXISTS "
                f"ux_{table_name}_markdown "
                f"ON {table_name} "
                f"(session_id, file_name, report_status, report_type) "
                f"WHERE report_status = '{MARKDOWN_REPORT_STATUS}'",
            )

    @staticmethod
    def _validate_standard_rows(
        rows: Iterable[FinancialStatementFactRow],
    ) -> None:
        for row in rows:
            if row.report_status not in _STANDARD_REPORT_STATUSES:
                raise ValueError(
                    "标准科目行 report_status 必须为 0 或 1"
                )

    @staticmethod
    def _validate_markdown_rows(
        rows: Iterable[FinancialStatementFactRow],
        *,
        session_id: str,
        file_name: str,
    ) -> None:
        seen_groups: set[tuple[str, str]] = set()
        for row in rows:
            if row.session_id != session_id:
                raise ValueError("Markdown 行 session_id 与替换目标不一致")
            if row.file_name != file_name:
                raise ValueError("Markdown 行 file_name 与替换目标不一致")
            if row.report_status != MARKDOWN_REPORT_STATUS:
                raise ValueError(
                    f"Markdown 行 report_status 必须为 {MARKDOWN_REPORT_STATUS}"
                )
            statement_type = str(row.statement_type or "").strip()
            if statement_type not in _STATEMENT_TYPES:
                raise ValueError(f"不支持的 statement_type: {statement_type}")
            group_key = (statement_type, str(row.report_type or "").strip())
            if group_key in seen_groups:
                raise ValueError(
                    "同一物理表和 report_type 只能保存一条 Markdown"
                )
            seen_groups.add(group_key)

    @staticmethod
    def _group_rows_by_statement_type(
        rows: Iterable[FinancialStatementFactRow],
    ) -> Dict[str, List[FinancialStatementFactRow]]:
        grouped_rows: Dict[str, List[FinancialStatementFactRow]] = {
            statement_type: [] for statement_type in _STATEMENT_TYPES
        }
        for row in rows:
            statement_type = str(row.statement_type or "").strip()
            if statement_type not in grouped_rows:
                raise ValueError(f"不支持的 statement_type: {statement_type}")
            grouped_rows[statement_type].append(row)
        return grouped_rows

    @staticmethod
    def _pick_unique_file_name(file_name: str, used_names: set[str]) -> str:
        candidate = str(file_name or "").strip()
        if not candidate:
            return ""
        if candidate not in used_names:
            used_names.add(candidate)
            return candidate

        match = re.match(r"^(?P<stem>.*?)(?P<suffix>\.[^.]+)?$", candidate)
        stem = (match.group("stem") if match else candidate) or candidate
        suffix = match.group("suffix") if match and match.group("suffix") else ""

        counter = 1
        while True:
            deduped = f"{stem}_{counter}{suffix}"
            if deduped not in used_names:
                used_names.add(deduped)
                return deduped
            counter += 1

    def _resolve_standard_replace_targets(
        self,
        *,
        rows: Iterable[FinancialStatementFactRow],
        group_to_name: Dict[str, str],
        used_names: set[str],
        report_status: str | None,
        target_sources: Iterable[FinancialStatementFactSource] | None,
    ) -> List[tuple[str, str, str, str]]:
        replace_targets: List[tuple[str, str, str, str]] = []
        seen_targets: set[tuple[str, str, str, str]] = set()

        prepared_rows = list(rows)
        row_statuses = {
            str(row.report_status or "").strip()
            for row in prepared_rows
        }
        normalized_report_status = str(report_status or "").strip()
        if normalized_report_status and normalized_report_status not in _STANDARD_REPORT_STATUSES:
            raise ValueError("report_status 必须为 0 或 1")
        if normalized_report_status and any(
            row_status != normalized_report_status for row_status in row_statuses
        ):
            raise ValueError("标准科目行 report_status 与替换目标不一致")

        for row in prepared_rows:
            self._append_unique_standard_replace_target(
                replace_targets,
                seen_targets,
                statement_type=row.statement_type,
                file_name=row.file_name,
                report_status=row.report_status,
                report_type=row.report_type,
            )

        if target_sources is None:
            return replace_targets

        if not normalized_report_status:
            if len(row_statuses) == 1:
                normalized_report_status = next(iter(row_statuses))
            else:
                raise ValueError(
                    "target_sources 非空时必须显式传入 report_status"
                )

        for index, source in enumerate(target_sources):
            group_key = str(getattr(source, "source_group_key", "") or f"__source_{index}")
            if group_key not in group_to_name:
                group_to_name[group_key] = self._pick_unique_file_name(
                    self._extract_target_source_file_name(source),
                    used_names,
                )
            mapped_result = getattr(source, "mapped_result", None)
            self._append_unique_standard_replace_target(
                replace_targets,
                seen_targets,
                statement_type=getattr(mapped_result, "statement_type", ""),
                file_name=group_to_name[group_key],
                report_status=normalized_report_status,
                report_type=(
                    "2"
                    if bool(getattr(mapped_result, "is_consolidated", False))
                    else "1"
                ),
            )

        return replace_targets

    @staticmethod
    def _append_unique_standard_replace_target(
        replace_targets: List[tuple[str, str, str, str]],
        seen_targets: set[tuple[str, str, str, str]],
        *,
        statement_type: str,
        file_name: str,
        report_status: str,
        report_type: str,
    ) -> None:
        normalized_statement_type = str(statement_type or "").strip()
        if normalized_statement_type not in _STATEMENT_TYPES:
            raise ValueError(f"不支持的 statement_type: {normalized_statement_type}")
        normalized_file_name = str(file_name or "").strip()
        normalized_report_status = str(report_status or "").strip()
        if normalized_report_status not in _STANDARD_REPORT_STATUSES:
            raise ValueError("标准科目行 report_status 必须为 0 或 1")
        normalized_report_type = str(report_type or "").strip()
        if not normalized_report_type:
            raise ValueError("report_type 不能为空")
        target = (
            normalized_statement_type,
            normalized_file_name,
            normalized_report_status,
            normalized_report_type,
        )
        if target in seen_targets:
            return
        seen_targets.add(target)
        replace_targets.append(target)

    @staticmethod
    def _extract_target_source_file_name(source: Any) -> str:
        file_name = str(getattr(source, "file_name", "") or "").strip()
        if file_name:
            return file_name
        mapped_result = getattr(source, "mapped_result", None)
        return str(getattr(mapped_result, "source_file_name", "") or "").strip()

    def _validated_table_names(self) -> Dict[str, str]:
        validated_table_names: Dict[str, str] = {}
        for statement_type in _STATEMENT_TYPES:
            table_name = self.table_names[statement_type]
            if not table_name:
                raise ValueError(f"缺少 postgres.table_names.{statement_type} 配置")
            if not _VALID_TABLE_NAME.fullmatch(table_name):
                raise ValueError(
                    f"非法的 postgres.table_names.{statement_type}: {table_name}"
                )
            validated_table_names[statement_type] = table_name
        return validated_table_names

    def _connect(self) -> Any:
        import psycopg

        return psycopg.connect(self.dsn)
