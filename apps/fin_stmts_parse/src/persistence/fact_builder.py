from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, Iterable, List, Optional

from fin_stmts_parse.src.core.contracts import resolve_statement_period
from fin_stmts_parse.src.persistence.contracts import (
    FinancialStatementFactRow,
    FinancialStatementFactSource,
)


class FinancialStatementFactBuilder:
    _CYCLE_BY_MONTH = {
        3: "QUATER",
        6: "INTERIM",
        9: "QUATER",
        12: "YEAR",
    }

    def build_rows(
        self,
        *,
        session_id: str,
        report_status: str,
        sources: Iterable[FinancialStatementFactSource],
    ) -> List[FinancialStatementFactRow]:
        normalized_session_id = str(session_id or "").strip()
        if not normalized_session_id:
            return []

        normalized_stat_date = self._generate_stat_date()
        normalized_report_status = str(report_status or "").strip()
        rows: List[FinancialStatementFactRow] = []

        for source in sources:
            mapped_result = source.mapped_result
            company_name = str(source.company_name or "").strip()
            file_name = str(source.file_name or mapped_result.source_file_name or "").strip()
            fns_year, fns_cycle, report_cycle_type = self._split_statement_date(mapped_result.date)
            report_type = "2" if mapped_result.is_consolidated else "1"

            for code, value in mapped_result.canonical_data_full.items():
                item_name = str(mapped_result.canonical_labels.get(code) or "").strip()
                if not item_name:
                    continue

                begin_amt, end_amt = self._extract_amounts(
                    statement_type=mapped_result.statement_type,
                    value=value,
                )
                rows.append(
                    FinancialStatementFactRow(
                        session_id=normalized_session_id,
                        company_name=company_name,
                        item_name=item_name,
                        fns_cycle=fns_cycle,
                        fns_year=fns_year,
                        report_cycle_type=report_cycle_type,
                        report_type=report_type,
                        begin_amt=begin_amt,
                        end_amt=end_amt,
                        report_status=normalized_report_status,
                        stat_date=normalized_stat_date,
                        file_name=file_name,
                        extension_field="",
                        stat_is_audit="",
                        statement_type=mapped_result.statement_type,
                        source_group_key=str(source.source_group_key or file_name),
                    )
                )

        return rows

    @staticmethod
    def _generate_stat_date() -> str:
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    @staticmethod
    def _split_statement_date(value: Any) -> tuple[str, str, str]:
        normalized = str(value or "").strip()
        if len(normalized) == 6 and normalized.isdigit():
            year = normalized[:4]
            month = int(normalized[4:])
            period = resolve_statement_period(normalized)
            return year, str(month), FinancialStatementFactBuilder._resolve_cycle(month, period)
        if len(normalized) == 4 and normalized.isdigit():
            return normalized, "12", "YEAR"
        return "", "", ""

    @classmethod
    def _resolve_cycle(cls, month: int, period: str = "") -> str:
        if month < 1 or month > 12:
            return ""
        period_to_cycle = {
            "YEAR": "YEAR",
            "INTERIM": "INTERIM",
            "QUATER": "QUATER",
            "MONTH": "MONTH",
        }
        if period in period_to_cycle:
            return period_to_cycle[period]
        return cls._CYCLE_BY_MONTH.get(month, "MONTH")

    def _extract_amounts(
        self,
        *,
        statement_type: str,
        value: Any,
    ) -> tuple[Optional[str], Optional[str]]:
        if statement_type in {"balance", "profit", "cashflow"}:
            if isinstance(value, list):
                begin_amt = self._stringify_amount(value[0] if len(value) > 0 else "")
                end_amt = self._stringify_amount(value[1] if len(value) > 1 else "")
                return begin_amt, end_amt
            if value is None:
                return None, None
            return "", self._stringify_amount(value)
        return "", self._stringify_amount(value)

    @staticmethod
    def _stringify_amount(value: Any) -> Optional[str]:
        if isinstance(value, Decimal):
            return str(value)
        if value == "":
            return ""
        if value is None:
            return None
        return str(value)
