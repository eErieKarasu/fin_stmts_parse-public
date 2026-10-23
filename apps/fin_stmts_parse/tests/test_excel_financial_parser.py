import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock

from openpyxl import Workbook

from apps.fin_stmts_parse.src.excel_financial_parser import ExcelFinancialParser


class FakeLLM:
    def chat(self, system_prompt, user_message):
        return (
            '{"header_row": 3, "column_mapping": {'
            '"资产": "资产", '
            '"2023-12-31": "期末余额", '
            '"2022-12-31": "期初余额"'
            "}}"
        )


class FakeCashflowLLM:
    def chat(self, system_prompt, user_message):
        return '{"header_row": 3, "column_mapping": {"项目": "项目"}}'


class FakeDualColumnBalanceLLM:
    def chat(self, system_prompt, user_message):
        return (
            '{"header_row": 3, "column_mapping": {'
            '"资产": "资产", '
            '"2026-03-31": "期末余额", '
            '"2025-12-31": "期初余额", '
            '"负债和所有者权益": "负债和所有者权益"'
            '}}'
        )


class ExcelFinancialParserMetadataTest(unittest.TestCase):
    def _build_parser(self):
        parser = ExcelFinancialParser.__new__(ExcelFinancialParser)
        parser.logger = mock.Mock()
        return parser

    def _find_info(self, parser, file_path, sheet_name):
        return parser._fuzzy_find_info(
            str(file_path),
            sheet_name,
            {
                "表名": ["资产负债", "利润", "现金流量", "损益"],
                "单位": ["亿元", "万元", "元"],
            },
        )

    def test_extract_date_uses_range_end_month(self):
        parser = self._build_parser()

        self.assertEqual(parser._extract_date("2026年1-3月"), "202603")

    @staticmethod
    def _write_sheet(file_path: Path, sheet_name: str, rows) -> None:
        workbook = Workbook()
        worksheet = workbook.active
        worksheet.title = sheet_name
        for row in rows:
            worksheet.append(row)
        workbook.save(file_path)

    def test_sheet_name_takes_priority_and_content_scan_fills_metadata(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            file_path = Path(temp_dir) / "metadata.xlsx"
            self._write_sheet(
                file_path,
                "资产负债表",
                [
                    ["2024年12月31日", None, "单位：万元"],
                    ["合并报表", None, None],
                    ["项目", "期末余额", "期初余额"],
                ],
            )

            parser = self._build_parser()
            info = self._find_info(parser, file_path, "资产负债表")

            self.assertEqual(info["表名"], "资产负债表")
            self.assertEqual(info["日期"], "202412")
            self.assertEqual(info["单位"], "万元")
            self.assertEqual(info["合并"], "是")

    def test_exact_sheet_name_matching_does_not_infer_consolidated(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            file_path = Path(temp_dir) / "metadata.xlsx"
            self._write_sheet(
                file_path,
                "资产负债表",
                [
                    ["2024年12月31日", None, "单位：元"],
                    ["编制单位：测试公司", None, None],
                ],
            )

            parser = self._build_parser()
            info = self._find_info(parser, file_path, "资产负债表")

            self.assertEqual(info["表名"], "资产负债表")
            self.assertEqual(info["合并"], "否")

    def test_non_exact_sheet_name_falls_back_to_content_detection(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            file_path = Path(temp_dir) / "metadata.xlsx"
            self._write_sheet(
                file_path,
                "资产负债表附注",
                [
                    ["利润表", None, None],
                    ["2024年6月", None, "单位：元"],
                ],
            )

            parser = self._build_parser()
            info = self._find_info(parser, file_path, "资产负债表附注")

            self.assertEqual(info["表名"], "利润表")

    def test_unmatched_sheet_name_falls_back_to_content_detection(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            file_path = Path(temp_dir) / "metadata.xlsx"
            self._write_sheet(
                file_path,
                "Sheet1",
                [
                    ["利润表", None, None],
                    ["2024年6月", None, "单位：元"],
                ],
            )

            parser = self._build_parser()
            info = self._find_info(parser, file_path, "Sheet1")

            self.assertEqual(info["表名"], "利润表")
            self.assertEqual(info["日期"], "202406")
            self.assertEqual(info["单位"], "元")

    def test_sheet_name_match_does_not_use_content_for_table_type(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            file_path = Path(temp_dir) / "metadata.xlsx"
            self._write_sheet(
                file_path,
                "资产负债表",
                [
                    ["利润表", None, None],
                    ["2024年12月", None, "单位：元"],
                ],
            )

            parser = self._build_parser()
            info = self._find_info(parser, file_path, "资产负债表")

            self.assertEqual(info["表名"], "资产负债表")
            parser.logger.warning.assert_not_called()

    def test_sheet_name_scope_overrides_conflicting_title_scope(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            file_path = Path(temp_dir) / "metadata.xlsx"
            self._write_sheet(
                file_path,
                "母公司利润表",
                [
                    ["合并利润表", None, None],
                    ["2024年12月", None, "单位：元"],
                ],
            )

            parser = self._build_parser()
            info = self._find_info(parser, file_path, "母公司利润表")

            self.assertEqual(info["表名"], "利润表")
            self.assertEqual(info["合并"], "否")
            parser.logger.warning.assert_called_once()

    def test_content_scope_is_used_when_sheet_name_has_no_scope(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            file_path = Path(temp_dir) / "metadata.xlsx"
            self._write_sheet(
                file_path,
                "Sheet1",
                [
                    ["合并资产负债表", None, None],
                    ["2024年12月31日", None, "单位：元"],
                ],
            )

            parser = self._build_parser()
            info = self._find_info(parser, file_path, "Sheet1")

            self.assertEqual(info["表名"], "资产负债表")
            self.assertEqual(info["合并"], "是")


class ExcelFinancialParserSheetModeTest(unittest.TestCase):
    def _build_parser(self, sheet_names):
        parser = ExcelFinancialParser.__new__(ExcelFinancialParser)
        parser.logger = mock.Mock()
        parser._get_visible_sheet_names = mock.Mock(return_value=sheet_names)
        parser._extract_company_name = mock.Mock(return_value="")
        parser._llm_detect_header_and_mapping = mock.Mock(return_value=(1, {}))
        parser._parse_balance_sheet = mock.Mock(return_value={"货币资金": 100})
        parser._parse_income_stmts = mock.Mock(return_value={"营业收入": 200})
        parser._parse_cash_stmts = mock.Mock(return_value={"销售商品、提供劳务收到的现金": 300})
        return parser

    def test_parse_uses_content_detection_for_unmatched_sheet_names(self):
        parser = self._build_parser(["资产负债表", "Other"])
        parser._fuzzy_find_info = mock.Mock(
            side_effect=[
                {"表名": "资产负债表", "日期": "202412", "单位": "元", "合并": "否"},
                {"表名": "利润表", "日期": "202412", "单位": "元", "合并": "否"},
            ]
        )

        result = parser.parse("/tmp/demo.xlsx")

        self.assertEqual([item["表名"] for item in result], ["资产负债表", "利润表"])
        self.assertEqual(
            [call.args[1] for call in parser._fuzzy_find_info.call_args_list],
            ["资产负债表", "Other"],
        )

    def test_parse_falls_back_to_content_detection_when_no_sheet_name_matches(self):
        parser = self._build_parser(["Sheet1", "Sheet2"])
        parser._fuzzy_find_info = mock.Mock(
            side_effect=[
                {"表名": "资产负债表", "日期": "202412", "单位": "元", "合并": "否"},
                {"表名": "利润表", "日期": "202412", "单位": "元", "合并": "否"},
            ]
        )

        result = parser.parse("/tmp/demo.xlsx")

        self.assertEqual([item["表名"] for item in result], ["资产负债表", "利润表"])
        self.assertEqual(
            [call.args[1] for call in parser._fuzzy_find_info.call_args_list],
            ["Sheet1", "Sheet2"],
        )

    def test_parse_keeps_consolidated_and_standalone_statements(self):
        parser = self._build_parser(
            [
                "合并资产负债表",
                "合并利润表",
                "母公司资产负债表",
                "母公司利润表",
                "合并资产负债表副本",
            ]
        )
        parser._fuzzy_find_info = mock.Mock(
            side_effect=[
                {"表名": "资产负债表", "日期": "202412", "单位": "元", "合并": "是"},
                {"表名": "利润表", "日期": "202412", "单位": "元", "合并": "是"},
                {"表名": "资产负债表", "日期": "202412", "单位": "元", "合并": "否"},
                {"表名": "利润表", "日期": "202412", "单位": "元", "合并": "否"},
                {"表名": "资产负债表", "日期": "202412", "单位": "元", "合并": "是"},
            ]
        )

        result = parser.parse("/tmp/demo.xlsx")

        self.assertEqual(
            [item["表名"] for item in result],
            ["合并资产负债表", "合并利润表", "资产负债表", "利润表"],
        )
        self.assertEqual([item["合并"] for item in result], ["是", "是", "否", "否"])
        self.assertEqual(parser._parse_balance_sheet.call_count, 2)
        self.assertEqual(parser._parse_income_stmts.call_count, 2)


class ExcelFinancialParserHeaderMappingTest(unittest.TestCase):
    def test_dual_column_numeric_date_headers_map_duplicate_suffix_columns(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            file_path = Path(temp_dir) / "dual-column-balance.xlsx"
            self._write_dual_column_balance_sheet_with_numeric_date_headers(file_path)

            parser = ExcelFinancialParser.__new__(ExcelFinancialParser)
            parser.logger = mock.Mock()
            parser.llm = FakeDualColumnBalanceLLM()

            header_row, column_mapping = parser._llm_detect_header_and_mapping(
                str(file_path),
                "资产负债表",
                "资产负债表",
            )

            self.assertEqual(header_row, 3)
            self.assertEqual(column_mapping["2026-03-31"], "期末余额")
            self.assertEqual(column_mapping["2025-12-31"], "期初余额")
            self.assertEqual(column_mapping["46112.1"], "期末余额")
            self.assertEqual(column_mapping["46022.1"], "期初余额")

            parsed_data = parser._parse_balance_sheet(
                str(file_path),
                "资产负债表",
                header_row,
                column_mapping,
            )

            self.assertEqual(parsed_data["货币资金"], [90.0, 100.0])
            self.assertEqual(parsed_data["短期借款"], [40.0, 50.0])

    def test_detect_header_mapping_matches_datetime_header_columns(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            file_path = Path(temp_dir) / "balance.xlsx"
            self._write_balance_sheet_with_datetime_headers(file_path)

            parser = ExcelFinancialParser.__new__(ExcelFinancialParser)
            parser.logger = mock.Mock()
            parser.llm = FakeLLM()

            header_row, column_mapping = parser._llm_detect_header_and_mapping(
                str(file_path),
                "资产负债表",
                "资产负债表",
            )

            self.assertEqual(header_row, 3)
            self.assertEqual(
                column_mapping,
                {
                    "资产": "资产",
                    "2023-12-31": "期末余额",
                    "2022-12-31": "期初余额",
                },
            )

            parsed_data = parser._parse_balance_sheet(
                str(file_path),
                "资产负债表",
                header_row,
                column_mapping,
            )

            self.assertEqual(parsed_data["货币资金"], [20885193.46, 21770968.43])
            self.assertEqual(parsed_data["流动资产："], [None, None])
            self.assertEqual(parsed_data["固定资产："], [None, None])
            self.assertEqual(parsed_data["固定资产净值"], [75279636.29, 87055616.87])
            self.assertEqual(parsed_data["固定资产净额"], [None, None])

    def test_cashflow_year_period_headers_fill_current_amount_column(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            file_path = Path(temp_dir) / "cashflow.xlsx"
            self._write_cashflow_sheet_with_year_period_headers(file_path)

            parser = ExcelFinancialParser.__new__(ExcelFinancialParser)
            parser.logger = mock.Mock()
            parser.llm = FakeCashflowLLM()

            header_row, column_mapping = parser._llm_detect_header_and_mapping(
                str(file_path),
                "现金流量表",
                "现金流量表",
            )

            self.assertEqual(header_row, 3)
            self.assertEqual(
                column_mapping,
                {
                    "项目": "项目",
                    "2023年度": "累计金额",
                },
            )

            parsed_data = parser._parse_cash_stmts(
                str(file_path),
                "现金流量表",
                header_row,
                column_mapping,
            )

            self.assertEqual(parsed_data["销售商品、提供劳务收到的现金"], 299020375.36)
            self.assertEqual(parsed_data["收到的税费返还"], 466343.18)
            self.assertEqual(parsed_data["经营活动现金流入小计"], 309072614.31)

    def test_cashflow_repeated_aggregate_rows_are_contextualized(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            file_path = Path(temp_dir) / "cashflow.xlsx"
            self._write_cashflow_sheet_with_repeated_aggregate_rows(file_path)

            parser = ExcelFinancialParser.__new__(ExcelFinancialParser)
            parser.logger = mock.Mock()
            parser.llm = FakeCashflowLLM()

            parsed_data = parser._parse_cash_stmts(
                str(file_path),
                "现金流量表",
                3,
                {
                    "项目": "项目",
                    "本年累计": "累计金额",
                },
            )

            self.assertNotIn("现金流入小计", parsed_data)
            self.assertNotIn("现金流出小计", parsed_data)
            self.assertEqual(parsed_data["经营活动现金流入小计"], 59006469.17)
            self.assertEqual(parsed_data["经营活动现金流出小计"], 76029445.67)
            self.assertEqual(parsed_data["投资活动现金流入小计"], 0.0)
            self.assertEqual(parsed_data["投资活动现金流出小计"], 2230787.0)
            self.assertEqual(parsed_data["筹资活动现金流入小计"], 88620000.0)
            self.assertEqual(parsed_data["筹资活动现金流出小计"], 70999524.32)

    @staticmethod
    def _write_dual_column_balance_sheet_with_numeric_date_headers(file_path: Path) -> None:
        workbook = Workbook()
        worksheet = workbook.active
        worksheet.title = "资产负债表"
        worksheet.append(["合并资产负债表", None, None, None, None, None, None, None])
        worksheet.append([46112, None, None, None, None, None, None, None])
        worksheet.append(["编制单位：测试公司", None, None, None, None, None, "单位：元", None])
        worksheet.append(
            [
                "资产",
                "行次",
                46112,
                46022,
                "负债和所有者权益",
                "行次",
                46112,
                46022,
            ]
        )
        worksheet.append(["货币资金", 1, 100.0, 90.0, "短期借款", 34, 50.0, 40.0])
        workbook.save(file_path)

    @staticmethod
    def _write_balance_sheet_with_datetime_headers(file_path: Path) -> None:
        workbook = Workbook()
        worksheet = workbook.active
        worksheet.title = "资产负债表"
        worksheet.append(["合并资产负债表", None, None, None])
        worksheet.append([datetime(2023, 12, 31), None, None, None])
        worksheet.append(["编制单位：示例企业043", None, "金额单位：人民币元", None])
        worksheet.append(["资产", "附注", datetime(2023, 12, 31), datetime(2022, 12, 31)])
        worksheet.append(["流动资产：", None, None, None])
        worksheet.append(["  货币资金", "五、（一）", 21770968.43, 20885193.46])
        worksheet.append(["固定资产：", None, None, None])
        worksheet.append(["固定资产净值", None, 87055616.87, 75279636.29])
        worksheet.append(["固定资产净额", None, None, None])
        workbook.save(file_path)

    @staticmethod
    def _write_cashflow_sheet_with_year_period_headers(file_path: Path) -> None:
        workbook = Workbook()
        worksheet = workbook.active
        worksheet.title = "现金流量表"
        worksheet.append(["合并现金流量表", None, None, None])
        worksheet.append(["2023年度", None, None, None])
        worksheet.append(["编制单位：示例企业043", None, "金额单位：人民币元", None])
        worksheet.append(["项目", "附注", "2023年度", "2022年度"])
        worksheet.append(["一、经营活动产生的现金流量", None, None, None])
        worksheet.append(["    销售商品、提供劳务收到的现金", None, 299020375.36, 304583654.25])
        worksheet.append(["    收到的税费返还", None, 466343.18, None])
        worksheet.append(["    收到其他与经营活动有关的现金", "五、（四十五）", 10052238.95, 8528930.75])
        worksheet.append(["经营活动现金流入小计", None, 309072614.31, 313578928.18])
        workbook.save(file_path)

    @staticmethod
    def _write_cashflow_sheet_with_repeated_aggregate_rows(file_path: Path) -> None:
        workbook = Workbook()
        worksheet = workbook.active
        worksheet.title = "现金流量表"
        worksheet.append(["现金流量表", None, None, None])
        worksheet.append(["会计期间:2024年6月", None, None, None])
        worksheet.append([None, None, None, "单位：元"])
        worksheet.append(["项目", "行次", "本年累计", "上年同期"])
        worksheet.append(["一、经营活动产生的现金流量：", 1, None, None])
        worksheet.append(["销售商品、提供劳务收到的现金", 2, 46416020.57, 54889761.00])
        worksheet.append(["收到的税费返还", 3, 0.0, 69781.96])
        worksheet.append(["收到的其他与经营活动有关的现金", 4, 12590448.6, 15551329.14])
        worksheet.append(["现金流入小计", 5, 59006469.17, 70510872.10])
        worksheet.append(["购买商品、接受劳务支付的现金", 6, 31373044.32, 35919424.88])
        worksheet.append(["支付给职工以及为职工支付的现金", 7, 36228315.08, 35848765.09])
        worksheet.append(["支付的各项税费", 8, 3953369.64, 2323698.71])
        worksheet.append(["支付的其他与经营活动有关的现金", 9, 4474716.63, 8841421.32])
        worksheet.append(["现金流出小计", 10, 76029445.67, 82933310.00])
        worksheet.append(["经营活动产生的现金流量净额", 11, -17022976.5, -12422437.90])
        worksheet.append(["二、投资活动产生的现金流量：", 12, None, 0.0])
        worksheet.append(["收回投资所收到的现金", 13, 0.0, 0.0])
        worksheet.append(["取得投资收益所收到的现金", 14, 0.0, 0.0])
        worksheet.append(["收到的其他与投资活动有关的现金", 16, 0.0, 0.0])
        worksheet.append(["现金流入小计", 17, 0.0, None])
        worksheet.append(["购建固定资产、无形资产和其他长期资产所支付的现金", 18, 175787.0, None])
        worksheet.append(["投资所支付的现金", 19, 2055000.0, 920001.0])
        worksheet.append(["支付的其他与投资活动有关的现金", 20, 0.0, 0.0])
        worksheet.append(["现金流出小计", 21, 2230787.0, 920001.0])
        worksheet.append(["投资活动产生的现金流量净额", 22, -2230787.0, -920001.0])
        worksheet.append(["三、筹资活动产生的现金流量：", 23, None, 0.0])
        worksheet.append(["吸收投资所收到的现金", 24, 0.0, 17999995.36])
        worksheet.append(["借款所收到的现金", 25, 88620000.0, 82533000.0])
        worksheet.append(["收到的其他与筹资活动有关的现金", 26, 0.0, None])
        worksheet.append(["现金流入小计", 27, 88620000.0, 100532995.36])
        worksheet.append(["偿还债务所支付的现金", 28, 67164718.8, 85784070.06])
        worksheet.append(["分配股利、利润或偿付利息所支付的现金", 29, 3834805.52, 3915531.54])
        worksheet.append(["支付的其他与筹资活动有关的现金", 30, 0.0, None])
        worksheet.append(["现金流出小计", 31, 70999524.32, 89699601.60])
        worksheet.append(["筹资活动产生的现金流量净额", 32, 17620475.68, 10833393.76])
        workbook.save(file_path)


if __name__ == "__main__":
    unittest.main()
