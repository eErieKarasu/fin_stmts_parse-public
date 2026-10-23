import tempfile
import unittest
from pathlib import Path
from unittest import mock

from openpyxl import Workbook

from apps.fin_stmts_parse.src.base_financial_processor import BaseFinancialProcessor
from apps.fin_stmts_parse.src.company_name_resolver import CompanyNameResolver
from apps.fin_stmts_parse.src.excel_financial_parser import ExcelFinancialParser
from apps.fin_stmts_parse.src.image_financial_parser import ImageFinancialProcessor
from apps.fin_stmts_parse.src.markdown_table_extractor import MarkdownTableExtractor
from apps.fin_stmts_parse.src.pdf_financial_parser import PDFFinancialProcessor
from apps.fin_stmts_parse.src.statement_metadata_resolver import StatementMetadataResolver


DUAL_ENTITY_PROFIT_MARKDOWN = """
| 项目 | 注释号 | 行次 | 2023年度 |  | 2022年度 |  |
| --- | --- | --- | --- | --- | --- | --- |
|  |  |  | 合并 | 母公司 | 合并 | 母公司 |
| 营业收入 | 五(四十二) | 1 | 3,288,635,968.37 | 104,263,029.69 | 2,621,747,215.51 | 99,038,216.36 |
| 净利润 |  | 25 | 108,893,977.91 | 150,541,108.62 | 110,488,373.82 | 22,988,339.11 |
""".strip()


def build_processor(processor_cls, *, markdown_metadata=None):
    # 运行真实构造函数装配组件，仅隔离模型客户端的创建。
    with mock.patch.object(BaseFinancialProcessor, "_initialize_openai_client"):
        processor = processor_cls(config={})
    if markdown_metadata is not None:
        processor.page_processor.metadata_resolver = StatementMetadataResolver(
            date_parser=processor.page_processor.table_extractor.parse_date_from_header,
            markdown_metadata_extractor=mock.Mock(return_value=markdown_metadata),
            logger=mock.Mock(),
        )
    return processor


class ImageFinancialProcessorCompanyNameTest(unittest.TestCase):
    def _build_processor(self):
        processor = build_processor(
            ImageFinancialProcessor, markdown_metadata={"日期": "202412", "单位": "元"}
        )
        processor.logger = mock.Mock()
        processor.page_processor.analyze_page_content = mock.Mock(
            return_value={"has_target_table": True, "table_type": "资产负债表"}
        )
        processor.page_processor.remove_watermark_from_file = mock.Mock(return_value="/tmp/demo.png")
        processor.page_processor.correct_image_orientation = mock.Mock(return_value="/tmp/demo.png")
        processor.page_processor._extract_table_content = mock.Mock(
            return_value=(
                "# 资产负债表\n\n**编制单位：** 规则公司\n\n| 项目 | 金额 |\n| --- | --- |\n| 货币资金 | 100 |",
                "mock",
            )
        )
        processor.page_processor._parse_markdown_table_to_dict = mock.Mock(return_value={"货币资金": 100})
        processor.page_processor.is_parsing_result_valid = mock.Mock(return_value=True)
        return processor

    def test_process_image_sets_company_name_from_vlm(self):
        processor = self._build_processor()
        processor.page_processor.extract_company_name_from_image = mock.Mock(return_value="视觉公司")
        processor.page_processor.company_name_resolver = mock.Mock()
        processor.page_processor.company_name_resolver.extract_from_text.return_value = ""

        with mock.patch("apps.fin_stmts_parse.src.image_financial_parser.os.path.exists", return_value=True):
            result = processor.process_image("/tmp/demo.png")

        self.assertEqual(result[0]["company_name"], "视觉公司")

    def test_process_image_falls_back_to_markdown_rules(self):
        processor = self._build_processor()
        processor.page_processor.extract_company_name_from_image = mock.Mock(return_value="")
        processor.page_processor.company_name_resolver = CompanyNameResolver(llm_client=None, logger=mock.Mock())

        with mock.patch("apps.fin_stmts_parse.src.image_financial_parser.os.path.exists", return_value=True):
            result = processor.process_image("/tmp/demo.png")

        self.assertEqual(result[0]["company_name"], "规则公司")

    def _build_dual_entity_processor(self):
        processor = build_processor(
            ImageFinancialProcessor, markdown_metadata={"日期": "202312", "单位": "元"}
        )
        processor.logger = mock.Mock()
        processor.page_processor.table_extractor = MarkdownTableExtractor(logger=mock.Mock(), llm_client=None)
        processor.page_processor.analyze_page_content = mock.Mock(
            return_value={"has_target_table": True, "table_type": "利润表"}
        )
        processor.page_processor.remove_watermark_from_file = mock.Mock(return_value="/tmp/demo.png")
        processor.page_processor.correct_image_orientation = mock.Mock(return_value="/tmp/demo.png")
        processor.page_processor._extract_table_content = mock.Mock(
            return_value=(DUAL_ENTITY_PROFIT_MARKDOWN, "mock")
        )
        processor.page_processor.extract_company_name_from_image = mock.Mock(return_value="视觉公司")
        processor.page_processor.company_name_resolver = mock.Mock()
        processor.page_processor.company_name_resolver.extract_from_text.return_value = ""
        return processor

    def test_process_image_splits_dual_entity_statement(self):
        processor = self._build_dual_entity_processor()

        with mock.patch("apps.fin_stmts_parse.src.image_financial_parser.os.path.exists", return_value=True):
            result = processor.process_image("/tmp/demo.png")

        self.assertEqual([item["表名"] for item in result], ["合并利润表", "利润表"])
        self.assertEqual([item["合并"] for item in result], ["是", "否"])
        self.assertEqual(result[0]["数据"]["营业收入"], [2621747215.51, 3288635968.37])
        self.assertEqual(result[1]["数据"]["营业收入"], [99038216.36, 104263029.69])
        self.assertIn("| 营业收入 | 2621747215.51 | 3288635968.37 |", result[0]["Markdown"])
        self.assertNotIn("104263029.69", result[0]["Markdown"])
        self.assertIn("| 营业收入 | 99038216.36 | 104263029.69 |", result[1]["Markdown"])
        self.assertNotIn("3288635968.37", result[1]["Markdown"])

    def test_process_image_filters_dual_entity_statement_by_consolidation_flag(self):
        with mock.patch("apps.fin_stmts_parse.src.image_financial_parser.os.path.exists", return_value=True):
            consolidated = self._build_dual_entity_processor().process_image(
                "/tmp/demo.png",
                is_consolidated=True,
            )
            standalone = self._build_dual_entity_processor().process_image(
                "/tmp/demo.png",
                is_consolidated=False,
            )

        self.assertEqual([item["表名"] for item in consolidated], ["合并利润表"])
        self.assertEqual([item["表名"] for item in standalone], ["利润表"])


class ExcelFinancialParserCompanyNameTest(unittest.TestCase):
    def test_extract_company_name_prefers_llm_result(self):
        parser = ExcelFinancialParser.__new__(ExcelFinancialParser)
        parser.logger = mock.Mock()
        parser.company_name_resolver = mock.Mock()
        parser.company_name_resolver.extract_from_text.return_value = "大模型公司"
        parser._extract_company_name_from_cells = mock.Mock(return_value="")
        parser._build_sheet_preview_rows_text = mock.Mock(
            return_value=["第0行: ['编制单位：规则公司']"]
        )

        company_name = parser._extract_company_name("/tmp/demo.xlsx", "资产负债表")

        self.assertEqual(company_name, "大模型公司")

    def test_extract_company_name_falls_back_to_rules(self):
        parser = ExcelFinancialParser.__new__(ExcelFinancialParser)
        parser.logger = mock.Mock()
        parser.company_name_resolver = mock.Mock()
        parser.company_name_resolver.extract_from_text.return_value = ""
        parser._extract_company_name_from_cells = mock.Mock(return_value="")
        parser._build_sheet_preview_rows_text = mock.Mock(
            return_value=["第0行: ['编制单位：规则公司']"]
        )

        company_name = parser._extract_company_name("/tmp/demo.xlsx", "资产负债表")

        self.assertEqual(company_name, "规则公司")

    def test_extract_company_name_directly_from_labeled_cell(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            file_path = Path(temp_dir) / "company_name.xlsx"
            workbook = Workbook()
            worksheet = workbook.active
            worksheet.title = "利润表"
            worksheet.append(["利润表"])
            worksheet.append(["财会年企02表"])
            worksheet.append([
                "编制单位：遂宁市鹏安投资有限公司",
                "2026年1-3月",
                "金额单位：元",
            ])
            workbook.save(file_path)

            parser = ExcelFinancialParser.__new__(ExcelFinancialParser)
            parser.logger = mock.Mock()
            parser.company_name_resolver = mock.Mock()

            company_name = parser._extract_company_name(str(file_path), "利润表")

        self.assertEqual(company_name, "遂宁市鹏安投资有限公司")
        parser.company_name_resolver.extract_from_text.assert_not_called()

    def test_parse_populates_file_level_company_name(self):
        parser = ExcelFinancialParser.__new__(ExcelFinancialParser)
        parser.logger = mock.Mock()
        parser.company_name_resolver = mock.Mock()
        parser._get_visible_sheet_names = mock.Mock(return_value=["sheet1"])
        parser._extract_company_name = mock.Mock(return_value="测试公司")
        parser._fuzzy_find_info = mock.Mock(
            return_value={"表名": "资产负债表", "日期": "202412", "单位": "元", "合并": "否"}
        )
        parser._llm_detect_header_and_mapping = mock.Mock(return_value=(1, {}))
        parser._parse_balance_sheet = mock.Mock(return_value={"货币资金": 100})
        parser._parse_income_stmts = mock.Mock(return_value=None)
        parser._parse_cash_stmts = mock.Mock(return_value=None)

        result = parser.parse("/tmp/demo.xlsx")

        self.assertEqual(result[0]["company_name"], "测试公司")


class PDFFinancialProcessorCompanyNameTest(unittest.TestCase):
    def _build(self, *, markdown=None, company="视觉公司", count=1, page_scan=None):
        processor = build_processor(PDFFinancialProcessor)
        processor.logger = mock.Mock()
        processor.page_processor.use_paddle = True
        processor.page_renderer.render = mock.Mock(side_effect=lambda doc, page, directory, number: f"/tmp/page_{number}.png")
        content = markdown or "# 利润表\n编制单位：规则公司\n| 项目 | 上期金额 | 本期金额 |\n| --- | --- | --- |\n| 营业收入 | 90 | 100 |\n| 净利润 | 20 | 30 |"
        processor.page_processor.extract_discovery_text = mock.Mock(return_value=content)
        processor.page_processor.remove_watermark_from_file = mock.Mock(side_effect=lambda path, **kwargs: path)
        processor.page_processor.correct_image_orientation = mock.Mock(side_effect=lambda path, **kwargs: path)
        processor.page_processor.extract_statement_group_with_vl = mock.Mock(return_value={
            "title": "利润表", "company_name": company, "date_raw": "2023年度", "unit": "元", "markdown": content,
        })
        if page_scan is not None:
            processor.config = {"pdf_parse": {"page_scan": page_scan}}
        doc = mock.Mock(page_count=count, is_closed=False)
        return processor, doc

    def _scan_window(self, count, fallback):
        processor, doc = self._build(count=count, page_scan={"initial_window_pages": 30, "fallback_full_scan": fallback})
        processor.page_processor.extract_discovery_text.return_value = "公司坚持产品研发和服务创新，积极提升客户满意度。" * 10
        with mock.patch("apps.fin_stmts_parse.src.pdf_financial_parser.fitz.open", return_value=doc):
            self.assertEqual(processor.process_pdf("/tmp/demo.pdf"), [])
        processor.page_processor.extract_statement_group_with_vl.assert_not_called()
        return processor.page_processor.extract_discovery_text.call_count

    def test_process_pdf_page_window_caps_at_total_pages(self):
        self.assertEqual(self._scan_window(5, True), 5)

    def test_process_pdf_page_window_can_skip_remaining_pages_without_fallback(self):
        self.assertEqual(self._scan_window(35, False), 30)

    def test_process_pdf_page_window_fallback_scans_remaining_pages(self):
        self.assertEqual(self._scan_window(35, True), 35)

    def test_process_pdf_populates_company_name_from_same_model_response(self):
        processor, doc = self._build()
        processor.page_processor.extract_company_name_from_image = mock.Mock(side_effect=AssertionError("extra model call"))
        with mock.patch("apps.fin_stmts_parse.src.pdf_financial_parser.fitz.open", return_value=doc):
            result = processor.process_pdf("/tmp/demo.pdf")
        self.assertEqual(result[0]["company_name"], "视觉公司")
        self.assertEqual(result[0]["page"], 1)
        processor.page_processor.extract_statement_group_with_vl.assert_called_once()

    def test_process_pdf_falls_back_to_local_markdown_rules(self):
        processor, doc = self._build(company="")
        with mock.patch("apps.fin_stmts_parse.src.pdf_financial_parser.fitz.open", return_value=doc):
            result = processor.process_pdf("/tmp/demo.pdf")
        self.assertEqual(result[0]["company_name"], "规则公司")

    def test_process_pdf_splits_dual_entity_statement(self):
        processor, doc = self._build(markdown="# 利润表\n" + DUAL_ENTITY_PROFIT_MARKDOWN)
        with mock.patch("apps.fin_stmts_parse.src.pdf_financial_parser.fitz.open", return_value=doc):
            result = processor.process_pdf("/tmp/demo.pdf")
        by_name = {item["表名"]: item for item in result}
        self.assertEqual(set(by_name), {"利润表", "合并利润表"})
        self.assertEqual(by_name["合并利润表"]["数据"]["营业收入"], [2621747215.51, 3288635968.37])
        self.assertEqual(by_name["利润表"]["数据"]["营业收入"], [99038216.36, 104263029.69])
        processor.page_processor.extract_statement_group_with_vl.assert_called_once()

    def test_process_pdf_filters_dual_entity_statement_by_consolidation_flag(self):
        for consolidated in (True, False):
            with self.subTest(consolidated=consolidated):
                processor, doc = self._build(markdown="# 利润表\n" + DUAL_ENTITY_PROFIT_MARKDOWN)
                with mock.patch("apps.fin_stmts_parse.src.pdf_financial_parser.fitz.open", return_value=doc):
                    result = processor.process_pdf("/tmp/demo.pdf", is_consolidated=consolidated)
                self.assertEqual([item["表名"] for item in result], ["合并利润表" if consolidated else "利润表"])



if __name__ == "__main__":
    unittest.main()
