import unittest

from apps.fin_stmts_parse.src.markdown_table_extractor import MarkdownTableExtractor


BALANCE_MARKDOWN_WITH_SPACED_THOUSANDS = """
| 资产 | 行次 | 期末余额 | 年初余额 |
| --- | --- | --- | --- |
| 货币资金 | 2 | 28, 683, 854.89 | 12, 094, 850.75 |
| 应收账款 | 5 | 52, 798, 582.26 | 61, 327, 804.91 |
| 应付账款 | 34 | -339, 827.67 | 3, 411, 206.13 |
""".strip()

CASHFLOW_MARKDOWN_WITH_PERIOD_END_HEADER = """
| 科目 | 行次 | 期末 |
| --- | --- | --- |
| 购建固定资产、无形资产等支付的现金 | 18 | 945,994,398.28 |
""".strip()

CASHFLOW_MARKDOWN_WITH_SUPPLEMENT_COLUMNS = """
| 项目 | 行次 | 金额 | 补充资料 | 行次 | 金额 |
| --- | --- | --- | --- | --- | --- |
| **一、经营活动产生的现金流量：** | | | **1、将净利润调节为经营活动现金流量：** | | |
| 销售商品、提供劳务收到的现金 | 1 | 217,731,159.95 | 净利润 | 57 | - |
| 收到的其他与经营活动有关的现金 | 8 | -12,938,047.53 | 固定资产折旧 | 59 | 3,232,715.54 |
| **现金流入小计** | 9 | 204,793,112.42 | 财务费用 | 68 | 14,621,219.01 |
| 购买商品、接受劳务支付的现金 | 10 | 222,422,143.58 | 经营性应付项目的增加（减：减少） | 73 | #REF! |
| **现金流出小计** | 20 | 234,239,559.93 | 其他 | 74 | #REF! |
| **经营活动产生的现金流量净额** | 21 | -29,446,447.51 | **经营活动产生的现金流量净额** | 75 | #REF! |
""".strip()

CASHFLOW_SUPPLEMENT_ONLY_MARKDOWN = """
| 补充资料 | 行次 | 金额 |
| --- | --- | --- |
| 净利润 | 57 | - |
| 固定资产折旧 | 59 | 3,232,715.54 |
| 财务费用 | 68 | 14,621,219.01 |
| 经营活动产生的现金流量净额 | 75 | #REF! |
""".strip()

CASHFLOW_MARKDOWN_WITH_DASH_AGGREGATE = """
| 项目 | 行次 | 金额 |
| --- | --- | --- |
| **二、投资活动产生的现金流量：** | | |
| 收回投资收到的现金 | 22 | - |
| 取得投资收益收到的现金 | 23 | - |
| 收到的其他与投资活动有关的现金 | 28 | - |
| **现金流入小计** | 29 | - |
| 购建固定资产、无形资产和其他长期资产所支付的现金 | 30 | 17,979,482.51 |
| **现金流出小计** | 36 | 17,979,482.51 |
| **投资活动产生的现金流量净额** | 37 | -17,979,482.51 |
""".strip()

CASHFLOW_MARKDOWN_WITH_REPEATED_AGGREGATES = """
| 项目 | 金额 |
| --- | --- |
| 一、经营活动产生的现金流量： |  |
| 销售商品、提供劳务收到的现金 | 46416020.57 |
| 收到的税费返还 | 0.0 |
| 收到的其他与经营活动有关的现金 | 12590448.6 |
| 现金流入小计 | 59006469.17 |
| 购买商品、接受劳务支付的现金 | 31373044.32 |
| 支付给职工以及为职工支付的现金 | 36228315.08 |
| 支付的各项税费 | 3953369.64 |
| 支付的其他与经营活动有关的现金 | 4474716.63 |
| 现金流出小计 | 76029445.67 |
| 经营活动产生的现金流量净额 | -17022976.5 |
| 二、投资活动产生的现金流量： |  |
| 收回投资所收到的现金 | 0.0 |
| 取得投资收益所收到的现金 | 0.0 |
| 收到的其他与投资活动有关的现金 | 0.0 |
| 现金流入小计 | 0.0 |
| 购建固定资产、无形资产和其他长期资产所支付的现金 | 175787.0 |
| 投资所支付的现金 | 2055000.0 |
| 支付的其他与投资活动有关的现金 | 0.0 |
| 现金流出小计 | 2230787.0 |
| 投资活动产生的现金流量净额 | -2230787.0 |
| 三、筹资活动产生的现金流量： |  |
| 吸收投资所收到的现金 | 0.0 |
| 借款所收到的现金 | 88620000.0 |
| 收到的其他与筹资活动有关的现金 | 0.0 |
| 现金流入小计 | 88620000.0 |
| 偿还债务所支付的现金 | 67164718.8 |
| 分配股利、利润或偿付利息所支付的现金 | 3834805.52 |
| 支付的其他与筹资活动有关的现金 | 0.0 |
| 现金流出小计 | 70999524.32 |
| 筹资活动产生的现金流量净额 | 17620475.68 |
""".strip()

PROFIT_MARKDOWN_WITH_LATEX_AMOUNTS = """
| 项目 | 金额 |
| --- | --- |
| 营业收入 | $137,028.32$ |
| 净利润 | $-5,131.78$ |
""".strip()

PROFIT_MARKDOWN_WITH_PARENTHESES_NEGATIVE_AMOUNTS = """
| 项目 | 金额 |
| --- | --- |
| 营业利润 | (257,315.88) |
| 净利润 | （1,234.56） |
""".strip()

DUAL_ENTITY_BALANCE_FLAT_HEADER = """
| 项目 | 注释号 | 行次 | 2023年12月31日合并 | 2023年12月31日母公司 | 2022年12月31日合并 | 2022年12月31日母公司 |
| --- | --- | --- | --- | --- | --- | --- |
| 货币资金 | 五(一) | 1 | 1,138,473,382.41 | 510,504,849.84 | 1,439,326,367.44 | 588,757,447.86 |
| 应收账款 | 五(三) | 5 | 1,469,843,627.82 | 63,346,511.85 | 1,169,245,631.61 | 96,568,743.91 |
""".strip()

BALANCE_MARKDOWN_WITH_NOTE_COLUMN = """
| 项目 | 附注 | 期末余额 | 期初余额 |
| --- | --- | --- | --- |
| 货币资金 | 五、（一） | 697,835.03 | 1,135,291.16 |
| 预付款项 | 五、（二） | 7,618.87 | 14,359.98 |
| 资产总计 |  | 314,333,467.45 | 281,236,682.74 |
""".strip()

BALANCE_MARKDOWN_WITH_PRIOR_YEAR_END_HEADER = """
| 资产 | 附注 | 期末余额 | 上年年末余额 |
| --- | --- | --- | --- |
| 货币资金 | 五、（一） | 697,835.03 | 1,135,291.16 |
| 预付款项 | 五、（二） | 7,618.87 | 14,359.98 |
| 资产总计 |  | 314,333,467.45 | 281,236,682.74 |
""".strip()

BALANCE_HTML_WITH_DUPLICATE_ITEM_NOTE_HEADER = """
<table>
<tr><td>项目</td><td>项目</td><td>2024年12月31日</td><td>2024年1月1日</td></tr>
<tr><td>流动资产：</td><td></td><td></td><td></td></tr>
<tr><td>货币资金</td><td>（一）</td><td>861,566,872.88</td><td>478,803,044.71</td></tr>
<tr><td>应收账款</td><td>五、（二）</td><td>2,867,627,610.53</td><td>2,482,332,547.04</td></tr>
<tr><td>存货</td><td>五、（五）</td><td>7,189,439,060.52</td><td>6,977,242,110.43</td></tr>
<tr><td>资产总计</td><td></td><td>17,117,799,164.03</td><td>18,015,851,561.97</td></tr>
</table>
""".strip()

DUAL_ENTITY_BALANCE_COMPANY_ALIAS = """
| 项目 | 附注 | 2024年12月31日 合并 | 2024年12月31日 公司 | 2023年12月31日 合并 | 2023年12月31日 公司 |
| --- | --- | --- | --- | --- | --- |
| 货币资金 | 五、1 | 3,621,879,183.43 | 675,245,640.88 | 4,215,091,018.05 | 855,022,551.04 |
| 预付款项 | 五、5 | 325,739,895.74 | 432,889.25 | 146,487,606.98 | 386,801.67 |
| 资产总计 |  | 114,786,972,756.30 | 47,224,067,784.57 | 103,509,593,079.36 | 36,787,091,744.69 |
""".strip()

DUAL_ENTITY_PROFIT_MULTI_HEADER = """
| 项目 | 注释号 | 行次 | 2023年度 |  | 2022年度 |  |
| --- | --- | --- | --- | --- | --- | --- |
|  |  |  | 合并 | 母公司 | 合并 | 母公司 |
| 营业收入 | 五(四十二) | 1 | 3,288,635,968.37 | 104,263,029.69 | 2,621,747,215.51 | 99,038,216.36 |
| 净利润 |  | 25 | 108,893,977.91 | 150,541,108.62 | 110,488,373.82 | 22,988,339.11 |
""".strip()

DUAL_ENTITY_CASHFLOW_MULTI_HEADER = """
| 项目 | 注释号 | 行次 | 2023年度 |  | 2022年度 |  |
| --- | --- | --- | --- | --- | --- | --- |
|  |  |  | 合并 | 母公司 | 合并 | 母公司 |
| 一、经营活动产生的现金流量： |  |  |  |  |  |  |
| 销售商品、提供劳务收到的现金 |  | 1 | 2,851,979,645.00 | 119,614,383.23 | 2,823,989,289.38 | 103,274,212.17 |
| 现金流入小计 |  | 4 | 3,319,651,984.90 | 292,114,037.45 | 3,706,903,027.38 | 127,867,571.63 |
""".strip()


class MarkdownTableExtractorTest(unittest.TestCase):
    def setUp(self) -> None:
        self.extractor = MarkdownTableExtractor(llm_client=None)

    def test_extract_numeric_value_handles_spaced_thousands_separators(self) -> None:
        self.assertEqual(self.extractor.extract_numeric_value("28, 683, 854.89"), 28683854.89)
        self.assertEqual(self.extractor.extract_numeric_value("52, 798, 582.26"), 52798582.26)
        self.assertEqual(self.extractor.extract_numeric_value("-339, 827.67"), -339827.67)

    def test_extract_numeric_value_handles_latex_inline_math_delimiters(self) -> None:
        self.assertEqual(self.extractor.extract_numeric_value("$137,028.32$"), 137028.32)
        self.assertEqual(self.extractor.extract_numeric_value("$-5,131.78$"), -5131.78)

    def test_extract_numeric_value_handles_parentheses_negative_amounts(self) -> None:
        self.assertEqual(self.extractor.extract_numeric_value("(257,315.88)"), -257315.88)
        self.assertEqual(self.extractor.extract_numeric_value("（257,315.88）"), -257315.88)
        self.assertEqual(self.extractor.extract_numeric_value("$(257,315.88)$"), -257315.88)

    def test_extract_numeric_value_preserves_empty_cells(self) -> None:
        self.assertIsNone(self.extractor.extract_numeric_value(""))
        self.assertIsNone(self.extractor.extract_numeric_value("-"))
        self.assertIsNone(self.extractor.extract_numeric_value("—"))

    def test_clean_item_text_removes_excel_escaped_control_chars(self) -> None:
        self.assertEqual(
            self.extractor.clean_item_text("使用权资产_x000D_"),
            "使用权资产",
        )

    def test_clean_item_text_removes_decorative_prefix_markers(self) -> None:
        self.assertEqual(
            self.extractor.clean_item_text("△☆其他权益工具投资"),
            "其他权益工具投资",
        )
        self.assertEqual(
            self.extractor.clean_item_text("$ ^{{*}}少数股东损益 $"),
            "少数股东损益",
        )

    def test_parse_markdown_table_handles_spaced_thousands_separators(self) -> None:
        parsed = self.extractor.parse_markdown_table_to_dict(
            BALANCE_MARKDOWN_WITH_SPACED_THOUSANDS,
            table_type="资产负债表",
        )

        self.assertEqual(parsed["货币资金"], [12094850.75, 28683854.89])
        self.assertEqual(parsed["应收账款"], [61327804.91, 52798582.26])
        self.assertEqual(parsed["应付账款"], [3411206.13, -339827.67])

    def test_parse_markdown_table_handles_latex_inline_math_amounts(self) -> None:
        parsed = self.extractor.parse_markdown_table_to_dict(
            PROFIT_MARKDOWN_WITH_LATEX_AMOUNTS,
            table_type="利润表",
        )

        self.assertEqual(parsed["营业收入"], [None, 137028.32])
        self.assertEqual(parsed["净利润"], [None, -5131.78])

    def test_parse_markdown_table_handles_parentheses_negative_amounts(self) -> None:
        parsed = self.extractor.parse_markdown_table_to_dict(
            PROFIT_MARKDOWN_WITH_PARENTHESES_NEGATIVE_AMOUNTS,
            table_type="利润表",
        )

        self.assertEqual(parsed["营业利润"], [None, -257315.88])
        self.assertEqual(parsed["净利润"], [None, -1234.56])

    def test_parse_cashflow_markdown_with_period_end_header(self) -> None:
        parsed = self.extractor.parse_markdown_table_to_dict(
            CASHFLOW_MARKDOWN_WITH_PERIOD_END_HEADER,
            table_type="现金流量表",
        )

        self.assertEqual(
            parsed["购建固定资产、无形资产等支付的现金"],
            [None, 945994398.28],
        )

    def test_parse_profit_returns_previous_and_current_values(self) -> None:
        parsed = self.extractor.parse_markdown_table_to_dict(
            """
            | 项目 | 上年累计数 | 本年累计数 |
            | --- | ---: | ---: |
            | 营业总收入 | 900.00 | 1000.00 |
            | 营业利润 | 80.00 | 100.00 |
            """,
            table_type="利润表",
        )

        self.assertEqual(parsed["营业总收入"], [900.0, 1000.0])
        self.assertEqual(parsed["营业利润"], [80.0, 100.0])

    def test_parse_cashflow_ignores_supplement_columns_as_main_items(self) -> None:
        parsed = self.extractor.parse_markdown_table_to_dict(
            CASHFLOW_MARKDOWN_WITH_SUPPLEMENT_COLUMNS,
            table_type="现金流量表",
        )

        self.assertEqual(parsed["经营活动现金流入小计"], [None, 204793112.42])
        self.assertEqual(parsed["经营活动现金流出小计"], [None, 234239559.93])
        self.assertEqual(parsed["经营活动产生的现金流量净额"], [None, -29446447.51])
        self.assertNotIn("净利润", parsed)
        self.assertNotIn("财务费用", parsed)

    def test_llm_guided_cashflow_mapping_ignores_supplement_columns(self) -> None:
        headers = ["项目", "行次", "金额", "补充资料", "行次", "金额"]
        rows = [
            ["销售商品、提供劳务收到的现金", "1", "217,731,159.95", "净利润", "57", "-"],
            ["经营活动产生的现金流量净额", "21", "-29,446,447.51", "财务费用", "68", "14,621,219.01"],
        ]
        column_mapping = [
            {"col_index": 0, "original_header": "项目", "mapped_to": "项目"},
            {"col_index": 2, "original_header": "金额", "mapped_to": "累计金额"},
            {"col_index": 3, "original_header": "补充资料", "mapped_to": "项目"},
            {"col_index": 5, "original_header": "金额", "mapped_to": "累计金额"},
        ]

        parsed, needs_rescue, rescue_reason = self.extractor.parse_table_rows(
            headers,
            rows,
            is_balance_sheet=False,
            table_type="现金流量表",
            column_mapping=column_mapping,
        )

        self.assertFalse(needs_rescue)
        self.assertEqual(rescue_reason, "")
        self.assertEqual(parsed["销售商品、提供劳务收到的现金"], [None, 217731159.95])
        self.assertEqual(parsed["经营活动产生的现金流量净额"], [None, -29446447.51])
        self.assertNotIn("净利润", parsed)
        self.assertNotIn("财务费用", parsed)

    def test_parse_cashflow_supplement_only_table_returns_empty_main_items(self) -> None:
        parsed = self.extractor.parse_markdown_table_to_dict(
            CASHFLOW_SUPPLEMENT_ONLY_MARKDOWN,
            table_type="现金流量表",
        )

        self.assertEqual(parsed, {})

    def test_parse_cashflow_dash_aggregate_preserves_empty_value(self) -> None:
        parsed = self.extractor.parse_markdown_table_to_dict(
            CASHFLOW_MARKDOWN_WITH_DASH_AGGREGATE,
            table_type="现金流量表",
        )

        self.assertEqual(parsed["收回投资收到的现金"], [None, None])
        self.assertEqual(parsed["投资活动现金流入小计"], [None, None])
        self.assertEqual(parsed["投资活动现金流出小计"], [None, 17979482.51])
        self.assertEqual(parsed["投资活动产生的现金流量净额"], [None, -17979482.51])

    def test_parse_cashflow_enum_type_contextualizes_repeated_aggregate_rows(self) -> None:
        parsed = self.extractor.parse_markdown_table_to_dict(
            CASHFLOW_MARKDOWN_WITH_REPEATED_AGGREGATES,
            table_type="cashflow",
        )

        self.assertNotIn("现金流入小计", parsed)
        self.assertNotIn("现金流出小计", parsed)
        self.assertEqual(parsed["经营活动现金流入小计"], [None, 59006469.17])
        self.assertEqual(parsed["经营活动现金流出小计"], [None, 76029445.67])
        self.assertEqual(parsed["投资活动现金流入小计"], [None, 0.0])
        self.assertEqual(parsed["投资活动现金流出小计"], [None, 2230787.0])
        self.assertEqual(parsed["筹资活动现金流入小计"], [None, 88620000.0])
        self.assertEqual(parsed["筹资活动现金流出小计"], [None, 70999524.32])

    def test_split_dual_entity_balance_sheet_flat_header(self) -> None:
        variants = self.extractor.try_split_dual_entity_comparative_statement(
            DUAL_ENTITY_BALANCE_FLAT_HEADER,
            table_type="资产负债表",
        )

        self.assertEqual([variant["table_type"] for variant in variants], ["合并资产负债表", "资产负债表"])
        self.assertEqual(
            variants[0]["data"]["货币资金"],
            [1439326367.44, 1138473382.41],
        )
        self.assertEqual(
            variants[1]["data"]["货币资金"],
            [588757447.86, 510504849.84],
        )
        self.assertNotIn("五(一)", variants[0]["data"])

    def test_split_dual_entity_profit_statement_multi_header(self) -> None:
        variants = self.extractor.try_split_dual_entity_comparative_statement(
            DUAL_ENTITY_PROFIT_MULTI_HEADER,
            table_type="利润表",
        )

        self.assertEqual(variants[0]["table_type"], "合并利润表")
        self.assertEqual(variants[1]["table_type"], "利润表")
        self.assertEqual(variants[0]["data"]["营业收入"], [2621747215.51, 3288635968.37])
        self.assertEqual(variants[1]["data"]["营业收入"], [99038216.36, 104263029.69])
        self.assertEqual(variants[0]["data"]["净利润"], [110488373.82, 108893977.91])
        self.assertEqual(variants[1]["data"]["净利润"], [22988339.11, 150541108.62])

    def test_split_dual_entity_cashflow_statement_multi_header(self) -> None:
        variants = self.extractor.try_split_dual_entity_comparative_statement(
            DUAL_ENTITY_CASHFLOW_MULTI_HEADER,
            table_type="现金流量表",
        )

        self.assertEqual(variants[0]["table_type"], "合并现金流量表")
        self.assertEqual(variants[1]["table_type"], "现金流量表")
        self.assertEqual(
            variants[0]["data"]["销售商品、提供劳务收到的现金"],
            [2823989289.38, 2851979645.0],
        )
        self.assertEqual(
            variants[1]["data"]["销售商品、提供劳务收到的现金"],
            [103274212.17, 119614383.23],
        )
        self.assertEqual(
            variants[0]["data"]["经营活动现金流入小计"],
            [3706903027.38, 3319651984.9],
        )
        self.assertEqual(
            variants[1]["data"]["经营活动现金流入小计"],
            [127867571.63, 292114037.45],
        )

    def test_regular_balance_sheet_does_not_split_as_dual_entity(self) -> None:
        variants = self.extractor.try_split_dual_entity_comparative_statement(
            BALANCE_MARKDOWN_WITH_SPACED_THOUSANDS,
            table_type="资产负债表",
        )

        self.assertEqual(variants, [])

    def test_parse_balance_sheet_ignores_note_column_when_inferring_item_columns(self) -> None:
        parsed = self.extractor.parse_markdown_table_to_dict(
            BALANCE_MARKDOWN_WITH_NOTE_COLUMN,
            table_type="合并资产负债表",
        )

        self.assertEqual(parsed["货币资金"], [1135291.16, 697835.03])
        self.assertEqual(parsed["预付款项"], [14359.98, 7618.87])
        self.assertEqual(parsed["资产总计"], [281236682.74, 314333467.45])
        self.assertNotIn("(一)", parsed)

    def test_parse_balance_sheet_treats_prior_year_end_as_beginning_balance(self) -> None:
        parsed = self.extractor.parse_markdown_table_to_dict(
            BALANCE_MARKDOWN_WITH_PRIOR_YEAR_END_HEADER,
            table_type="合并资产负债表",
        )

        self.assertEqual(parsed["货币资金"], [1135291.16, 697835.03])
        self.assertEqual(parsed["预付款项"], [14359.98, 7618.87])
        self.assertEqual(parsed["资产总计"], [281236682.74, 314333467.45])
        self.assertNotIn("(一)", parsed)

    def test_parse_balance_sheet_ignores_ocr_duplicate_item_note_header(self) -> None:
        parsed = self.extractor.parse_markdown_table_to_dict(
            BALANCE_HTML_WITH_DUPLICATE_ITEM_NOTE_HEADER,
            table_type="合并资产负债表",
        )

        self.assertEqual(parsed["货币资金"], [478803044.71, 861566872.88])
        self.assertEqual(parsed["应收账款"], [2482332547.04, 2867627610.53])
        self.assertEqual(parsed["存货"], [6977242110.43, 7189439060.52])
        self.assertEqual(parsed["资产总计"], [18015851561.97, 17117799164.03])
        self.assertNotIn("(一)", parsed)

    def test_split_dual_entity_balance_sheet_accepts_company_alias(self) -> None:
        variants = self.extractor.try_split_dual_entity_comparative_statement(
            DUAL_ENTITY_BALANCE_COMPANY_ALIAS,
            table_type="资产负债表",
        )

        self.assertEqual([variant["table_type"] for variant in variants], ["合并资产负债表", "资产负债表"])
        self.assertEqual(
            variants[0]["data"]["货币资金"],
            [4215091018.05, 3621879183.43],
        )
        self.assertEqual(
            variants[1]["data"]["货币资金"],
            [855022551.04, 675245640.88],
        )


if __name__ == "__main__":
    unittest.main()
