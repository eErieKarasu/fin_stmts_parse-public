import os
import unittest
from unittest.mock import patch

from apps.fin_stmts_parse.src.core.contracts import InspectionResult
from lwade_utils.bootload import load_entry_module


os.environ["RUNNING_ENV"] = "local"

module = load_entry_module("apps/fin_stmts_parse_mcp", "mcp", "service.py")

SHORT_REASONS = {
    "校验通过",
    "复核通过",
    "校验未通过",
    "字段缺失",
    "无法校验",
    "疑似字段错误",
}


BALANCE_PASS_MAPPED = {
    "Z01010001": ["流动资产合计", "100", "120"],
    "Z01010100": ["货币资金", "60", "70"],
    "Z01010610": ["应收账款", "40", "50"],
}

BALANCE_FAIL_MAPPED = {
    "Z01010001": ["流动资产合计", "90", "90"],
    "Z01010100": ["货币资金", "60", "60"],
    "Z01011100": ["其他应收款", "20", "20"],
    "Z01011210": ["存货", "30", "30"],
}

PROFIT_PASS_MAPPED = {
    "L00000000": ["营业总收入", "900", "1000"],
    "L02010100": ["营业成本", "350", "400"],
    "L02010800": ["税金及附加", "8", "10"],
    "L02010900": ["销售费用", "45", "50"],
    "L03040000": ["管理费用", "55", "60"],
    "L02011000": ["研发费用", "65", "70"],
    "L03050000": ["财务费用", "18", "20"],
    "L02011100": ["其他收益", "4", "5"],
    "L04020000": ["投资收益", "12", "15"],
    "SY1000006": ["净敞口套期收益", "1", "2"],
    "L02011200": ["公允价值变动收益", "2", "3"],
    "SY1000016": ["信用减值损失", "3", "4"],
    "SG5020000": ["资产减值损失", "4", "5"],
    "L02011300": ["资产处置收益", "5", "6"],
    "L04010000": ["营业利润", "385", "430"],
    "L04050000": ["营业外收入", "15", "20"],
    "L04070000": ["营业外支出", "8", "10"],
    "L05010000": ["利润总额", "392", "440"],
    "L04010100": ["所得税费用", "32", "40"],
    "L06010000": ["净利润", "360", "400"],
    "L05010200": ["持续经营净利润", "220", "250"],
    "L05010300": ["终止经营净利润", "140", "150"],
    "L06010100": ["其他综合收益的税后净额", "8", "10"],
    "L07000000": ["综合收益总额", "368", "410"],
}

PROFIT_FAIL_MAPPED = {
    "L06010000": ["净利润", "399"],
    "L05010200": ["持续经营净利润", "250"],
    "L05010300": ["终止经营净利润", "150"],
}

CASHFLOW_PASS_MAPPED = {
    "X01040000": ["经营活动现金流入小计", "115"],
    "X01010000": ["销售商品、提供劳务收到的现金", "100"],
    "X01020000": ["收到的税费返还", "10"],
    "X01030000": ["收到的其他与经营活动有关的现金", "5"],
    "X01090000": ["经营活动现金流出小计", "140"],
    "X01050000": ["购买商品、接受劳务支付的现金", "90"],
    "X01060000": ["支付给职工以及为职工支付的现金", "20"],
    "X01070000": ["支付的各项税费", "10"],
    "X01011800": ["支付其他与经营活动有关的现金", "20"],
    "X01100000": ["经营活动产生的现金流量净额", "-25"],
    "X02050000": ["投资活动现金流入小计", "45"],
    "X02010000": ["收回投资收到的现金", "20"],
    "X02020000": ["取得投资收益收到的现金", "5"],
    "X02030000": ["处置固定、无形和其他长期资产所收回的现金净额", "10"],
    "X02030100": ["处置子公司及其他营业单位收到的现金净额", "4"],
    "X02040000": ["收到的其他与投资活动有关的现金", "6"],
    "X02090000": ["投资活动现金流出小计", "31"],
    "X02060000": ["购建固定资产、无形资产和其他长期资产所支付的现金", "11"],
    "X02070000": ["投资支付的现金", "7"],
    "X02080200": ["取得子公司及其他营业单位支付的现金净额", "5"],
    "X02080300": ["支付其他与投资活动有关的现金", "8"],
    "X02100000": ["投资活动产生的现金流量净额", "14"],
    "X03040000": ["筹资活动现金流入小计", "95"],
    "X03010000": ["吸收投资收到的现金", "30"],
    "X02080500": ["取得借款收到的现金", "40"],
    "X03020100": ["发行债券收到的现金", "15"],
    "X03030000": ["收到的其他与筹资活动有关的现金", "10"],
    "X03080000": ["筹资活动现金流出小计", "60"],
    "X03050000": ["偿还债务支付的现金", "25"],
    "X03060000": ["分配股利、利润或偿付利息支付的现金", "20"],
    "X03070000": ["支付其他与筹资活动有关的现金", "15"],
    "X03090000": ["筹资活动产生的现金流量净额", "35"],
}

CASHFLOW_FAIL_MAPPED = {
    "X02050000": ["投资活动现金流入小计", "44"],
    "X02010000": ["收回投资收到的现金", "20"],
    "X02020000": ["取得投资收益收到的现金", "5"],
    "X02030000": ["处置固定、无形和其他长期资产所收回的现金净额", "10"],
    "X02030100": ["处置子公司及其他营业单位收到的现金净额", "4"],
    "X02040000": ["收到的其他与投资活动有关的现金", "6"],
}


def make_mapped_result(statement_type, canonical_data, **overrides):
    item = {
        "table_name": {
            "balance": "资产负债表",
            "profit": "利润表",
            "cashflow": "现金流量表",
        }[statement_type],
        "date": "202412",
        "is_consolidated": False,
        "canonical_data": canonical_data,
    }
    item.update(overrides)
    return item


def make_view_only_mapped_result(statement_type, view_data, **overrides):
    item = {
        "table_name": {
            "balance": "资产负债表",
            "profit": "利润表",
            "cashflow": "现金流量表",
        }[statement_type],
        "date": "202412",
        "is_consolidated": False,
        "view_data": view_data,
    }
    item.update(overrides)
    return item


def make_map_result_file(mapped_results, *, file_name="demo.pdf", company_name="测试公司", message="映射成功"):
    return [
        {
            "message": message,
            "file_name": file_name,
            "company_name": company_name,
            "mapped_results": mapped_results,
        }
    ]


def make_parse_result(markdown_files, *, file_name="demo.pdf", company_name="测试公司", message="解析成功"):
    return [
        {
            "message": message,
            "file_name": file_name,
            "company_name": company_name,
            "markdown_files": markdown_files,
        }
    ]


class FinStmtsParseInspectTests(unittest.TestCase):
    def tearDown(self) -> None:
        module.map_service = None
        module.inspect_service = None
        module._clear_private_map_results_cache()

    @staticmethod
    def _first_inspected_result(result):
        return result[0]["inspected_results"][0]

    def test_inspect_requires_complete_map_results(self):
        with self.assertRaisesRegex(ValueError, "fin_stmts_parse_map 的完整输出"):
            module.fin_stmts_parse_inspect(
                [make_mapped_result("balance", BALANCE_PASS_MAPPED)],
                session_id="session-1",
            )

    def test_inspect_rejects_markdown_report_status(self):
        with self.assertRaisesRegex(ValueError, "report_status 仅支持 0 或 1"):
            module.fin_stmts_parse_inspect(
                make_map_result_file(
                    [make_mapped_result("balance", BALANCE_PASS_MAPPED)]
                ),
                session_id="session-1",
                report_status="-1",
            )

    def test_single_balance_item_returns_minimal_payload(self):
        with patch.object(module.get_inspect_service().repository, "replace_session_snapshot"):
            result = module.fin_stmts_parse_inspect(
                make_map_result_file(
                    [make_mapped_result("balance", BALANCE_PASS_MAPPED)]
                ),
                session_id="session-1",
            )

        self.assertEqual(set(result[0]), {"message", "file_name", "company_name", "inspection_passed", "inspected_results"})
        self.assertEqual(
            result[0]["message"],
            "勾稽校验完成，有1 张表参与了校验；总计 20 条，2 条通过，18 条失败",
        )
        self.assertFalse(result[0]["inspection_passed"])
        inspected = self._first_inspected_result(result)
        self.assertEqual(inspected["table_name"], "资产负债表")
        self.assertEqual(inspected["table_type"], "balance")
        self.assertEqual(inspected["period"], "YEAR")
        self.assertEqual(len(inspected["details"]), 20)
        self.assertTrue(
            all(
                set(detail) == {"check_item", "status", "period", "suspects", "reason"}
                for detail in inspected["details"]
            )
        )

    def test_inspect_can_hydrate_canonical_data_from_session_cache(self):
        module.map_service = None
        module.inspect_service = None
        with patch.object(
            module.FinStmtsMapService,
            "_run_passive_inspect",
            return_value=None,
        ), patch.object(
            module.get_inspect_service().repository,
            "replace_session_snapshot",
        ):
            map_result = module.fin_stmts_parse_map(
                make_parse_result(
                    [
                        {
                            "table_name": "资产负债表",
                            "date": "202412",
                            "content": """
# 资产负债表

| 资产 | 行次 | 期末余额 | 年初余额 |
| :--- | :---: | :---: | :---: |
| 流动资产合计 | 1 | 120 | 100 |
| 货币资金 | 2 | 70 | 60 |
| 应收账款 | 3 | 50 | 40 |
""",
                        }
                    ]
                ),
                session_id="session-cache",
            )
            self.assertNotIn("canonical_data", map_result[0]["mapped_results"][0])

            inspect_result = module.fin_stmts_parse_inspect(
                map_result,
                session_id="session-cache",
                report_status="0",
            )

        self.assertFalse(inspect_result[0]["inspection_passed"])
        self.assertTrue(inspect_result[0]["inspected_results"][0]["details"])

    def test_active_inspect_materializes_canonical_data_from_current_view_data(self):
        captured = {}

        def capture_mapped_results(mapped_results):
            mapped_result_list = list(mapped_results)
            captured["mapped_result"] = mapped_result_list[0]
            return InspectionResult(
                passed=True,
                details=[
                    {
                        "_table": "profit",
                        "check": "当前页面",
                        "result": "pass",
                        "suspects": [],
                    }
                ],
                summary={
                    "total_checks": 1,
                    "passed_checks": 1,
                    "failed_checks": 0,
                    "skipped_checks": 0,
                },
            )

        module._cache_private_map_results(
            "session-active-view",
            make_map_result_file(
                [
                    make_mapped_result(
                        "profit",
                        {"L06010000": ["净利润", "999"]},
                    )
                ]
            ),
        )

        with patch.object(
            module.get_inspect_service().inspect_core,
            "inspect_mapped_results",
            side_effect=capture_mapped_results,
        ), patch.object(module.get_inspect_service().repository, "replace_session_snapshot"):
            result = module.fin_stmts_parse_inspect(
                make_map_result_file(
                    [make_view_only_mapped_result("profit", PROFIT_PASS_MAPPED)]
                ),
                session_id="session-active-view",
                report_status="1",
            )

        self.assertTrue(result[0]["inspection_passed"])
        mapped_result = captured["mapped_result"]
        self.assertEqual(
            mapped_result.canonical_data_full["L06010000"],
            ["360", "400"],
        )
        self.assertEqual(mapped_result.canonical_labels["L06010000"], "净利润")

    def test_active_inspect_keeps_cached_hidden_canonical_items(self):
        captured = {}

        def capture_mapped_results(mapped_results):
            mapped_result_list = list(mapped_results)
            captured["mapped_result"] = mapped_result_list[0]
            return InspectionResult(
                passed=True,
                details=[],
                summary={
                    "total_checks": 0,
                    "passed_checks": 0,
                    "failed_checks": 0,
                    "skipped_checks": 0,
                },
            )

        module._cache_private_map_results(
            "session-active-hidden-canonical",
            make_map_result_file(
                [
                    make_mapped_result(
                        "balance",
                        {
                            "Z01020100": ["长期投资合计", "5100000.00", "10000000.00"],
                            "Z01030000": ["固定资产", "1", "2"],
                        },
                    )
                ]
            ),
        )

        with patch.object(
            module.get_inspect_service().inspect_core,
            "inspect_mapped_results",
            side_effect=capture_mapped_results,
        ), patch.object(module.get_inspect_service().repository, "replace_session_snapshot"):
            module.fin_stmts_parse_inspect(
                make_map_result_file(
                    [
                        make_view_only_mapped_result(
                            "balance",
                            {"Z01030000": ["固定资产", "3", "4"]},
                        )
                    ]
                ),
                session_id="session-active-hidden-canonical",
                report_status="1",
            )

        mapped_result = captured["mapped_result"]
        self.assertEqual(
            mapped_result.canonical_data_full["Z01020100"],
            ["5100000.00", "10000000.00"],
        )
        self.assertEqual(mapped_result.canonical_data_full["Z01030000"], ["3", "4"])

    def test_active_inspect_accepts_view_data_without_canonical_data(self):
        with patch.object(module.get_inspect_service().repository, "replace_session_snapshot"):
            result = module.fin_stmts_parse_inspect(
                make_map_result_file(
                    [make_view_only_mapped_result("profit", PROFIT_PASS_MAPPED)]
                ),
                session_id="session-active-no-canonical",
                report_status="1",
            )

        self.assertTrue(result[0]["inspection_passed"])
        self.assertEqual(
            result[0]["message"],
            "勾稽校验完成，有1 张表参与了校验；总计 5 条，5 条通过，0 条失败",
        )

    def test_balance_details_keep_period_suffix(self):
        with patch.object(module.get_inspect_service().repository, "replace_session_snapshot"):
            result = module.fin_stmts_parse_inspect(
                make_map_result_file(
                    [make_mapped_result("balance", BALANCE_PASS_MAPPED)]
                ),
                session_id="session-1",
            )

        details_list = self._first_inspected_result(result)["details"]
        check_items = {detail["check_item"] for detail in details_list}
        self.assertIn("流动资产合计(年初)", check_items)
        self.assertIn("流动资产合计(期末)", check_items)
        details = {
            detail["check_item"]: detail
            for detail in details_list
        }
        self.assertEqual(details["流动资产合计(年初)"]["period"], "begin")
        self.assertEqual(details["流动资产合计(期末)"]["period"], "end")

    def test_single_profit_item_returns_minimal_payload(self):
        with patch.object(module.get_inspect_service().repository, "replace_session_snapshot"):
            result = module.fin_stmts_parse_inspect(
                make_map_result_file(
                    [make_mapped_result("profit", PROFIT_PASS_MAPPED)]
                ),
                session_id="session-profit",
            )

        self.assertEqual(set(result[0]), {"message", "file_name", "company_name", "inspection_passed", "inspected_results"})
        self.assertEqual(
            result[0]["message"],
            "勾稽校验完成，有1 张表参与了校验；总计 5 条，5 条通过，0 条失败",
        )
        self.assertTrue(result[0]["inspection_passed"])
        inspected = self._first_inspected_result(result)
        self.assertEqual(inspected["table_type"], "profit")
        self.assertEqual(len(inspected["details"]), 5)
        self.assertTrue(
            all(
                set(detail) == {"check_item", "status", "period", "suspects", "reason"}
                for detail in inspected["details"]
            )
        )

    def test_single_cashflow_item_returns_minimal_payload(self):
        with patch.object(module.get_inspect_service().repository, "replace_session_snapshot"):
            result = module.fin_stmts_parse_inspect(
                make_map_result_file(
                    [make_mapped_result("cashflow", CASHFLOW_PASS_MAPPED)]
                ),
                session_id="session-cashflow",
            )

        self.assertEqual(set(result[0]), {"message", "file_name", "company_name", "inspection_passed", "inspected_results"})
        self.assertEqual(
            result[0]["message"],
            "勾稽校验完成，有1 张表参与了校验；总计 9 条，9 条通过，0 条失败",
        )
        self.assertTrue(result[0]["inspection_passed"])
        inspected = self._first_inspected_result(result)
        self.assertEqual(inspected["table_type"], "cashflow")
        self.assertEqual(len(inspected["details"]), 9)
        self.assertTrue(
            all(
                set(detail) == {"check_item", "status", "period", "suspects", "reason"}
                for detail in inspected["details"]
            )
        )

    def test_failures_expose_participating_suspects_in_order(self):
        with patch.object(module.get_inspect_service().repository, "replace_session_snapshot"):
            result = module.fin_stmts_parse_inspect(
                make_map_result_file(
                    [make_mapped_result("balance", BALANCE_FAIL_MAPPED)]
                ),
                session_id="session-1",
            )

        details = {
            detail["check_item"]: detail
            for detail in self._first_inspected_result(result)["details"]
        }
        self.assertNotIn("流动资产合计(年初)", details)
        expected_suspects = {
            "货币资金": {"code": "Z01010100", "name": "货币资金"},
            "其他应收款": {"code": "Z01011100", "name": "其他应收款"},
            "存货": {"code": "Z01011210", "name": "存货"},
        }
        for name, suspect in expected_suspects.items():
            self.assertEqual(details[f"{name}(期初)"]["status"], "fail")
            self.assertEqual(details[f"{name}(期初)"]["reason"], "疑似字段错误")
            self.assertEqual(details[f"{name}(期初)"]["suspects"], [suspect])

    def test_subtotal_failure_marks_visible_participants_suspected(self):
        balance = {
            "Z01000001": ["资产总计", "300", "300"],
            "Z01010001": ["流动资产合计", "100", "100"],
            "Z01010100": ["货币资金", "60", "60"],
            "Z01011100": ["其他应收款", "39", "39"],
            "ZY2015058": ["非流动资产合计", "200", "200"],
            "Z01030000": ["固定资产", "200", "200"],
        }
        with patch.object(module.get_inspect_service().repository, "replace_session_snapshot"):
            result = module.fin_stmts_parse_inspect(
                make_map_result_file(
                    [make_mapped_result("balance", balance)]
                ),
                session_id="session-supported-subtotal",
            )

        details = {
            detail["check_item"]: detail
            for detail in self._first_inspected_result(result)["details"]
        }
        self.assertEqual(details["流动资产合计(期初)"]["status"], "pass")
        self.assertIn(details["流动资产合计(期初)"]["reason"], SHORT_REASONS)
        expected_suspects = {
            "货币资金": {"code": "Z01010100", "name": "货币资金"},
            "其他应收款": {"code": "Z01011100", "name": "其他应收款"},
        }
        for name, suspect in expected_suspects.items():
            self.assertEqual(details[f"{name}(期初)"]["status"], "fail")
            self.assertEqual(details[f"{name}(期初)"]["reason"], "疑似字段错误")
            self.assertEqual(details[f"{name}(期初)"]["suspects"], [suspect])

    def test_recomputed_subtotal_failure_marks_visible_participants_suspected(self):
        balance = {
            "Z01000001": ["资产总计", "320", "320"],
            "Z05010000": ["负债和所有者权益（或股东权益）总计", "320", "320"],
            "Z01010001": ["流动资产合计", "100", "100"],
            "Z01010100": ["货币资金", "60", "60"],
            "Z01010610": ["应收账款", "60", "60"],
            "ZY2015058": ["非流动资产合计", "200", "200"],
            "Z01030000": ["固定资产", "200", "200"],
        }
        with patch.object(module.get_inspect_service().repository, "replace_session_snapshot"):
            result = module.fin_stmts_parse_inspect(
                make_map_result_file(
                    [make_mapped_result("balance", balance)]
                ),
                session_id="session-recomputed-subtotal-attribution",
            )

        details = {
            detail["check_item"]: detail
            for detail in self._first_inspected_result(result)["details"]
        }
        self.assertNotIn("流动资产合计(期初)", details)
        for name in ["货币资金", "应收账款"]:
            self.assertEqual(details[f"{name}(期初)"]["status"], "fail")
            self.assertEqual(details[f"{name}(期初)"]["reason"], "疑似字段错误")
        self.assertEqual(details["非流动资产合计(年初)"]["status"], "pass")
        self.assertIn(
            details["非流动资产合计(年初)"]["reason"],
            SHORT_REASONS,
        )
        self.assertEqual(details["资产总计(期初)"]["status"], "pass")
        self.assertNotEqual(details["非流动资产合计(年初)"]["status"], "fail")

    def test_consolidated_parent_equity_total_supported_by_equity_cross_check(self):
        balance = {
            "Z01000001": ["资产总计", "300", "300"],
            "Z05010000": ["负债和所有者权益（或股东权益）总计", "300", "300"],
            "Z02000001": ["负债合计", "136", "136"],
            "Z02010001": ["流动负债合计", "136", "136"],
            "Z02010100": ["短期借款", "136", "136"],
            "Z04020110": ["所有者权益（或股东权益）合计", "164", "164"],
            "Z04030400": ["归属于母公司所有者权益（或股东权益）合计", "154", "154"],
            "Z03000000": ["少数股东权益", "10", "10"],
            "Z04020200": ["实收资本（股本）", "100", "100"],
            "Z04020000": ["资本公积", "50", "50"],
        }
        with patch.object(module.get_inspect_service().repository, "replace_session_snapshot"):
            result = module.fin_stmts_parse_inspect(
                make_map_result_file(
                    [make_mapped_result("balance", balance, is_consolidated=True)]
                ),
                session_id="session-parent-equity-cross-check",
            )

        details = {
            detail["check_item"]: detail
            for detail in self._first_inspected_result(result)["details"]
        }
        self.assertEqual(
            details["归属于母公司所有者权益（或股东权益）合计(期初)"]["status"],
            "pass",
        )
        self.assertIn(
            details["归属于母公司所有者权益（或股东权益）合计(期初)"]["reason"],
            SHORT_REASONS,
        )
        self.assertEqual(details["实收资本(期初)"]["status"], "fail")
        self.assertIn(
            details["实收资本(期初)"]["reason"],
            SHORT_REASONS,
        )

    def test_owner_equity_total_supported_by_asset_liability_equity_identity(self):
        balance = {
            "Z01000001": ["资产总计", "300", "300"],
            "Z02000001": ["负债合计", "136", "136"],
            "Z02010001": ["流动负债合计", "136", "136"],
            "Z02010100": ["短期借款", "136", "136"],
            "Z04020110": ["所有者权益（或股东权益）合计", "164", "164"],
            "Z04020200": ["实收资本（股本）", "100", "100"],
            "Z04020000": ["资本公积", "50", "50"],
        }
        with patch.object(module.get_inspect_service().repository, "replace_session_snapshot"):
            result = module.fin_stmts_parse_inspect(
                make_map_result_file(
                    [make_mapped_result("balance", balance)]
                ),
                session_id="session-equity-supported-by-asset-identity",
            )

        details = {
            detail["check_item"]: detail
            for detail in self._first_inspected_result(result)["details"]
        }
        self.assertEqual(
            details["所有者权益（或股东权益）合计(期初)"]["status"],
            "pass",
        )
        self.assertIn(
            details["所有者权益（或股东权益）合计(期初)"]["reason"],
            SHORT_REASONS,
        )
        self.assertEqual(details["实收资本（股本）(期初)"]["status"], "fail")
        self.assertIn(
            details["实收资本（股本）(期初)"]["reason"],
            SHORT_REASONS,
        )

    def test_absent_minority_equity_placeholders_are_checked_as_zero(self):
        balance = {
            "Z04020110": ["所有者权益（或股东权益）合计", "164", "164"],
            "Z04030400": ["归属于母公司所有者权益（或股东权益）合计", None, None],
            "Z03000000": ["少数股东权益", None, None],
            "Z04020200": ["实收资本（股本）", "100", "100"],
            "Z04020000": ["资本公积", "50", "50"],
            "Z04050000": ["未分配利润", "14", "14"],
        }
        with patch.object(module.get_inspect_service().repository, "replace_session_snapshot"):
            result = module.fin_stmts_parse_inspect(
                make_map_result_file(
                    [make_mapped_result("balance", balance, is_consolidated=True)]
                ),
                session_id="session-absent-minority-equity-placeholders",
            )

        details = {
            detail["check_item"]: detail
            for detail in self._first_inspected_result(result)["details"]
        }
        self.assertEqual(
            details["所有者权益（或股东权益）合计(年初)"]["status"],
            "pass",
        )
        self.assertEqual(
            details["归属于母公司所有者权益（或股东权益）合计(期初)"]["status"],
            "fail",
        )
        self.assertEqual(
            details["归属于母公司所有者权益（或股东权益）合计(期初)"]["reason"],
            "字段缺失，推测值是164",
        )
        self.assertEqual(
            details["少数股东权益(期初)"]["status"],
            "pass",
        )
        self.assertIn(
            details["少数股东权益(期初)"]["reason"],
            SHORT_REASONS,
        )
        self.assertIn(
            details["所有者权益（或股东权益）合计(期初)"]["reason"],
            SHORT_REASONS,
        )
        self.assertNotIn(
            "所有者权益（或股东权益）合计 = 归属于母公司所有者权益（或股东权益）合计 + 少数股东权益(期初)",
            details,
        )

    def test_balance_other_receivables_children_are_checked(self):
        balance = {
            "Z01011100": ["其他应收款", "30", "40"],
            "Z01010500": ["应收利息", "10", "15"],
            "Z01010400": ["应收股利", "20", "25"],
        }
        with patch.object(module.get_inspect_service().repository, "replace_session_snapshot"):
            result = module.fin_stmts_parse_inspect(
                make_map_result_file(
                    [make_mapped_result("balance", balance)]
                ),
                session_id="session-other-receivables-pass",
            )

        details = {
            detail["check_item"]: detail
            for detail in self._first_inspected_result(result)["details"]
        }
        self.assertEqual(details["应收利息(期初)"]["status"], "pass")
        self.assertIn(details["应收利息(期初)"]["reason"], SHORT_REASONS)
        self.assertEqual(details["应收股利(期初)"]["status"], "pass")
        self.assertIn(details["应收股利(期初)"]["reason"], SHORT_REASONS)
        self.assertNotIn("其他应收款(年初)", details)

    def test_balance_other_payables_children_are_checked(self):
        balance = {
            "ZG2010800": ["其他应付款", "70", "90"],
            "Z02010107": ["应付利息", "30", "40"],
            "Z02010700": ["应付股利", "40", "50"],
        }
        with patch.object(module.get_inspect_service().repository, "replace_session_snapshot"):
            result = module.fin_stmts_parse_inspect(
                make_map_result_file(
                    [make_mapped_result("balance", balance)]
                ),
                session_id="session-other-payables-pass",
            )

        details = {
            detail["check_item"]: detail
            for detail in self._first_inspected_result(result)["details"]
        }
        self.assertEqual(details["应付利息(期初)"]["status"], "pass")
        self.assertIn(details["应付利息(期初)"]["reason"], SHORT_REASONS)
        self.assertEqual(details["应付股利(期初)"]["status"], "pass")
        self.assertIn(details["应付股利(期初)"]["reason"], SHORT_REASONS)
        self.assertNotIn("其他应付款(年初)", details)

    def test_balance_other_payables_parallel_track_is_accepted(self):
        balance = {
            "Z02010001": ["流动负债合计", "18", "25"],
            "Z02010100": ["短期借款", "10", "12"],
            "ZG2010800": ["其他应付款", "5", "7"],
            "Z02010107": ["应付利息", "1", "2"],
            "Z02010700": ["应付股利", "2", "4"],
        }
        with patch.object(module.get_inspect_service().repository, "replace_session_snapshot"):
            result = module.fin_stmts_parse_inspect(
                make_map_result_file(
                    [make_mapped_result("balance", balance)]
                ),
                session_id="session-other-payables-parallel",
            )

        details = {
            detail["check_item"]: detail
            for detail in self._first_inspected_result(result)["details"]
        }
        self.assertEqual(details["流动负债合计(年初)"]["status"], "pass")
        self.assertIn(details["流动负债合计(年初)"]["reason"], SHORT_REASONS)
        self.assertEqual(details["其他应付款(期初)"]["status"], "pass")
        self.assertIn(details["其他应付款(期初)"]["reason"], SHORT_REASONS)
        self.assertEqual(details["应付利息(期初)"]["status"], "pass")
        self.assertIn(
            details["应付利息(期初)"]["reason"],
            SHORT_REASONS,
        )
        self.assertEqual(details["应付股利(期初)"]["status"], "pass")

    def test_balance_other_receivables_single_track_marks_optional_children_pass(self):
        balance = {
            "Z01010001": ["流动资产合计", "100", "120"],
            "Z01010100": ["货币资金", "70", "90"],
            "Z01011100": ["其他应收款", "30", "30"],
            "Z01010500": ["应收利息", "", ""],
            "Z01010400": ["应收股利", "0", "0"],
        }
        with patch.object(module.get_inspect_service().repository, "replace_session_snapshot"):
            result = module.fin_stmts_parse_inspect(
                make_map_result_file(
                    [make_mapped_result("balance", balance)]
                ),
                session_id="session-other-receivables-single-track",
            )

        details = {
            detail["check_item"]: detail
            for detail in self._first_inspected_result(result)["details"]
        }
        self.assertEqual(details["流动资产合计(年初)"]["status"], "pass")
        self.assertEqual(details["其他应收款(期初)"]["status"], "pass")
        self.assertEqual(details["应收利息(期初)"]["status"], "pass")
        self.assertEqual(details["应收股利(期初)"]["status"], "pass")
        self.assertIn(
            details["应收利息(期初)"]["reason"],
            SHORT_REASONS,
        )

    def test_balance_other_equity_instruments_children_are_checked(self):
        balance = {
            "Z04020300": ["其他权益工具", "80", "100"],
            "Z04020400": ["所有者权益优先股", "30", "40"],
            "Z04020500": ["所有者权益永续债", "50", "60"],
        }
        with patch.object(module.get_inspect_service().repository, "replace_session_snapshot"):
            result = module.fin_stmts_parse_inspect(
                make_map_result_file(
                    [make_mapped_result("balance", balance)]
                ),
                session_id="session-other-equity-instruments-pass",
            )

        details = {
            detail["check_item"]: detail
            for detail in self._first_inspected_result(result)["details"]
        }
        self.assertEqual(details["所有者权益优先股(期初)"]["status"], "pass")
        self.assertIn(details["所有者权益优先股(期初)"]["reason"], SHORT_REASONS)
        self.assertEqual(details["所有者权益永续债(期初)"]["status"], "pass")
        self.assertIn(details["所有者权益永续债(期初)"]["reason"], SHORT_REASONS)
        self.assertNotIn("其他权益工具(年初)", details)

    def test_balance_optional_breakdown_absent_children_have_no_detail(self):
        balance = {
            "Z01011100": ["其他应收款", "30", "40"],
            "ZG2010800": ["其他应付款", "70", "90"],
            "Z04020300": ["其他权益工具", "80", "100"],
        }
        with patch.object(module.get_inspect_service().repository, "replace_session_snapshot"):
            result = module.fin_stmts_parse_inspect(
                make_map_result_file(
                    [make_mapped_result("balance", balance)]
                ),
                session_id="session-optional-breakdown-not-checked",
            )

        details = {
            detail["check_item"]: detail
            for detail in self._first_inspected_result(result)["details"]
        }
        self.assertNotIn("其他应收款(年初)", details)
        self.assertNotIn("应收利息(期初)", details)
        self.assertNotIn("应收股利(期初)", details)
        self.assertNotIn("其他应付款(年初)", details)
        self.assertNotIn("应付利息(期初)", details)
        self.assertNotIn("应付股利(期初)", details)
        self.assertNotIn("其他权益工具(年初)", details)
        self.assertNotIn("所有者权益优先股(期初)", details)
        self.assertNotIn("所有者权益永续债(期初)", details)

    def test_balance_optional_breakdown_unextracted_children_have_no_detail(self):
        balance = {
            "Z01011100": ["其他应收款", "30", "40"],
            "Z01010500": ["应收利息", None, None],
            "Z01010400": ["应收股利", None, None],
        }
        with patch.object(module.get_inspect_service().repository, "replace_session_snapshot"):
            result = module.fin_stmts_parse_inspect(
                make_map_result_file(
                    [make_mapped_result("balance", balance)]
                ),
                session_id="session-optional-breakdown-unextracted",
            )

        details = {
            detail["check_item"]: detail
            for detail in self._first_inspected_result(result)["details"]
        }
        self.assertNotIn("其他应收款(年初)", details)
        self.assertNotIn("应收利息(期初)", details)
        self.assertNotIn("应收股利(期初)", details)

    def test_balance_optional_breakdown_empty_children_have_no_detail(self):
        balance = {
            "Z01011100": ["其他应收款", "0", "0"],
            "Z01010500": ["应收利息", "", ""],
            "Z01010400": ["应收股利", "", ""],
            "ZG2010800": ["其他应付款", "0", "0"],
            "Z02010107": ["应付利息", "", ""],
            "Z02010700": ["应付股利", "", ""],
        }
        with patch.object(module.get_inspect_service().repository, "replace_session_snapshot"):
            result = module.fin_stmts_parse_inspect(
                make_map_result_file(
                    [make_mapped_result("balance", balance)]
                ),
                session_id="session-optional-breakdown-empty",
            )

        details = {
            detail["check_item"]: detail
            for detail in self._first_inspected_result(result)["details"]
        }
        self.assertNotIn("其他应收款(年初)", details)
        self.assertNotIn("应收利息(期初)", details)
        self.assertNotIn("应收股利(期初)", details)
        self.assertNotIn("其他应付款(年初)", details)
        self.assertNotIn("应付利息(期初)", details)
        self.assertNotIn("应付股利(期初)", details)

    def test_balance_optional_breakdown_parent_and_children_unextracted_has_no_detail(self):
        balance = {
            "Z04020300": ["其他权益工具", None, None],
            "Z04020400": ["所有者权益优先股", None, None],
            "Z04020500": ["所有者权益永续债", None, None],
        }
        with patch.object(module.get_inspect_service().repository, "replace_session_snapshot"):
            result = module.fin_stmts_parse_inspect(
                make_map_result_file(
                    [make_mapped_result("balance", balance)]
                ),
                session_id="session-optional-breakdown-all-unextracted",
            )

        details = {
            detail["check_item"]: detail
            for detail in self._first_inspected_result(result)["details"]
        }
        self.assertNotIn("其他权益工具(年初)", details)
        self.assertNotIn("其他权益工具(期末)", details)
        self.assertNotIn("所有者权益优先股(期初)", details)
        self.assertNotIn("所有者权益永续债(期初)", details)

    def test_profit_net_profit_breakdown_absent_components_have_no_detail(self):
        profit = dict(PROFIT_PASS_MAPPED)
        profit.pop("L05010200")
        profit.pop("L05010300")

        with patch.object(module.get_inspect_service().repository, "replace_session_snapshot"):
            result = module.fin_stmts_parse_inspect(
                make_map_result_file(
                    [make_mapped_result("profit", profit)]
                ),
                session_id="session-profit-breakdown-not-checked",
            )

        details = {
            detail["check_item"]: detail
            for detail in self._first_inspected_result(result)["details"]
        }
        self.assertTrue(result[0]["inspection_passed"])
        self.assertIn("总计 4 条，4 条通过，0 条失败", result[0]["message"])
        self.assertNotIn("净利润 = 持续经营净利润 + 终止经营净利润", details)

    def test_profit_failures_expose_participating_suspects_in_order(self):
        with patch.object(module.get_inspect_service().repository, "replace_session_snapshot"):
            result = module.fin_stmts_parse_inspect(
                make_map_result_file(
                    [make_mapped_result("profit", PROFIT_FAIL_MAPPED)]
                ),
                session_id="session-profit",
            )

        details = {
            detail["check_item"]: detail
            for detail in self._first_inspected_result(result)["details"]
        }
        self.assertEqual(
            details["净利润 = 持续经营净利润 + 终止经营净利润"],
            {
                "check_item": "净利润 = 持续经营净利润 + 终止经营净利润",
                "status": "fail",
                "period": "end",
                "suspects": [
                    {"code": "L06010000", "name": "净利润"},
                    {"code": "L05010200", "name": "持续经营净利润"},
                    {"code": "L05010300", "name": "终止经营净利润"},
                ],
                "reason": "校验未通过",
            },
        )

    def test_profit_missing_total_reason_includes_inferred_value(self):
        profit_missing_total = {
            "L05010000": ["利润总额", "50132525.57"],
            "L04010100": ["所得税费用", "0"],
            "L06010100": ["其他综合收益的税后净额", "0"],
        }
        with patch.object(module.get_inspect_service().repository, "replace_session_snapshot"):
            result = module.fin_stmts_parse_inspect(
                make_map_result_file(
                    [make_mapped_result("profit", profit_missing_total)]
                ),
                session_id="session-profit-missing-total",
            )

        details = {
            detail["check_item"]: detail
            for detail in self._first_inspected_result(result)["details"]
        }
        self.assertEqual(
            details["净利润 = 利润总额 - 所得税费用"]["reason"],
            "字段缺失",
        )
        self.assertEqual(
            details["综合收益总额(期末)"]["reason"],
            "字段缺失，推测值是50132525.57",
        )

    def test_profit_semantic_validation_can_pass_old_standard_operating_profit(self):
        canonical_profit = {
            "L03000000": ["主营业务利润", "480"],
            "L03010000": ["其他业务利润", "80"],
            "L02010900": ["销售费用", "50"],
            "L03040000": ["管理费用", "60"],
            "L03050000": ["财务费用", "20"],
            "L04010000": ["营业利润", "430"],
        }
        view_profit = {
            "L04010000": ["营业利润", "430"],
            "L02010900": ["销售费用", "50"],
            "L03040000": ["管理费用", "60"],
            "L03050000": ["财务费用", "20"],
            "L04020000": ["投资收益", "15"],
        }
        with patch.object(module.get_inspect_service().repository, "replace_session_snapshot"):
            result = module.fin_stmts_parse_inspect(
                make_map_result_file(
                    [make_mapped_result("profit", canonical_profit, view_data=view_profit)]
                ),
                session_id="session-profit-semantic-pass",
                report_status="0",
            )

        details = {
            detail["check_item"]: detail
            for detail in self._first_inspected_result(result)["details"]
        }
        self.assertEqual(details["营业利润"]["status"], "pass")
        self.assertIn(details["营业利润"]["reason"], SHORT_REASONS)

    def test_balance_semantic_validation_can_pass_old_standard_long_term_investment(self):
        canonical_balance = {
            "ZY2015058": ["非流动资产合计", "1638107433.15", "2648107433.15"],
            "Z01020100": ["长期投资合计", "5100000.00", "10000000.00"],
            "Z01020121": ["投资性房地产", "51284469.51", "52484415.51"],
            "Z01030000": ["固定资产", "1384256669.98", "2165899605.26"],
            "Z01030300": ["在建工程", "151584698.55", "254572349.63"],
            "Z01040100": ["无形资产", "45881595.11", "45881595.11"],
        }
        view_balance = {
            "ZY2015058": ["非流动资产合计", "1638107433.15", "2648107433.15"],
            "Z01020121": ["投资性房地产", "51284469.51", "52484415.51"],
            "Z01030000": ["固定资产", "1384256669.98", "2165899605.26"],
            "Z01030300": ["在建工程", "151584698.55", "254572349.63"],
            "Z01040100": ["无形资产", "45881595.11", "45881595.11"],
        }
        with patch.object(module.get_inspect_service().repository, "replace_session_snapshot"):
            result = module.fin_stmts_parse_inspect(
                make_map_result_file(
                    [make_mapped_result("balance", canonical_balance, view_data=view_balance)]
                ),
                session_id="session-balance-semantic-pass",
                report_status="0",
            )

        details = {
            detail["check_item"]: detail
            for detail in self._first_inspected_result(result)["details"]
        }
        self.assertEqual(details["非流动资产合计(年初)"]["status"], "pass")
        self.assertIn(details["非流动资产合计(年初)"]["reason"], SHORT_REASONS)
        self.assertEqual(
            details["非流动资产合计(年初)"]["validated_components"],
            [
                {"code": "Z01020121", "name": "投资性房地产"},
                {"code": "Z01030000", "name": "固定资产"},
                {"code": "Z01030300", "name": "在建工程"},
                {"code": "Z01040100", "name": "无形资产"},
            ],
        )

    def test_balance_old_standard_hidden_subtotals_are_split_to_visible_rows(self):
        canonical_balance = {
            "Z01020100": ["长期投资合计", "5100000.00", "10000000.00"],
            "Z01030010": ["固定资产合计", "1535841368.53", "2420471954.89"],
            "Z01040000": ["无形资产及其他资产合计", "97166064.62", "98366010.62"],
        }
        view_balance = {
            "Z01000001": ["资产总计", "2347987161.49", "3338681675.00"],
            "Z01010001": ["流动资产合计", "709879728.34", "809843709.49"],
            "Z01020110": ["长期股权投资", None, None],
            "ZY2015109": ["其他权益工具投资", None, None],
            "ZY2015073": ["债权投资", None, None],
            "ZY2015074": ["其他债权投资", None, None],
            "ZY2015110": ["其他非流动金融资产", None, None],
            "Z01020121": ["投资性房地产", "51284469.51", "52484415.51"],
            "Z01030000": ["固定资产", "1384256669.98", "2165899605.26"],
            "Z01030300": ["在建工程", "151584698.55", "254572349.63"],
            "Z01040100": ["无形资产", "45881595.11", "45881595.11"],
            "ZY2015058": ["非流动资产合计", None, None],
        }
        with patch.object(module.get_inspect_service().repository, "replace_session_snapshot"):
            result = module.fin_stmts_parse_inspect(
                make_map_result_file(
                    [
                        make_mapped_result(
                            "balance",
                            canonical_balance,
                            view_data=view_balance,
                        )
                    ]
                ),
                session_id="session-balance-old-standard-row-split",
                report_status="0",
            )

        details = {
            detail["check_item"]: detail
            for detail in self._first_inspected_result(result)["details"]
        }
        for name in ["固定资产", "在建工程", "无形资产", "投资性房地产"]:
            self.assertEqual(details[f"{name}(期初)"]["status"], "pass")

        for name in [
            "长期股权投资",
            "其他权益工具投资",
            "债权投资",
            "其他债权投资",
            "其他非流动金融资产",
        ]:
            self.assertEqual(details[f"{name}(期初)"]["status"], "fail")
            self.assertIn(
                details[f"{name}(期初)"]["reason"],
                SHORT_REASONS,
            )

    def test_profit_semantic_missing_total_reason_uses_canonical_formula_value(self):
        canonical_profit = {
            "L03000000": ["主营业务利润", "480"],
            "L03010000": ["其他业务利润", "80"],
            "L02010900": ["销售费用", "50"],
            "L03040000": ["管理费用", "60"],
            "L03050000": ["财务费用", "20"],
            "L04050000": ["营业外收入", "20"],
            "L04070000": ["营业外支出", "10"],
        }
        view_profit = {
            "L04050000": ["营业外收入", "20"],
            "L04070000": ["营业外支出", "10"],
        }
        with patch.object(module.get_inspect_service().repository, "replace_session_snapshot"):
            result = module.fin_stmts_parse_inspect(
                make_map_result_file(
                    [make_mapped_result("profit", canonical_profit, view_data=view_profit)]
                ),
                session_id="session-profit-semantic-missing-total",
                report_status="0",
            )

        details = {
            detail["check_item"]: detail
            for detail in self._first_inspected_result(result)["details"]
        }
        self.assertEqual(details["营业利润"]["reason"], "字段缺失")
        self.assertEqual(details["利润总额"]["reason"], "字段缺失")

    def test_cashflow_failures_expose_participating_suspects_in_order(self):
        with patch.object(module.get_inspect_service().repository, "replace_session_snapshot"):
            result = module.fin_stmts_parse_inspect(
                make_map_result_file(
                    [make_mapped_result("cashflow", CASHFLOW_FAIL_MAPPED)]
                ),
                session_id="session-cashflow",
            )

        details = {
            detail["check_item"]: detail
            for detail in self._first_inspected_result(result)["details"]
        }
        self.assertEqual(
            details["投资活动现金流入小计"],
            {
                "check_item": "投资活动现金流入小计",
                "status": "fail",
                "period": "end",
                "suspects": [
                    {"code": "X02050000", "name": "投资活动现金流入小计"},
                    {"code": "X02010000", "name": "收回投资收到的现金"},
                    {"code": "X02020000", "name": "取得投资收益收到的现金"},
                    {"code": "X02030000", "name": "处置固定、无形和其他长期资产所收回的现金净额"},
                    {"code": "X02030100", "name": "处置子公司及其他营业单位收到的现金净额"},
                    {"code": "X02040000", "name": "收到的其他与投资活动有关的现金"},
                ],
                "reason": "校验未通过",
            },
        )

    def test_cashflow_subtotal_confirmed_by_net_marks_subtotal_pass_and_children_fail(self):
        cashflow = {
            "X02050000": ["投资活动现金流入小计", "1315531.99"],
            "X02020000": ["取得投资收益收到的现金", "295531.99"],
            "X02030000": ["处置固定、无形和其他长期资产所收回的现金净额", "0.0"],
            "X02040000": ["收到的其他与投资活动有关的现金", "0.0"],
            "X02090000": ["投资活动现金流出小计", "426315896.02"],
            "X02060000": ["购建固定资产、无形资产和其他长期资产所支付的现金", "426315896.02"],
            "X02080300": ["支付其他与投资活动有关的现金", "0.0"],
            "X02100000": ["投资活动产生的现金流量净额", "-425000364.03"],
        }

        with patch.object(module.get_inspect_service().repository, "replace_session_snapshot"):
            result = module.fin_stmts_parse_inspect(
                make_map_result_file(
                    [make_mapped_result("cashflow", cashflow)]
                ),
                session_id="session-cashflow-confirmed-subtotal",
            )

        details = {
            detail["check_item"]: detail
            for detail in self._first_inspected_result(result)["details"]
        }
        self.assertEqual(details["投资活动现金流入小计(期末)"]["status"], "pass")
        self.assertIn(
            details["投资活动现金流入小计(期末)"]["reason"],
            SHORT_REASONS,
        )
        self.assertEqual(details["收回投资收到的现金(期末)"]["status"], "fail")
        self.assertEqual(details["取得投资收益收到的现金(期末)"]["status"], "fail")
        self.assertIn(details["收回投资收到的现金(期末)"]["reason"], SHORT_REASONS)
        self.assertEqual(
            details["投资活动产生的现金流量净额 = 投资活动现金流入小计 - 投资活动现金流出小计"]["status"],
            "pass",
        )

    def test_cashflow_subtotal_component_sum_confirmed_by_net_marks_subtotal_suspected(self):
        cases = [
            (
                "operating",
                {
                    "X01040000": ["经营活动现金流入小计", "", "90"],
                    "X01010000": ["销售商品、提供劳务收到的现金", "", "70"],
                    "X01020000": ["收到的税费返还", "", "10"],
                    "X01030000": ["收到的其他与经营活动有关的现金", "", "20"],
                    "X01090000": ["经营活动现金流出小计", "", "40"],
                    "X01050000": ["购买商品、接受劳务支付的现金", "", "25"],
                    "X01060000": ["支付给职工以及为职工支付的现金", "", "5"],
                    "X01070000": ["支付的各项税费", "", "4"],
                    "X01011800": ["支付其他与经营活动有关的现金", "", "6"],
                    "X01100000": ["经营活动产生的现金流量净额", "", "60"],
                },
                "经营活动现金流入小计(期末)",
                "疑似字段错误，推测值是100",
                "经营活动产生的现金流量净额(期末)",
                "销售商品、提供劳务收到的现金(期末)",
            ),
            (
                "investing",
                {
                    "X02050000": ["投资活动现金流入小计", "", "56107500.0"],
                    "X02020000": ["取得投资收益收到的现金", "", "6187500.0"],
                    "X02040000": ["收到的其他与投资活动有关的现金", "", "50000000.0"],
                    "X02090000": ["投资活动现金流出小计", "", "230106986.35"],
                    "X02060000": [
                        "购建固定资产、无形资产和其他长期资产所支付的现金",
                        "",
                        "230106986.35",
                    ],
                    "X02100000": ["投资活动产生的现金流量净额", "", "-173919486.35"],
                },
                "投资活动现金流入小计(期末)",
                "疑似字段错误，推测值是56187500.0",
                "投资活动产生的现金流量净额(期末)",
                "取得投资收益收到的现金(期末)",
            ),
            (
                "financing",
                {
                    "X03040000": ["筹资活动现金流入小计", "", "200"],
                    "X03010000": ["吸收投资收到的现金", "", "50"],
                    "X02080500": ["取得借款收到的现金", "", "120"],
                    "X03020100": ["发行债券收到的现金", "", "20"],
                    "X03030000": ["收到的其他与筹资活动有关的现金", "", "10"],
                    "X03080000": ["筹资活动现金流出小计", "", "70"],
                    "X03050000": ["偿还债务支付的现金", "", "30"],
                    "X03060000": ["分配股利、利润或偿付利息支付的现金", "", "25"],
                    "X03070000": ["支付其他与筹资活动有关的现金", "", "20"],
                    "X03090000": ["筹资活动产生的现金流量净额", "", "125"],
                },
                "筹资活动现金流出小计(期末)",
                "疑似字段错误，推测值是75",
                "筹资活动产生的现金流量净额(期末)",
                "偿还债务支付的现金(期末)",
            ),
        ]

        for section, cashflow, subtotal_key, reason, net_key, component_key in cases:
            with self.subTest(section=section):
                with patch.object(module.get_inspect_service().repository, "replace_session_snapshot"):
                    result = module.fin_stmts_parse_inspect(
                        make_map_result_file(
                            [make_mapped_result("cashflow", cashflow)]
                        ),
                        session_id=f"session-cashflow-{section}-subtotal-inferred",
                    )

                details = {
                    detail["check_item"]: detail
                    for detail in self._first_inspected_result(result)["details"]
                }
                self.assertEqual(details[subtotal_key]["status"], "fail")
                self.assertEqual(details[subtotal_key]["reason"], reason)
                self.assertEqual(details[net_key]["status"], "pass")
                self.assertNotIn(component_key, details)

    def test_cashflow_multiple_missing_subtotals_supported_by_net_report_inferred_values(self):
        cashflow_missing_subtotals = {
            "X01010000": ["销售商品、提供劳务收到的现金", "460914309.38"],
            "X01020000": ["收到的税费返还", "0"],
            "X01030000": ["收到的其他与经营活动有关的现金", "104902614.97"],
            "X01050000": ["购买商品、接受劳务支付的现金", "517122787.55"],
            "X01060000": ["支付给职工以及为职工支付的现金", "602598.0"],
            "X01070000": ["支付的各项税费", "13745547.1"],
            "X01011800": ["支付其他与经营活动有关的现金", "22004282.59"],
            "X01100000": ["经营活动产生的现金流量净额", "12341709.11"],
        }
        with patch.object(module.get_inspect_service().repository, "replace_session_snapshot"):
            result = module.fin_stmts_parse_inspect(
                make_map_result_file(
                    [make_mapped_result("cashflow", cashflow_missing_subtotals)]
                ),
                session_id="session-cashflow-missing-subtotals",
            )

        details = {
            detail["check_item"]: detail
            for detail in self._first_inspected_result(result)["details"]
        }
        self.assertEqual(details["经营活动现金流入小计(期末)"]["status"], "fail")
        self.assertEqual(
            details["经营活动现金流入小计(期末)"]["reason"],
            "字段缺失，推测值是565816924.35",
        )
        self.assertEqual(details["经营活动现金流出小计(期末)"]["status"], "fail")
        self.assertEqual(
            details["经营活动现金流出小计(期末)"]["reason"],
            "字段缺失，推测值是553475215.24",
        )
        self.assertEqual(details["经营活动产生的现金流量净额(期末)"]["status"], "pass")
        validated_codes = {
            component["code"]
            for component in details["经营活动产生的现金流量净额(期末)"]["validated_components"]
        }
        self.assertEqual(
            validated_codes,
            {
                "X01010000",
                "X01020000",
                "X01030000",
                "X01050000",
                "X01060000",
                "X01070000",
                "X01011800",
            },
        )

    def test_cashflow_missing_outflow_subtotal_is_supported_by_net_and_marks_children_pass(self):
        cashflow = {
            "X01040000": ["经营活动现金流入小计", "1701299920.15"],
            "X01010000": ["销售商品、提供劳务收到的现金", "1677144131.22"],
            "X01030000": ["收到的其他与经营活动有关的现金", "24155788.93"],
            "X01050000": ["购买商品、接受劳务支付的现金", "1316374934.35"],
            "X01060000": ["支付给职工以及为职工支付的现金", "301200.0"],
            "X01070000": ["支付的各项税费", "695002.5"],
            "X01011800": ["支付其他与经营活动有关的现金", "39582.07"],
            "X01100000": ["经营活动产生的现金流量净额", "383889201.23"],
        }

        with patch.object(module.get_inspect_service().repository, "replace_session_snapshot"):
            result = module.fin_stmts_parse_inspect(
                make_map_result_file(
                    [make_mapped_result("cashflow", cashflow)]
                ),
                session_id="session-cashflow-missing-outflow-supported",
            )

        details = {
            detail["check_item"]: detail
            for detail in self._first_inspected_result(result)["details"]
        }
        self.assertEqual(details["经营活动现金流出小计(期末)"]["status"], "fail")
        self.assertEqual(
            details["经营活动现金流出小计(期末)"]["reason"],
            "字段缺失，推测值是1317410718.92",
        )
        self.assertNotIn("购买商品、接受劳务支付的现金(期末)", details)
        self.assertNotIn("支付给职工以及为职工支付的现金(期末)", details)
        self.assertEqual(details["经营活动产生的现金流量净额(期末)"]["status"], "pass")
        self.assertIn(
            details["经营活动产生的现金流量净额(期末)"]["reason"],
            SHORT_REASONS,
        )
        validated_codes = {
            component["code"]
            for component in details["经营活动产生的现金流量净额(期末)"]["validated_components"]
        }
        self.assertEqual(
            validated_codes,
            {"X01050000", "X01060000", "X01070000", "X01011800"},
        )

    def test_balance_missing_total_reason_includes_inferred_zero_from_empty_components(self):
        balance_missing_non_current_liabilities = {
            "Z02000001": ["负债合计", "79026659.5", "96236162.38"],
            "Z02010001": ["流动负债合计", "79026659.5", "96236162.38"],
            "Z02020100": ["长期借款", "", ""],
            "Z02020200": ["应付债券", "", ""],
            "Z02020300": ["长期应付款", "", ""],
            "Z02011200": ["预计负债", "", ""],
        }
        with patch.object(module.get_inspect_service().repository, "replace_session_snapshot"):
            result = module.fin_stmts_parse_inspect(
                make_map_result_file(
                    [make_mapped_result("balance", balance_missing_non_current_liabilities)]
                ),
                session_id="session-balance-empty-liabilities",
            )

        details = {
            detail["check_item"]: detail
            for detail in self._first_inspected_result(result)["details"]
        }
        self.assertEqual(details["非流动负债合计(期末)"]["status"], "fail")
        self.assertEqual(details["非流动负债合计(期末)"]["reason"], "字段缺失，推测值是0")

    def test_balance_missing_non_current_liability_uses_parent_residual_without_marking_downstream_red(self):
        balance = {
            "Z02010001": ["流动负债合计", "100", "100"],
            "Z02010100": ["短期借款", "100", "100"],
            "Z02020100": ["长期借款", "25", "25"],
            "Z02020200": ["应付债券", "", ""],
            "Z02020300": ["长期应付款", "5", "5"],
            "Z02000001": ["负债合计", "150", "150"],
            "Z04020110": ["所有者权益（或股东权益）合计", "80", "80"],
            "Z04020200": ["实收资本（股本）", "80", "80"],
            "Z05010000": ["负债和所有者权益（或股东权益）总计", "230", "230"],
            "Z01000001": ["资产总计", "230", "230"],
        }

        with patch.object(module.get_inspect_service().repository, "replace_session_snapshot"):
            result = module.fin_stmts_parse_inspect(
                make_map_result_file(
                    [make_mapped_result("balance", balance)]
                ),
                session_id="session-balance-liability-residual",
            )

        detail_items = self._first_inspected_result(result)["details"]
        details = {detail["check_item"]: detail for detail in detail_items}

        current_end_items = [
            detail
            for detail in detail_items
            if detail["check_item"] == "流动负债合计(期末)"
        ]
        liability_equity_end_items = [
            detail
            for detail in detail_items
            if (
                detail["period"] == "end"
                and "负债和所有者权益" in detail["check_item"]
            )
        ]

        self.assertTrue(current_end_items)
        self.assertTrue(all(detail["status"] == "pass" for detail in current_end_items))
        self.assertEqual(details["非流动负债合计(期末)"]["status"], "fail")
        self.assertEqual(details["非流动负债合计(期末)"]["reason"], "字段缺失，推测值是50")
        for name, code in {
            "长期借款": "Z02020100",
            "应付债券": "Z02020200",
            "长期应付款": "Z02020300",
        }.items():
            item = details[f"{name}(期末)"]
            self.assertEqual(item["status"], "fail")
            self.assertEqual(item["reason"], "子项和不匹配")
            self.assertEqual(item["suspects"], [{"code": code, "name": name}])
        self.assertEqual(details["负债合计(期末)"]["status"], "pass")
        self.assertTrue(liability_equity_end_items)
        self.assertTrue(all(detail["status"] == "pass" for detail in liability_equity_end_items))

    def test_unqualified_skip_detail_is_filtered(self):
        inspection_result = InspectionResult(
            passed=True,
            details=[
                {
                    "check": "流动资产合计(期末)",
                    "result": "skip",
                    "period": "期末",
                    "_table": "balance",
                    "suspects": [],
                }
            ],
            summary={"passed_checks": 0},
        )

        with patch.object(
            module.get_inspect_service().inspect_core,
            "inspect_mapped_results",
            return_value=inspection_result,
        ), patch.object(module.get_inspect_service().repository, "replace_session_snapshot"):
            result = module.fin_stmts_parse_inspect(
                make_map_result_file(
                    [make_mapped_result("balance", BALANCE_PASS_MAPPED)]
                ),
                session_id="session-1",
            )

        self.assertEqual(self._first_inspected_result(result)["details"], [])

    def test_upper_asset_total_pass_marks_unverifiable_non_current_components_fail(self):
        inspection_result = InspectionResult(
            passed=True,
            details=[
                {
                    "check": "非流动资产合计(期末)",
                    "result": "skip",
                    "period": "期末",
                    "_table": "balance",
                    "_rule_total_code": "ZY2015058",
                    "components": {},
                    "suspects": [],
                    "reason": "view中缺少足够组成项，无法校验",
                },
                {
                    "check": "资产总计 = 流动资产合计 + 非流动资产合计(期末)",
                    "result": "pass",
                    "period": "期末",
                    "_table": "balance",
                    "_rule_total_code": "Z01000001",
                    "total": {
                        "code": "Z01000001",
                        "name": "资产总计",
                        "value": "961160471.16",
                    },
                    "components": {
                        "Z01010001": {
                            "name": "流动资产合计",
                            "reported_value": "916500682.76",
                            "recomputed_value": "916500682.76",
                            "basic_result": "pass",
                        },
                        "ZY2015058": {
                            "name": "非流动资产合计",
                            "reported_value": "44659788.40",
                            "recomputed_value": None,
                            "basic_result": "skip",
                        },
                    },
                    "suspects": [],
                    "reason": "层级校验通过",
                },
            ],
            summary={
                "total_checks": 2,
                "passed_checks": 1,
                "failed_checks": 0,
                "skipped_checks": 1,
            },
        )

        with patch.object(
            module.get_inspect_service().inspect_core,
            "inspect_mapped_results",
            return_value=inspection_result,
        ), patch.object(module.get_inspect_service().repository, "replace_session_snapshot"):
            result = module.fin_stmts_parse_inspect(
                make_map_result_file(
                    [make_mapped_result("balance", BALANCE_PASS_MAPPED)]
                ),
                session_id="session-non-current-skip-supported",
            )

        self.assertFalse(result[0]["inspection_passed"])
        details = {
            detail["check_item"]: detail
            for detail in self._first_inspected_result(result)["details"]
        }
        self.assertEqual(details["非流动资产合计(期末)"]["status"], "pass")
        self.assertIn(
            details["非流动资产合计(期末)"]["reason"],
            SHORT_REASONS,
        )
        self.assertEqual(details["固定资产(期末)"]["status"], "fail")
        self.assertEqual(
            details["固定资产(期末)"]["suspects"],
            [{"code": "Z01030000", "name": "固定资产"}],
        )
        self.assertIn(
            details["固定资产(期末)"]["reason"],
            SHORT_REASONS,
        )
        self.assertEqual(details["无形资产(期末)"]["status"], "fail")
        self.assertEqual(
            details["资产总计 = 流动资产合计 + 非流动资产合计(期末)"]["status"],
            "pass",
        )

    def test_zero_reported_non_current_liability_total_supported_by_upper_pass_marks_children_pass(self):
        inspection_result = InspectionResult(
            passed=True,
            details=[
                {
                    "check": "非流动负债合计(期末)",
                    "result": "skip",
                    "period": "期末",
                    "_table": "balance",
                    "_rule_total_code": "ZY2015061",
                    "components": {},
                    "suspects": [],
                    "reason": "view中缺少足够组成项，无法校验",
                },
                {
                    "check": "负债合计 = 流动负债合计 + 非流动负债合计(期末)",
                    "result": "pass",
                    "period": "期末",
                    "_table": "balance",
                    "_rule_total_code": "Z02000001",
                    "total": {
                        "code": "Z02000001",
                        "name": "负债合计",
                        "value": "616341.0",
                    },
                    "components": {
                        "Z02010001": {
                            "name": "流动负债合计",
                            "reported_value": "616341.0",
                            "recomputed_value": "616341.0",
                            "basic_result": "pass",
                        },
                        "ZY2015061": {
                            "name": "非流动负债合计",
                            "reported_value": "0.0",
                            "recomputed_value": None,
                            "basic_result": "skip",
                        },
                    },
                    "suspects": [],
                    "reason": "层级校验通过",
                },
            ],
            summary={
                "total_checks": 2,
                "passed_checks": 1,
                "failed_checks": 0,
                "skipped_checks": 1,
            },
        )

        with patch.object(
            module.get_inspect_service().inspect_core,
            "inspect_mapped_results",
            return_value=inspection_result,
        ), patch.object(module.get_inspect_service().repository, "replace_session_snapshot"):
            result = module.fin_stmts_parse_inspect(
                make_map_result_file(
                    [make_mapped_result("balance", BALANCE_PASS_MAPPED)]
                ),
                session_id="session-zero-non-current-liability-supported",
            )

        details = {
            detail["check_item"]: detail
            for detail in self._first_inspected_result(result)["details"]
        }
        self.assertEqual(details["非流动负债合计(期末)"]["status"], "pass")
        self.assertIn(details["非流动负债合计(期末)"]["reason"], SHORT_REASONS)
        self.assertNotIn("长期借款(期末)", details)
        self.assertNotIn("应付债券(期末)", details)
        self.assertNotIn("长期应付款(期末)", details)
        validated_codes = {
            component["code"]
            for component in details["非流动负债合计(期末)"]["validated_components"]
        }
        self.assertIn("Z02020100", validated_codes)
        self.assertIn("Z02020200", validated_codes)
        self.assertIn("Z02010710", validated_codes)
        self.assertIn("Z02010711", validated_codes)
        self.assertIn("Z02020300", validated_codes)
        self.assertEqual(
            details["负债合计 = 流动负债合计 + 非流动负债合计(期末)"]["status"],
            "pass",
        )

    def test_semantic_attribution_is_folded_into_reason_and_suspects(self):
        inspection_result = InspectionResult(
            passed=False,
            details=[
                {
                    "check": "非流动资产合计(期末)",
                    "result": "fail",
                    "period": "期末",
                    "_table": "balance",
                    "suspects": [
                        {
                            "code": "Z01030000",
                            "name": "固定资产",
                            "source": "semantic_inference",
                        }
                    ],
                    "semantic_attribution": {
                        "culprit_code": "Z01030000",
                        "culprit_name": "固定资产",
                        "mode": "semantic_component_inference_match",
                        "inferred_value": "273072.44",
                        "candidate_sum": "373072.44",
                        "validation_chain": {
                            "supports_parent_check": True,
                            "supports_grandparent_check": True,
                            "grandparent_check": {
                                "rule": "资产总计 = 流动资产合计 + 非流动资产合计",
                            },
                        },
                    },
                }
            ],
            summary={"passed_checks": 0},
        )

        with patch.object(
            module.get_inspect_service().inspect_core,
            "inspect_mapped_results",
            return_value=inspection_result,
        ), patch.object(module.get_inspect_service().repository, "replace_session_snapshot"):
            result = module.fin_stmts_parse_inspect(
                make_map_result_file(
                    [make_mapped_result("balance", BALANCE_PASS_MAPPED)]
                ),
                session_id="session-1",
            )

        details = {
            detail["check_item"]: detail
            for detail in self._first_inspected_result(result)["details"]
        }
        detail = details["固定资产(期末)"]
        self.assertEqual(
            set(detail),
            {"check_item", "status", "period", "suspects", "reason"},
        )
        self.assertEqual(detail["suspects"], [{"code": "Z01030000", "name": "固定资产"}])
        self.assertEqual(detail["reason"], "疑似字段错误")
        self.assertIn(
            details["非流动资产合计(期末)"]["reason"],
            SHORT_REASONS,
        )
        self.assertIn(
            details["资产总计(期末)"]["reason"],
            SHORT_REASONS,
        )

    def test_missing_total_semantic_attribution_is_folded_into_reason_and_suspects(self):
        inspection_result = InspectionResult(
            passed=False,
            details=[
                {
                    "check": "非流动资产合计(期末)",
                    "result": "fail",
                    "period": "期末",
                    "_table": "balance",
                    "suspects": [
                        {
                            "code": "ZY2015058",
                            "name": "非流动资产合计",
                            "source": "missing_total",
                        },
                        {
                            "code": "Z01030000",
                            "name": "固定资产",
                            "source": "semantic_inference",
                        },
                    ],
                    "semantic_attribution": {
                        "culprit_code": "Z01030000",
                        "culprit_name": "固定资产",
                        "mode": "semantic_component_inference_with_missing_parent",
                        "inferred_value": "398345.12",
                        "candidate_sum": "398345.12",
                        "missing_total_code": "ZY2015058",
                        "missing_total_name": "非流动资产合计",
                        "validation_chain": {
                            "supports_parent_check": None,
                            "supports_grandparent_check": True,
                            "grandparent_check": {
                                "rule": "资产总计 = 流动资产合计 + 非流动资产合计",
                            },
                        },
                    },
                }
            ],
            summary={"passed_checks": 0},
        )

        with patch.object(
            module.get_inspect_service().inspect_core,
            "inspect_mapped_results",
            return_value=inspection_result,
        ), patch.object(module.get_inspect_service().repository, "replace_session_snapshot"):
            result = module.fin_stmts_parse_inspect(
                make_map_result_file(
                    [make_mapped_result("balance", BALANCE_PASS_MAPPED)]
                ),
                session_id="session-1",
            )

        details = {
            detail["check_item"]: detail
            for detail in self._first_inspected_result(result)["details"]
        }
        detail = details["固定资产(期末)"]
        self.assertEqual(
            set(detail),
            {"check_item", "status", "period", "suspects", "reason"},
        )
        self.assertEqual(detail["suspects"], [{"code": "Z01030000", "name": "固定资产"}])
        self.assertEqual(detail["reason"], "疑似字段错误")
        self.assertEqual(
            details["非流动资产合计(期末)"]["suspects"],
            [{"code": "ZY2015058", "name": "非流动资产合计"}],
        )
        self.assertEqual(
            details["非流动资产合计(期末)"]["reason"],
            "字段缺失，推测值是398345.12",
        )
        self.assertIn(
            details["资产总计(期末)"]["reason"],
            SHORT_REASONS,
        )

    def test_operating_cost_subtotal_attribution_is_folded_into_reason(self):
        inspection_result = InspectionResult(
            passed=False,
            details=[
                {
                    "check": "营业利润",
                    "result": "fail",
                    "_table": "profit",
                    "suspects": [
                        {
                            "code": "L02010100",
                            "name": "营业成本",
                            "source": "supporting_subtotal_component",
                        },
                        {
                            "code": "L02010800",
                            "name": "税金及附加",
                            "source": "supporting_subtotal_component",
                        },
                    ],
                    "total": {
                        "code": "L04010000",
                        "name": "营业利润",
                        "value": "249857603.82",
                    },
                    "components": {
                        "L00000000": {
                            "name": "营业总收入",
                            "sign": "+",
                            "value": "1740659676.99",
                        },
                        "L02010100": {
                            "name": "营业成本",
                            "sign": "-",
                            "value": "1468916629.39",
                        },
                        "L02010800": {
                            "name": "税金及附加",
                            "sign": "-",
                            "value": "46365751.61",
                        },
                        "L02011100": {
                            "name": "其他收益",
                            "sign": "+",
                            "value": "232278228.46",
                        },
                    },
                    "semantic_attribution": {
                        "mode": "supporting_subtotal_match",
                        "subtotal_code": "L02000000",
                        "subtotal_name": "营业总成本",
                        "subtotal_value": "1755103810.53",
                        "component_sum": "1755103810.50",
                        "component_diff": "0.03",
                        "repair_candidates": [
                            {
                                "code": "L02010100",
                                "name": "营业成本",
                                "current_value": "1468916629.39",
                                "corrected_value": "1468916629.42",
                            },
                            {
                                "code": "L02010800",
                                "name": "税金及附加",
                                "current_value": "46365751.61",
                                "corrected_value": "46365751.64",
                            },
                        ],
                    },
                }
            ],
            summary={"passed_checks": 0},
        )

        with patch.object(
            module.get_inspect_service().inspect_core,
            "inspect_mapped_results",
            return_value=inspection_result,
        ), patch.object(module.get_inspect_service().repository, "replace_session_snapshot"):
            result = module.fin_stmts_parse_inspect(
                make_map_result_file(
                    [make_mapped_result("profit", {"L04010000": ["营业利润", "430"]})]
                ),
                session_id="session-1",
            )

        details = {
            detail["check_item"]: detail
            for detail in self._first_inspected_result(result)["details"]
        }
        self.assertEqual(details["营业利润(期末)"]["status"], "pass")
        self.assertIn(
            details["营业利润(期末)"]["reason"],
            SHORT_REASONS,
        )
        self.assertEqual(details["营业总收入(期末)"]["status"], "pass")
        self.assertIn(
            details["营业总收入(期末)"]["reason"],
            SHORT_REASONS,
        )
        self.assertEqual(details["其他收益(期末)"]["status"], "pass")
        self.assertEqual(details["营业成本(期末)"]["status"], "fail")
        self.assertEqual(details["税金及附加(期末)"]["status"], "fail")
        self.assertIn(
            details["税金及附加(期末)"]["reason"],
            SHORT_REASONS,
        )

    def test_profit_total_pass_moves_operating_profit_failure_to_components(self):
        inspection_result = InspectionResult(
            passed=False,
            details=[
                {
                    "check": "营业利润",
                    "result": "fail",
                    "_table": "profit",
                    "total": {
                        "code": "L04010000",
                        "name": "营业利润",
                        "value": "249857603.82",
                    },
                    "expected": "249857603.85",
                    "amounts": {
                        "reported_total": "249857603.82",
                        "recomputed_total": "249857603.85",
                    },
                    "components": {
                        "L00000000": {
                            "name": "营业总收入",
                            "sign": "+",
                            "value": "1740659676.99",
                        },
                        "L02010100": {
                            "name": "营业成本",
                            "sign": "-",
                            "value": "1468916629.39",
                        },
                        "L02010800": {
                            "name": "税金及附加",
                            "sign": "-",
                            "value": "46365751.61",
                        },
                    },
                    "suspects": [
                        {"code": "L04010000", "name": "营业利润", "source": "view_participant"},
                        {"code": "L00000000", "name": "营业总收入", "source": "view_participant"},
                        {"code": "L02010100", "name": "营业成本", "source": "view_participant"},
                        {"code": "L02010800", "name": "税金及附加", "source": "view_participant"},
                    ],
                },
                {
                    "check": "利润总额",
                    "result": "pass",
                    "_table": "profit",
                    "total": {
                        "code": "L05010000",
                        "name": "利润总额",
                        "value": "247159445.61",
                    },
                    "expected": "247159445.61",
                    "components": {
                        "L04010000": {
                            "name": "营业利润",
                            "sign": "+",
                            "value": "249857603.82",
                        },
                        "L04050000": {
                            "name": "营业外收入",
                            "sign": "+",
                            "value": "2054987.08",
                        },
                        "L04070000": {
                            "name": "营业外支出",
                            "sign": "-",
                            "value": "4753145.29",
                        },
                    },
                    "suspects": [],
                },
            ],
            summary={"passed_checks": 1, "failed_checks": 1},
        )

        with patch.object(
            module.get_inspect_service().inspect_core,
            "inspect_mapped_results",
            return_value=inspection_result,
        ), patch.object(module.get_inspect_service().repository, "replace_session_snapshot"):
            result = module.fin_stmts_parse_inspect(
                make_map_result_file(
                    [make_mapped_result("profit", PROFIT_PASS_MAPPED)]
                ),
                session_id="session-profit-total-confirms-operating-profit",
            )

        details = {
            detail["check_item"]: detail
            for detail in self._first_inspected_result(result)["details"]
        }
        self.assertEqual(details["营业利润(期末)"]["status"], "pass")
        self.assertIn(
            details["营业利润(期末)"]["reason"],
            SHORT_REASONS,
        )
        self.assertEqual(details["营业总收入(期末)"]["status"], "fail")
        self.assertEqual(details["营业成本(期末)"]["status"], "fail")
        self.assertIn(
            details["营业总收入(期末)"]["reason"],
            SHORT_REASONS,
        )
        self.assertIn(details["营业总收入(期末)"]["reason"], SHORT_REASONS)

    def test_verified_component_is_returned_as_pass_detail_and_removed_from_suspects(self):
        inspection_result = InspectionResult(
            passed=False,
            details=[
                {
                    "_table": "balance",
                    "check": "非流动资产合计(年初)",
                    "period": "年初",
                    "_rule_total_code": "ZY2015058",
                    "result": "fail",
                    "suspects": [
                        {
                            "code": "ZY2015058",
                            "name": "非流动资产合计",
                            "source": "view_participant",
                        },
                        {
                            "code": "Z01040100",
                            "name": "无形资产",
                            "source": "view_participant",
                        },
                    ],
                    "verified_components": [
                        {
                            "code": "Z01030000",
                            "name": "固定资产",
                            "source": "semantic_formula",
                            "inferred_value": "300",
                        }
                    ],
                }
            ],
            summary={"passed_checks": 0},
        )

        with patch.object(
            module.get_inspect_service().inspect_core,
            "inspect_mapped_results",
            return_value=inspection_result,
        ), patch.object(module.get_inspect_service().repository, "replace_session_snapshot"):
            result = module.fin_stmts_parse_inspect(
                make_map_result_file(
                    [make_mapped_result("balance", BALANCE_PASS_MAPPED)]
                ),
                session_id="session-1",
            )

        details = {
            detail["check_item"]: detail
            for detail in self._first_inspected_result(result)["details"]
        }
        fixed_asset = details["固定资产(期初)"]
        self.assertEqual(fixed_asset["status"], "pass")
        self.assertEqual(fixed_asset["suspects"], [{"code": "Z01030000", "name": "固定资产"}])
        self.assertIn(
            fixed_asset["reason"],
            SHORT_REASONS,
        )
        non_current_assets = details["非流动资产合计(年初)"]
        self.assertEqual(
            non_current_assets["suspects"],
            [
                {"code": "ZY2015058", "name": "非流动资产合计"},
                {"code": "Z01040100", "name": "无形资产"},
            ],
        )
        self.assertIn(
            non_current_assets["reason"],
            SHORT_REASONS,
        )

    def test_missing_non_current_liability_inference_is_split_by_row(self):
        inspection_result = InspectionResult(
            passed=False,
            details=[
                {
                    "check": "非流动负债合计(期末)",
                    "result": "fail",
                    "period": "期末",
                    "_table": "balance",
                    "_rule_total_code": "ZY2015061",
                    "suspects": [
                        {
                            "code": "ZY2015061",
                            "name": "非流动负债合计",
                            "source": "missing_total_inferred_from_components",
                        }
                    ],
                    "expected": "0",
                    "_inferred_total": "0",
                    "components": {
                        "Z02020100": {
                            "name": "长期借款",
                            "value": "0",
                        },
                        "Z02020200": {
                            "name": "应付债券",
                            "value": "0",
                            "source": "empty",
                        },
                    },
                    "attribution": {
                        "mode": "missing_total_inferred_from_components",
                        "culprit_code": "ZY2015061",
                        "culprit_name": "非流动负债合计",
                        "candidate_sum": "0",
                    },
                },
                {
                    "check": "负债合计 = 流动负债合计 + 非流动负债合计(期末)",
                    "result": "fail",
                    "period": "期末",
                    "_table": "balance",
                    "_rule_total_code": "Z02000001",
                    "suspects": [
                        {
                            "code": "ZY2015061",
                            "name": "非流动负债合计",
                            "source": "missing_hierarchical_component",
                        }
                    ],
                    "expected": "805382935.0",
                    "components": {
                        "Z02010001": {
                            "name": "流动负债合计",
                            "reported_value": "805382935.0",
                            "recomputed_value": "805382935.0",
                            "basic_result": "pass",
                        },
                        "ZY2015061": {
                            "name": "非流动负债合计",
                            "reported_value": None,
                            "recomputed_value": "0",
                            "basic_result": "fail",
                        },
                    },
                    "attribution": {
                        "mode": "missing_component_inferred_match",
                        "culprit_codes": ["ZY2015061"],
                        "culprit_names": ["非流动负债合计"],
                        "candidate_sum": "805382935.0",
                    },
                },
            ],
            summary={"passed_checks": 0},
        )

        with patch.object(
            module.get_inspect_service().inspect_core,
            "inspect_mapped_results",
            return_value=inspection_result,
        ), patch.object(module.get_inspect_service().repository, "replace_session_snapshot"):
            result = module.fin_stmts_parse_inspect(
                make_map_result_file(
                    [make_mapped_result("balance", BALANCE_PASS_MAPPED)]
                ),
                session_id="session-1",
            )

        details = {
            detail["check_item"]: detail
            for detail in self._first_inspected_result(result)["details"]
        }
        self.assertNotIn("长期借款(期末)", details)
        self.assertNotIn("应付债券(期末)", details)
        self.assertEqual(details["非流动负债合计(期末)"]["status"], "fail")
        self.assertEqual(
            details["非流动负债合计(期末)"]["reason"],
            "字段缺失，推测值是0",
        )
        validated_codes = {
            component["code"]
            for component in details["负债合计(期末)"]["validated_components"]
        }
        self.assertIn("Z02020100", validated_codes)
        self.assertIn("Z02020200", validated_codes)
        self.assertIn("Z02010710", validated_codes)
        self.assertIn("Z02010711", validated_codes)
        self.assertIn("Z02020300", validated_codes)
        self.assertIn(
            details["负债合计(期末)"]["reason"],
            SHORT_REASONS,
        )

    def test_missing_non_current_asset_total_is_only_failed_asset_total_culprit(self):
        inspection_result = InspectionResult(
            passed=False,
            details=[
                {
                    "check": "流动资产合计(期末)",
                    "result": "pass",
                    "period": "期末",
                    "_table": "balance",
                    "_rule_total_code": "Z01010001",
                    "suspects": [],
                    "reason": "校验通过",
                },
                {
                    "check": "非流动资产合计(期末)",
                    "result": "fail",
                    "period": "期末",
                    "_table": "balance",
                    "_rule_total_code": "ZY2015058",
                    "suspects": [
                        {
                            "code": "ZY2015058",
                            "name": "非流动资产合计",
                            "source": "missing_total_inferred_from_components",
                        }
                    ],
                    "expected": "120031665.63",
                    "_inferred_total": "120031665.63",
                    "components": {
                        "Z01030000": {
                            "name": "固定资产",
                            "value": "120031665.63",
                        },
                    },
                    "attribution": {
                        "mode": "missing_total_inferred_from_components",
                        "culprit_code": "ZY2015058",
                        "culprit_name": "非流动资产合计",
                        "candidate_sum": "120031665.63",
                    },
                },
                {
                    "check": "资产总计 = 流动资产合计 + 非流动资产合计(期末)",
                    "result": "fail",
                    "period": "期末",
                    "_table": "balance",
                    "_rule_total_code": "Z01000001",
                    "total": {
                        "code": "Z01000001",
                        "name": "资产总计",
                        "value": "211885939.57",
                    },
                    "components": {
                        "Z01010001": {
                            "name": "流动资产合计",
                            "reported_value": "91854273.94",
                            "recomputed_value": "91854273.94",
                            "basic_result": "pass",
                        },
                        "ZY2015058": {
                            "name": "非流动资产合计",
                            "reported_value": None,
                            "recomputed_value": "120031665.63",
                            "basic_result": "fail",
                        },
                    },
                    "attribution": {
                        "mode": "missing_component_inferred_match",
                        "culprit_codes": ["ZY2015058"],
                        "culprit_names": ["非流动资产合计"],
                        "candidate_sum": "211885939.57",
                    },
                    "suspects": [
                        {
                            "code": "ZY2015058",
                            "name": "非流动资产合计",
                            "source": "missing_hierarchical_component",
                        }
                    ],
                },
            ],
            summary={"passed_checks": 1, "failed_checks": 2},
        )

        with patch.object(
            module.get_inspect_service().inspect_core,
            "inspect_mapped_results",
            return_value=inspection_result,
        ), patch.object(module.get_inspect_service().repository, "replace_session_snapshot"):
            result = module.fin_stmts_parse_inspect(
                make_map_result_file(
                    [make_mapped_result("balance", BALANCE_PASS_MAPPED)]
                ),
                session_id="session-missing-non-current-assets",
            )

        details_list = self._first_inspected_result(result)["details"]
        current_asset_details = [
            detail
            for detail in details_list
            if detail["check_item"] == "流动资产合计(期末)"
        ]
        self.assertTrue(current_asset_details)
        self.assertTrue(
            all(detail["status"] == "pass" for detail in current_asset_details)
        )

        details = {
            detail["check_item"]: detail
            for detail in details_list
        }
        self.assertEqual(details["非流动资产合计(期末)"]["status"], "fail")
        self.assertEqual(
            details["非流动资产合计(期末)"]["reason"],
            "字段缺失，推测值是120031665.63",
        )
        self.assertNotIn("固定资产(期末)", details)
        self.assertNotIn("长期股权投资(期末)", details)
        self.assertNotIn("无形资产(期末)", details)
        self.assertEqual(details["资产总计(期末)"]["status"], "pass")
        self.assertIn(
            details["资产总计(期末)"]["reason"],
            SHORT_REASONS,
        )
        validated_codes = {
            component["code"]
            for component in details["资产总计(期末)"]["validated_components"]
        }
        self.assertIn("Z01030000", validated_codes)
        self.assertIn("Z01020110", validated_codes)
        self.assertIn("Z01040100", validated_codes)

    def test_asset_mixed_inference_marks_current_asset_participants_suspected(self):
        balance = {
            "Z01000001": ["资产总计", "384550416.37", "384550416.37"],
            "Z01010001": ["流动资产合计", "301665131.61", "301665131.61"],
            "Z01010100": ["货币资金", "10635481.24", "10635481.24"],
            "Z01010610": ["应收账款", "71925417.63", "71925417.63"],
            "Z01011100": ["其他应收款", "8054238.16", "8054238.16"],
            "Z01011210": ["存货", "211069994.58", "211069994.58"],
            "Z01030000": ["固定资产", "36566665.29", "36566665.29"],
            "Z01040100": ["无形资产", "46298619.47", "46298619.47"],
        }

        with patch.object(module.get_inspect_service().repository, "replace_session_snapshot"):
            result = module.fin_stmts_parse_inspect(
                make_map_result_file(
                    [make_mapped_result("balance", balance)]
                ),
                session_id="session-asset-mixed-inference",
            )

        details = {
            detail["check_item"]: detail
            for detail in self._first_inspected_result(result)["details"]
        }
        self.assertNotIn("流动资产合计(期末)", details)
        for name in ["货币资金", "应收账款", "其他应收款", "存货"]:
            self.assertEqual(details[f"{name}(期末)"]["status"], "fail")
            self.assertEqual(details[f"{name}(期末)"]["reason"], "疑似字段错误")

        self.assertEqual(details["非流动资产合计(期末)"]["status"], "fail")
        self.assertEqual(
            details["非流动资产合计(期末)"]["reason"],
            "字段缺失，推测值是82865284.76",
        )
        self.assertEqual(details["资产总计(期末)"]["status"], "pass")
        self.assertIn(details["资产总计(期末)"]["reason"], SHORT_REASONS)

    def test_liability_mixed_inference_marks_current_subtree_fail_and_non_current_children_pass(self):
        balance = {
            "Z02000001": ["负债合计", "803687526.84", "891319377.40"],
            "Z02010001": ["流动负债合计", "726775454.34", "844174698.28"],
            "Z02010100": ["短期借款", "305000000", "345000000"],
            "Z02010300": ["应付账款", "408133019.17", "475226480.89"],
            "Z02010410": ["预收款项", "25467088.37", "14437870.14"],
            "ZY2015006": ["应付职工薪酬", "3594291.99", "5081336.11"],
            "ZY2015008": ["应交税费", "1230365.91", "1053116.39"],
            "ZG2010800": ["其他应付款", "3350688.90", "3375894.75"],
            "ZY2015061": ["非流动负债合计", "", ""],
            "Z02020300": ["长期应付款", "56912072.50", "47144679.12"],
        }

        with patch.object(module.get_inspect_service().repository, "replace_session_snapshot"):
            result = module.fin_stmts_parse_inspect(
                make_map_result_file(
                    [make_mapped_result("balance", balance)]
                ),
                session_id="session-liability-mixed-inference",
            )

        details = {
            detail["check_item"]: detail
            for detail in self._first_inspected_result(result)["details"]
        }
        self.assertNotIn("流动负债合计(期初)", details)
        for name in ["短期借款", "应付账款", "预收款项", "应付职工薪酬", "应交税费", "其他应付款"]:
            self.assertEqual(details[f"{name}(期初)"]["status"], "fail")
            self.assertEqual(details[f"{name}(期初)"]["reason"], "疑似字段错误")
        self.assertNotIn("长期应付款(期初)", details)
        self.assertEqual(details["非流动负债合计(期初)"]["status"], "fail")
        self.assertEqual(details["负债合计(期初)"]["status"], "pass")
        validated_codes = {
            component["code"]
            for component in details["负债合计(期初)"]["validated_components"]
        }
        self.assertIn("Z02020300", validated_codes)
        self.assertIn("Z02010710", validated_codes)
        self.assertIn("Z02010711", validated_codes)
        self.assertIn(
            details["负债合计(期初)"]["reason"],
            SHORT_REASONS,
        )

    def test_current_liability_total_failure_marks_participants_suspected(self):
        balance = {
            "Z02000001": ["211428613.88", "805382935.0"],
            "Z02010001": ["211428613.88", "805382935.0"],
            "Z02010200": ["150000000.0", "533870000.0"],
            "Z02010300": ["60502391.51", "5424372.56"],
            "Z02010410": ["", "240971641.94"],
            "ZY2015008": ["48583.92", "83493.1"],
            "ZG2010800": ["877638.45", "25033427.38"],
            "ZY2015061": ["", ""],
            "Z02020100": ["", ""],
            "Z02020200": ["", ""],
            "Z02020300": ["", ""],
            "Z02011200": ["", ""],
            "Z01044104": ["", ""],
        }

        with patch.object(module.get_inspect_service().repository, "replace_session_snapshot"):
            result = module.fin_stmts_parse_inspect(
                make_map_result_file(
                    [make_mapped_result("balance", balance)]
                ),
                session_id="session-current-liability-participants",
            )

        details = {
            detail["check_item"]: detail
            for detail in self._first_inspected_result(result)["details"]
        }
        self.assertEqual(details["流动负债合计(期末)"]["status"], "pass")
        self.assertIn(details["流动负债合计(期末)"]["reason"], SHORT_REASONS)
        expected_suspects = {
            "应付票据": {"code": "Z02010200", "name": "应付票据"},
            "应付账款": {"code": "Z02010300", "name": "应付账款"},
            "预收款项": {"code": "Z02010410", "name": "预收款项"},
            "应交税费": {"code": "ZY2015008", "name": "应交税费"},
            "其他应付款": {"code": "ZG2010800", "name": "其他应付款"},
        }
        for name, suspect in expected_suspects.items():
            self.assertEqual(details[f"{name}(期末)"]["status"], "fail")
            self.assertEqual(details[f"{name}(期末)"]["reason"], "疑似字段错误")
            self.assertEqual(details[f"{name}(期末)"]["suspects"], [suspect])
        self.assertEqual(details["非流动负债合计(期末)"]["reason"], "字段缺失，推测值是0")
        self.assertEqual(details["负债合计(期末)"]["status"], "pass")

    def test_non_current_asset_total_failure_marks_participants_suspected(self):
        balance = {
            "ZY2015058": ["非流动资产合计", "100", "100"],
            "Z01030000": ["固定资产", "60", "60"],
            "Z01040100": ["无形资产", "50", "50"],
        }

        with patch.object(module.get_inspect_service().repository, "replace_session_snapshot"):
            result = module.fin_stmts_parse_inspect(
                make_map_result_file(
                    [make_mapped_result("balance", balance)]
                ),
                session_id="session-non-current-asset-participants",
            )

        details = {
            detail["check_item"]: detail
            for detail in self._first_inspected_result(result)["details"]
        }
        self.assertNotIn("非流动资产合计(期末)", details)
        expected_suspects = {
            "固定资产": {"code": "Z01030000", "name": "固定资产"},
            "无形资产": {"code": "Z01040100", "name": "无形资产"},
        }
        for name, suspect in expected_suspects.items():
            self.assertEqual(details[f"{name}(期末)"]["status"], "fail")
            self.assertEqual(details[f"{name}(期末)"]["reason"], "疑似字段错误")
            self.assertEqual(details[f"{name}(期末)"]["suspects"], [suspect])

    def test_non_current_liability_total_failure_marks_participants_suspected(self):
        balance = {
            "ZY2015061": ["非流动负债合计", "100", "100"],
            "Z02020100": ["长期借款", "60", "60"],
            "Z02020200": ["应付债券", "50", "50"],
        }

        with patch.object(module.get_inspect_service().repository, "replace_session_snapshot"):
            result = module.fin_stmts_parse_inspect(
                make_map_result_file(
                    [make_mapped_result("balance", balance)]
                ),
                session_id="session-non-current-liability-participants",
            )

        details = {
            detail["check_item"]: detail
            for detail in self._first_inspected_result(result)["details"]
        }
        self.assertNotIn("非流动负债合计(期末)", details)
        expected_suspects = {
            "长期借款": {"code": "Z02020100", "name": "长期借款"},
            "应付债券": {"code": "Z02020200", "name": "应付债券"},
        }
        for name, suspect in expected_suspects.items():
            self.assertEqual(details[f"{name}(期末)"]["status"], "fail")
            self.assertEqual(details[f"{name}(期末)"]["reason"], "疑似字段错误")
            self.assertEqual(details[f"{name}(期末)"]["suspects"], [suspect])

    def test_missing_total_inference_uses_direct_parent_support_when_higher_check_fails(self):
        inspection_result = InspectionResult(
            passed=False,
            details=[
                {
                    "check": "非流动负债合计(期末)",
                    "result": "fail",
                    "period": "期末",
                    "_table": "balance",
                    "_rule_total_code": "ZY2015061",
                    "suspects": [
                        {
                            "code": "ZY2015061",
                            "name": "非流动负债合计",
                            "source": "missing_total_inferred_from_components",
                        }
                    ],
                    "expected": "0",
                    "_inferred_total": "0",
                    "attribution": {
                        "mode": "missing_total_inferred_from_components",
                        "culprit_code": "ZY2015061",
                        "culprit_name": "非流动负债合计",
                        "candidate_sum": "0",
                    },
                },
                {
                    "check": "负债合计 = 流动负债合计 + 非流动负债合计(期末)",
                    "result": "fail",
                    "period": "期末",
                    "_table": "balance",
                    "_rule_total_code": "Z02000001",
                    "suspects": [
                        {
                            "code": "ZY2015061",
                            "name": "非流动负债合计",
                            "source": "missing_hierarchical_component",
                        }
                    ],
                    "expected": "805382935.0",
                    "components": {
                        "ZY2015061": {
                            "name": "非流动负债合计",
                            "reported_value": None,
                            "recomputed_value": "0",
                            "basic_result": "fail",
                        },
                    },
                    "attribution": {
                        "mode": "missing_component_inferred_match",
                        "culprit_codes": ["ZY2015061"],
                        "culprit_names": ["非流动负债合计"],
                        "candidate_sum": "805382935.0",
                    },
                },
                {
                    "check": "负债和所有者权益总计 = 流动负债合计 + 非流动负债合计 + 所有者权益（或股东权益）合计(期末)",
                    "result": "fail",
                    "period": "期末",
                    "_table": "balance",
                    "_rule_total_code": "Z05010000",
                    "suspects": [
                        {
                            "code": "Z05010000",
                            "name": "负债和所有者权益（或股东权益）总计",
                            "source": "hierarchical_total",
                        }
                    ],
                    "components": {
                        "ZY2015061": {
                            "name": "非流动负债合计",
                            "reported_value": None,
                            "recomputed_value": "0",
                            "basic_result": "fail",
                        },
                    },
                },
            ],
            summary={"passed_checks": 0},
        )

        with patch.object(
            module.get_inspect_service().inspect_core,
            "inspect_mapped_results",
            return_value=inspection_result,
        ), patch.object(module.get_inspect_service().repository, "replace_session_snapshot"):
            result = module.fin_stmts_parse_inspect(
                make_map_result_file(
                    [make_mapped_result("balance", BALANCE_PASS_MAPPED)]
                ),
                session_id="session-1",
            )

        details = {
            detail["check_item"]: detail
            for detail in self._first_inspected_result(result)["details"]
        }
        self.assertEqual(details["非流动负债合计(期末)"]["status"], "fail")
        self.assertEqual(details["非流动负债合计(期末)"]["reason"], "字段缺失，推测值是0")
        self.assertEqual(details["负债合计(期末)"]["status"], "pass")
        self.assertIn(
            details["负债合计(期末)"]["reason"],
            SHORT_REASONS,
        )

    def test_missing_zero_component_inference_formats_parent_chain_as_pass(self):
        inspection_result = InspectionResult(
            passed=False,
            details=[
                {
                    "check": "非流动负债合计(期末)",
                    "result": "fail",
                    "period": "期末",
                    "_table": "balance",
                    "_rule_total_code": "ZY2015061",
                    "suspects": [
                        {
                            "code": "ZY2015061",
                            "name": "非流动负债合计",
                            "source": "missing_total",
                        }
                    ],
                },
                {
                    "check": "负债合计 = 流动负债合计 + 非流动负债合计(期末)",
                    "result": "fail",
                    "period": "期末",
                    "_table": "balance",
                    "_rule_total_code": "Z02000001",
                    "suspects": [
                        {
                            "code": "ZY2015061",
                            "name": "非流动负债合计",
                            "source": "missing_hierarchical_component",
                        }
                    ],
                    "expected": "20699247.33",
                    "components": {
                        "Z02010001": {
                            "name": "流动负债合计",
                            "reported_value": "20699247.33",
                            "recomputed_value": None,
                            "basic_result": "pass",
                        },
                        "ZY2015061": {
                            "name": "非流动负债合计",
                            "reported_value": None,
                            "recomputed_value": "0",
                            "basic_result": "fail",
                        },
                    },
                    "attribution": {
                        "mode": "missing_component_zero_inferred_match",
                        "culprit_codes": ["ZY2015061"],
                        "culprit_names": ["非流动负债合计"],
                        "candidate_sum": "20699247.33",
                    },
                },
                {
                    "check": "负债和所有者权益（或股东权益）总计 = 流动负债合计 + 非流动负债合计 + 所有者权益（或股东权益）合计(期末)",
                    "result": "fail",
                    "period": "期末",
                    "_table": "balance",
                    "_rule_total_code": "Z05010000",
                    "suspects": [
                        {
                            "code": "ZY2015061",
                            "name": "非流动负债合计",
                            "source": "missing_hierarchical_component",
                        }
                    ],
                    "expected": "121489414.91",
                    "components": {
                        "Z02010001": {
                            "name": "流动负债合计",
                            "reported_value": "20699247.33",
                            "recomputed_value": None,
                            "basic_result": "pass",
                        },
                        "ZY2015061": {
                            "name": "非流动负债合计",
                            "reported_value": None,
                            "recomputed_value": "0",
                            "basic_result": "fail",
                        },
                        "Z04020110": {
                            "name": "所有者权益（或股东权益）合计",
                            "reported_value": "100790167.58",
                            "recomputed_value": None,
                            "basic_result": "pass",
                        },
                    },
                    "attribution": {
                        "mode": "missing_component_zero_inferred_match",
                        "culprit_codes": ["ZY2015061"],
                        "culprit_names": ["非流动负债合计"],
                        "candidate_sum": "121489414.91",
                    },
                },
            ],
            summary={"passed_checks": 0},
        )

        with patch.object(
            module.get_inspect_service().inspect_core,
            "inspect_mapped_results",
            return_value=inspection_result,
        ), patch.object(module.get_inspect_service().repository, "replace_session_snapshot"):
            result = module.fin_stmts_parse_inspect(
                make_map_result_file(
                    [make_mapped_result("balance", BALANCE_PASS_MAPPED)]
                ),
                session_id="session-1",
            )

        details = {
            detail["check_item"]: detail
            for detail in self._first_inspected_result(result)["details"]
        }
        self.assertEqual(details["非流动负债合计(期末)"]["status"], "fail")
        self.assertEqual(details["非流动负债合计(期末)"]["reason"], "字段缺失，推测值是0")
        self.assertEqual(details["负债合计(期末)"]["status"], "pass")
        self.assertIn(
            details["负债合计(期末)"]["reason"],
            SHORT_REASONS,
        )
        self.assertEqual(details["负债和所有者权益（或股东权益）总计(期末)"]["status"], "pass")
        self.assertIn(
            details["负债和所有者权益（或股东权益）总计(期末)"]["reason"],
            SHORT_REASONS,
        )


if __name__ == "__main__":
    unittest.main()
