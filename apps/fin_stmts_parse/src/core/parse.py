from __future__ import annotations

import os
from typing import Any, Dict, Iterable, List, Optional

from fin_stmts_parse.clients.llm_client import LLMClient
from fin_stmts_parse.src.company_name_resolver import (
    CompanyNameResolver,
    pick_explicit_company_name,
    resolve_unique_company_name,
    extract_company_name_by_rule,
)
from fin_stmts_parse.src.core.contracts import (
    StatementMarkdownDocument,
    normalize_is_consolidated,
    statement_markdown_document_from_item,
)
from fin_stmts_parse.src.excel_financial_parser import ExcelFinancialParser
from fin_stmts_parse.src.image_financial_parser import ImageFinancialProcessor
from fin_stmts_parse.src.pdf_financial_parser import PDFFinancialProcessor


SUPPORTED_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".bmp", ".tiff", ".tif", ".webp"}
SUPPORTED_PDF_EXTENSIONS = {".pdf"}
SUPPORTED_EXCEL_EXTENSIONS = {".xlsx", ".xls"}


class FinancialStatementParseCore:
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        paddle_config = config.get("paddle_ocr", {})
        use_paddle = paddle_config.get("enabled", False)

        llm_config = config.get("llm", {})
        shared_llm_client = LLMClient(llm_config) if llm_config.get("base_url") else None
        self.company_name_resolver = CompanyNameResolver(llm_client=shared_llm_client)

        self.pdf_processor = PDFFinancialProcessor(
            config,
            use_paddle=use_paddle,
            llm_client=shared_llm_client,
        )
        self.image_processor = ImageFinancialProcessor(
            config,
            use_paddle=use_paddle,
            llm_client=shared_llm_client,
        )
        self.excel_parser = ExcelFinancialParser(llm_client=shared_llm_client)

    def parse_local_file(
        self,
        file_path: str,
        *,
        output_dir: Optional[str] = None,
        is_consolidated: Optional[bool] = None,
        report_period: Optional[str] = None,
    ) -> List[StatementMarkdownDocument]:
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"文件不存在: {file_path}")

        file_ext = os.path.splitext(file_path)[1].lower()
        if file_ext in SUPPORTED_PDF_EXTENSIONS:
            items = self.pdf_processor.process_pdf(
                pdf_path=file_path,
                output_dir=output_dir,
                is_consolidated=is_consolidated,
                report_period=report_period,
            )
        elif file_ext in SUPPORTED_IMAGE_EXTENSIONS:
            items = self.image_processor.process_image(
                image_path=file_path,
                output_dir=output_dir,
                is_consolidated=is_consolidated,
                report_period=report_period,
            )
        elif file_ext in SUPPORTED_EXCEL_EXTENSIONS:
            items = self.excel_parser.parse(file_path)
        else:
            raise ValueError(f"不支持的文件格式: {file_ext}")

        resolved_company_name = self._resolve_file_company_name(
            items, allow_llm=file_ext not in SUPPORTED_PDF_EXTENSIONS
        )
        return self._build_documents(
            items,
            source_file_path=file_path,
            default_company_name=resolved_company_name,
        )

    def parse_local_files(
        self,
        file_paths: Iterable[str],
        *,
        output_dir: Optional[str] = None,
        is_consolidated: Optional[bool] = None,
        report_period: Optional[str] = None,
    ) -> List[StatementMarkdownDocument]:
        documents: List[StatementMarkdownDocument] = []
        for file_path in file_paths:
            documents.extend(
                self.parse_local_file(
                    file_path,
                    output_dir=output_dir,
                    is_consolidated=is_consolidated,
                    report_period=report_period,
                )
            )
        return documents

    def _build_documents(
        self,
        items: Iterable[Dict[str, Any]],
        *,
        source_file_path: str,
        default_company_name: str = "",
    ) -> List[StatementMarkdownDocument]:
        documents: List[StatementMarkdownDocument] = []
        default_source_file_name = os.path.basename(source_file_path)

        for item in items:
            document = statement_markdown_document_from_item(
                item,
                default_source_file_path=source_file_path,
                default_source_file_name=default_source_file_name,
            )
            if document is None:
                continue

            content = document.content.strip()
            if not content:
                content = self._render_markdown_from_item(item, document)

            if not content.strip():
                continue

            documents.append(
                StatementMarkdownDocument(
                    table_name=document.table_name,
                    page=document.page,
                    date=document.date,
                    unit=document.unit,
                    company_name=document.company_name or default_company_name,
                    is_consolidated=document.is_consolidated,
                    content=content,
                    source_file_name=document.source_file_name,
                    source_file_path=document.source_file_path,
                )
            )

        return documents

    def _resolve_file_company_name(
        self,
        items: Iterable[Dict[str, Any]],
        *,
        allow_llm: bool = True,
    ) -> str:
        item_list = list(items)
        explicit_candidates = [
            company_name
            for company_name in (
                pick_explicit_company_name(item)
                for item in item_list
            )
            if company_name
        ]
        if len(set(explicit_candidates)) > 1:
            return ""
        explicit_company_name = resolve_unique_company_name(explicit_candidates)
        if explicit_company_name:
            return explicit_company_name
        if not allow_llm:
            return resolve_unique_company_name(
                extract_company_name_by_rule(item.get("Markdown", "")) for item in item_list
            )

        markdown_fragments = []
        for item in item_list:
            if not isinstance(item, dict):
                continue
            markdown = item.get("Markdown")
            if isinstance(markdown, str) and markdown.strip():
                markdown_fragments.append(markdown.strip())

        if not markdown_fragments:
            return ""

        return self.company_name_resolver.extract_from_text(
            "\n\n".join(markdown_fragments),
            source_type="markdown",
        )

    def _render_markdown_from_item(
        self,
        item: Dict[str, Any],
        document: StatementMarkdownDocument,
    ) -> str:
        parsed_data = item.get("数据")
        if not isinstance(parsed_data, dict) or not parsed_data:
            return ""

        lines = [f"## {document.table_name}", ""]
        if document.date and document.date != "N/A":
            lines.extend([document.date, ""])
        if document.unit and document.unit != "N/A":
            lines.extend([f"单位: {document.unit}", ""])

        lines.append(self._render_markdown_table(document.table_name, parsed_data))
        lines.append("")
        return "\n".join(lines).strip()

    def _render_markdown_table(self, table_name: str, parsed_data: Dict[str, Any]) -> str:
        is_balance_sheet = "资产负债表" in table_name
        if is_balance_sheet:
            table_lines = [
                "| 项目 | 年初数 | 期末数 |",
                "| --- | --- | --- |",
            ]
            for item_name, value in parsed_data.items():
                beginning_value = ""
                ending_value = ""
                if isinstance(value, list):
                    if len(value) > 0:
                        beginning_value = self._stringify_cell(value[0])
                    if len(value) > 1:
                        ending_value = self._stringify_cell(value[1])
                table_lines.append(f"| {item_name} | {beginning_value} | {ending_value} |")
            return "\n".join(table_lines)

        table_lines = [
            "| 项目 | 金额 |",
            "| --- | --- |",
        ]
        for item_name, value in parsed_data.items():
            table_lines.append(f"| {item_name} | {self._stringify_cell(value)} |")
        return "\n".join(table_lines)

    @staticmethod
    def _stringify_cell(value: Any) -> str:
        if value in ("", None):
            return ""
        return str(value)


def parse_local_file(
    file_path: str,
    *,
    config: Dict[str, Any],
    output_dir: Optional[str] = None,
    is_consolidated: Optional[bool] = None,
    report_period: Optional[str] = None,
) -> List[StatementMarkdownDocument]:
    return FinancialStatementParseCore(config).parse_local_file(
        file_path,
        output_dir=output_dir,
        is_consolidated=is_consolidated,
        report_period=report_period,
    )


def parse_local_files(
    file_paths: Iterable[str],
    *,
    config: Dict[str, Any],
    output_dir: Optional[str] = None,
    is_consolidated: Optional[bool] = None,
    report_period: Optional[str] = None,
) -> List[StatementMarkdownDocument]:
    return FinancialStatementParseCore(config).parse_local_files(
        file_paths,
        output_dir=output_dir,
        is_consolidated=is_consolidated,
        report_period=report_period,
    )
