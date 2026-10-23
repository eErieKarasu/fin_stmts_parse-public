import unittest
from unittest.mock import Mock

from apps.fin_stmts_parse.src.core.contracts import StatementMarkdownDocument
from apps.fin_stmts_parse.src.persistence.contracts import MARKDOWN_REPORT_STATUS
from apps.fin_stmts_parse.src.persistence.markdown_fact_builder import (
    MarkdownFinancialStatementFactBuilder,
)


class MarkdownFinancialStatementFactBuilderTest(unittest.TestCase):
    def setUp(self) -> None:
        self.logger = Mock()
        self.builder = MarkdownFinancialStatementFactBuilder(logger=self.logger)

    def test_build_rows_joins_pages_in_page_order_and_keeps_unknown_last(self) -> None:
        rows = self.builder.build_rows(
            session_id="session-1",
            company_name="测试公司",
            file_name="demo.pdf",
            documents=[
                self._document(page=24, content="page-24"),
                self._document(page=None, content="page-unknown"),
                self._document(page=23, content="page-23-first"),
                self._document(page=23, content="page-23-second"),
            ],
        )

        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row.statement_type, "balance")
        self.assertEqual(row.report_type, "2")
        self.assertEqual(row.report_status, MARKDOWN_REPORT_STATUS)
        self.assertEqual(row.item_name, "合并资产负债表")
        self.assertEqual(row.fns_year, "2024")
        self.assertEqual(row.fns_cycle, "12")
        self.assertEqual(row.report_cycle_type, "YEAR")
        self.assertIsNone(row.begin_amt)
        self.assertIsNone(row.end_amt)
        self.assertEqual(
            row.extension_field,
            "<!-- page: 23 -->\n\npage-23-first\n\n"
            "<!-- page: 23 -->\n\npage-23-second\n\n"
            "<!-- page: 24 -->\n\npage-24\n\n"
            "<!-- page: unknown -->\n\npage-unknown",
        )

    def test_build_rows_separates_consolidated_and_standalone_documents(self) -> None:
        rows = self.builder.build_rows(
            session_id="session-1",
            company_name="测试公司",
            file_name="demo.pdf",
            documents=[
                self._document(
                    page=1,
                    content="consolidated",
                    is_consolidated=True,
                ),
                self._document(
                    page=2,
                    content="standalone",
                    is_consolidated=False,
                ),
            ],
        )

        self.assertEqual(len(rows), 2)
        rows_by_report_type = {row.report_type: row for row in rows}
        self.assertEqual(rows_by_report_type["2"].item_name, "合并资产负债表")
        self.assertEqual(rows_by_report_type["1"].item_name, "资产负债表")
        self.assertIn("consolidated", rows_by_report_type["2"].extension_field)
        self.assertIn("standalone", rows_by_report_type["1"].extension_field)

    def test_build_rows_uses_first_sorted_valid_date_and_warns_on_conflict(self) -> None:
        rows = self.builder.build_rows(
            session_id="session-1",
            company_name="测试公司",
            file_name="demo.pdf",
            documents=[
                self._document(page=2, content="second", date="202412"),
                self._document(page=1, content="first", date="202312"),
            ],
        )

        self.assertEqual(rows[0].fns_year, "2023")
        self.logger.warning.assert_called_once()

    def test_build_rows_normalizes_html_tables_before_page_join(self) -> None:
        rows = self.builder.build_rows(
            session_id="session-1",
            company_name="测试公司",
            file_name="demo.pdf",
            documents=[
                self._document(
                    page=1,
                    content=(
                        "# 资产负债表\n\n"
                        "<table><tr><th>项目</th><th>期末余额</th></tr>"
                        "<tr><td>货币资金</td><td>100</td></tr></table>"
                    ),
                )
            ],
        )

        self.assertNotIn("<table", rows[0].extension_field.lower())
        self.assertIn("| 项目 | 期末余额 |", rows[0].extension_field)
        self.assertIn("| 货币资金 | 100 |", rows[0].extension_field)
        self.assertTrue(rows[0].extension_field.startswith("<!-- page: 1 -->"))

    @staticmethod
    def _document(
        *,
        page,
        content: str,
        date: str = "202412",
        is_consolidated: bool = True,
    ) -> StatementMarkdownDocument:
        return StatementMarkdownDocument(
            table_name=(
                "合并资产负债表"
                if is_consolidated
                else "资产负债表"
            ),
            table_type="balance",
            page=page,
            date=date,
            company_name="测试公司",
            is_consolidated=is_consolidated,
            content=content,
        )


if __name__ == "__main__":
    unittest.main()
