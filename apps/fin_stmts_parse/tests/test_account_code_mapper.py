import unittest
from decimal import Decimal
from pathlib import Path

from apps.fin_stmts_parse.src.account_code_mapper import AccountCodeMapper


class AccountCodeMapperTest(unittest.TestCase):
    @staticmethod
    def _semantic_config_path() -> Path:
        repo_root = Path(__file__).resolve().parents[3]
        return (
            repo_root
            / "apps/fin_stmts_parse/config/mappings/balance/standalone/semantic.yaml"
        )

    @staticmethod
    def _cashflow_semantic_config_path() -> Path:
        repo_root = Path(__file__).resolve().parents[3]
        return (
            repo_root
            / "apps/fin_stmts_parse/config/mappings/cashflow/standalone/semantic.yaml"
        )

    @staticmethod
    def _profit_semantic_config_path() -> Path:
        repo_root = Path(__file__).resolve().parents[3]
        return (
            repo_root
            / "apps/fin_stmts_parse/config/mappings/profit/standalone/semantic.yaml"
        )

    def test_distinguishes_unmatched_item_from_matched_empty_value(self) -> None:
        mapper = AccountCodeMapper(str(self._semantic_config_path()))

        result = mapper.map_data({
            "货币资金": None,
        })

        self.assertEqual(result["Z01010100"], "")
        self.assertIsNone(result["ZY2015061"])

    def test_generic_fixed_asset_only_maps_to_its_own_standard_code(self) -> None:
        mapper = AccountCodeMapper(str(self._semantic_config_path()))

        result = mapper.map_data({
            "固定资产": ["180", "200"],
        })

        self.assertEqual(result["Z01030000"], [Decimal("180"), Decimal("200")])
        self.assertIsNone(result["Z01030005"])

    def test_fixed_asset_net_value_stays_on_its_own_semantic_code(self) -> None:
        mapper = AccountCodeMapper(str(self._semantic_config_path()))

        result = mapper.map_data({
            "固定资产净值": ["170", "190"],
        })

        self.assertEqual(result["Z01030003"], [Decimal("170"), Decimal("190")])
        self.assertIsNone(result["Z01030000"])

    def test_old_long_term_investment_alias_prefers_non_empty_detail_row(self) -> None:
        mapper = AccountCodeMapper(str(self._semantic_config_path()))

        result = mapper.map_data({
            "长期投资:": [None, None],
            "长期投资": ["5100000.00", "10000000.00"],
        })

        self.assertEqual(
            result["Z01020100"],
            [Decimal("5100000.00"), Decimal("10000000.00")],
        )

    def test_display_field_variants_match_standard_codes(self) -> None:
        mapper = AccountCodeMapper(str(self._semantic_config_path()))

        result = mapper.map_data({
            "其他权益工具投资": "120",
            "永续债": "50",
            "专项存储": "30",
        })

        self.assertEqual(result["ZY2015109"], Decimal("120"))
        self.assertEqual(result["Z02010711"], Decimal("50"))
        self.assertEqual(result["Z04020800"], Decimal("30"))

    def test_decorative_prefix_markers_do_not_block_item_matching(self) -> None:
        mapper = AccountCodeMapper(str(self._semantic_config_path()))

        result = mapper.map_data({
            "△☆其他权益工具投资": "120",
        })

        self.assertEqual(result["ZY2015109"], Decimal("120"))

    def test_excel_escaped_control_chars_do_not_block_item_matching(self) -> None:
        mapper = AccountCodeMapper(str(self._semantic_config_path()))

        result = mapper.map_data({
            "使用权资产_x000D_": ["1459982.03", "1459982.03"],
        })

        self.assertEqual(
            result["Z01020310"],
            [Decimal("1459982.03"), Decimal("1459982.03")],
        )

    def test_cashflow_subtotals_do_not_use_fuzzy_match(self) -> None:
        mapper = AccountCodeMapper(str(self._cashflow_semantic_config_path()))

        result = mapper.map_data({
            "经营活动产生的现金流出小计": "100",
            "经营活动产生的现金流入小计": "120",
        })

        self.assertIsNone(result["X01040000"])
        self.assertIsNone(result["X01090000"])

    def test_cashflow_other_activity_aliases_map_standard_codes(self) -> None:
        mapper = AccountCodeMapper(str(self._cashflow_semantic_config_path()))

        result = mapper.map_data({
            "收到其他与经营活动有关的现金": "10",
            "支付的其他与经营活动有关的现金": "20",
            "收到其他与投资活动有关的现金": "30",
            "支付的其他与投资活动有关的现金": "40",
            "收到其他与筹资活动有关的现金": "50",
            "支付的其他与筹资活动有关的现金": "60",
        })

        self.assertEqual(result["X01030000"], Decimal("10"))
        self.assertEqual(result["X01011800"], Decimal("20"))
        self.assertEqual(result["X02040000"], Decimal("30"))
        self.assertEqual(result["X02080300"], Decimal("40"))
        self.assertEqual(result["X03030000"], Decimal("50"))
        self.assertEqual(result["X03070000"], Decimal("60"))

    def test_cashflow_other_activity_fuzzy_requires_matching_direction_and_activity(self) -> None:
        mapper = AccountCodeMapper(str(self._cashflow_semantic_config_path()))

        result = mapper.map_data({
            "支付其他与经营活动有关的现金": "100",
            "收到的其他与筹资活动有关的现金": "300",
        })

        self.assertIsNone(result["X01030000"])
        self.assertEqual(result["X01011800"], Decimal("100"))
        self.assertIsNone(result["X02040000"])
        self.assertEqual(result["X03030000"], Decimal("300"))

    def test_cashflow_other_activity_structured_fuzzy_accepts_unlisted_variant(self) -> None:
        mapper = AccountCodeMapper(str(self._cashflow_semantic_config_path()))

        result = mapper.map_data({
            "收到其他与投资活动相关现金": "70",
            "支付其他与筹资活动有关款项": "80",
        })

        self.assertEqual(result["X02040000"], Decimal("70"))
        self.assertEqual(result["X03070000"], Decimal("80"))

    def test_cashflow_alias_maps_fixed_asset_payment_item(self) -> None:
        mapper = AccountCodeMapper(str(self._cashflow_semantic_config_path()))

        result = mapper.map_data({
            "购建固定资产、无形资产等支付的现金": "945,994,398.28",
        })

        self.assertEqual(result["X02060000"], Decimal("945994398.28"))

    def test_cashflow_bold_amount_text_is_parsed_as_amount(self) -> None:
        mapper = AccountCodeMapper(str(self._cashflow_semantic_config_path()))

        result = mapper.map_data({
            "经营活动现金流入小计": "**566,634,174.99**",
            "投资活动产生的现金流量净额": "**-253,258,474.94**",
            "现金及现金等价物净增加额": "**33,160,091.43**",
        })

        self.assertEqual(result["X01040000"], Decimal("566634174.99"))
        self.assertEqual(result["X02100000"], Decimal("-253258474.94"))
        self.assertEqual(result["X05000000"], Decimal("33160091.43"))

    def test_numbered_profit_item_with_parenthetical_note_maps_to_total_profit(self) -> None:
        mapper = AccountCodeMapper(str(self._profit_semantic_config_path()))

        result = mapper.map_data({
            "**四、利润总额（亏损以“—”号填列）**": "26,761,056.08",
        })

        self.assertEqual(result["L05010000"], Decimal("26761056.08"))

    def test_profit_operating_cost_total_maps_for_cross_validation(self) -> None:
        mapper = AccountCodeMapper(str(self._profit_semantic_config_path()))

        result = mapper.map_data({
            "**二、营业总成本**": "1,755,103,810.53",
        })

        self.assertEqual(result["L02000000"], Decimal("1755103810.53"))

    def test_profit_latex_footnote_markers_do_not_block_item_matching(self) -> None:
        mapper = AccountCodeMapper(str(self._profit_semantic_config_path()))

        result = mapper.map_data({
            "$ ^{{*}}信用减值损失（损失以“-”号填列）": "120",
            "$ ^{{*}}少数股东损益 $": "30",
        })

        self.assertEqual(result["SY1000016"], Decimal("120"))
        self.assertEqual(result["L06020000"], Decimal("30"))

    def test_profit_items_with_chinese_colon_numbering_map_to_standard_codes(self) -> None:
        mapper = AccountCodeMapper(str(self._profit_semantic_config_path()))

        result = mapper.map_data({
            "一：商品销售收入": "1,195,553.99",
            "三：主营业务利润：": "340,619.71",
            "四：营业利润": "37,648.73",
            "五：利润总额": "37,648.73",
            "六：净利润": "28,236.55",
        })

        self.assertEqual(result["L00000000"], Decimal("1195553.99"))
        self.assertEqual(result["L03000000"], Decimal("340619.71"))
        self.assertEqual(result["L04010000"], Decimal("37648.73"))
        self.assertEqual(result["L05010000"], Decimal("37648.73"))
        self.assertEqual(result["L06010000"], Decimal("28236.55"))


if __name__ == "__main__":
    unittest.main()
