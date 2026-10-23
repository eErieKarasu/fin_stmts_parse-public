import unittest

from apps.fin_stmts_parse.src.financial_inspector import FinancialInspector


class FinancialInspectorTest(unittest.TestCase):
    def setUp(self) -> None:
        self.inspector = FinancialInspector()

    def test_balance_basic_check_passes_when_total_equals_direct_children(self) -> None:
        result = self.inspector.inspect_view(
            {
                "balance": {
                    "Z01010001": [100, 120],
                    "Z01010100": [60, 70],
                    "Z01010610": [40, 50],
                },
                "profit": {},
                "cashflow": {},
            }
        )

        details = {detail["check"]: detail for detail in result["details"]}
        self.assertFalse(result["passed"])
        self.assertEqual(result["total_checks"], 20)
        self.assertEqual(result["passed_checks"], 2)
        self.assertEqual(result["failed_checks"], 18)
        self.assertEqual(result["skipped_checks"], 0)
        self.assertEqual(details["流动资产合计(年初)"]["result"], "pass")
        self.assertEqual(details["流动资产合计(期末)"]["result"], "pass")

    def test_balance_failure_marks_total_and_participating_direct_children_as_suspects(self) -> None:
        result = self.inspector.inspect_view(
            {
                "balance": {
                    "Z01010001": [90, 90],
                    "Z01010100": [60, 60],
                    "Z01011100": [20, 20],
                    "Z01011210": [30, 30],
                    "Z01010500": [999, 999],
                    "Z01010400": [888, 888],
                },
                "profit": {},
                "cashflow": {},
            }
        )

        details = {detail["check"]: detail for detail in result["details"]}
        year_start = details["流动资产合计(年初)"]
        year_end = details["流动资产合计(期末)"]

        self.assertFalse(result["passed"])
        self.assertEqual(year_start["result"], "fail")
        self.assertEqual(year_end["result"], "fail")
        self.assertEqual(
            [item["code"] for item in year_start["suspects"]],
            ["Z01010001", "Z01010100", "Z01011100", "Z01011210"],
        )
        self.assertEqual(
            [item["name"] for item in year_start["suspects"]],
            ["流动资产合计", "货币资金", "其他应收款", "存货"],
        )

    def test_nested_breakdown_items_do_not_participate_in_parent_total_check(self) -> None:
        result = self.inspector.inspect_view(
            {
                "balance": {
                    "Z01010001": [80, 100],
                    "Z01010100": [30, 40],
                    "Z01011100": [50, 60],
                    "Z01010500": [10, 10],
                    "Z01010400": [20, 20],
                },
                "profit": {},
                "cashflow": {},
            }
        )

        details = {detail["check"]: detail for detail in result["details"]}
        self.assertEqual(details["流动资产合计(年初)"]["result"], "pass")
        self.assertEqual(details["流动资产合计(期末)"]["result"], "pass")
        self.assertEqual(
            set(details["流动资产合计(年初)"]["components"]),
            {"Z01010100", "Z01011100"},
        )
        self.assertNotIn("Z01010500", details["流动资产合计(年初)"]["components"])
        self.assertNotIn("Z01010400", details["流动资产合计(年初)"]["components"])

    def test_other_receivables_breakdown_is_checked_when_children_are_present(self) -> None:
        result = self.inspector.inspect_view(
            {
                "balance": {
                    "Z01011100": [30, 40],
                    "Z01010500": [10, 15],
                    "Z01010400": [20, 25],
                },
                "profit": {},
                "cashflow": {},
            }
        )

        details = {detail["check"]: detail for detail in result["details"]}
        year_start = details["其他应收款(年初)"]
        year_end = details["其他应收款(期末)"]

        self.assertEqual(year_start["result"], "pass")
        self.assertEqual(year_end["result"], "pass")
        self.assertEqual(
            set(year_start["components"]),
            {"Z01010500", "Z01010400"},
        )
        self.assertTrue(year_start["_display_on_components"])

    def test_other_receivables_breakdown_fails_before_semantic_attribution(self) -> None:
        result = self.inspector.inspect_view(
            {
                "balance": {
                    "Z01011100": [35, 40],
                    "Z01010500": [10, 15],
                    "Z01010400": [20, 25],
                },
                "profit": {},
                "cashflow": {},
            }
        )

        details = {detail["check"]: detail for detail in result["details"]}
        year_start = details["其他应收款(年初)"]

        self.assertEqual(year_start["result"], "fail")
        self.assertEqual(year_start["expected"], "30")
        self.assertEqual(
            [item["code"] for item in year_start["suspects"]],
            ["Z01011100", "Z01010500", "Z01010400"],
        )

    def test_other_receivables_breakdown_is_not_run_when_children_are_absent(self) -> None:
        result = self.inspector.inspect_view(
            {
                "balance": {
                    "Z01011100": [30, 40],
                },
                "profit": {},
                "cashflow": {},
            }
        )

        details = {detail["check"]: detail for detail in result["details"]}
        self.assertNotIn("其他应收款(年初)", details)
        self.assertNotIn("其他应收款(期末)", details)

    def test_other_receivables_breakdown_is_not_run_when_children_are_unextracted(self) -> None:
        result = self.inspector.inspect_view(
            {
                "balance": {
                    "Z01011100": [30, 40],
                    "Z01010500": [None, None],
                    "Z01010400": [None, None],
                },
                "profit": {},
                "cashflow": {},
            }
        )

        details = {detail["check"]: detail for detail in result["details"]}
        self.assertNotIn("其他应收款(年初)", details)
        self.assertNotIn("其他应收款(期末)", details)

    def test_other_receivables_breakdown_is_not_run_when_children_are_empty(self) -> None:
        result = self.inspector.inspect_view(
            {
                "balance": {
                    "Z01011100": [0, 0],
                    "Z01010500": ["", ""],
                    "Z01010400": ["", ""],
                },
                "profit": {},
                "cashflow": {},
            }
        )

        details = {detail["check"]: detail for detail in result["details"]}
        self.assertNotIn("其他应收款(年初)", details)
        self.assertNotIn("其他应收款(期末)", details)

    def test_other_payables_breakdown_is_checked_when_children_are_present(self) -> None:
        result = self.inspector.inspect_view(
            {
                "balance": {
                    "ZG2010800": [70, 90],
                    "Z02010107": [30, 40],
                    "Z02010700": [40, 50],
                },
                "profit": {},
                "cashflow": {},
            }
        )

        details = {detail["check"]: detail for detail in result["details"]}
        year_start = details["其他应付款(年初)"]
        year_end = details["其他应付款(期末)"]

        self.assertEqual(year_start["result"], "pass")
        self.assertEqual(year_end["result"], "pass")
        self.assertEqual(
            set(year_start["components"]),
            {"Z02010107", "Z02010700"},
        )

    def test_current_liabilities_passes_parallel_other_payables_track(self) -> None:
        result = self.inspector.inspect_view(
            {
                "balance": {
                    "Z02010001": [18, 25],
                    "Z02010100": [10, 12],
                    "ZG2010800": [5, 7],
                    "Z02010107": [1, 2],
                    "Z02010700": [2, 4],
                },
                "profit": {},
                "cashflow": {},
            }
        )

        details = {detail["check"]: detail for detail in result["details"]}
        current_liabilities = details["流动负债合计(年初)"]
        other_payables = details["其他应付款(年初)"]

        self.assertEqual(current_liabilities["result"], "pass")
        self.assertEqual(current_liabilities["reason"], "已按并列科目口径复核通过")
        self.assertEqual(current_liabilities["expected"], "18")
        self.assertEqual(
            current_liabilities["attribution"]["mode"],
            "parallel_components_match",
        )
        self.assertEqual(other_payables["result"], "pass")
        self.assertEqual(
            other_payables["reason"],
            "已按流动负债合计并列科目口径复核通过",
        )

    def test_other_payables_child_check_passes_when_single_track_parent_total_matches(self) -> None:
        result = self.inspector.inspect_view(
            {
                "balance": {
                    "Z02010001": [15, 19],
                    "Z02010100": [10, 12],
                    "ZG2010800": [5, 7],
                    "Z02010107": [1, 2],
                    "Z02010700": [2, 4],
                },
                "profit": {},
                "cashflow": {},
            }
        )

        details = {detail["check"]: detail for detail in result["details"]}
        current_liabilities = details["流动负债合计(年初)"]
        other_payables = details["其他应付款(年初)"]

        self.assertEqual(current_liabilities["result"], "pass")
        self.assertEqual(current_liabilities["reason"], "校验通过")
        self.assertEqual(other_payables["result"], "pass")
        self.assertEqual(
            other_payables["reason"],
            "已按流动负债合计单项科目口径复核通过",
        )

    def test_other_payables_breakdown_is_not_run_when_children_are_empty(self) -> None:
        result = self.inspector.inspect_view(
            {
                "balance": {
                    "ZG2010800": [0, 0],
                    "Z02010107": ["", ""],
                    "Z02010700": ["", ""],
                },
                "profit": {},
                "cashflow": {},
            }
        )

        details = {detail["check"]: detail for detail in result["details"]}
        self.assertNotIn("其他应付款(年初)", details)
        self.assertNotIn("其他应付款(期末)", details)

    def test_other_equity_instruments_breakdown_is_checked_when_children_are_present(self) -> None:
        result = self.inspector.inspect_view(
            {
                "balance": {
                    "Z04020300": [80, 100],
                    "Z04020400": [30, 40],
                    "Z04020500": [50, 60],
                },
                "profit": {},
                "cashflow": {},
            }
        )

        details = {detail["check"]: detail for detail in result["details"]}
        year_start = details["其他权益工具(年初)"]
        year_end = details["其他权益工具(期末)"]

        self.assertEqual(year_start["result"], "pass")
        self.assertEqual(year_end["result"], "pass")
        self.assertEqual(
            set(year_start["components"]),
            {"Z04020400", "Z04020500"},
        )

    def test_optional_balance_breakdowns_are_not_run_when_children_are_absent(self) -> None:
        result = self.inspector.inspect_view(
            {
                "balance": {
                    "ZG2010800": [70, 90],
                    "Z04020300": [80, 100],
                },
                "profit": {},
                "cashflow": {},
            }
        )

        details = {detail["check"]: detail for detail in result["details"]}
        self.assertNotIn("其他应付款(年初)", details)
        self.assertNotIn("其他应付款(期末)", details)
        self.assertNotIn("其他权益工具(年初)", details)
        self.assertNotIn("其他权益工具(期末)", details)

    def test_optional_balance_breakdown_is_not_run_when_parent_and_children_are_unextracted(self) -> None:
        result = self.inspector.inspect_view(
            {
                "balance": {
                    "Z04020300": [None, None],
                    "Z04020400": [None, None],
                    "Z04020500": [None, None],
                },
                "profit": {},
                "cashflow": {},
            }
        )

        details = {detail["check"]: detail for detail in result["details"]}
        self.assertNotIn("其他权益工具(年初)", details)
        self.assertNotIn("其他权益工具(期末)", details)

    def test_consolidated_parent_equity_subtracts_treasury_stock(self) -> None:
        result = self.inspector.inspect_view(
            {
                "balance": {
                    "Z04030400": [154, 154],
                    "Z04020200": [100, 100],
                    "Z04020300": [10, 10],
                    "Z04020000": [50, 50],
                    "Z04020600": [6, 6],
                    "Z04020700": [1, 1],
                    "Z04020800": [2, 2],
                    "Z04030000": [3, 3],
                    "Z04050000": [-6, -6],
                    "Z03000000": [10, 10],
                    "Z04020110": [164, 164],
                },
                "profit": {},
                "cashflow": {},
            }
        )

        details = {detail["check"]: detail for detail in result["details"]}
        detail = details["归属于母公司所有者权益（或股东权益）合计(期末)"]

        self.assertEqual(detail["result"], "pass")
        self.assertEqual(detail["expected"], "154")
        self.assertEqual(detail["components"]["Z04020600"]["value"], "-6")
        self.assertEqual(detail["components"]["Z04020600"]["operator"], "-")

    def test_consolidated_equity_total_equals_parent_equity_plus_minority(self) -> None:
        result = self.inspector.inspect_view(
            {
                "balance": {
                    "Z04030400": [154, 154],
                    "Z03000000": [10, 10],
                    "Z04020110": [164, 164],
                },
                "profit": {},
                "cashflow": {},
            }
        )

        details = {detail["check"]: detail for detail in result["details"]}
        detail = details[
            "所有者权益（或股东权益）合计 = 归属于母公司所有者权益（或股东权益）合计 + 少数股东权益(期末)"
        ]

        self.assertEqual(detail["result"], "pass")
        self.assertEqual(detail["expected"], "164")

    def test_absent_minority_equity_is_checked_as_zero_with_inferred_parent_equity(self) -> None:
        result = self.inspector.inspect_view(
            {
                "balance": {
                    "Z04020110": [164, 164],
                    "Z04030400": [None, None],
                    "Z03000000": [None, None],
                    "Z04020200": [100, 100],
                    "Z04020000": [50, 50],
                    "Z04050000": [14, 14],
                },
                "profit": {},
                "cashflow": {},
            }
        )

        details = {detail["check"]: detail for detail in result["details"]}

        self.assertEqual(
            details["所有者权益（或股东权益）合计(期末)"]["result"],
            "pass",
        )
        parent_equity = details["归属于母公司所有者权益（或股东权益）合计(期末)"]
        self.assertEqual(parent_equity["result"], "fail")
        self.assertEqual(parent_equity["_inferred_total"], "164")

        consolidated_equity = details[
            "所有者权益（或股东权益）合计 = 归属于母公司所有者权益（或股东权益）合计 + 少数股东权益(期末)"
        ]
        self.assertEqual(consolidated_equity["result"], "pass")
        self.assertEqual(
            consolidated_equity["components"]["Z04030400"]["source"],
            "inferred",
        )
        self.assertEqual(
            consolidated_equity["components"]["Z03000000"]["source"],
            "inferred_zero",
        )
        self.assertEqual(consolidated_equity["attribution"]["culprit_codes"], ["Z03000000"])

    def test_missing_total_fails_in_view_based_inspection(self) -> None:
        result = self.inspector.inspect_view(
            {
                "balance": {
                    "Z01010100": [60, 70],
                },
                "profit": {},
                "cashflow": {},
            }
        )

        details = {detail["check"]: detail for detail in result["details"]}
        self.assertEqual(details["流动资产合计(年初)"]["result"], "fail")
        self.assertEqual(details["流动资产合计(期末)"]["result"], "fail")
        self.assertEqual(
            details["流动资产合计(年初)"]["reason"],
            "合计项缺失，但可由已提取子项推导",
        )
        self.assertEqual(
            [item["code"] for item in details["流动资产合计(年初)"]["suspects"]],
            ["Z01010001"],
        )

    def test_balance_hierarchical_check_blames_reported_asset_total_when_children_pass(self) -> None:
        result = self.inspector.inspect_view(
            {
                "balance": {
                    "Z01000001": [280, 300],
                    "Z01010001": [100, 120],
                    "Z01010100": [60, 70],
                    "Z01010610": [40, 50],
                    "ZY2015058": [200, 190],
                    "Z01030000": [200, 190],
                },
                "profit": {},
                "cashflow": {},
            }
        )

        details = {detail["check"]: detail for detail in result["details"]}
        hierarchical = details["资产总计 = 流动资产合计 + 非流动资产合计(期末)"]

        self.assertEqual(hierarchical["result"], "fail")
        self.assertEqual(
            hierarchical["reason"],
            "下级合计均通过，但资产总计与其和不一致，疑似资产总计字段有误",
        )
        self.assertEqual(
            [item["code"] for item in hierarchical["suspects"]],
            ["Z01000001"],
        )
        self.assertEqual(hierarchical["attribution"]["culprit_code"], "Z01000001")

    def test_balance_hierarchical_check_blames_failed_current_assets_total_when_recomputed_fits(self) -> None:
        result = self.inspector.inspect_view(
            {
                "balance": {
                    "Z01000001": [300, 310],
                    "Z01010001": [90, 100],
                    "Z01010100": [60, 70],
                    "Z01010610": [40, 50],
                    "ZY2015058": [200, 190],
                    "Z01030000": [200, 190],
                },
                "profit": {},
                "cashflow": {},
            }
        )

        details = {detail["check"]: detail for detail in result["details"]}
        base = details["流动资产合计(期末)"]
        hierarchical = details["资产总计 = 流动资产合计 + 非流动资产合计(期末)"]

        self.assertEqual(base["result"], "fail")
        self.assertEqual(hierarchical["result"], "fail")
        self.assertEqual(
            hierarchical["reason"],
            "使用流动资产合计的子项重算值后等式成立，疑似流动资产合计字段有误",
        )
        self.assertEqual(
            [item["code"] for item in hierarchical["suspects"]],
            ["Z01010001"],
        )
        self.assertEqual(hierarchical["attribution"]["culprit_code"], "Z01010001")

    def test_balance_hierarchical_check_blames_reported_liability_equity_total_when_children_pass(self) -> None:
        result = self.inspector.inspect_view(
            {
                "balance": {
                    "Z05010000": [290, 300],
                    "Z02010001": [100, 110],
                    "Z02010100": [100, 110],
                    "ZY2015061": [90, 100],
                    "Z02020100": [90, 100],
                    "Z04020110": [95, 105],
                    "Z04020200": [95, 105],
                },
                "profit": {},
                "cashflow": {},
            }
        )

        details = {detail["check"]: detail for detail in result["details"]}
        hierarchical = details[
            "负债和所有者权益（或股东权益）总计 = 流动负债合计 + 非流动负债合计 + 所有者权益（或股东权益）合计(期末)"
        ]

        self.assertEqual(hierarchical["result"], "fail")
        self.assertEqual(
            hierarchical["reason"],
            "下级合计均通过，但负债和所有者权益（或股东权益）总计与其和不一致，疑似负债和所有者权益（或股东权益）总计字段有误",
        )
        self.assertEqual(
            [item["code"] for item in hierarchical["suspects"]],
            ["Z05010000"],
        )

    def test_balance_hierarchical_checks_liability_equity_total_against_liability_total_and_assets(self) -> None:
        result = self.inspector.inspect_view(
            {
                "balance": {
                    "Z01000001": [300, 315],
                    "Z05010000": [300, 315],
                    "Z02000001": [190, 210],
                    "Z02010001": [100, 110],
                    "ZY2015061": [90, 100],
                    "Z04020110": [110, 105],
                },
                "profit": {},
                "cashflow": {},
            }
        )

        details = {detail["check"]: detail for detail in result["details"]}
        self.assertEqual(
            details[
                "负债和所有者权益（或股东权益）总计 = 负债合计 + 所有者权益（或股东权益）合计(期末)"
            ]["result"],
            "pass",
        )
        self.assertEqual(
            details["负债和所有者权益（或股东权益）总计 = 资产总计(期末)"]["result"],
            "pass",
        )

    def test_balance_hierarchical_check_blames_failed_current_liability_total_when_recomputed_fits(self) -> None:
        result = self.inspector.inspect_view(
            {
                "balance": {
                    "Z05010000": [290, 315],
                    "Z02010001": [95, 100],
                    "Z02010100": [100, 110],
                    "ZY2015061": [90, 100],
                    "Z02020100": [90, 100],
                    "Z04020110": [95, 105],
                    "Z04020200": [95, 105],
                },
                "profit": {},
                "cashflow": {},
            }
        )

        details = {detail["check"]: detail for detail in result["details"]}
        hierarchical = details[
            "负债和所有者权益（或股东权益）总计 = 流动负债合计 + 非流动负债合计 + 所有者权益（或股东权益）合计(期末)"
        ]
        self.assertEqual(hierarchical["result"], "fail")
        self.assertEqual(
            hierarchical["reason"],
            "使用流动负债合计的子项重算值后等式成立，疑似流动负债合计字段有误",
        )
        self.assertEqual(
            [item["code"] for item in hierarchical["suspects"]],
            ["Z02010001"],
        )

    def test_balance_hierarchical_check_blames_multiple_failed_subtotals_when_all_recomputed_fit(self) -> None:
        result = self.inspector.inspect_view(
            {
                "balance": {
                    "Z05010000": [311, 330],
                    "Z02010001": [104, 107],
                    "Z02010100": [100, 110],
                    "ZY2015061": [92, 96],
                    "Z02020100": [90, 100],
                    "Z04020110": [115, 115],
                    "Z04020200": [115, 120],
                },
                "profit": {},
                "cashflow": {},
            }
        )

        details = {detail["check"]: detail for detail in result["details"]}
        hierarchical = details[
            "负债和所有者权益（或股东权益）总计 = 流动负债合计 + 非流动负债合计 + 所有者权益（或股东权益）合计(期末)"
        ]
        self.assertEqual(hierarchical["result"], "fail")
        self.assertEqual(
            hierarchical["reason"],
            "使用多个中间合计的子项重算值后等式成立，疑似这些中间合计字段有误，负债和所有者权益（或股东权益）总计大概率正确",
        )
        self.assertEqual(
            [item["code"] for item in hierarchical["suspects"]],
            ["Z02010001", "ZY2015061", "Z04020110"],
        )
        self.assertEqual(
            hierarchical["attribution"]["mode"],
            "multiple_component_recomputed_match",
        )

    def test_balance_hierarchical_check_reports_multi_field_or_detail_error_when_no_single_point_attribution(self) -> None:
        result = self.inspector.inspect_view(
            {
                "balance": {
                    "Z05010000": [290, 318],
                    "Z02010001": [95, 100],
                    "Z02010100": [100, 110],
                    "ZY2015061": [85, 95],
                    "Z02020100": [90, 100],
                    "Z04020110": [95, 105],
                    "Z04020200": [95, 105],
                },
                "profit": {},
                "cashflow": {},
            }
        )

        details = {detail["check"]: detail for detail in result["details"]}
        hierarchical = details[
            "负债和所有者权益（或股东权益）总计 = 流动负债合计 + 非流动负债合计 + 所有者权益（或股东权益）合计(期末)"
        ]
        self.assertEqual(hierarchical["result"], "fail")
        self.assertEqual(
            hierarchical["reason"],
            "层级校验未通过，且无法单点归因，可能存在多个字段或明细项错误",
        )

    def test_balance_basic_check_uses_semantic_fixed_asset_inference_for_non_current_assets(self) -> None:
        result = self.inspector.inspect_view(
            {
                "balance": {
                    "Z01000001": [598345.12, 493072.44],
                    "Z01010001": [100000, 120000],
                    "ZY2015058": [498345.12, 373072.44],
                    "Z01030000": [0, 0],
                    "Z01040100": [100000, 100000],
                },
                "profit": {},
                "cashflow": {},
            },
            semantic_merged_data={
                "balance": {
                    "Z01030001": [659330.00, 659330.00],
                    "Z01030002": [260984.88, 386257.56],
                    "Z01030003": [398345.12, 273072.44],
                    "Z01030004": ["", ""],
                    "Z01030005": [0, 0],
                }
            },
        )

        details = {detail["check"]: detail for detail in result["details"]}
        non_current_assets = details["非流动资产合计(期末)"]
        self.assertEqual(non_current_assets["result"], "fail")
        self.assertEqual(
            non_current_assets["reason"],
            "使用固定资产内部勾稽推理值后等式成立，疑似固定资产字段有误",
        )
        self.assertEqual(
            [item["code"] for item in non_current_assets["suspects"]],
            ["Z01030000"],
        )
        self.assertEqual(
            non_current_assets["semantic_attribution"]["culprit_code"],
            "Z01030000",
        )
        self.assertEqual(
            non_current_assets["semantic_attribution"]["inferred_value"],
            "273072.44",
        )
        self.assertTrue(
            non_current_assets["semantic_attribution"]["validation_chain"]["supports_parent_check"]
        )
        self.assertTrue(
            non_current_assets["semantic_attribution"]["validation_chain"]["supports_grandparent_check"]
        )

    def test_non_current_assets_failure_excludes_semantically_verified_fixed_asset(self) -> None:
        result = self.inspector.inspect_view(
            {
                "balance": {
                    "ZY2015058": [450, 450],
                    "Z01030000": [300, 300],
                    "Z01040100": [100, 100],
                },
                "profit": {},
                "cashflow": {},
            },
            semantic_merged_data={
                "balance": {
                    "Z01030001": [400, 400],
                    "Z01030002": [100, 100],
                    "Z01030003": [300, 300],
                    "Z01030004": ["", ""],
                    "Z01030005": [300, 300],
                }
            },
        )

        details = {detail["check"]: detail for detail in result["details"]}
        non_current_assets = details["非流动资产合计(年初)"]

        self.assertEqual(non_current_assets["result"], "fail")
        self.assertEqual(
            [item["code"] for item in non_current_assets["suspects"]],
            ["ZY2015058", "Z01040100"],
        )
        verified = non_current_assets["verified_components"][0]
        self.assertEqual(verified["code"], "Z01030000")
        self.assertEqual(verified["name"], "固定资产")
        self.assertEqual(verified["source"], "semantic_formula")
        self.assertEqual(verified["inferred_value"], "300")
        self.assertEqual(
            verified["trace"]["formula"],
            "固定资产净额 = 固定资产净值 - 固定资产减值准备; 固定资产净值 = 固定资产原价 - 累计折旧",
        )

    def test_missing_non_current_assets_total_uses_fixed_asset_inference_and_asset_total_validation(self) -> None:
        result = self.inspector.inspect_view(
            {
                "balance": {
                    "Z01000001": [224086608.04, 224086608.04],
                    "Z01010001": [223688262.92, 223688262.92],
                    "Z01010100": [150098824.64, 150098824.64],
                    "Z01010610": [61783326.60, 61783326.60],
                    "Z01011100": [46757.27, 46757.27],
                    "Z01010611": [1423734.23, 1423734.23],
                    "Z01011210": [10335620.18, 10335620.18],
                    "Z01030000": [0, 0],
                },
                "profit": {},
                "cashflow": {},
            },
            semantic_merged_data={
                "balance": {
                    "Z01030001": [659330.00, 659330.00],
                    "Z01030002": [260984.88, 260984.88],
                    "Z01030003": [398345.12, 398345.12],
                    "Z01030004": ["", ""],
                    "Z01030005": [0, 0],
                }
            },
        )

        details = {detail["check"]: detail for detail in result["details"]}
        non_current_assets = details["非流动资产合计(期末)"]
        asset_total = details["资产总计 = 流动资产合计 + 非流动资产合计(期末)"]

        self.assertEqual(non_current_assets["result"], "fail")
        self.assertEqual(
            [item["code"] for item in non_current_assets["suspects"]],
            ["ZY2015058", "Z01030000"],
        )
        self.assertEqual(non_current_assets["_inferred_total"], "398345.12")
        self.assertEqual(
            non_current_assets["semantic_attribution"]["inferred_value"],
            "398345.12",
        )
        self.assertTrue(
            non_current_assets["semantic_attribution"]["validation_chain"]["supports_grandparent_check"]
        )
        self.assertEqual(asset_total["result"], "pass")
        self.assertEqual(asset_total["reason"], "使用缺失下级合计的推导值后校验通过")
        self.assertEqual(
            [item["code"] for item in asset_total["suspects"]],
            [],
        )
        self.assertEqual(
            asset_total["attribution"]["mode"],
            "missing_component_inferred_match",
        )

    def test_missing_non_current_assets_total_includes_old_long_term_investment_without_fixed_asset_blame(self) -> None:
        result = self.inspector.inspect_view(
            {
                "balance": {
                    "Z01000001": ["2347987161.49", "3338681675.00"],
                    "Z01010001": ["709879728.34", "809843709.49"],
                    "Z01020110": [None, None],
                    "ZY2015109": [None, None],
                    "ZY2015073": [None, None],
                    "ZY2015074": [None, None],
                    "ZY2015110": [None, None],
                    "Z01020121": ["51284469.51", "52484415.51"],
                    "Z01030000": ["1384256669.98", "2165899605.26"],
                    "Z01030300": ["151584698.55", "254572349.63"],
                    "Z01040100": ["45881595.11", "45881595.11"],
                },
                "profit": {},
                "cashflow": {},
            },
            semantic_merged_data={
                "balance": {
                    "Z01020100": ["5100000.00", "10000000.00"],
                    "Z01030001": ["1475461258.51", "2318468005.71"],
                    "Z01030002": ["91204588.53", "152568400.45"],
                    "Z01030003": ["1384256669.98", "2165899605.26"],
                    "Z01030004": ["", ""],
                    "Z01030010": ["1535841368.53", "2420471954.89"],
                    "Z01040000": ["97166064.62", "98366010.62"],
                }
            },
        )

        details = {detail["check"]: detail for detail in result["details"]}
        non_current_assets = details["非流动资产合计(年初)"]
        asset_total = details["资产总计 = 流动资产合计 + 非流动资产合计(年初)"]

        self.assertEqual(non_current_assets["result"], "fail")
        self.assertEqual(non_current_assets["_inferred_total"], "1638107433.15")
        self.assertEqual(non_current_assets["reason"], "合计项缺失，但可由旧准则口径推导")
        self.assertNotIn("semantic_attribution", non_current_assets)
        self.assertEqual(
            non_current_assets["attribution"]["mode"],
            "missing_total_inferred_from_components",
        )
        self.assertEqual(
            non_current_assets["semantic_validation"]["mode"],
            "old_standard_hidden_subtotals",
        )
        self.assertEqual(
            set(non_current_assets["components"]),
            {"Z01020100", "Z01030010", "Z01040000"},
        )
        self.assertEqual(
            non_current_assets["components"]["Z01020100"]["value"],
            "5100000.00",
        )
        self.assertEqual(
            non_current_assets["components"]["Z01020100"]["source"],
            "semantic",
        )
        self.assertEqual(
            [item["code"] for item in non_current_assets["validated_components"]],
            ["Z01020121", "Z01030000", "Z01030300", "Z01040100"],
        )
        self.assertEqual(
            [item["code"] for item in non_current_assets["invalid_components"]],
            ["Z01020110", "ZY2015109", "ZY2015073", "ZY2015074", "ZY2015110"],
        )
        self.assertEqual(
            non_current_assets["invalid_components"][0]["aggregate_value"],
            "5100000.00",
        )
        self.assertEqual(
            non_current_assets["invalid_components"][0]["component_sum"],
            "0",
        )
        self.assertEqual(asset_total["result"], "pass")
        self.assertEqual(asset_total["expected"], "2347987161.49")
        self.assertEqual(
            asset_total["attribution"]["mode"],
            "missing_component_inferred_match",
        )

    def test_missing_non_current_assets_total_does_not_double_count_long_term_investment_when_long_term_equity_is_visible(self) -> None:
        result = self.inspector.inspect_view(
            {
                "balance": {
                    "Z01020110": ["4200000.0", "4200000.0"],
                    "Z01030000": ["90533880.77", "243655836.14"],
                    "Z01030300": ["26225021.19", "49417733.24"],
                },
                "profit": {},
                "cashflow": {},
            },
            semantic_merged_data={
                "balance": {
                    "Z01020100": ["4200000.0", "4200000.0"],
                }
            },
        )

        details = {detail["check"]: detail for detail in result["details"]}
        non_current_assets = details["非流动资产合计(年初)"]

        self.assertEqual(non_current_assets["result"], "fail")
        self.assertEqual(non_current_assets["_inferred_total"], "120958901.96")
        self.assertEqual(
            set(non_current_assets["components"]),
            {"Z01020110", "Z01030000", "Z01030300"},
        )

    def test_non_current_assets_total_can_pass_after_semantic_long_term_investment_recheck(self) -> None:
        result = self.inspector.inspect_view(
            {
                "balance": {
                    "ZY2015058": ["1638107433.15", "2648107433.15"],
                    "Z01020121": ["51284469.51", "52484415.51"],
                    "Z01030000": ["1384256669.98", "2165899605.26"],
                    "Z01030300": ["151584698.55", "254572349.63"],
                    "Z01040100": ["45881595.11", "45881595.11"],
                },
                "profit": {},
                "cashflow": {},
            },
            semantic_merged_data={
                "balance": {
                    "Z01020100": ["5100000.00", "10000000.00"],
                }
            },
        )

        details = {detail["check"]: detail for detail in result["details"]}
        non_current_assets = details["非流动资产合计(年初)"]

        self.assertEqual(non_current_assets["result"], "pass")
        self.assertEqual(non_current_assets["reason"], "已按旧准则口径复核通过")
        self.assertEqual(non_current_assets["expected"], "1638107433.15")
        self.assertEqual(
            non_current_assets["semantic_validation"]["mode"],
            "old_standard_hidden_subtotals",
        )
        self.assertEqual(
            set(non_current_assets["components"]),
            {"Z01020100", "Z01030010", "Z01040000"},
        )
        self.assertEqual(
            non_current_assets["components"]["Z01020100"]["source"],
            "semantic",
        )
        self.assertEqual(
            non_current_assets["components"]["Z01030010"]["source"],
            "derived",
        )
        self.assertEqual(
            non_current_assets["components"]["Z01040000"]["source"],
            "derived",
        )
        self.assertEqual(
            [item["code"] for item in non_current_assets["validated_components"]],
            ["Z01020121", "Z01030000", "Z01030300", "Z01040100"],
        )

    def test_non_current_assets_total_does_not_invent_old_long_term_investment(self) -> None:
        result = self.inspector.inspect_view(
            {
                "balance": {
                    "ZY2015058": ["1638107433.15", "2648107433.15"],
                    "Z01020121": ["51284469.51", "52484415.51"],
                    "Z01030000": ["1384256669.98", "2165899605.26"],
                    "Z01030300": ["151584698.55", "254572349.63"],
                    "Z01040100": ["45881595.11", "45881595.11"],
                },
                "profit": {},
                "cashflow": {},
            },
            semantic_merged_data={"balance": {}},
        )

        details = {detail["check"]: detail for detail in result["details"]}
        non_current_assets = details["非流动资产合计(年初)"]

        self.assertEqual(non_current_assets["result"], "fail")
        self.assertEqual(non_current_assets["reason"], "校验未通过")
        self.assertEqual(non_current_assets["expected"], "1633007433.15")
        self.assertNotIn("semantic_validation", non_current_assets)
        self.assertNotIn("validated_components", non_current_assets)

    def test_old_standard_non_current_assets_prefers_direct_hidden_subtotals(self) -> None:
        result = self.inspector.inspect_view(
            {
                "balance": {
                    "ZY2015058": ["1638107433.15", "2648107433.15"],
                    "Z01020121": ["51284469.51", "52484415.51"],
                    "Z01030000": ["1384256669.98", "2165899605.26"],
                    "Z01030300": ["151584698.55", "254572349.63"],
                    "Z01040100": ["45881595.11", "45881595.11"],
                },
                "profit": {},
                "cashflow": {},
            },
            semantic_merged_data={
                "balance": {
                    "Z01020100": ["5100000.00", "10000000.00"],
                    "Z01030010": ["1535841368.53", "2420471954.89"],
                    "Z01040000": ["97166064.62", "98366010.62"],
                }
            },
        )

        details = {detail["check"]: detail for detail in result["details"]}
        non_current_assets = details["非流动资产合计(年初)"]

        self.assertEqual(non_current_assets["result"], "pass")
        self.assertEqual(non_current_assets["reason"], "已按旧准则口径复核通过")
        self.assertEqual(
            non_current_assets["components"]["Z01030010"],
            {
                "name": "固定资产合计",
                "value": "1535841368.53",
                "source": "semantic",
            },
        )
        self.assertEqual(
            non_current_assets["components"]["Z01040000"],
            {
                "name": "无形资产及其他资产合计",
                "value": "97166064.62",
                "source": "semantic",
            },
        )

    def test_missing_non_current_liabilities_total_is_inferred_for_liability_total_check(self) -> None:
        result = self.inspector.inspect_view(
            {
                "balance": {
                    "Z02000001": [211428613.88, 805382935.0],
                    "Z02010001": [211428613.88, 805382935.0],
                    "Z02010100": [211428613.88, 805382935.0],
                    "Z02020100": [0, 0],
                    "Z02020200": [0, 0],
                    "Z02020300": [0, 0],
                    "Z02011200": [0, 0],
                    "Z01044104": [0, 0],
                },
                "profit": {},
                "cashflow": {},
            }
        )

        details = {detail["check"]: detail for detail in result["details"]}
        non_current_liabilities = details["非流动负债合计(期末)"]
        liability_total = details["负债合计 = 流动负债合计 + 非流动负债合计(期末)"]

        self.assertEqual(non_current_liabilities["result"], "fail")
        self.assertEqual(non_current_liabilities["_inferred_total"], "0")
        self.assertEqual(
            non_current_liabilities["attribution"]["mode"],
            "missing_total_inferred_from_components",
        )
        self.assertEqual(liability_total["result"], "pass")
        self.assertEqual(liability_total["reason"], "使用缺失下级合计的推导值后校验通过")
        self.assertEqual(
            liability_total["attribution"]["mode"],
            "missing_component_inferred_match",
        )
        self.assertEqual(liability_total["attribution"]["candidate_sum"], "805382935.0")

    def test_missing_non_current_liabilities_total_is_inferred_from_empty_components(self) -> None:
        result = self.inspector.inspect_view(
            {
                "balance": {
                    "Z02000001": [79026659.5, 96236162.38],
                    "Z02010001": [79026659.5, 96236162.38],
                    "Z02020100": ["", ""],
                    "Z02020200": ["", ""],
                    "Z02020300": ["", ""],
                    "Z02011200": ["", ""],
                },
                "profit": {},
                "cashflow": {},
            }
        )

        details = {detail["check"]: detail for detail in result["details"]}
        non_current_liabilities = details["非流动负债合计(期末)"]
        liability_total = details["负债合计 = 流动负债合计 + 非流动负债合计(期末)"]

        self.assertEqual(non_current_liabilities["result"], "fail")
        self.assertEqual(non_current_liabilities["_inferred_total"], "0")
        self.assertEqual(
            non_current_liabilities["attribution"]["mode"],
            "missing_total_inferred_from_components",
        )
        self.assertEqual(non_current_liabilities["_participating_component_count"], 4)
        self.assertEqual(liability_total["result"], "pass")
        self.assertEqual(liability_total["reason"], "使用缺失下级合计的推导值后校验通过")
        self.assertEqual(
            liability_total["attribution"]["mode"],
            "missing_component_inferred_match",
        )
        self.assertEqual(liability_total["attribution"]["candidate_sum"], "96236162.38")

    def test_missing_non_current_liabilities_total_prefers_parent_residual_when_child_sum_conflicts(self) -> None:
        result = self.inspector.inspect_view(
            {
                "balance": {
                    "Z02010001": [100, 100],
                    "Z02010100": [100, 100],
                    "Z02020100": [25, 25],
                    "Z02020300": [5, 5],
                    "Z02000001": [150, 150],
                    "Z04020110": [80, 80],
                    "Z04020200": [80, 80],
                    "Z05010000": [230, 230],
                    "Z01000001": [230, 230],
                },
                "profit": {},
                "cashflow": {},
            }
        )

        details = {detail["check"]: detail for detail in result["details"]}
        current_liabilities = details["流动负债合计(期末)"]
        non_current_liabilities = details["非流动负债合计(期末)"]
        liability_total = details["负债合计 = 流动负债合计 + 非流动负债合计(期末)"]
        liability_equity_total = details[
            "负债和所有者权益（或股东权益）总计 = 流动负债合计 + 非流动负债合计 + 所有者权益（或股东权益）合计(期末)"
        ]

        self.assertEqual(current_liabilities["result"], "pass")
        self.assertEqual(non_current_liabilities["result"], "fail")
        self.assertEqual(non_current_liabilities["_inferred_total"], "50")
        self.assertEqual(non_current_liabilities["attribution"]["component_sum"], "30")
        self.assertEqual(non_current_liabilities["attribution"]["diff"], "20")
        self.assertEqual(liability_total["result"], "pass")
        self.assertEqual(
            liability_total["attribution"]["mode"],
            "missing_component_residual_inferred_match",
        )
        self.assertEqual(
            liability_total["attribution"]["inferred_components"][0]["inferred_value"],
            "50",
        )
        self.assertEqual(liability_equity_total["result"], "pass")
        self.assertEqual(
            liability_equity_total["components"]["ZY2015061"]["recomputed_value"],
            "50",
        )

    def test_missing_non_current_liabilities_zero_is_inferred_from_parent_chain(self) -> None:
        result = self.inspector.inspect_view(
            {
                "balance": {
                    "Z01000001": [None, 121489414.91],
                    "Z02010001": [None, 20699247.33],
                    "Z02000001": [None, 20699247.33],
                    "Z04020200": [None, 100000000.0],
                    "Z04050000": [None, 790167.58],
                    "Z04020110": [None, 100790167.58],
                    "Z05010000": [None, 121489414.91],
                },
                "profit": {},
                "cashflow": {},
            }
        )

        details = {detail["check"]: detail for detail in result["details"]}
        liability_total = details["负债合计 = 流动负债合计 + 非流动负债合计(期末)"]
        liability_equity_total = details[
            "负债和所有者权益（或股东权益）总计 = 流动负债合计 + 非流动负债合计 + 所有者权益（或股东权益）合计(期末)"
        ]
        liability_equity_by_total = details[
            "负债和所有者权益（或股东权益）总计 = 负债合计 + 所有者权益（或股东权益）合计(期末)"
        ]

        self.assertEqual(liability_total["result"], "pass")
        self.assertEqual(liability_total["reason"], "使用缺失下级合计推定值0后校验通过")
        self.assertEqual(
            liability_total["attribution"]["mode"],
            "missing_component_zero_inferred_match",
        )
        self.assertEqual(liability_total["components"]["ZY2015061"]["recomputed_value"], "0")
        self.assertEqual(liability_total["attribution"]["culprit_codes"], ["ZY2015061"])
        self.assertEqual(liability_total["attribution"]["candidate_sum"], "20699247.33")
        self.assertEqual(liability_equity_total["result"], "pass")
        self.assertEqual(
            liability_equity_total["reason"],
            "使用缺失下级合计推定值0后校验通过",
        )
        self.assertEqual(
            liability_equity_total["attribution"]["mode"],
            "missing_component_zero_inferred_match",
        )
        self.assertEqual(liability_equity_total["components"]["ZY2015061"]["recomputed_value"], "0")
        self.assertEqual(liability_equity_total["attribution"]["candidate_sum"], "121489414.91")
        self.assertEqual(liability_equity_by_total["result"], "pass")

    def test_liability_total_attributes_mismatch_to_current_liability_subtree_when_missing_non_current_is_supported(self) -> None:
        result = self.inspector.inspect_view(
            {
                "balance": {
                    "Z02000001": [803687526.84, 891319377.40],
                    "Z02010001": [726775454.34, 844174698.28],
                    "Z02010100": [305000000, 345000000],
                    "Z02010300": [408133019.17, 475226480.89],
                    "Z02010410": [25467088.37, 14437870.14],
                    "ZY2015006": [3594291.99, 5081336.11],
                    "ZY2015008": [1230365.91, 1053116.39],
                    "ZG2010800": [3350688.90, 3375894.75],
                    "Z02020300": [56912072.50, 47144679.12],
                },
                "profit": {},
                "cashflow": {},
            }
        )

        details = {detail["check"]: detail for detail in result["details"]}
        current_liabilities = details["流动负债合计(年初)"]
        non_current_liabilities = details["非流动负债合计(年初)"]
        liability_total = details["负债合计 = 流动负债合计 + 非流动负债合计(年初)"]

        self.assertEqual(current_liabilities["result"], "fail")
        self.assertEqual(current_liabilities["expected"], "746775454.34")
        self.assertEqual(non_current_liabilities["_inferred_total"], "56912072.5")
        self.assertEqual(liability_total["result"], "fail")
        self.assertEqual(
            liability_total["attribution"]["mode"],
            "missing_component_and_recomputed_component_match",
        )
        self.assertEqual(liability_total["attribution"]["culprit_codes"], ["Z02010001"])
        self.assertEqual(
            liability_total["attribution"]["validated_missing_component_codes"],
            ["ZY2015061"],
        )
        self.assertEqual(liability_total["attribution"]["candidate_sum"], "803687526.84")
        self.assertEqual(
            liability_total["attribution"]["component_diffs"][0]["diff"],
            "20000000.00",
        )

    def test_profit_basic_checks_pass(self) -> None:
        result = self.inspector.inspect_view(
            {
                "balance": {},
                "profit": {
                    "L00000000": [900, 1000],
                    "L02010100": [350, 400],
                    "L02010800": [8, 10],
                    "L02010900": [45, 50],
                    "L03040000": [55, 60],
                    "L02011000": [65, 70],
                    "L03050000": [18, 20],
                    "L02011100": [4, 5],
                    "L04020000": [12, 15],
                    "SY1000006": [1, 2],
                    "L02011200": [2, 3],
                    "SY1000016": [3, 4],
                    "SG5020000": [4, 5],
                    "L02011300": [5, 6],
                    "L04010000": [385, 430],
                    "L04050000": [15, 20],
                    "L04070000": [8, 10],
                    "L05010000": [392, 440],
                    "L04010100": [32, 40],
                    "L06010000": [360, 400],
                    "L05010200": [220, 250],
                    "L05010300": [140, 150],
                    "L06010100": [8, 10],
                    "L07000000": [368, 410],
                },
                "cashflow": {},
            }
        )

        details = {detail["check"]: detail for detail in result["details"]}
        self.assertTrue(result["passed"])
        self.assertEqual(result["total_checks"], 5)
        self.assertEqual(result["passed_checks"], 5)
        self.assertEqual(result["failed_checks"], 0)
        self.assertEqual(result["skipped_checks"], 0)
        self.assertEqual(details["营业利润"]["result"], "pass")
        self.assertEqual(details["利润总额"]["result"], "pass")
        self.assertEqual(details["净利润 = 利润总额 - 所得税费用"]["result"], "pass")
        self.assertEqual(details["净利润 = 持续经营净利润 + 终止经营净利润"]["result"], "pass")
        self.assertEqual(details["综合收益总额"]["result"], "pass")

    def test_profit_net_profit_breakdown_is_not_run_when_components_are_absent(self) -> None:
        result = self.inspector.inspect_view(
            {
                "balance": {},
                "profit": {
                    "L00000000": [900, 1000],
                    "L02010100": [350, 400],
                    "L02010800": [8, 10],
                    "L02010900": [45, 50],
                    "L03040000": [55, 60],
                    "L02011000": [65, 70],
                    "L03050000": [18, 20],
                    "L02011100": [4, 5],
                    "L04020000": [12, 15],
                    "SY1000006": [1, 2],
                    "L02011200": [2, 3],
                    "SY1000016": [3, 4],
                    "SG5020000": [4, 5],
                    "L02011300": [5, 6],
                    "L04010000": [385, 430],
                    "L04050000": [15, 20],
                    "L04070000": [8, 10],
                    "L05010000": [392, 440],
                    "L04010100": [32, 40],
                    "L06010000": [360, 400],
                    "L06010100": [8, 10],
                    "L07000000": [368, 410],
                },
                "cashflow": {},
            }
        )

        details = {detail["check"]: detail for detail in result["details"]}
        self.assertTrue(result["passed"])
        self.assertEqual(result["total_checks"], 4)
        self.assertEqual(result["passed_checks"], 4)
        self.assertEqual(result["skipped_checks"], 0)
        self.assertNotIn("净利润 = 持续经营净利润 + 终止经营净利润", details)

    def test_profit_failure_marks_total_and_participating_components_as_suspects(self) -> None:
        result = self.inspector.inspect_view(
            {
                "balance": {},
                "profit": {
                    "L06010000": [399],
                    "L05010200": [250],
                    "L05010300": [150],
                },
                "cashflow": {},
            }
        )

        details = {detail["check"]: detail for detail in result["details"]}
        self.assertFalse(result["passed"])
        self.assertEqual(
            details["净利润 = 持续经营净利润 + 终止经营净利润"]["result"],
            "fail",
        )
        self.assertEqual(
            [item["code"] for item in details["净利润 = 持续经营净利润 + 终止经营净利润"]["suspects"]],
            ["L06010000", "L05010200", "L05010300"],
        )
        self.assertEqual(
            [item["name"] for item in details["净利润 = 持续经营净利润 + 终止经营净利润"]["suspects"]],
            ["净利润", "持续经营净利润", "终止经营净利润"],
        )
        self.assertEqual(
            details["净利润 = 持续经营净利润 + 终止经营净利润"]["expected"],
            "400",
        )

    def test_profit_missing_total_reports_inferred_value_and_reuses_it_as_component(self) -> None:
        result = self.inspector.inspect_view(
            {
                "balance": {},
                "profit": {
                    "L05010000": ["50132525.57"],
                    "L04010100": ["0"],
                    "L06010100": ["0"],
                },
                "cashflow": {},
            }
        )

        details = {detail["check"]: detail for detail in result["details"]}
        net_profit = details["净利润 = 利润总额 - 所得税费用"]
        comprehensive_income = details["综合收益总额"]

        self.assertEqual(net_profit["result"], "fail")
        self.assertEqual(net_profit["expected"], "50132525.57")
        self.assertEqual(net_profit["_inferred_total"], "50132525.57")
        self.assertEqual(
            net_profit["attribution"]["mode"],
            "missing_total_inferred_from_components",
        )
        self.assertEqual(comprehensive_income["result"], "fail")
        self.assertEqual(comprehensive_income["expected"], "50132525.57")
        self.assertEqual(
            comprehensive_income["components"]["L06010000"]["source"],
            "inferred",
        )

    def test_profit_nested_breakdown_items_do_not_participate_in_parent_formula(self) -> None:
        result = self.inspector.inspect_view(
            {
                "balance": {},
                "profit": {
                    "L00000000": [1000],
                    "L02010100": [400],
                    "L02010800": [10],
                    "L02010900": [50],
                    "L03040000": [60],
                    "L02011000": [70],
                    "L03050000": [20],
                    "L02011001": [999],
                    "L02011002": [888],
                    "L02011100": [5],
                    "L04020000": [15],
                    "L04020100": [777],
                    "L04020200": [666],
                    "SY1000006": [2],
                    "L02011200": [3],
                    "SY1000016": [4],
                    "SG5020000": [5],
                    "L02011300": [6],
                    "L04010000": [430],
                },
                "cashflow": {},
            }
        )

        details = {detail["check"]: detail for detail in result["details"]}
        self.assertEqual(details["营业利润"]["result"], "pass")
        self.assertIn("L03050000", details["营业利润"]["components"])
        self.assertIn("L04020000", details["营业利润"]["components"])
        self.assertNotIn("L02011001", details["营业利润"]["components"])
        self.assertNotIn("L02011002", details["营业利润"]["components"])
        self.assertNotIn("L04020100", details["营业利润"]["components"])
        self.assertNotIn("L04020200", details["营业利润"]["components"])

    def test_profit_semantic_variants_can_clear_view_failure_for_operating_profit(self) -> None:
        result = self.inspector.inspect_view(
            {
                "balance": {},
                "profit": {
                    "L04010000": [430],
                    "L02010900": [50],
                    "L03040000": [60],
                    "L03050000": [20],
                    "L04020000": [15],
                },
                "cashflow": {},
            },
            semantic_merged_data={
                "profit": {
                    "L03000000": [480],
                    "L03010000": [80],
                    "L02010900": [50],
                    "L03040000": [60],
                    "L03050000": [20],
                },
            },
        )

        details = {detail["check"]: detail for detail in result["details"]}
        operating_profit = details["营业利润"]

        self.assertEqual(operating_profit["result"], "pass")
        self.assertEqual(operating_profit["expected"], "430")
        self.assertEqual(
            set(operating_profit["components"]),
            {"L03000000", "L03010000", "L02010900", "L03040000", "L03050000"},
        )
        self.assertEqual(
            operating_profit["components"]["L03000000"]["source"],
            "semantic",
        )

    def test_profit_semantic_variants_infer_missing_operating_profit_and_reuse_it(self) -> None:
        result = self.inspector.inspect_view(
            {
                "balance": {},
                "profit": {
                    "L04050000": [20],
                    "L04070000": [10],
                },
                "cashflow": {},
            },
            semantic_merged_data={
                "profit": {
                    "L03000000": [480],
                    "L03010000": [80],
                    "L02010900": [50],
                    "L03040000": [60],
                    "L03050000": [20],
                    "L04050000": [20],
                    "L04070000": [10],
                },
            },
        )

        details = {detail["check"]: detail for detail in result["details"]}
        operating_profit = details["营业利润"]
        total_profit = details["利润总额"]

        self.assertEqual(operating_profit["result"], "fail")
        self.assertEqual(operating_profit["expected"], "430")
        self.assertEqual(operating_profit["_inferred_total"], "430")
        self.assertEqual(total_profit["result"], "fail")
        self.assertEqual(total_profit["expected"], "440")
        self.assertEqual(total_profit["_inferred_total"], "440")
        self.assertEqual(
            total_profit["components"]["L04010000"]["source"],
            "inferred",
        )

    def test_profit_failure_reports_single_field_repair_candidates(self) -> None:
        result = self.inspector.inspect_view(
            {
                "balance": {},
                "profit": {
                    "L00000000": [1000],
                    "L02010100": [400],
                    "L02010800": [9.97],
                    "L02010900": [50],
                    "L03040000": [60],
                    "L02011000": [70],
                    "L03050000": [20],
                    "L02011100": [5],
                    "L04020000": [15],
                    "SY1000006": [2],
                    "L02011200": [3],
                    "SY1000016": [4],
                    "SG5020000": [5],
                    "L02011300": [6],
                    "L04010000": [430],
                },
                "cashflow": {},
            }
        )

        details = {detail["check"]: detail for detail in result["details"]}
        operating_profit = details["营业利润"]
        candidates = operating_profit["attribution_candidates"]["candidates"]
        tax_candidate = next(item for item in candidates if item["code"] == "L02010800")

        self.assertEqual(operating_profit["result"], "fail")
        self.assertEqual(operating_profit["amounts"]["reported_total"], "430")
        self.assertEqual(operating_profit["amounts"]["recomputed_total"], "430.03")
        self.assertEqual(operating_profit["attribution_candidates"]["residual"], "-0.03")
        self.assertEqual(tax_candidate["current_value"], "9.97")
        self.assertEqual(tax_candidate["corrected_value"], "10.00")
        self.assertEqual(tax_candidate["required_delta"], "0.03")

    def test_profit_failure_uses_operating_cost_subtotal_to_narrow_suspects(self) -> None:
        result = self.inspector.inspect_view(
            {
                "balance": {},
                "profit": {
                    "L00000000": [1000],
                    "L02010100": [400],
                    "L02010800": [9.97],
                    "L02010900": [50],
                    "L03040000": [60],
                    "L02011000": [70],
                    "L03050000": [20],
                    "L02011100": [5],
                    "L04020000": [15],
                    "SY1000006": [2],
                    "L02011200": [3],
                    "SY1000016": [4],
                    "SG5020000": [5],
                    "L02011300": [6],
                    "L04010000": [430],
                },
                "cashflow": {},
            },
            semantic_merged_data={
                "profit": {
                    "L02000000": [610],
                },
            },
        )

        details = {detail["check"]: detail for detail in result["details"]}
        operating_profit = details["营业利润"]
        subtotal_attribution = operating_profit["semantic_attribution"]
        tax_candidate = next(
            item
            for item in subtotal_attribution["repair_candidates"]
            if item["code"] == "L02010800"
        )

        self.assertEqual(operating_profit["result"], "fail")
        self.assertEqual(
            operating_profit["reason"],
            "按营业总成本独立合计复核营业利润通过，差异来自营业总成本明细，无法单点定位",
        )
        self.assertEqual(subtotal_attribution["mode"], "supporting_subtotal_match")
        self.assertEqual(subtotal_attribution["subtotal_value"], "610")
        self.assertEqual(subtotal_attribution["component_sum"], "609.97")
        self.assertEqual(subtotal_attribution["component_diff"], "0.03")
        self.assertEqual(
            [item["code"] for item in operating_profit["suspects"]],
            [
                "L02010100",
                "L02010800",
                "L02010900",
                "L03040000",
                "L02011000",
                "L03050000",
            ],
        )
        self.assertEqual(tax_candidate["corrected_value"], "10.00")

    def test_cashflow_basic_checks_pass(self) -> None:
        result = self.inspector.inspect_view(
            {
                "balance": {},
                "profit": {},
                "cashflow": {
                    "X01040000": [115],
                    "X01010000": [100],
                    "X01020000": [10],
                    "X01030000": [5],
                    "X01090000": [140],
                    "X01050000": [90],
                    "X01060000": [20],
                    "X01070000": [10],
                    "X01011800": [20],
                    "X01100000": [-25],
                    "X02050000": [45],
                    "X02010000": [20],
                    "X02020000": [5],
                    "X02030000": [10],
                    "X02030100": [4],
                    "X02040000": [6],
                    "X02090000": [31],
                    "X02060000": [11],
                    "X02070000": [7],
                    "X02080200": [5],
                    "X02080300": [8],
                    "X02100000": [14],
                    "X03040000": [95],
                    "X03010000": [30],
                    "X02080500": [40],
                    "X03020100": [15],
                    "X03030000": [10],
                    "X03080000": [60],
                    "X03050000": [25],
                    "X03060000": [20],
                    "X03070000": [15],
                    "X03090000": [35],
                },
            }
        )

        details = {detail["check"]: detail for detail in result["details"]}
        self.assertTrue(result["passed"])
        self.assertEqual(result["total_checks"], 9)
        self.assertEqual(result["passed_checks"], 9)
        self.assertEqual(result["failed_checks"], 0)
        self.assertEqual(result["skipped_checks"], 0)
        self.assertEqual(details["经营活动现金流入小计"]["result"], "pass")
        self.assertEqual(details["经营活动现金流出小计"]["result"], "pass")
        self.assertEqual(details["投资活动现金流入小计"]["result"], "pass")
        self.assertEqual(details["投资活动现金流出小计"]["result"], "pass")
        self.assertEqual(details["筹资活动现金流入小计"]["result"], "pass")
        self.assertEqual(details["筹资活动现金流出小计"]["result"], "pass")
        self.assertEqual(
            details["经营活动产生的现金流量净额 = 经营活动现金流入小计 - 经营活动现金流出小计"]["result"],
            "pass",
        )
        self.assertEqual(
            details["投资活动产生的现金流量净额 = 投资活动现金流入小计 - 投资活动现金流出小计"]["result"],
            "pass",
        )
        self.assertEqual(
            details["筹资活动产生的现金流量净额 = 筹资活动现金流入小计 - 筹资活动现金流出小计"]["result"],
            "pass",
        )

    def test_cashflow_empty_values_participate_as_zero(self) -> None:
        result = self.inspector.inspect_view(
            {
                "balance": {},
                "profit": {},
                "cashflow": {
                    "X02050000": [""],
                    "X02010000": [""],
                    "X02020000": [""],
                    "X02030000": [""],
                    "X02030100": [""],
                    "X02040000": [""],
                    "X02090000": ["17979482.51"],
                    "X02060000": ["17979482.51"],
                    "X02070000": [""],
                    "X02080200": [""],
                    "X02080300": [""],
                    "X02100000": ["-17979482.51"],
                },
            }
        )

        details = {detail["check"]: detail for detail in result["details"]}
        inflow = details["投资活动现金流入小计"]
        net_amount = details["投资活动产生的现金流量净额 = 投资活动现金流入小计 - 投资活动现金流出小计"]

        self.assertEqual(inflow["result"], "pass")
        self.assertEqual(inflow["total"]["value"], "0")
        self.assertEqual(inflow["expected"], "0")
        self.assertEqual(inflow["components"]["X02010000"]["value"], "0")
        self.assertEqual(inflow["components"]["X02010000"]["source"], "empty")
        self.assertEqual(net_amount["result"], "pass")
        self.assertEqual(net_amount["components"]["X02050000"]["value"], "0")
        self.assertEqual(net_amount["components"]["X02050000"]["source"], "empty")

    def test_cashflow_reported_zero_subtotal_without_children_is_supported_by_parent(self) -> None:
        result = self.inspector.inspect_view(
            {
                "balance": {},
                "profit": {},
                "cashflow": {
                    "X02050000": ["0.0"],
                    "X02090000": ["31892466.39"],
                    "X02060000": ["31892466.39"],
                    "X02100000": ["-31892466.39"],
                },
            }
        )

        details = {detail["check"]: detail for detail in result["details"]}
        inflow = details["投资活动现金流入小计"]
        net_amount = details["投资活动产生的现金流量净额 = 投资活动现金流入小计 - 投资活动现金流出小计"]

        self.assertEqual(inflow["result"], "pass")
        self.assertEqual(inflow["reason"], "小计为0，已由投资活动产生的现金流量净额交叉校验确认")
        self.assertEqual(inflow["total"]["value"], "0")
        self.assertEqual(inflow["expected"], "0")
        self.assertEqual(net_amount["result"], "pass")

    def test_cashflow_net_increase_infers_missing_zero_activity_amounts(self) -> None:
        result = self.inspector.inspect_view(
            {
                "balance": {},
                "profit": {},
                "cashflow": {
                    "X01040000": ["1261114997.88"],
                    "X01010000": ["1261114997.88"],
                    "X01030000": ["-0.0"],
                    "X01090000": ["1119304658.06"],
                    "X01050000": ["1116358333.57"],
                    "X01060000": ["568710.0"],
                    "X01070000": ["1185172.44"],
                    "X01011800": ["1192442.05"],
                    "X01100000": ["141810339.82"],
                    "X03040000": ["20000000.0"],
                    "X03010000": ["20000000.0"],
                    "X03090000": ["20000000.0"],
                    "X05000000": ["161810339.82"],
                },
            }
        )

        details = {detail["check"]: detail for detail in result["details"]}
        net_increase = details[
            "现金及现金等价物净增加额 = 经营活动产生的现金流量净额 + 投资活动产生的现金流量净额 + 筹资活动产生的现金流量净额 + 汇率变动对现金及现金等价物的影响"
        ]
        investing_inflow = details["投资活动现金流入小计"]
        investing_outflow = details["投资活动现金流出小计"]
        investing_net = details["投资活动产生的现金流量净额 = 投资活动现金流入小计 - 投资活动现金流出小计"]
        financing_outflow = details["筹资活动现金流出小计"]

        self.assertTrue(result["passed"])
        self.assertEqual(result["total_checks"], 10)
        self.assertEqual(result["passed_checks"], 10)
        self.assertEqual(result["failed_checks"], 0)
        self.assertEqual(net_increase["result"], "pass")
        self.assertEqual(investing_net["result"], "pass")
        self.assertEqual(investing_net["total"]["value"], "0")
        self.assertEqual(investing_inflow["result"], "pass")
        self.assertEqual(investing_inflow["total"]["value"], "0")
        self.assertEqual(investing_outflow["result"], "pass")
        self.assertEqual(investing_outflow["total"]["value"], "0")
        self.assertEqual(financing_outflow["result"], "pass")
        self.assertEqual(financing_outflow["total"]["value"], "0")

    def test_cashflow_failure_marks_total_and_participating_components_as_suspects(self) -> None:
        result = self.inspector.inspect_view(
            {
                "balance": {},
                "profit": {},
                "cashflow": {
                    "X03080000": [59],
                    "X03050000": [25],
                    "X03060000": [20],
                    "X03070000": [15],
                },
            }
        )

        details = {detail["check"]: detail for detail in result["details"]}
        self.assertFalse(result["passed"])
        self.assertEqual(details["筹资活动现金流出小计"]["result"], "fail")
        self.assertEqual(
            [item["code"] for item in details["筹资活动现金流出小计"]["suspects"]],
            ["X03080000", "X03050000", "X03060000", "X03070000"],
        )
        self.assertEqual(
            [item["name"] for item in details["筹资活动现金流出小计"]["suspects"]],
            ["筹资活动现金流出小计", "偿还债务支付的现金", "分配股利、利润或偿付利息支付的现金", "支付其他与筹资活动有关的现金"],
        )

    def test_cashflow_failed_subtotal_confirmed_by_net_amount_narrows_to_children(self) -> None:
        result = self.inspector.inspect_view(
            {
                "balance": {},
                "profit": {},
                "cashflow": {
                    "X02050000": ["1315531.99"],
                    "X02020000": ["295531.99"],
                    "X02030000": ["0.0"],
                    "X02040000": ["0.0"],
                    "X02090000": ["426315896.02"],
                    "X02060000": ["426315896.02"],
                    "X02080300": ["0.0"],
                    "X02100000": ["-425000364.03"],
                },
            }
        )

        details = {detail["check"]: detail for detail in result["details"]}
        inflow = details["投资活动现金流入小计"]
        net_amount = details["投资活动产生的现金流量净额 = 投资活动现金流入小计 - 投资活动现金流出小计"]
        attribution = inflow["semantic_attribution"]

        self.assertEqual(inflow["result"], "fail")
        self.assertEqual(inflow["expected"], "295531.99")
        self.assertEqual(net_amount["result"], "pass")
        self.assertEqual(
            attribution["mode"],
            "cashflow_subtotal_confirmed_by_net_amount",
        )
        self.assertEqual(attribution["confirmation_code"], "X02100000")
        self.assertEqual(attribution["component_diff"], "1020000.00")
        self.assertEqual(
            [item["code"] for item in inflow["suspects"]],
            ["X02010000", "X02020000", "X02030000", "X02030100", "X02040000"],
        )

    def test_cashflow_net_amount_failure_marks_net_and_subtotals_as_suspects(self) -> None:
        result = self.inspector.inspect_view(
            {
                "balance": {},
                "profit": {},
                "cashflow": {
                    "X01100000": [-20],
                    "X01040000": [115],
                    "X01090000": [140],
                },
            }
        )

        details = {detail["check"]: detail for detail in result["details"]}
        detail = details["经营活动产生的现金流量净额 = 经营活动现金流入小计 - 经营活动现金流出小计"]
        self.assertEqual(detail["result"], "fail")
        self.assertEqual(detail["expected"], "-25")
        self.assertEqual(
            [item["code"] for item in detail["suspects"]],
            ["X01100000", "X01040000", "X01090000"],
        )
        self.assertEqual(
            [item["name"] for item in detail["suspects"]],
            ["经营活动产生的现金流量净额", "经营活动现金流入小计", "经营活动现金流出小计"],
        )

    def test_cashflow_missing_subtotals_report_inferred_values_and_support_net_amount_check(self) -> None:
        result = self.inspector.inspect_view(
            {
                "balance": {},
                "profit": {},
                "cashflow": {
                    "X01010000": ["460914309.38"],
                    "X01020000": ["0"],
                    "X01030000": ["104902614.97"],
                    "X01050000": ["517122787.55"],
                    "X01060000": ["602598.0"],
                    "X01070000": ["13745547.1"],
                    "X01011800": ["22004282.59"],
                    "X01100000": ["12341709.11"],
                },
            }
        )

        details = {detail["check"]: detail for detail in result["details"]}
        inflow = details["经营活动现金流入小计"]
        outflow = details["经营活动现金流出小计"]
        net_amount = details["经营活动产生的现金流量净额 = 经营活动现金流入小计 - 经营活动现金流出小计"]

        self.assertEqual(inflow["result"], "fail")
        self.assertEqual(inflow["expected"], "565816924.35")
        self.assertEqual(inflow["_inferred_total"], "565816924.35")
        self.assertEqual(
            inflow["attribution"]["mode"],
            "missing_total_inferred_from_components",
        )
        self.assertEqual(outflow["result"], "fail")
        self.assertEqual(outflow["expected"], "553475215.24")
        self.assertEqual(outflow["_inferred_total"], "553475215.24")
        self.assertEqual(net_amount["result"], "pass")
        self.assertEqual(net_amount["expected"], "12341709.11")
        self.assertEqual(
            net_amount["components"]["X01040000"]["source"],
            "inferred",
        )
        self.assertEqual(
            net_amount["components"]["X01090000"]["source"],
            "inferred",
        )


if __name__ == "__main__":
    unittest.main()
