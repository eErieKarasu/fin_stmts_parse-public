import json
import os
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path
from unittest.mock import Mock, patch

from apps.fin_stmts_parse.src.core.contracts import MappedStatementResult
from lwade_utils.bootload import load_entry_module


os.environ["RUNNING_ENV"] = "local"

module = load_entry_module("apps/fin_stmts_parse_mcp", "mcp", "service.py")


BALANCE_MARKDOWN = """
# 资产负债表

**编制单位：** 测试公司
**日期：** 2024-12-31
**单位：** 元

| 资产 | 行次 | 期末余额 | 年初余额 |
| :--- | :---: | :---: | :---: |
| 货币资金 | 1 | 100.50 | 90.25 |
| 应收账款 | 2 | 200.00 | 180.00 |
| 资产总计 | 30 | 300.50 | 270.25 |
"""


PROFIT_MARKDOWN = """
# 利润表

**编制单位：** 测试公司
**日期：** 2024年12月
**单位：** 元

| 项目 | 行次 | 本年累计金额 | 本期金额 |
| :--- | :---: | :---: | :---: |
| 营业总收入 | 1 | 1000.00 | 100.00 |
| 营业成本 | 2 | 700.00 | 70.00 |
| 所得税费用 | 31 | 10.00 | 1.00 |
"""


def make_parse_result(markdown_files, *, file_name="demo.pdf", company_name="测试公司", message="解析成功"):
    return [
        {
            "message": message,
            "file_name": file_name,
            "company_name": company_name,
            "markdown_files": markdown_files,
        }
    ]


def find_view_row(view_data, code):
    def visit_node(node):
        if isinstance(node, list):
            for child in node:
                found = visit_node(child)
                if found is not None:
                    return found
            return None
        if not isinstance(node, dict):
            return None
        if node.get("code") == code:
            return {
                "code": node.get("code"),
                "name": node.get("name"),
                "values": node.get("values", []),
            }
        for child in node.get("children", []):
            found = visit_node(child)
            if found is not None:
                return found
        for group in node.get("groups", []):
            found = visit_node(group)
            if found is not None:
                return found
        return None

    return visit_node(view_data)


def find_view_group(view_data, key):
    def visit_node(node):
        if isinstance(node, list):
            for child in node:
                found = visit_node(child)
                if found is not None:
                    return found
            return None
        if not isinstance(node, dict):
            return None
        if node.get("key") == key:
            return node
        for child in node.get("children", []):
            found = visit_node(child)
            if found is not None:
                return found
        for group in node.get("groups", []):
            found = visit_node(group)
            if found is not None:
                return found
        return None

    return visit_node(view_data)


class FinStmtsParseMapTests(unittest.TestCase):
    def setUp(self) -> None:
        module._clear_private_map_results_cache()
        module.map_service = None
        module.inspect_service = Mock()
        module.inspect_service.fin_stmts_parse_inspect.return_value = {
            "message": "被动勾稽校验完成",
            "inspection_passed": True,
            "details": [],
        }

    def tearDown(self) -> None:
        module.map_service = None
        module.inspect_service = None
        module._clear_private_map_results_cache()

    def test_map_requires_complete_parse_results(self):
        with self.assertRaisesRegex(ValueError, "parse_fin_stmts_markdown 的完整输出"):
            module.fin_stmts_parse_map(
                parse_results=[
                    {
                        "table_name": "资产负债表",
                        "date": "202412",
                        "content": BALANCE_MARKDOWN,
                    }
                ],
                session_id="session-1",
            )

    def test_balance_markdown_maps_with_new_file_level_contract(self):
        result = module.fin_stmts_parse_map(
            parse_results=make_parse_result(
                [
                    {
                        "table_name": "资产负债表",
                        "page": 23,
                        "date": "202412",
                        "is_consolidated": False,
                        "content": BALANCE_MARKDOWN,
                    }
                ]
            ),
            session_id="session-1",
        )

        self.assertEqual(len(result), 1)
        file_result = result[0]
        self.assertEqual(
            set(file_result.keys()),
            {"message", "file_name", "company_name", "mapped_results"},
        )
        self.assertEqual(file_result["message"], "全部 1 项 markdown 映射成功")
        self.assertEqual(file_result["file_name"], "demo.pdf")
        self.assertEqual(file_result["company_name"], "测试公司")
        item = file_result["mapped_results"][0]
        self.assertEqual(
            set(item.keys()),
            {"table_name", "table_type", "page", "date", "period", "is_consolidated", "view_data"},
        )
        self.assertEqual(item["table_name"], "资产负债表")
        self.assertEqual(item["table_type"], "balance")
        self.assertEqual(item["page"], 23)
        self.assertEqual(item["date"], "202412")
        self.assertEqual(item["period"], "YEAR")
        self.assertFalse(item["is_consolidated"])
        self.assertEqual(
            [node["key"] for node in item["view_data"]],
            ["assets", "liabilities_and_equity"],
        )
        liabilities_and_equity = find_view_group(item["view_data"], "liabilities_and_equity")
        self.assertEqual(
            [
                child.get("key") or child.get("code")
                for child in liabilities_and_equity["children"]
            ],
            [
                "current_liabilities",
                "non_current_liabilities",
                "Z02000001",
                "equity",
                "Z05010000",
            ],
        )
        self.assertIsNotNone(find_view_group(item["view_data"], "current_assets"))
        self.assertIsNotNone(find_view_group(item["view_data"], "non_current_assets"))
        self.assertEqual(
            find_view_row(item["view_data"], "Z01010100"),
            {"code": "Z01010100", "name": "货币资金", "values": ["90.25", "100.5"]},
        )
        self.assertEqual(
            find_view_row(item["view_data"], "Z01000001"),
            {"code": "Z01000001", "name": "资产总计", "values": ["270.25", "300.5"]},
        )
        self.assertEqual(
            find_view_row(item["view_data"], "Z01011100"),
            {"code": "Z01011100", "name": "其他应收款", "values": [None]},
        )
        json.dumps(result, ensure_ascii=False)

    def test_profit_markdown_maps_with_new_file_level_contract(self):
        result = module.fin_stmts_parse_map(
            parse_results=make_parse_result(
                [
                    {
                        "table_name": "利润表",
                        "date": "202412",
                        "content": PROFIT_MARKDOWN,
                    }
                ]
            ),
            session_id="session-1",
        )

        self.assertEqual(result[0]["message"], "全部 1 项 markdown 映射成功")
        self.assertEqual(result[0]["company_name"], "测试公司")
        item = result[0]["mapped_results"][0]
        self.assertEqual(item["table_name"], "利润表")
        self.assertEqual(item["table_type"], "profit")
        self.assertEqual(item["period"], "YEAR")
        self.assertFalse(item["is_consolidated"])
        self.assertEqual(
            [node["key"] for node in item["view_data"]],
            [
                "operating_revenue",
                "operating_profit",
                "total_profit",
                "net_profit",
                "other_comprehensive_income",
                "comprehensive_income",
                "earnings_per_share",
            ],
        )
        self.assertIsNotNone(find_view_group(item["view_data"], "operating_revenue"))
        self.assertEqual(
            find_view_row(item["view_data"], "L00000000"),
            {"code": "L00000000", "name": "营业总收入", "values": [None, "1000.0"]},
        )
        self.assertEqual(
            find_view_row(item["view_data"], "L04010000"),
            {"code": "L04010000", "name": "营业利润", "values": [None, None]},
        )

    def test_map_preserves_null_and_empty_values_in_private_canonical_data(self):
        service = module.get_map_service()
        mapped_result = MappedStatementResult(
            statement_type="balance",
            table_name="资产负债表",
            date="202412",
            is_consolidated=False,
            canonical_data_full={
                "Z01030003": [Decimal("398345.12"), Decimal("273072.44")],
                "Z01030004": ["", ""],
                "Z01030005": [None, ""],
            },
            canonical_labels={
                "Z01030003": "固定资产净值",
                "Z01030004": "固定资产减值准备",
                "Z01030005": "固定资产净额",
            },
            view_data_full={},
            view_labels={},
        )

        with patch.object(service.map_core, "map_markdown_document", return_value=mapped_result):
            result = module.fin_stmts_parse_map(
                parse_results=make_parse_result(
                    [
                        {
                            "table_name": "资产负债表",
                            "date": "202412",
                            "content": BALANCE_MARKDOWN,
                        }
                    ]
                ),
                session_id="session-1",
            )

        item = result[0]["mapped_results"][0]
        self.assertNotIn("canonical_data", item)
        self.assertEqual(item["view_data"], [])
        private_result = module.inspect_service.fin_stmts_parse_inspect.call_args.kwargs["map_results"][0]
        private_item = private_result["mapped_results"][0]
        self.assertEqual(
            private_item["canonical_data"]["Z01030003"],
            ["固定资产净值", "398345.12", "273072.44"],
        )
        self.assertEqual(
            private_item["canonical_data"]["Z01030004"],
            ["固定资产减值准备", "", ""],
        )
        self.assertEqual(
            private_item["canonical_data"]["Z01030005"],
            ["固定资产净额", None, ""],
        )

    def test_map_infers_company_name_from_markdown_with_llm(self):
        with patch.object(module.CompanyNameResolver, "_extract_with_llm", return_value="测试公司"):
            result = module.fin_stmts_parse_map(
                parse_results=make_parse_result(
                    [
                        {
                            "table_name": "利润表",
                            "date": "202412",
                            "content": PROFIT_MARKDOWN,
                        }
                    ],
                    company_name="",
                ),
                session_id="session-1",
            )

        self.assertEqual(result[0]["company_name"], "测试公司")

    def test_map_falls_back_to_rules_when_llm_returns_empty(self):
        with patch.object(module.CompanyNameResolver, "_extract_with_llm", return_value=""):
            result = module.fin_stmts_parse_map(
                parse_results=make_parse_result(
                    [
                        {
                            "table_name": "资产负债表",
                            "date": "202412",
                            "content": BALANCE_MARKDOWN,
                        }
                    ],
                    company_name="",
                ),
                session_id="session-1",
            )

        self.assertEqual(result[0]["company_name"], "测试公司")

    def test_special_html_tables_map_without_private_intermediate_data(self):
        result = module.fin_stmts_parse_map(
            parse_results=make_parse_result(
                [
                    {
                        "table_name": "资产负债表",
                        "date": "202512",
                        "is_consolidated": False,
                        "content": (
                            "<table>"
                            "<tr><td></td><td>行次</td><td>年初数</td><td>期末数</td>"
                            "<td>负债及所有者权益</td><td>行次</td><td>年初数</td><td>期末数</td></tr>"
                            "<tr><td>货币资金</td><td>1</td><td>557647747.48</td><td>688211360.94</td>"
                            "<td>应付票据</td><td>29</td><td>528000000.00</td><td>643800000.00</td></tr>"
                            "<tr><td>资产总计</td><td>27</td><td>619481514.39</td><td>744427156.09</td>"
                            "<td>负债及所有者权益合计</td><td>54</td><td>619481514.39</td><td>744427156.09</td></tr>"
                            "</table>"
                        ),
                    },
                    {
                        "table_name": "现金流量表",
                        "date": "202512",
                        "is_consolidated": False,
                        "content": (
                            "<table>"
                            "<tr><td>项目</td><td>行次</td><td>金额</td><td>补充资料</td><td>行次</td><td>金额</td></tr>"
                            "<tr><td>销售商品、提供劳务收到的现金</td><td>1</td><td>1726639479.36</td>"
                            "<td>净利润</td><td>57</td><td>23967915.26</td></tr>"
                            "<tr><td>经营活动产生的现金流量净额</td><td>21</td><td>130573613.46</td>"
                            "<td>经营活动产生的现金流量净额</td><td>75</td><td>130573613.46</td></tr>"
                            "</table>"
                        ),
                    },
                ]
            ),
            session_id="session-1",
        )

        self.assertEqual(result[0]["message"], "全部 2 项 markdown 映射成功")
        balance_item, cashflow_item = result[0]["mapped_results"]
        self.assertEqual(
            find_view_row(balance_item["view_data"], "Z01010100"),
            {
                "code": "Z01010100",
                "name": "货币资金",
                "values": ["557647747.48", "688211360.94"],
            },
        )
        self.assertEqual(
            find_view_row(cashflow_item["view_data"], "X01010000"),
            {
                "code": "X01010000",
                "name": "销售商品、提供劳务收到的现金",
                "values": [None, "1726639479.36"],
            },
        )
        self.assertEqual(
            [node["key"] for node in cashflow_item["view_data"]],
            [
                "operating_cash_flow",
                "investing_cash_flow",
                "financing_cash_flow",
                "exchange_rate_effect",
                "net_cash_increase",
                "end_cash_and_cash_equivalents",
            ],
        )
        operating_inflow = find_view_group(cashflow_item["view_data"], "X01040000")
        self.assertIsNotNone(operating_inflow)
        self.assertEqual(
            [child.get("code") for child in operating_inflow["children"]],
            ["X01010000", "X01020000", "X01030000"],
        )
        self.assertEqual(
            find_view_row(cashflow_item["view_data"], "X06010000"),
            {
                "code": "X06010000",
                "name": "期末现金及现金等价物余额",
                "values": [None, None],
            },
        )
        self.assertEqual(
            find_view_row(cashflow_item["view_data"], "X01100000"),
            {
                "code": "X01100000",
                "name": "经营活动产生的现金流量净额",
                "values": [None, "130573613.46"],
            },
        )

    def test_mapping_config_dir_override_uses_provided_directory(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_dir = Path(temp_dir) / "custom_balance"
            config_dir.mkdir()
            (config_dir / "semantic.yaml").write_text(
                "semantic_items:\n"
                "  - code: \"CUSTOM_BALANCE_CASH\"\n"
                "    name: \"货币资金\"\n",
                encoding="utf-8",
            )
            (config_dir / "view.yaml").write_text(
                "view_data:\n"
                "  - code: \"CUSTOM_BALANCE_CASH\"\n"
                "    name: \"货币资金\"\n",
                encoding="utf-8",
            )

            result = module.fin_stmts_parse_map(
                parse_results=make_parse_result(
                    [
                        {
                            "table_name": "资产负债表",
                            "date": "202412",
                            "is_consolidated": False,
                            "content": BALANCE_MARKDOWN,
                            "mapping_config_dir": str(config_dir),
                        }
                    ]
                ),
                session_id="session-1",
            )

        self.assertEqual(result[0]["message"], "全部 1 项 markdown 映射成功")
        item = result[0]["mapped_results"][0]
        self.assertEqual(
            item["view_data"],
            [
                {
                    "type": "row",
                    "code": "CUSTOM_BALANCE_CASH",
                    "name": "货币资金",
                    "values": ["90.25", "100.5"],
                },
            ],
        )

    def test_map_requires_session_id(self):
        with self.assertRaisesRegex(ValueError, "session_id 不能为空"):
            module.fin_stmts_parse_map(
                make_parse_result(
                    [
                        {
                            "table_name": "资产负债表",
                            "date": "202412",
                            "content": BALANCE_MARKDOWN,
                        }
                    ]
                ),
                session_id="",
            )

    def test_map_auto_triggers_passive_inspect(self):
        result = module.fin_stmts_parse_map(
            make_parse_result(
                [
                    {
                        "table_name": "资产负债表",
                        "date": "202412",
                        "content": BALANCE_MARKDOWN,
                    }
                ]
            ),
            session_id="session-1",
        )

        module.inspect_service.fin_stmts_parse_inspect.assert_called_once()
        private_map_results = module.inspect_service.fin_stmts_parse_inspect.call_args.kwargs["map_results"]
        self.assertEqual(private_map_results[0]["file_name"], result[0]["file_name"])
        self.assertEqual(private_map_results[0]["company_name"], result[0]["company_name"])
        private_item = private_map_results[0]["mapped_results"][0]
        public_item = result[0]["mapped_results"][0]
        self.assertIn("canonical_data", private_item)
        self.assertNotIn("canonical_data", public_item)
        self.assertEqual(
            module.inspect_service.fin_stmts_parse_inspect.call_args.kwargs["session_id"],
            "session-1",
        )
        self.assertEqual(
            module.inspect_service.fin_stmts_parse_inspect.call_args.kwargs["report_status"],
            "0",
        )

    def test_map_returns_results_when_passive_inspect_fails(self):
        module.inspect_service.fin_stmts_parse_inspect.side_effect = RuntimeError("inspect down")

        with patch.object(module.logger, "warning") as log_warning:
            result = module.fin_stmts_parse_map(
                make_parse_result(
                    [
                        {
                            "table_name": "资产负债表",
                            "date": "202412",
                            "content": BALANCE_MARKDOWN,
                        }
                    ]
                ),
                session_id="session-1",
            )

        self.assertEqual(result[0]["message"], "全部 1 项 markdown 映射成功")
        log_warning.assert_called_once()
        self.assertIn("map 后触发被动勾稽校验失败", log_warning.call_args.args[0])

    def test_tool_returns_one_top_level_result_per_input_file(self):
        parse_results = [
            {
                "message": "解析成功",
                "file_name": "one.pdf",
                "company_name": "公司甲",
                "markdown_files": [
                    {
                        "table_name": "资产负债表",
                        "date": "202412",
                        "content": BALANCE_MARKDOWN,
                    }
                ],
            },
            {
                "message": "未识别到财报表格内容",
                "file_name": "two.pdf",
                "company_name": "",
                "markdown_files": [],
            },
        ]

        result = module.fin_stmts_parse_map(parse_results, session_id="session-1")

        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]["file_name"], "one.pdf")
        self.assertEqual(result[0]["company_name"], "公司甲")
        self.assertEqual(result[1]["message"], "没有可映射的 markdown_files")
        self.assertEqual(result[1]["file_name"], "two.pdf")
        self.assertEqual(result[1]["mapped_results"], [])


if __name__ == "__main__":
    unittest.main()
