import unittest
from unittest import mock

from apps.fin_stmts_parse.src.core.parse import FinancialStatementParseCore


class FinancialStatementParseCoreTest(unittest.TestCase):
    def setUp(self) -> None:
        self.core = FinancialStatementParseCore.__new__(FinancialStatementParseCore)
        self.core.pdf_processor = mock.Mock()
        self.core.image_processor = mock.Mock()
        self.core.excel_parser = mock.Mock()
        self.core.company_name_resolver = mock.Mock()

    def test_parse_local_file_returns_standard_markdown_document(self) -> None:
        self.core.pdf_processor.process_pdf.return_value = [
            {
                "表名": "资产负债表",
                "page": 12,
                "日期": "202412",
                "company_name": "测试公司",
                "合并": "否",
                "Markdown": "# 资产负债表\n\n| 项目 | 期末余额 |\n| --- | --- |\n| 货币资金 | 100 |",
            }
        ]
        self.core.company_name_resolver.extract_from_text.return_value = ""

        with mock.patch("apps.fin_stmts_parse.src.core.parse.os.path.exists", return_value=True):
            documents = self.core.parse_local_file("/tmp/demo.pdf", is_consolidated=False)

        self.assertEqual(len(documents), 1)
        self.assertEqual(documents[0].company_name, "测试公司")
        self.assertEqual(
            documents[0].to_dict(),
            {
                "table_name": "资产负债表",
                "table_type": "balance",
                "page": 12,
                "date": "202412",
                "period": "YEAR",
                "is_consolidated": False,
                "content": "# 资产负债表\n\n| 项目 | 期末余额 |\n| --- | --- |\n| 货币资金 | 100 |",
                "source_file_name": "demo.pdf",
                "source_file_path": "/tmp/demo.pdf",
            },
        )
        self.assertEqual(documents[0].period, "YEAR")
        self.assertEqual(documents[0].table_type, "balance")

    def test_parse_local_file_renders_excel_data_to_markdown_when_content_missing(self) -> None:
        self.core.excel_parser.parse.return_value = [
            {
                "表名": "利润表",
                "日期": "202412",
                "单位": "元",
                "合并": "否",
                "数据": {
                    "营业总收入": 1000.0,
                    "营业成本": 700.0,
                },
            }
        ]
        self.core.company_name_resolver.extract_from_text.return_value = ""

        with mock.patch("apps.fin_stmts_parse.src.core.parse.os.path.exists", return_value=True):
            documents = self.core.parse_local_file("/tmp/demo.xlsx")

        self.assertEqual(len(documents), 1)
        self.assertIn("| 项目 | 金额 |", documents[0].content)
        self.assertIn("| 营业总收入 | 1000.0 |", documents[0].content)

    def test_parse_local_file_uses_markdown_company_name_fallback(self) -> None:
        self.core.pdf_processor.process_pdf.return_value = [
            {
                "表名": "利润表",
                "日期": "202412",
                "合并": "否",
                "Markdown": "# 利润表\n\n**编制单位：** 规则兜底公司\n\n| 项目 | 金额 |\n| --- | --- |\n| 营业收入 | 100 |",
            }
        ]
        self.core.company_name_resolver.extract_from_text.return_value = "规则兜底公司"

        with mock.patch("apps.fin_stmts_parse.src.core.parse.os.path.exists", return_value=True):
            documents = self.core.parse_local_file("/tmp/fallback.pdf")

        self.assertEqual(len(documents), 1)
        self.assertEqual(documents[0].company_name, "规则兜底公司")
        self.core.company_name_resolver.extract_from_text.assert_not_called()


if __name__ == "__main__":
    unittest.main()
