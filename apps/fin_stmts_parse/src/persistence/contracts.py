from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from fin_stmts_parse.src.core.contracts import MappedStatementResult


MARKDOWN_REPORT_STATUS = "-1"


@dataclass(frozen=True)
class FinancialStatementFactSource:
    mapped_result: MappedStatementResult
    company_name: str = ""
    file_name: str = ""
    source_group_key: str = ""


@dataclass(frozen=True)
class FinancialStatementFactRow:
    session_id: str
    company_name: str
    item_name: str
    fns_cycle: str
    fns_year: str
    report_cycle_type: str
    report_type: str
    begin_amt: Optional[str]
    end_amt: Optional[str]
    report_status: str
    stat_date: str
    file_name: str
    extension_field: str
    stat_is_audit: str
    statement_type: str = field(default="", repr=False, compare=False)
    source_group_key: str = field(default="", repr=False, compare=False)

    @classmethod
    def db_columns(cls) -> tuple[str, ...]:
        return (
            "session_id",
            "company_name",
            "item_name",
            "fns_cycle",
            "fns_year",
            "report_cycle_type",
            "report_type",
            "begin_amt",
            "end_amt",
            "report_status",
            "stat_date",
            "file_name",
            "extension_field",
            "stat_is_audit",
        )

    def to_db_tuple(self) -> tuple[object, ...]:
        return (
            self.session_id,
            self.company_name,
            self.item_name,
            self.fns_cycle,
            self.fns_year,
            self.report_cycle_type,
            self.report_type,
            self.begin_amt,
            self.end_amt,
            self.report_status,
            self.stat_date,
            self.file_name,
            self.extension_field,
            self.stat_is_audit,
        )
