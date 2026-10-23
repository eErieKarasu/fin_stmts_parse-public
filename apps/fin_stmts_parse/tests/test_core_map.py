import unittest
from pathlib import Path

import yaml

from apps.fin_stmts_parse.src.core.contracts import StatementMarkdownDocument
from apps.fin_stmts_parse.src.core.map import FinancialStatementMapCore
from apps.fin_stmts_parse.src.view_data_projector import ViewDataProjector


BALANCE_MARKDOWN = """
# 资产负债表

| 资产 | 行次 | 期末余额 | 年初余额 |
| :--- | :---: | :---: | :---: |
| 货币资金 | 1 | 100.50 | 90.25 |
| 应收账款 | 2 | 200.00 | 180.00 |
| 资产总计 | 30 | 300.50 | 270.25 |
"""


FIXED_ASSET_ONLY_MARKDOWN = """
# 资产负债表

| 资产 | 行次 | 期末余额 | 年初余额 |
| :--- | :---: | :---: | :---: |
| 固定资产 | 1 | 200.00 | 180.00 |
| 资产总计 | 30 | 200.00 | 180.00 |
"""


FIXED_ASSET_NET_VALUE_ONLY_MARKDOWN = """
# 资产负债表

| 资产 | 行次 | 期末余额 | 年初余额 |
| :--- | :---: | :---: | :---: |
| 固定资产净值 | 1 | 190.00 | 170.00 |
| 资产总计 | 30 | 190.00 | 170.00 |
"""


EXCEL_ESCAPED_CONTROL_CHAR_MARKDOWN = """
# 资产负债表

| 项目 | 年初数 | 期末数 |
| :--- | :---: | :---: |
| 使用权资产_x000D_ | 1459982.03 | 1459982.03 |
| 资产总计 | 1459982.03 | 1459982.03 |
"""


OLD_LONG_TERM_INVESTMENT_MARKDOWN = """
# 资产负债表

| 资产 | 行次 | 期末余额 | 年初余额 |
| :--- | :---: | :---: | :---: |
| 长期投资: |  |  |  |
| 长期投资 | 21 | 10000000.00 | 5100000.00 |
| 资产总计 | 45 | 10000000.00 | 5100000.00 |
"""


SPECIAL_BALANCE_HTML = """
<table>
<tr><td></td><td>行次</td><td>年初数</td><td>期末数</td><td>负债及所有者权益</td><td>行次</td><td>年初数</td><td>期末数</td></tr>
<tr><td>货币资金</td><td>1</td><td>557647747.48</td><td>688211360.94</td><td>应付票据</td><td>29</td><td>528000000.00</td><td>643800000.00</td></tr>
<tr><td>资产总计</td><td>27</td><td>619481514.39</td><td>744427156.09</td><td>负债及所有者权益合计</td><td>54</td><td>619481514.39</td><td>744427156.09</td></tr>
</table>
"""


SPECIAL_CASHFLOW_HTML = """
<table>
<tr><td>项目</td><td>行次</td><td>金额</td><td>补充资料</td><td>行次</td><td>金额</td></tr>
<tr><td>销售商品、提供劳务收到的现金</td><td>1</td><td>1726639479.36</td><td>净利润</td><td>57</td><td>23967915.26</td></tr>
<tr><td>经营活动产生的现金流量净额</td><td>21</td><td>130573613.46</td><td>经营活动产生的现金流量净额</td><td>75</td><td>130573613.46</td></tr>
</table>
"""

SPECIAL_CASHFLOW_ALIAS_MARKDOWN = """
# 现金流量表

| 科目 | 行次 | 期末 |
| :--- | :---: | :---: |
| 购建固定资产、无形资产等支付的现金 | 18 | 945,994,398.28 |
""".strip()


SPECIAL_CASHFLOW_DUPLICATE_SUPPLEMENT_MARKDOWN = """
# 现金流量表

| 项目 | 行次 | 金额 | 补充资料 | 行次 | 金额 |
| :--- | :---: | :---: | :--- | :---: | :---: |
| **一、经营活动产生的现金流量：** | | | **1、将净利润调节为经营活动现金流量：** | | |
| 销售商品、提供劳务收到的现金 | 1 | 217,731,159.95 | 净利润 | 57 | - |
| 收到的税费返还 | 3 | - | 加：计提的资产减值准备 | 58 | - |
| 收到的其他与经营活动有关的现金 | 8 | -12,938,047.53 | 固定资产折旧 | 59 | 3,232,715.54 |
| **现金流入小计** | 9 | 204,793,112.42 | 无形资产摊销 | 60 | - |
| 购买商品、接受劳务支付的现金 | 10 | 222,422,143.58 | 长期待摊费用摊销 | 61 | - |
| 支付给职工以及为职工支付的现金 | 12 | 454,166.56 | 待摊费用减少（减：增加） | 64 | #REF! |
| 支付的各项税费 | 13 | 9,757,595.32 | 预提费用增加（减：减少） | 65 | #REF! |
| 支付的其他与经营活动有关的现金 | 18 | 1,605,654.47 | 处置固定资产、无形资产和其他长期资产的损失（减：收益） | 66 | - |
| **现金流出小计** | 20 | 234,239,559.93 | 固定资产报废损失 | 67 | - |
| **经营活动产生的现金流量净额** | 21 | -29,446,447.51 | 财务费用 | 68 | 14,621,219.01 |
| **二、投资活动产生的现金流量：** | | | 经营性应付项目的增加（减：减少） | 73 | #REF! |
| **现金流入小计** | 29 | - | **经营活动产生的现金流量净额** | 75 | #REF! |
""".strip()


OLD_PROFIT_NBSP_MARKDOWN = """
# 利润及利润分配表

| 项 &nbsp;&nbsp;&nbsp;&nbsp;目 | 行次 | 上年累计数 | 本年累计数 |
| :--- | :---: | :---: | :---: |
| 一、主营业务收入 | 1 | | 260,043,375.64 |
| &nbsp;&nbsp;&nbsp;&nbsp;减：主营业务成本 | 2 | | 197,603,575.87 |
| &nbsp;&nbsp;&nbsp;&nbsp;主营业务税金及附加 | 3 | | 9,640,244.16 |
| &nbsp;&nbsp;&nbsp;&nbsp;减：营业费用 | 6 | | 4,260,604.24 |
| &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;管理费用 | 7 | | 5,450,459.21 |
| &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;财务费用 | 8 | | 16,327,436.08 |
| 三、营业利润（亏损以“－”号填列） | 9 | | 26,761,056.08 |
| 四、利润总额（亏损以“－”号填列） | 14 | | 26,761,056.08 |
| 减：所得税 | 15 | | 6,690,264.02 |
| 五、净利润（亏损以“－”号填列） | 17 | | 20,070,792.06 |
""".strip()


class FinancialStatementMapCoreTest(unittest.TestCase):
    def setUp(self) -> None:
        self.core = FinancialStatementMapCore(
            config={},
            repo_root=Path(__file__).resolve().parents[3],
        )

    def test_standalone_balance_view_config_matches_display_fields(self) -> None:
        view_config_path = (
            Path(__file__).resolve().parents[1]
            / "config"
            / "mappings"
            / "balance"
            / "standalone"
            / "view.yaml"
        )
        config = yaml.safe_load(view_config_path.read_text(encoding="utf-8"))
        projector = ViewDataProjector(str(view_config_path))

        self.assertIn("view_data", config)
        self.assertNotIn("view_items", config)
        self.assertEqual(
            [item["name"] for item in projector.view_rules],
            [
                "货币资金",
                "交易性金融资产",
                "衍生金融资产",
                "应收票据",
                "应收账款",
                "应收款项融资",
                "预付款项",
                "其他应收款",
                "应收利息",
                "应收股利",
                "存货",
                "合同资产",
                "持有待售资产",
                "一年内到期的非流动资产",
                "其他流动资产",
                "流动资产合计",
                "债权投资",
                "其他债权投资",
                "长期应收款",
                "长期股权投资",
                "其他权益工具投资",
                "其他非流动金融资产",
                "投资性房地产",
                "固定资产",
                "在建工程",
                "生产性生物资产",
                "油气资产",
                "使用权资产",
                "无形资产",
                "开发支出",
                "商誉",
                "长期待摊费用",
                "递延所得税资产",
                "其他非流动资产",
                "非流动资产合计",
                "资产总计",
                "短期借款",
                "交易性金融负债",
                "衍生金融负债",
                "应付票据",
                "应付账款",
                "预收款项",
                "合同负债",
                "应付职工薪酬",
                "应交税费",
                "其他应付款",
                "应付利息",
                "应付股利",
                "持有待售负债",
                "一年内到期的非流动负债",
                "其他流动负债",
                "流动负债合计",
                "长期借款",
                "应付债券",
                "优先股",
                "永续债",
                "租赁负债",
                "长期应付款",
                "预计负债",
                "递延收益",
                "递延所得税负债",
                "其他非流动负债",
                "非流动负债合计",
                "负债合计",
                "实收资本（股本）",
                "其他权益工具",
                "所有者权益优先股",
                "所有者权益永续债",
                "资本公积",
                "库存股",
                "其他综合收益",
                "专项存储",
                "盈余公积",
                "未分配利润",
                "所有者权益（或股东权益）合计",
                "负债和所有者权益（或股东权益）总计",
            ],
        )

    def test_standalone_balance_view_config_declares_display_groups(self) -> None:
        view_config_path = (
            Path(__file__).resolve().parents[1]
            / "config"
            / "mappings"
            / "balance"
            / "standalone"
            / "view.yaml"
        )
        config = yaml.safe_load(view_config_path.read_text(encoding="utf-8"))
        projector = ViewDataProjector(str(view_config_path))

        self.assertIn("view_data", config)
        self.assertNotIn("view_groups", config)
        view_codes = [item["code"] for item in projector.view_rules]
        groups = {group["key"]: group for group in projector.view_groups}

        self.assertEqual(
            set(groups),
            {
                "assets",
                "current_assets",
                "non_current_assets",
                "Z01011100",
                "liabilities_and_equity",
                "current_liabilities",
                "ZG2010800",
                "non_current_liabilities",
                "Z02020200",
                "equity",
                "Z04020300",
                "Z04020000",
            },
        )
        self.assertEqual(groups["assets"]["item_codes"], view_codes[:36])
        self.assertEqual(groups["current_assets"]["item_codes"], view_codes[:16])
        self.assertEqual(groups["non_current_assets"]["item_codes"], view_codes[16:35])
        self.assertEqual(groups["liabilities_and_equity"]["item_codes"], view_codes[36:])
        self.assertEqual(groups["current_liabilities"]["item_codes"], view_codes[36:52])
        self.assertEqual(groups["non_current_liabilities"]["item_codes"], view_codes[52:63])
        self.assertEqual(groups["equity"]["item_codes"], view_codes[64:75])

        self.assertEqual(groups["current_assets"]["parent"], "assets")
        self.assertEqual(groups["non_current_assets"]["parent"], "assets")
        self.assertEqual(groups["Z01011100"]["parent"], "current_assets")
        self.assertEqual(
            groups["Z01011100"]["item_codes"],
            ["Z01011100", "Z01010500", "Z01010400"],
        )
        self.assertEqual(groups["current_liabilities"]["parent"], "liabilities_and_equity")
        self.assertEqual(groups["ZG2010800"]["parent"], "current_liabilities")
        self.assertEqual(
            groups["ZG2010800"]["item_codes"],
            ["ZG2010800", "Z02010107", "Z02010700"],
        )
        self.assertEqual(groups["non_current_liabilities"]["parent"], "liabilities_and_equity")
        self.assertEqual(groups["Z02020200"]["parent"], "non_current_liabilities")
        self.assertEqual(
            groups["Z02020200"]["item_codes"],
            ["Z02020200", "Z02010710", "Z02010711"],
        )
        self.assertEqual(groups["equity"]["parent"], "liabilities_and_equity")
        self.assertEqual(groups["Z04020300"]["parent"], "equity")
        self.assertEqual(
            groups["Z04020300"]["item_codes"],
            ["Z04020300", "Z04020400", "Z04020500"],
        )
        self.assertEqual(groups["Z04020000"]["parent"], "equity")
        self.assertEqual(
            groups["Z04020000"]["item_codes"],
            ["Z04020000", "Z04020600"],
        )

    def test_consolidated_balance_view_config_declares_display_groups(self) -> None:
        view_config_path = (
            Path(__file__).resolve().parents[1]
            / "config"
            / "mappings"
            / "balance"
            / "consolidated"
            / "view.yaml"
        )
        config = yaml.safe_load(view_config_path.read_text(encoding="utf-8"))
        projector = ViewDataProjector(str(view_config_path))

        self.assertIn("view_data", config)
        self.assertNotIn("view_items", config)
        view_codes = [item["code"] for item in projector.view_rules]
        groups = {group["key"]: group for group in projector.view_groups}

        self.assertEqual(
            set(groups),
            {
                "assets",
                "current_assets",
                "non_current_assets",
                "Z01011100",
                "liabilities_and_equity",
                "current_liabilities",
                "ZG2010800",
                "non_current_liabilities",
                "Z02020200",
                "equity",
                "Z04030400",
                "Z04020300",
            },
        )
        self.assertEqual(groups["assets"]["item_codes"], view_codes[:36])
        self.assertEqual(groups["current_assets"]["item_codes"], view_codes[:16])
        self.assertEqual(groups["non_current_assets"]["item_codes"], view_codes[16:35])
        self.assertEqual(groups["liabilities_and_equity"]["item_codes"], view_codes[36:])
        self.assertEqual(groups["current_liabilities"]["item_codes"], view_codes[36:52])
        self.assertEqual(groups["non_current_liabilities"]["item_codes"], view_codes[52:63])
        self.assertEqual(groups["equity"]["item_codes"], view_codes[64:77])

        self.assertEqual(groups["equity"]["parent"], "liabilities_and_equity")
        self.assertEqual(groups["Z04030400"]["parent"], "equity")
        self.assertEqual(
            groups["Z04030400"]["item_codes"],
            [
                "Z04030400",
                "Z04020200",
                "Z04020300",
                "Z04020400",
                "Z04020500",
                "Z04020000",
                "Z04020600",
                "Z04020700",
                "Z04020800",
                "Z04030000",
                "Z04050000",
            ],
        )
        self.assertEqual(groups["Z04020300"]["parent"], "Z04030400")
        self.assertEqual(
            groups["Z04020300"]["item_codes"],
            ["Z04020300", "Z04020400", "Z04020500"],
        )
        self.assertEqual(
            projector.view_labels["Z04030400"],
            "归属于母公司所有者权益（或股东权益）合计",
        )
        self.assertEqual(projector.view_labels["Z04020200"], "实收资本")
        self.assertEqual(projector.view_labels["Z04020600"], "减：库存股")
        self.assertEqual(projector.view_labels["Z03000000"], "少数股东权益")
        self.assertEqual(projector.view_labels["Z04020800"], "专项储备")
        self.assertEqual(
            projector.view_labels["Z05010000"],
            "负债和所有者权益（或股东权益）总计",
        )

    def test_standalone_profit_view_config_declares_display_groups(self) -> None:
        view_config_path = (
            Path(__file__).resolve().parents[1]
            / "config"
            / "mappings"
            / "profit"
            / "standalone"
            / "view.yaml"
        )
        config = yaml.safe_load(view_config_path.read_text(encoding="utf-8"))
        projector = ViewDataProjector(str(view_config_path))

        self.assertIn("view_data", config)
        self.assertNotIn("view_items", config)
        self.assertEqual(
            [group["key"] for group in projector.view_groups],
            [
                "operating_revenue",
                "L03050000",
                "L04020000",
                "operating_profit",
                "total_profit",
                "net_profit",
                "other_comprehensive_income",
                "comprehensive_income",
                "earnings_per_share",
            ],
        )
        self.assertEqual(
            [item["name"] for item in projector.view_rules],
            [
                "营业总收入",
                "营业成本",
                "税金及附加",
                "销售费用",
                "管理费用",
                "研发费用",
                "财务费用",
                "利息费用",
                "财务费用利息收入",
                "其他收益",
                "投资收益",
                "对联营企业和合营企业的投资收益",
                "以摊余成本计量的金融资产终止确认收益",
                "净敞口套期收益",
                "公允价值变动收益",
                "信用减值损失",
                "资产减值损失",
                "资产处置收益",
                "营业利润",
                "营业外收入",
                "营业外支出",
                "利润总额",
                "所得税费用",
                "净利润",
                "持续经营净利润",
                "终止经营净利润",
                "其他综合收益的税后净额",
                "综合收益总额",
                "基本每股收益",
                "稀释每股收益",
            ],
        )
        groups = {group["key"]: group for group in projector.view_groups}
        self.assertEqual(groups["L03050000"]["parent"], "operating_revenue")
        self.assertEqual(
            groups["L03050000"]["item_codes"],
            ["L03050000", "L02011001", "L02011002"],
        )
        self.assertEqual(groups["L04020000"]["parent"], "operating_revenue")
        self.assertEqual(
            groups["L04020000"]["item_codes"],
            ["L04020000", "L04020100", "L04020200"],
        )

    def test_consolidated_profit_view_config_declares_display_groups(self) -> None:
        view_config_path = (
            Path(__file__).resolve().parents[1]
            / "config"
            / "mappings"
            / "profit"
            / "consolidated"
            / "view.yaml"
        )
        config = yaml.safe_load(view_config_path.read_text(encoding="utf-8"))
        projector = ViewDataProjector(str(view_config_path))

        self.assertIn("view_data", config)
        self.assertNotIn("view_items", config)
        self.assertEqual(
            [group["key"] for group in projector.view_groups],
            [
                "operating_revenue",
                "L03050000",
                "L04020000",
                "operating_profit",
                "total_profit",
                "net_profit",
                "other_comprehensive_income",
                "comprehensive_income",
                "earnings_per_share",
            ],
        )
        self.assertEqual(
            [item["name"] for item in projector.view_rules],
            [
                "营业总收入",
                "营业成本",
                "税金及附加",
                "销售费用",
                "管理费用",
                "研发费用",
                "财务费用",
                "利息费用",
                "利息收入",
                "其他收益",
                "投资收益",
                "对联营企业和合营企业的投资收益",
                "以摊余成本计量的金融资产终止确认收益",
                "净敞口套期收益",
                "公允价值变动收益",
                "信用减值损失",
                "资产减值损失",
                "资产处置收益",
                "营业利润",
                "营业外收入",
                "营业外支出",
                "利润总额",
                "所得税费用",
                "净利润",
                "持续经营净利润",
                "终止经营净利润",
                "其他综合收益的税后净额",
                "综合收益总额",
                "基本每股收益（元/股）",
                "稀释每股收益",
            ],
        )
        groups = {group["key"]: group for group in projector.view_groups}
        self.assertEqual(groups["L03050000"]["parent"], "operating_revenue")
        self.assertEqual(
            groups["L03050000"]["item_codes"],
            ["L03050000", "L02011001", "L02011002"],
        )
        self.assertEqual(groups["L04020000"]["parent"], "operating_revenue")
        self.assertEqual(
            groups["L04020000"]["item_codes"],
            ["L04020000", "L04020100", "L04020200"],
        )
        self.assertEqual(
            groups["earnings_per_share"]["item_codes"],
            ["L08000100", "L08000200"],
        )

    def test_consolidated_balance_view_config_can_pick_first_non_empty_source_code(self) -> None:
        view_config_path = (
            Path(__file__).resolve().parents[1]
            / "config"
            / "mappings"
            / "balance"
            / "consolidated"
            / "view.yaml"
        )
        projector = ViewDataProjector(str(view_config_path))

        projected = projector.project(
            {
                "Z01030003": ["170.0", "190.0"],
                "Z01030000": ["999.0", "999.0"],
            }
        )

        self.assertEqual(projected["Z01030000"], ["170.0", "190.0"])

    def test_standalone_cashflow_view_config_declares_display_groups(self) -> None:
        view_config_path = (
            Path(__file__).resolve().parents[1]
            / "config"
            / "mappings"
            / "cashflow"
            / "standalone"
            / "view.yaml"
        )
        config = yaml.safe_load(view_config_path.read_text(encoding="utf-8"))
        projector = ViewDataProjector(str(view_config_path))

        self.assertIn("view_data", config)
        self.assertNotIn("view_items", config)
        self.assertEqual(
            [group["key"] for group in projector.view_groups],
            [
                "operating_cash_flow",
                "X01040000",
                "X01090000",
                "investing_cash_flow",
                "X02050000",
                "X02090000",
                "financing_cash_flow",
                "X03040000",
                "X03080000",
                "exchange_rate_effect",
                "net_cash_increase",
                "end_cash_and_cash_equivalents",
            ],
        )
        self.assertEqual(
            [item["name"] for item in projector.view_rules],
            [
                "经营活动现金流入小计",
                "销售商品、提供劳务收到的现金",
                "收到的税费返还",
                "收到的其他与经营活动有关的现金",
                "经营活动现金流出小计",
                "购买商品、接受劳务支付的现金",
                "支付给职工以及为职工支付的现金",
                "支付的各项税费",
                "支付其他与经营活动有关的现金",
                "经营活动产生的现金流量净额",
                "投资活动现金流入小计",
                "收回投资收到的现金",
                "取得投资收益收到的现金",
                "处置固定、无形和其他长期资产所收回的现金净额",
                "处置子公司及其他营业单位收到的现金净额",
                "收到的其他与投资活动有关的现金",
                "投资活动现金流出小计",
                "购建固定资产、无形资产和其他长期资产所支付的现金",
                "投资支付的现金",
                "取得子公司及其他营业单位支付的现金净额",
                "支付其他与投资活动有关的现金",
                "投资活动产生的现金流量净额",
                "筹资活动现金流入小计",
                "吸收投资收到的现金",
                "取得借款收到的现金",
                "发行债券收到的现金",
                "收到的其他与筹资活动有关的现金",
                "筹资活动现金流出小计",
                "偿还债务支付的现金",
                "分配股利、利润或偿付利息支付的现金",
                "支付其他与筹资活动有关的现金",
                "筹资活动产生的现金流量净额",
                "汇率变动对现金及现金等价物的影响",
                "现金及现金等价物净增加额",
                "期初现金及现金等价物余额",
                "期末现金及现金等价物余额",
            ],
        )
        groups = {group["key"]: group for group in projector.view_groups}
        self.assertEqual(groups["X01040000"]["parent"], "operating_cash_flow")
        self.assertEqual(
            groups["X01040000"]["item_codes"],
            ["X01040000", "X01010000", "X01020000", "X01030000"],
        )
        self.assertEqual(groups["X01090000"]["parent"], "operating_cash_flow")
        self.assertEqual(
            groups["X01090000"]["item_codes"],
            ["X01090000", "X01050000", "X01060000", "X01070000", "X01011800"],
        )
        self.assertEqual(groups["X02050000"]["parent"], "investing_cash_flow")
        self.assertEqual(
            groups["X02050000"]["item_codes"],
            ["X02050000", "X02010000", "X02020000", "X02030000", "X02030100", "X02040000"],
        )
        self.assertEqual(groups["X02090000"]["parent"], "investing_cash_flow")
        self.assertEqual(
            groups["X02090000"]["item_codes"],
            ["X02090000", "X02060000", "X02070000", "X02080200", "X02080300"],
        )
        self.assertEqual(groups["X03040000"]["parent"], "financing_cash_flow")
        self.assertEqual(
            groups["X03040000"]["item_codes"],
            ["X03040000", "X03010000", "X02080500", "X03020100", "X03030000"],
        )
        self.assertEqual(groups["X03080000"]["parent"], "financing_cash_flow")
        self.assertEqual(
            groups["X03080000"]["item_codes"],
            ["X03080000", "X03050000", "X03060000", "X03070000"],
        )
        self.assertEqual(groups["net_cash_increase"]["item_codes"], ["X05000000", "X04010100"])
        self.assertEqual(groups["end_cash_and_cash_equivalents"]["item_codes"], ["X06010000"])

    def test_consolidated_cashflow_view_config_declares_display_groups(self) -> None:
        view_config_path = (
            Path(__file__).resolve().parents[1]
            / "config"
            / "mappings"
            / "cashflow"
            / "consolidated"
            / "view.yaml"
        )
        config = yaml.safe_load(view_config_path.read_text(encoding="utf-8"))
        projector = ViewDataProjector(str(view_config_path))

        self.assertIn("view_data", config)
        self.assertNotIn("view_items", config)
        self.assertEqual(
            [group["key"] for group in projector.view_groups],
            [
                "operating_cash_flow",
                "X01040000",
                "X01090000",
                "investing_cash_flow",
                "X02050000",
                "X02090000",
                "financing_cash_flow",
                "X03040000",
                "X03080000",
                "exchange_rate_effect",
                "net_cash_increase",
                "X06010000",
            ],
        )
        self.assertEqual(projector.view_labels["X01040000"], "经营活动现金流入小计")
        self.assertEqual(projector.view_labels["X01100000"], "经营活动产生的现金流量净额")
        self.assertEqual(projector.view_labels["X02050000"], "投资活动现金流入小计")
        self.assertEqual(projector.view_labels["X02100000"], "投资活动产生的现金流量净额")
        self.assertEqual(projector.view_labels["X03040000"], "筹资活动现金流入小计")
        self.assertEqual(projector.view_labels["X03090000"], "筹资活动产生的现金流量净额")
        self.assertEqual(projector.view_labels["X06010000"], "现金及现金等价物余额")

        groups = {group["key"]: group for group in projector.view_groups}
        self.assertEqual(groups["X01040000"]["parent"], "operating_cash_flow")
        self.assertEqual(
            groups["X01040000"]["item_codes"],
            ["X01040000", "X01010000", "X01020000", "X01030000"],
        )
        self.assertEqual(groups["X01090000"]["parent"], "operating_cash_flow")
        self.assertEqual(
            groups["X01090000"]["item_codes"],
            ["X01090000", "X01050000", "X01060000", "X01070000", "X01011800"],
        )
        self.assertEqual(groups["X02050000"]["parent"], "investing_cash_flow")
        self.assertEqual(
            groups["X02050000"]["item_codes"],
            ["X02050000", "X02010000", "X02020000", "X02030000", "X02030100", "X02040000"],
        )
        self.assertEqual(groups["X02090000"]["parent"], "investing_cash_flow")
        self.assertEqual(
            groups["X02090000"]["item_codes"],
            ["X02090000", "X02060000", "X02070000", "X02080200", "X02080300"],
        )
        self.assertEqual(groups["X03040000"]["parent"], "financing_cash_flow")
        self.assertEqual(
            groups["X03040000"]["item_codes"],
            ["X03040000", "X03010000", "X02080500", "X03020100", "X03030000"],
        )
        self.assertEqual(groups["X03080000"]["parent"], "financing_cash_flow")
        self.assertEqual(
            groups["X03080000"]["item_codes"],
            ["X03080000", "X03050000", "X03060000", "X03070000"],
        )
        self.assertEqual(groups["net_cash_increase"]["item_codes"], ["X05000000"])
        self.assertEqual(groups["X06010000"]["item_codes"], ["X06010000", "X04010100"])

    def test_map_markdown_document_returns_canonical_and_view_mapping(self) -> None:
        result = self.core.map_markdown_document(
            StatementMarkdownDocument(
                table_name="资产负债表",
                date="202412",
                content=BALANCE_MARKDOWN,
            )
        )

        self.assertEqual(result.statement_type, "balance")
        self.assertIn("Z01010100", result.canonical_data_full)
        self.assertEqual(
            result.to_serialized_view_data()["Z01010100"],
            ["货币资金", "90.25", "100.5"],
        )

    def test_map_profit_rows_with_html_nbsp_indentation(self) -> None:
        result = self.core.map_markdown_document(
            StatementMarkdownDocument(
                table_name="利润表",
                date="202512",
                content=OLD_PROFIT_NBSP_MARKDOWN,
            )
        )

        view_data = result.to_serialized_view_data()
        self.assertEqual(view_data["L00000000"], ["营业总收入", None, "260043375.64"])
        self.assertEqual(view_data["L02010100"], ["营业成本", None, "197603575.87"])
        self.assertEqual(view_data["L02010800"], ["税金及附加", None, "9640244.16"])
        self.assertEqual(view_data["L02010900"], ["销售费用", None, "4260604.24"])
        self.assertEqual(view_data["L03040000"], ["管理费用", None, "5450459.21"])
        self.assertEqual(view_data["L03050000"], ["财务费用", None, "16327436.08"])

    def test_map_markdown_document_can_serialize_grouped_view_data(self) -> None:
        result = self.core.map_markdown_document(
            StatementMarkdownDocument(
                table_name="资产负债表",
                date="202412",
                content=BALANCE_MARKDOWN,
            )
        )

        view_data = result.to_serialized_view_data_tree()
        assets = view_data[0]
        current_assets = assets["children"][0]

        self.assertEqual([node["key"] for node in view_data], ["assets", "liabilities_and_equity"])
        self.assertEqual(assets["name"], "资产")
        self.assertEqual(current_assets["name"], "流动资产")
        self.assertEqual(
            current_assets["children"][0],
            {
                "type": "row",
                "code": "Z01010100",
                "name": "货币资金",
                "values": ["90.25", "100.5"],
            },
        )
        self.assertEqual(
            assets["children"][-1],
            {
                "type": "row",
                "code": "Z01000001",
                "name": "资产总计",
                "values": ["270.25", "300.5"],
            },
        )
        self.assertEqual(
            [child.get("key") or child.get("code") for child in assets["children"]],
            ["current_assets", "non_current_assets", "Z01000001"],
        )
        self.assertEqual(current_assets["children"][7]["type"], "group")
        self.assertEqual(current_assets["children"][7]["key"], "Z01011100")
        self.assertEqual(current_assets["children"][7]["code"], "Z01011100")
        self.assertEqual(current_assets["children"][7]["name"], "其他应收款")
        self.assertEqual(current_assets["children"][7]["values"], [None])
        self.assertEqual(
            [child["code"] for child in current_assets["children"][7]["children"]],
            ["Z01010500", "Z01010400"],
        )

    def test_map_special_html_tables_without_private_parse_output(self) -> None:
        balance_result = self.core.map_markdown_document(
            StatementMarkdownDocument(
                table_name="资产负债表",
                date="202512",
                content=SPECIAL_BALANCE_HTML,
            )
        )
        cashflow_result = self.core.map_markdown_document(
            StatementMarkdownDocument(
                table_name="现金流量表",
                date="202512",
                content=SPECIAL_CASHFLOW_HTML,
            )
        )

        self.assertEqual(
            balance_result.to_serialized_view_data()["Z01010100"],
            ["货币资金", "557647747.48", "688211360.94"],
        )
        self.assertEqual(
            cashflow_result.to_serialized_view_data()["X01010000"],
            ["销售商品、提供劳务收到的现金", None, "1726639479.36"],
        )

    def test_map_cashflow_alias_item_from_markdown_period_end_column(self) -> None:
        result = self.core.map_markdown_document(
            StatementMarkdownDocument(
                table_name="现金流量表",
                date="202512",
                content=SPECIAL_CASHFLOW_ALIAS_MARKDOWN,
            )
        )

        self.assertEqual(
            result.to_serialized_canonical_data()["X02060000"],
            ["购建固定资产、无形资产和其他长期资产所支付的现金", None, "945994398.28"],
        )

    def test_map_cashflow_keeps_direct_net_when_supplement_duplicate_is_invalid(self) -> None:
        result = self.core.map_markdown_document(
            StatementMarkdownDocument(
                table_name="现金流量表",
                date="202512",
                content=SPECIAL_CASHFLOW_DUPLICATE_SUPPLEMENT_MARKDOWN,
            )
        )

        serialized = result.to_serialized_canonical_data()
        self.assertEqual(
            serialized["X01040000"],
            ["经营活动现金流入小计", None, "204793112.42"],
        )
        self.assertEqual(
            serialized["X01090000"],
            ["经营活动现金流出小计", None, "234239559.93"],
        )
        self.assertEqual(
            serialized["X01100000"],
            ["经营活动产生的现金流量净额", None, "-29446447.51"],
        )
        self.assertEqual(
            serialized["X02050000"],
            ["投资活动现金流入小计", None, None],
        )

    def test_map_generic_fixed_asset_as_net_amount_when_detail_rows_are_absent(self) -> None:
        result = self.core.map_markdown_document(
            StatementMarkdownDocument(
                table_name="资产负债表",
                date="202412",
                content=FIXED_ASSET_ONLY_MARKDOWN,
            )
        )

        self.assertEqual(
            result.canonical_data_full["Z01030000"],
            result.view_data_full["Z01030000"],
        )
        self.assertIsNone(result.canonical_data_full["Z01030005"])
        self.assertEqual(
            result.to_serialized_canonical_data()["Z01030000"],
            ["固定资产", "180.0", "200.0"],
        )
        self.assertEqual(
            result.to_serialized_view_data()["Z01030000"],
            ["固定资产", "180.0", "200.0"],
        )

    def test_map_display_fixed_asset_prefers_net_value_semantic_field(self) -> None:
        result = self.core.map_markdown_document(
            StatementMarkdownDocument(
                table_name="资产负债表",
                date="202412",
                content=FIXED_ASSET_NET_VALUE_ONLY_MARKDOWN,
            )
        )

        self.assertEqual(
            result.canonical_data_full["Z01030003"],
            result.view_data_full["Z01030000"],
        )
        self.assertIsNone(result.canonical_data_full["Z01030000"])
        self.assertEqual(
            result.to_serialized_canonical_data()["Z01030003"],
            ["固定资产净值", "170.0", "190.0"],
        )
        self.assertEqual(
            result.to_serialized_view_data()["Z01030000"],
            ["固定资产", "170.0", "190.0"],
        )

    def test_map_balance_item_with_excel_escaped_control_char_suffix(self) -> None:
        result = self.core.map_markdown_document(
            StatementMarkdownDocument(
                table_name="资产负债表",
                date="202406",
                content=EXCEL_ESCAPED_CONTROL_CHAR_MARKDOWN,
            )
        )

        self.assertEqual(
            result.to_serialized_canonical_data()["Z01020310"],
            ["使用权资产", "1459982.03", "1459982.03"],
        )
        self.assertEqual(
            result.to_serialized_view_data()["Z01020310"],
            ["使用权资产", "1459982.03", "1459982.03"],
        )

    def test_map_old_long_term_investment_into_canonical_data_only(self) -> None:
        result = self.core.map_markdown_document(
            StatementMarkdownDocument(
                table_name="资产负债表",
                date="202412",
                content=OLD_LONG_TERM_INVESTMENT_MARKDOWN,
            )
        )

        self.assertEqual(
            result.to_serialized_canonical_data()["Z01020100"],
            ["长期投资合计", "5100000.0", "10000000.0"],
        )
        self.assertNotIn("Z01020100", result.view_data_full)


if __name__ == "__main__":
    unittest.main()
