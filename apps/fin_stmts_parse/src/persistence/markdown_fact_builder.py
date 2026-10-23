from __future__ import annotations

from collections import defaultdict
from typing import Any, Dict, Iterable, List, Tuple

from fin_stmts_parse.src.core.contracts import (
    StatementMarkdownDocument,
    resolve_statement_type,
)
from fin_stmts_parse.src.persistence.contracts import (
    MARKDOWN_REPORT_STATUS,
    FinancialStatementFactRow,
)
from fin_stmts_parse.src.persistence.fact_builder import FinancialStatementFactBuilder
from fin_stmts_parse.src.persistence.markdown_content_normalizer import (
    MarkdownStorageContentNormalizer,
)
from fin_stmts_parse.utils.logger import logger as default_logger


_STATEMENT_TYPES = ("balance", "profit", "cashflow")
_TABLE_NAMES = {
    ("balance", "1"): "资产负债表",
    ("balance", "2"): "合并资产负债表",
    ("profit", "1"): "利润表",
    ("profit", "2"): "合并利润表",
    ("cashflow", "1"): "现金流量表",
    ("cashflow", "2"): "合并现金流量表",
}


class MarkdownFinancialStatementFactBuilder:
    def __init__(
        self,
        logger: Any = None,
        content_normalizer: MarkdownStorageContentNormalizer | None = None,
    ) -> None:
        self.logger = logger or default_logger
        self.content_normalizer = (
            content_normalizer or MarkdownStorageContentNormalizer()
        )

    def build_rows(
        self,
        *,
        session_id: str,
        company_name: str,
        file_name: str,
        documents: Iterable[StatementMarkdownDocument],
    ) -> List[FinancialStatementFactRow]:
        normalized_session_id = str(session_id or "").strip()
        normalized_file_name = str(file_name or "").strip()
        if not normalized_session_id or not normalized_file_name:
            return []

        groups: Dict[
            Tuple[str, str],
            List[Tuple[int, StatementMarkdownDocument]],
        ] = defaultdict(list)
        for index, document in enumerate(documents):
            if not isinstance(
                getattr(document, "content", None),
                str,
            ):
                continue
            if not document.content.strip():
                continue

            statement_type = self._resolve_statement_type(document)
            if statement_type not in _STATEMENT_TYPES:
                self.logger.warning(
                    "跳过无法路由的 Markdown 报表: "
                    f"table_name={document.table_name}, table_type={document.table_type}"
                )
                continue
            report_type = "2" if document.is_consolidated else "1"
            groups[(statement_type, report_type)].append((index, document))

        stat_date = FinancialStatementFactBuilder._generate_stat_date()
        rows: List[FinancialStatementFactRow] = []
        for (statement_type, report_type), indexed_documents in groups.items():
            sorted_documents = sorted(
                indexed_documents,
                key=self._document_sort_key,
            )
            date = self._pick_group_date(
                sorted_documents,
                statement_type=statement_type,
                report_type=report_type,
            )
            fns_year, fns_cycle, report_cycle_type = (
                FinancialStatementFactBuilder._split_statement_date(date)
            )
            rows.append(
                FinancialStatementFactRow(
                    session_id=normalized_session_id,
                    company_name=str(company_name or "").strip(),
                    item_name=_TABLE_NAMES[(statement_type, report_type)],
                    fns_cycle=fns_cycle,
                    fns_year=fns_year,
                    report_cycle_type=report_cycle_type,
                    report_type=report_type,
                    begin_amt=None,
                    end_amt=None,
                    report_status=MARKDOWN_REPORT_STATUS,
                    stat_date=stat_date,
                    file_name=normalized_file_name,
                    extension_field=self._join_markdown(sorted_documents),
                    stat_is_audit="",
                    statement_type=statement_type,
                    source_group_key=f"{statement_type}:{report_type}",
                )
            )
        return rows

    @staticmethod
    def _resolve_statement_type(document: StatementMarkdownDocument) -> str:
        statement_type = str(document.table_type or "").strip()
        if statement_type:
            return statement_type
        try:
            statement_type, _ = resolve_statement_type(
                document.table_name,
                document.is_consolidated,
            )
        except ValueError:
            return ""
        return statement_type

    @staticmethod
    def _document_sort_key(
        indexed_document: Tuple[int, StatementMarkdownDocument],
    ) -> Tuple[bool, int, int]:
        index, document = indexed_document
        page = document.page
        return page is None, page if page is not None else 0, index

    def _pick_group_date(
        self,
        indexed_documents: List[Tuple[int, StatementMarkdownDocument]],
        *,
        statement_type: str,
        report_type: str,
    ) -> str:
        valid_dates: List[str] = []
        for _, document in indexed_documents:
            date = str(document.date or "").strip()
            if FinancialStatementFactBuilder._split_statement_date(date)[0]:
                valid_dates.append(date)

        unique_dates = list(dict.fromkeys(valid_dates))
        if len(unique_dates) > 1:
            self.logger.warning(
                "同一 Markdown 报表分组存在多个日期，使用排序后首个有效日期: "
                f"statement_type={statement_type}, report_type={report_type}, "
                f"dates={unique_dates}"
            )
        return unique_dates[0] if unique_dates else ""

    def _join_markdown(
        self,
        indexed_documents: List[Tuple[int, StatementMarkdownDocument]],
    ) -> str:
        segments: List[str] = []
        for _, document in indexed_documents:
            page_label = str(document.page) if document.page is not None else "unknown"
            normalized_content = self.content_normalizer.normalize(
                document.content.strip()
            )
            segments.append(
                f"<!-- page: {page_label} -->\n\n{normalized_content.strip()}"
            )
        return "\n\n".join(segments)
