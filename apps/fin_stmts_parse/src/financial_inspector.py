#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Optional


BALANCE_BASIC_RULES: List[Dict[str, Any]] = [
    {
        "name": "流动资产合计",
        "total_code": "Z01010001",
        "display_fail_on_components": True,
        "components": [
            ("Z01010100", "货币资金"),
            ("Z01010101", "交易性金融资产"),
            ("Z01010104", "衍生金融资产"),
            ("Z01010300", "应收票据"),
            ("Z01010610", "应收账款"),
            ("Z01010616", "应收款项融资"),
            ("Z01010611", "预付款项"),
            ("Z01011100", "其他应收款"),
            ("Z01011210", "存货"),
            ("ZY2015082", "合同资产"),
            ("Z01011230", "持有待售资产"),
            ("Z01011510", "一年内到期的非流动资产"),
            ("Z01011600", "其他流动资产"),
        ],
    },
    {
        "name": "其他应收款",
        "total_code": "Z01011100",
        "applies_if_any_present": ["Z01010500", "Z01010400"],
        "display_on_components": True,
        "components": [
            ("Z01010500", "应收利息"),
            ("Z01010400", "应收股利"),
        ],
    },
    {
        "name": "非流动资产合计",
        "total_code": "ZY2015058",
        "display_fail_on_components": True,
        "components": [
            ("ZY2015073", "债权投资"),
            ("ZY2015074", "其他债权投资"),
            ("Z01020240", "长期应收款"),
            ("Z01020110", "长期股权投资"),
            ("ZY2015109", "其他权益工具投资"),
            ("ZY2015110", "其他非流动金融资产"),
            ("Z01020121", "投资性房地产"),
            ("Z01030000", "固定资产"),
            ("Z01030300", "在建工程"),
            ("Z01020250", "生产性生物资产"),
            ("Z01020260", "油气资产"),
            ("Z01020310", "使用权资产"),
            ("Z01040100", "无形资产"),
            ("Z01020270", "开发支出"),
            ("Z01020280", "商誉"),
            ("ZG1040110", "长期待摊费用"),
            ("Z01044101", "递延所得税资产"),
            ("Z01020290", "其他非流动资产"),
        ],
    },
    {
        "name": "流动负债合计",
        "total_code": "Z02010001",
        "display_fail_on_components": True,
        "components": [
            ("Z02010100", "短期借款"),
            ("Z02010101", "交易性金融负债"),
            ("Z02010113", "衍生金融负债"),
            ("Z02010200", "应付票据"),
            ("Z02010300", "应付账款"),
            ("Z02010410", "预收款项"),
            ("ZY2015093", "合同负债"),
            ("ZY2015006", "应付职工薪酬"),
            ("ZY2015008", "应交税费"),
            ("ZG2010800", "其他应付款"),
            ("Z02010530", "持有待售负债"),
            ("Z02010540", "一年内到期的非流动负债"),
            ("Z02011400", "其他流动负债"),
        ],
    },
    {
        "name": "其他应付款",
        "total_code": "ZG2010800",
        "applies_if_any_present": ["Z02010107", "Z02010700"],
        "display_on_components": True,
        "components": [
            ("Z02010107", "应付利息"),
            ("Z02010700", "应付股利"),
        ],
    },
    {
        "name": "非流动负债合计",
        "total_code": "ZY2015061",
        "display_fail_on_components": True,
        "components": [
            ("Z02020100", "长期借款"),
            ("Z02020200", "应付债券"),
            ("Z02020600", "租赁负债"),
            ("Z02020300", "长期应付款"),
            ("Z02011200", "预计负债"),
            ("L02060000", "递延收益"),
            ("Z01044104", "递延所得税负债"),
            ("Z02011500", "其他非流动负债"),
        ],
    },
    {
        "name": "所有者权益（或股东权益）合计",
        "total_code": "Z04020110",
        "skip_if_any_present": ["Z04030400", "Z03000000"],
        "components": [
            ("Z04020200", "实收资本（股本）"),
            ("Z04020300", "其他权益工具"),
            ("Z04020000", "资本公积"),
            ("-", "Z04020600", "库存股"),
            ("Z04020700", "其他综合收益"),
            ("Z04020800", "专项存储"),
            ("Z04030000", "盈余公积"),
            ("Z04050000", "未分配利润"),
        ],
    },
    {
        "name": "其他权益工具",
        "total_code": "Z04020300",
        "applies_if_any_present": ["Z04020400", "Z04020500"],
        "display_on_components": True,
        "components": [
            ("Z04020400", "所有者权益优先股"),
            ("Z04020500", "所有者权益永续债"),
        ],
    },
    {
        "name": "归属于母公司所有者权益（或股东权益）合计",
        "total_code": "Z04030400",
        "applies_if_any_present": ["Z04030400", "Z03000000"],
        "components": [
            ("Z04020200", "实收资本"),
            ("Z04020300", "其他权益工具"),
            ("Z04020000", "资本公积"),
            ("-", "Z04020600", "库存股"),
            ("Z04020700", "其他综合收益"),
            ("Z04020800", "专项储备"),
            ("Z04030000", "盈余公积"),
            ("Z04050000", "未分配利润"),
        ],
    },
    {
        "name": "所有者权益（或股东权益）合计 = 归属于母公司所有者权益（或股东权益）合计 + 少数股东权益",
        "total_code": "Z04020110",
        "applies_if_any_present": ["Z04030400", "Z03000000"],
        "zero_if_missing_codes": ["Z03000000"],
        "components": [
            ("Z04030400", "归属于母公司所有者权益（或股东权益）合计"),
            ("Z03000000", "少数股东权益"),
        ],
    },
]

BALANCE_HIERARCHICAL_RULES: List[Dict[str, Any]] = [
    {
        "name": "资产总计 = 流动资产合计 + 非流动资产合计",
        "total_code": "Z01000001",
        "total_name": "资产总计",
        "components": [
            ("Z01010001", "流动资产合计"),
            ("ZY2015058", "非流动资产合计"),
        ],
    },
    {
        "name": "负债合计 = 流动负债合计 + 非流动负债合计",
        "total_code": "Z02000001",
        "total_name": "负债合计",
        "components": [
            ("Z02010001", "流动负债合计"),
            ("ZY2015061", "非流动负债合计"),
        ],
    },
    {
        "name": "负债和所有者权益（或股东权益）总计 = 流动负债合计 + 非流动负债合计 + 所有者权益（或股东权益）合计",
        "total_code": "Z05010000",
        "total_name": "负债和所有者权益（或股东权益）总计",
        "components": [
            ("Z02010001", "流动负债合计"),
            ("ZY2015061", "非流动负债合计"),
            ("Z04020110", "所有者权益（或股东权益）合计"),
        ],
    },
    {
        "name": "负债和所有者权益（或股东权益）总计 = 负债合计 + 所有者权益（或股东权益）合计",
        "total_code": "Z05010000",
        "total_name": "负债和所有者权益（或股东权益）总计",
        "components": [
            ("Z02000001", "负债合计"),
            ("Z04020110", "所有者权益（或股东权益）合计"),
        ],
    },
    {
        "name": "负债和所有者权益（或股东权益）总计 = 资产总计",
        "total_code": "Z05010000",
        "total_name": "负债和所有者权益（或股东权益）总计",
        "components": [
            ("Z01000001", "资产总计"),
        ],
    },
]

MAIN_BUSINESS_PROFIT_COMPONENTS = [
    ("+", "L00000000", "营业总收入"),
    ("-", "L02010100", "营业成本"),
    ("-", "L02010800", "税金及附加"),
]

OPERATING_COST_TOTAL_CODE = "L02000000"
OPERATING_COST_TOTAL_NAME = "营业总成本"
OPERATING_COST_COMPONENTS = [
    ("L02010100", "营业成本"),
    ("L02010800", "税金及附加"),
    ("L02010900", "销售费用"),
    ("L03040000", "管理费用"),
    ("L02011000", "研发费用"),
    ("L03050000", "财务费用"),
]
OPERATING_COST_COMPONENT_CODES = {
    code
    for code, _name in OPERATING_COST_COMPONENTS
}

OPERATING_PROFIT_OLD_COMPONENTS = [
    ("+", "L03000000", "主营业务利润"),
    ("+", "L03010000", "其他业务利润"),
    ("-", "L02010900", "销售费用"),
    ("-", "L03040000", "管理费用"),
    ("-", "L03050000", "财务费用"),
]

OPERATING_PROFIT_NEW_COMPONENTS = [
    ("+", "L00000000", "营业总收入"),
    ("-", "L02010100", "营业成本"),
    ("-", "L02010800", "税金及附加"),
    ("-", "L02010900", "销售费用"),
    ("-", "L03040000", "管理费用"),
    ("-", "L02011000", "研发费用"),
    ("-", "L03050000", "财务费用"),
    ("+", "L02011100", "其他收益"),
    ("+", "L04020000", "投资收益"),
    ("+", "SY1000006", "净敞口套期收益"),
    ("+", "L02011200", "公允价值变动收益"),
    ("+", "SY1000016", "信用减值损失"),
    ("+", "SG5020000", "资产减值损失"),
    ("+", "L02011300", "资产处置收益"),
]

TOTAL_PROFIT_OLD_COMPONENTS = [
    ("+", "L04010000", "营业利润"),
    ("+", "L04020000", "投资收益"),
    ("+", "L04060000", "补贴收入"),
    ("+", "L04050000", "营业外收入"),
    ("-", "L04070000", "营业外支出"),
]

TOTAL_PROFIT_NEW_COMPONENTS = [
    ("+", "L04010000", "营业利润"),
    ("+", "L04050000", "营业外收入"),
    ("-", "L04070000", "营业外支出"),
]

NET_PROFIT_WITH_MINORITY_COMPONENTS = [
    ("+", "L05010000", "利润总额"),
    ("-", "L04010100", "所得税费用"),
    ("-", "L06020000", "少数股东损益"),
]

NET_PROFIT_TAX_COMPONENTS = [
    ("+", "L05010000", "利润总额"),
    ("-", "L04010100", "所得税费用"),
]

NET_PROFIT_BREAKDOWN_COMPONENTS = [
    ("+", "L05010200", "持续经营净利润"),
    ("+", "L05010300", "终止经营净利润"),
]

COMPREHENSIVE_INCOME_COMPONENTS = [
    ("+", "L06010000", "净利润"),
    ("+", "L06010100", "其他综合收益的税后净额"),
]

PROFIT_BASIC_RULES: List[Dict[str, Any]] = [
    {
        "name": "营业利润",
        "total_code": "L04010000",
        "components": OPERATING_PROFIT_NEW_COMPONENTS,
    },
    {
        "name": "利润总额",
        "total_code": "L05010000",
        "components": TOTAL_PROFIT_NEW_COMPONENTS,
    },
    {
        "name": "净利润 = 利润总额 - 所得税费用",
        "total_code": "L06010000",
        "components": NET_PROFIT_TAX_COMPONENTS,
    },
    {
        "name": "净利润 = 持续经营净利润 + 终止经营净利润",
        "total_code": "L06010000",
        "applies_if_any_present": ["L05010200", "L05010300"],
        "components": NET_PROFIT_BREAKDOWN_COMPONENTS,
    },
    {
        "name": "综合收益总额",
        "total_code": "L07000000",
        "components": COMPREHENSIVE_INCOME_COMPONENTS,
    },
]

PROFIT_SEMANTIC_RULES_BY_TOTAL_CODE: Dict[str, Dict[str, Any]] = {
    "L03000000": {
        "name": "主营业务利润",
        "variants": [MAIN_BUSINESS_PROFIT_COMPONENTS],
    },
    "L04010000": {
        "name": "营业利润",
        "variants": [
            OPERATING_PROFIT_OLD_COMPONENTS,
            OPERATING_PROFIT_NEW_COMPONENTS,
        ],
    },
    "L05010000": {
        "name": "利润总额",
        "variants": [
            TOTAL_PROFIT_OLD_COMPONENTS,
            TOTAL_PROFIT_NEW_COMPONENTS,
        ],
    },
    "L06010000": {
        "name": "净利润",
        "variants": [
            NET_PROFIT_WITH_MINORITY_COMPONENTS,
            NET_PROFIT_TAX_COMPONENTS,
            NET_PROFIT_BREAKDOWN_COMPONENTS,
        ],
    },
    "L07000000": {
        "name": "综合收益总额",
        "variants": [COMPREHENSIVE_INCOME_COMPONENTS],
    },
}

CASHFLOW_BASIC_RULES: List[Dict[str, Any]] = [
    {
        "name": "经营活动现金流入小计",
        "total_code": "X01040000",
        "components": [
            ("X01010000", "销售商品、提供劳务收到的现金"),
            ("X01020000", "收到的税费返还"),
            ("X01030000", "收到的其他与经营活动有关的现金"),
        ],
    },
    {
        "name": "经营活动现金流出小计",
        "total_code": "X01090000",
        "components": [
            ("X01050000", "购买商品、接受劳务支付的现金"),
            ("X01060000", "支付给职工以及为职工支付的现金"),
            ("X01070000", "支付的各项税费"),
            ("X01011800", "支付其他与经营活动有关的现金"),
        ],
    },
    {
        "name": "投资活动现金流入小计",
        "total_code": "X02050000",
        "components": [
            ("X02010000", "收回投资收到的现金"),
            ("X02020000", "取得投资收益收到的现金"),
            ("X02030000", "处置固定、无形和其他长期资产所收回的现金净额"),
            ("X02030100", "处置子公司及其他营业单位收到的现金净额"),
            ("X02040000", "收到的其他与投资活动有关的现金"),
        ],
    },
    {
        "name": "投资活动现金流出小计",
        "total_code": "X02090000",
        "components": [
            ("X02060000", "购建固定资产、无形资产和其他长期资产所支付的现金"),
            ("X02070000", "投资支付的现金"),
            ("X02080200", "取得子公司及其他营业单位支付的现金净额"),
            ("X02080300", "支付其他与投资活动有关的现金"),
        ],
    },
    {
        "name": "筹资活动现金流入小计",
        "total_code": "X03040000",
        "components": [
            ("X03010000", "吸收投资收到的现金"),
            ("X02080500", "取得借款收到的现金"),
            ("X03020100", "发行债券收到的现金"),
            ("X03030000", "收到的其他与筹资活动有关的现金"),
        ],
    },
    {
        "name": "筹资活动现金流出小计",
        "total_code": "X03080000",
        "components": [
            ("X03050000", "偿还债务支付的现金"),
            ("X03060000", "分配股利、利润或偿付利息支付的现金"),
            ("X03070000", "支付其他与筹资活动有关的现金"),
        ],
    },
    {
        "name": "经营活动产生的现金流量净额 = 经营活动现金流入小计 - 经营活动现金流出小计",
        "total_code": "X01100000",
        "total_name": "经营活动产生的现金流量净额",
        "components": [
            ("+", "X01040000", "经营活动现金流入小计"),
            ("-", "X01090000", "经营活动现金流出小计"),
        ],
    },
    {
        "name": "投资活动产生的现金流量净额 = 投资活动现金流入小计 - 投资活动现金流出小计",
        "total_code": "X02100000",
        "total_name": "投资活动产生的现金流量净额",
        "components": [
            ("+", "X02050000", "投资活动现金流入小计"),
            ("-", "X02090000", "投资活动现金流出小计"),
        ],
    },
    {
        "name": "筹资活动产生的现金流量净额 = 筹资活动现金流入小计 - 筹资活动现金流出小计",
        "total_code": "X03090000",
        "total_name": "筹资活动产生的现金流量净额",
        "components": [
            ("+", "X03040000", "筹资活动现金流入小计"),
            ("-", "X03080000", "筹资活动现金流出小计"),
        ],
    },
    {
        "name": "现金及现金等价物净增加额 = 经营活动产生的现金流量净额 + 投资活动产生的现金流量净额 + 筹资活动产生的现金流量净额 + 汇率变动对现金及现金等价物的影响",
        "total_code": "X05000000",
        "total_name": "现金及现金等价物净增加额",
        "applies_if_total_present": True,
        "components": [
            ("+", "X01100000", "经营活动产生的现金流量净额"),
            ("+", "X02100000", "投资活动产生的现金流量净额"),
            ("+", "X03090000", "筹资活动产生的现金流量净额"),
            ("+", "X04010000", "汇率变动对现金及现金等价物的影响"),
        ],
    },
]

PERIODS = ((0, "年初"), (1, "期末"))
DECIMAL_TOLERANCE = Decimal("0.01")
LONG_TERM_INVESTMENT_COMPONENT_CODES: List[tuple[str, str]] = [
    ("Z01020110", "长期股权投资"),
    ("ZY2015109", "其他权益工具投资"),
    ("ZY2015073", "债权投资"),
    ("ZY2015074", "其他债权投资"),
    ("ZY2015110", "其他非流动金融资产"),
]
LEGACY_LONG_TERM_INVESTMENT_COMPONENT_CODES: List[tuple[str, str]] = [
    ("Z01020110", "长期股权投资"),
    ("ZY2015071", "长期债权投资"),
]
LONG_TERM_INVESTMENT_COMPONENT_VARIANTS: List[tuple[str, ...]] = [
    tuple(code for code, _ in LONG_TERM_INVESTMENT_COMPONENT_CODES),
    tuple(code for code, _ in LEGACY_LONG_TERM_INVESTMENT_COMPONENT_CODES),
]
LONG_TERM_INVESTMENT_COMPONENT_NAMES: Dict[str, str] = {
    code: name
    for code, name in [
        *LONG_TERM_INVESTMENT_COMPONENT_CODES,
        *LEGACY_LONG_TERM_INVESTMENT_COMPONENT_CODES,
    ]
}
FIXED_ASSET_TOTAL_COMPONENT_CODES: List[tuple[str, str]] = [
    ("Z01030000", "固定资产"),
    ("Z01030200", "工程物资"),
    ("Z01030300", "在建工程"),
    ("Z01030400", "固定资产清理"),
]
INTANGIBLE_AND_OTHER_ASSET_COMPONENT_CODES: List[tuple[str, str]] = [
    ("Z01040100", "无形资产"),
    ("ZG1040110", "长期待摊费用"),
    ("Z01040200", "其他长期资产"),
    ("Z01020121", "投资性房地产"),
]
NESTED_OR_PARALLEL_BALANCE_GROUPS: List[Dict[str, Any]] = [
    {
        "aggregate_code": "Z01011100",
        "aggregate_name": "其他应收款",
        "parent_total_code": "Z01010001",
        "parent_total_name": "流动资产合计",
        "components": [
            ("Z01010500", "应收利息"),
            ("Z01010400", "应收股利"),
        ],
    },
    {
        "aggregate_code": "ZG2010800",
        "aggregate_name": "其他应付款",
        "parent_total_code": "Z02010001",
        "parent_total_name": "流动负债合计",
        "components": [
            ("Z02010107", "应付利息"),
            ("Z02010700", "应付股利"),
        ],
    },
]
NESTED_OR_PARALLEL_GROUP_BY_AGGREGATE_CODE = {
    str(group["aggregate_code"]): group
    for group in NESTED_OR_PARALLEL_BALANCE_GROUPS
}
NESTED_OR_PARALLEL_GROUPS_BY_PARENT_TOTAL_CODE: Dict[str, List[Dict[str, Any]]] = {}
for _group in NESTED_OR_PARALLEL_BALANCE_GROUPS:
    NESTED_OR_PARALLEL_GROUPS_BY_PARENT_TOTAL_CODE.setdefault(
        str(_group["parent_total_code"]),
        [],
    ).append(_group)


class FinancialInspector:
    def inspect(self, merged_data: Dict[str, Any]) -> Dict[str, Any]:
        return self.inspect_view(merged_data)

    def inspect_view(
        self,
        merged_data: Dict[str, Any],
        *,
        semantic_merged_data: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        balance_data = merged_data.get("balance")
        profit_data = merged_data.get("profit")
        cashflow_data = merged_data.get("cashflow")
        semantic_balance_data = (semantic_merged_data or {}).get("balance") or {}
        semantic_profit_data = (semantic_merged_data or {}).get("profit") or {}

        has_balance = isinstance(balance_data, dict) and bool(balance_data)
        has_profit = isinstance(profit_data, dict) and bool(profit_data)
        has_cashflow = isinstance(cashflow_data, dict) and bool(cashflow_data)
        if not has_balance and not has_profit and not has_cashflow:
            return {
                "passed": True,
                "details": [],
                "total_checks": 0,
                "passed_checks": 0,
                "failed_checks": 0,
                "skipped_checks": 0,
            }

        details: List[Dict[str, Any]] = []
        passed_checks = 0
        failed_checks = 0
        skipped_checks = 0

        if has_balance:
            balance_basic_details_by_key: Dict[tuple[int, str], Dict[str, Any]] = {}
            inferred_balance_values: Dict[tuple[int, str], Decimal] = {}
            for rule in BALANCE_BASIC_RULES:
                if not self._balance_rule_applies(balance_data, rule):
                    continue
                for period_index, period_name in PERIODS:
                    if not self._balance_rule_applies_for_period(
                        balance_data,
                        rule,
                        period_index,
                    ):
                        continue
                    detail = self._inspect_balance_rule(
                        balance_data=balance_data,
                        semantic_balance_data=semantic_balance_data,
                        rule=rule,
                        period_index=period_index,
                        period_name=period_name,
                        inferred_balance_values=inferred_balance_values,
                    )
                    details.append(detail)
                    balance_basic_details_by_key[(period_index, str(rule["total_code"]))] = detail
                    inferred_total = _to_decimal(detail.get("_inferred_total"))
                    if inferred_total is not None:
                        inferred_balance_values[(period_index, str(rule["total_code"]))] = inferred_total
                    result = detail["result"]
                    if result == "pass":
                        passed_checks += 1
                    elif result == "fail":
                        failed_checks += 1
                    else:
                        skipped_checks += 1

            for rule in BALANCE_HIERARCHICAL_RULES:
                for period_index, period_name in PERIODS:
                    detail = self._inspect_balance_hierarchical_rule(
                        balance_data=balance_data,
                        rule=rule,
                        period_index=period_index,
                        period_name=period_name,
                        basic_details_by_key=balance_basic_details_by_key,
                    )
                    self._apply_residual_inferred_balance_components(
                        detail=detail,
                        basic_details_by_key=balance_basic_details_by_key,
                        inferred_balance_values=inferred_balance_values,
                    )
                    details.append(detail)
                    result = detail["result"]
                    if result == "pass":
                        passed_checks += 1
                    elif result == "fail":
                        failed_checks += 1
                    else:
                        skipped_checks += 1

        if has_profit:
            inferred_profit_values: Dict[str, Decimal] = {}
            for rule in PROFIT_BASIC_RULES:
                if not self._profit_rule_applies(profit_data, rule):
                    continue
                detail = self._inspect_profit_rule(
                    profit_data=profit_data,
                    semantic_profit_data=semantic_profit_data,
                    rule=rule,
                    inferred_profit_values=inferred_profit_values,
                )
                details.append(detail)
                inferred_total = _to_decimal(detail.get("_inferred_total"))
                if inferred_total is not None:
                    inferred_profit_values[str(rule["total_code"])] = inferred_total
                result = detail["result"]
                if result == "pass":
                    passed_checks += 1
                elif result == "fail":
                    failed_checks += 1
                else:
                    skipped_checks += 1

        if has_cashflow:
            inferred_cashflow_values: Dict[str, Decimal] = {}
            cashflow_details: List[Dict[str, Any]] = []
            for rule in CASHFLOW_BASIC_RULES:
                if not self._cashflow_rule_applies(cashflow_data, rule):
                    continue
                detail = self._inspect_cashflow_rule(
                    cashflow_data=cashflow_data,
                    rule=rule,
                    inferred_cashflow_values=inferred_cashflow_values,
                )
                cashflow_details.append(detail)
                inferred_total = _to_decimal(detail.get("_inferred_total"))
                if inferred_total is not None:
                    inferred_cashflow_values[str(rule["total_code"])] = inferred_total
            self._attach_cashflow_subtotal_confirmations(cashflow_details)
            self._apply_cashflow_zero_residual_inferences(cashflow_data, cashflow_details)
            for detail in cashflow_details:
                details.append(detail)
                result = detail["result"]
                if result == "pass":
                    passed_checks += 1
                elif result == "fail":
                    failed_checks += 1
                else:
                    skipped_checks += 1

        return {
            "passed": failed_checks == 0,
            "details": details,
            "total_checks": len(details),
            "passed_checks": passed_checks,
            "failed_checks": failed_checks,
            "skipped_checks": skipped_checks,
        }

    @staticmethod
    def _balance_rule_applies(balance_data: Dict[str, Any], rule: Dict[str, Any]) -> bool:
        skipped_codes = [
            str(code)
            for code in rule.get("skip_if_any_present", [])
            if str(code or "").strip()
        ]
        if any(
            FinancialInspector._balance_code_has_present_value(balance_data.get(code))
            for code in skipped_codes
        ):
            return False

        required_codes = [
            str(code)
            for code in rule.get("applies_if_any_present", [])
            if str(code or "").strip()
        ]
        if required_codes:
            if rule.get("display_on_components"):
                has_present_component = any(
                    FinancialInspector._balance_code_has_numeric_value(balance_data.get(code))
                    for code in required_codes
                )
                if not has_present_component:
                    return False
            elif not any(code in balance_data for code in required_codes):
                return False

        return True

    @staticmethod
    def _balance_code_has_present_value(value: Any) -> bool:
        values = value if isinstance(value, list) else [value]
        for item in values:
            if item == "":
                return True
            if _to_decimal(item) is not None:
                return True
        return False

    @staticmethod
    def _balance_code_has_numeric_value(value: Any) -> bool:
        values = value if isinstance(value, list) else [value]
        for item in values:
            if _to_decimal(item) is not None:
                return True
        return False

    @staticmethod
    def _balance_rule_applies_for_period(
        balance_data: Dict[str, Any],
        rule: Dict[str, Any],
        period_index: int,
    ) -> bool:
        if not rule.get("display_on_components"):
            return True

        return any(
            _extract_balance_period_value(balance_data.get(code), period_index) is not None
            for _sign, code, _name in _iter_signed_components(rule["components"])
        )

    @staticmethod
    def _profit_rule_applies(profit_data: Dict[str, Any], rule: Dict[str, Any]) -> bool:
        required_codes = [
            str(code)
            for code in rule.get("applies_if_any_present", [])
            if str(code or "").strip()
        ]
        if not required_codes:
            return True

        return any(
            _extract_current_period_value(profit_data.get(code)) is not None
            for code in required_codes
        )

    def _inspect_balance_rule(
        self,
        *,
        balance_data: Dict[str, Any],
        semantic_balance_data: Dict[str, Any],
        rule: Dict[str, Any],
        period_index: int,
        period_name: str,
        inferred_balance_values: Optional[Dict[tuple[int, str], Decimal]] = None,
    ) -> Dict[str, Any]:
        check_name = f"{rule['name']}({period_name})"
        total_code = str(rule["total_code"])
        total_name = str(rule["name"])
        total_value = _extract_balance_period_value(balance_data.get(total_code), period_index)

        participants = []
        zero_if_missing_codes = {
            str(code)
            for code in rule.get("zero_if_missing_codes", [])
            if str(code or "").strip()
        }
        zero_inferred_candidates = []
        participant_sum = Decimal("0")
        for sign, code, name in _iter_signed_components(rule["components"]):
            value, value_state = _extract_balance_period_value_with_state(
                balance_data.get(code),
                period_index,
            )
            source = "view"
            if value is None:
                inferred_value = (inferred_balance_values or {}).get((period_index, code))
                if inferred_value is not None:
                    value = inferred_value
                    source = "inferred"
                elif value_state != "empty" or rule.get("display_on_components"):
                    if code in zero_if_missing_codes and value_state == "excluded":
                        zero_inferred_candidates.append(
                            {
                                "code": code,
                                "name": name,
                                "operator": sign,
                            }
                        )
                    continue
                else:
                    value = Decimal("0")
                    source = "empty"
            signed_value = value if sign != "-" else -value
            participants.append(
                {
                    "code": code,
                    "name": name,
                    "value": str(signed_value),
                    "source": source,
                    "operator": sign,
                }
            )
            participant_sum += signed_value

        detail = {
            "_table": "balance",
            "check": check_name,
            "period": period_name,
            "_period_index": period_index,
            "_rule_total_code": total_code,
            **({"_display_on_components": True} if rule.get("display_on_components") else {}),
            **(
                {"_display_fail_on_components": True}
                if rule.get("display_fail_on_components")
                else {}
            ),
            "components": {
                item["code"]: {
                    "name": item["name"],
                    "value": item["value"],
                    **({"operator": item["operator"]} if item.get("operator") == "-" else {}),
                    **({"source": item["source"]} if item.get("source") != "view" else {}),
                }
                for item in participants
            },
            "_participating_component_count": len(participants),
        }

        if total_value is None:
            missing_total_attribution = self._try_missing_non_current_assets_attribution(
                balance_data=balance_data,
                semantic_balance_data=semantic_balance_data,
                rule=rule,
                period_index=period_index,
                participants=participants,
                participant_sum=participant_sum,
            )
            if missing_total_attribution is not None:
                detail.update(missing_total_attribution)
                return detail

            missing_total_from_components = self._try_missing_balance_total_from_components(
                rule=rule,
                participants=participants,
                participant_sum=participant_sum,
            )
            if missing_total_from_components is not None:
                detail.update(missing_total_from_components)
                semantic_detail = self._try_semantic_balance_validation(
                    base_detail=detail,
                    balance_data=balance_data,
                    semantic_balance_data=semantic_balance_data,
                    rule=rule,
                    period_index=period_index,
                )
                if semantic_detail is not None:
                    return semantic_detail
                return detail

            detail["result"] = "fail"
            detail["reason"] = "view中缺少合计项，无法校验"
            detail["suspects"] = [
                {
                    "code": total_code,
                    "name": total_name,
                    "source": "missing_total",
                }
            ]
            semantic_detail = self._try_semantic_balance_validation(
                base_detail=detail,
                balance_data=balance_data,
                semantic_balance_data=semantic_balance_data,
                rule=rule,
                period_index=period_index,
            )
            if semantic_detail is not None:
                return semantic_detail
            return detail

        if not participants:
            detail["result"] = "skip"
            detail["reason"] = "view中缺少足够组成项，无法校验"
            detail["suspects"] = []
            return detail

        detail["total"] = {
            "code": total_code,
            "name": total_name,
            "value": str(total_value),
        }
        detail["expected"] = str(participant_sum)
        detail["amounts"] = {
            "reported_total": str(total_value),
            "recomputed_total": str(participant_sum),
        }

        if (
            zero_inferred_candidates
            and abs(total_value - participant_sum) <= DECIMAL_TOLERANCE
        ):
            for item in zero_inferred_candidates:
                components = detail.setdefault("components", {})
                components[item["code"]] = {
                    "name": item["name"],
                    "value": "0",
                    "source": "inferred_zero",
                    **({"operator": item["operator"]} if item.get("operator") == "-" else {}),
                }
            missing_names = self._join_component_names(zero_inferred_candidates)
            detail["result"] = "pass"
            detail["reason"] = f"{missing_names}未抽取，按0参与校验通过"
            detail["suspects"] = []
            detail["_participating_component_count"] = len(detail.get("components") or {})
            detail["attribution"] = {
                "mode": "missing_component_zero_inferred_match",
                "culprit_codes": [item["code"] for item in zero_inferred_candidates],
                "culprit_names": [item["name"] for item in zero_inferred_candidates],
                "candidate_sum": str(participant_sum),
                "inferred_zero_component_codes": [
                    item["code"] for item in zero_inferred_candidates
                ],
                "inferred_zero_component_names": [
                    item["name"] for item in zero_inferred_candidates
                ],
            }
            return detail

        if abs(total_value - participant_sum) <= DECIMAL_TOLERANCE:
            detail["result"] = "pass"
            detail["reason"] = "校验通过"
            detail["suspects"] = []
            return detail

        parallel_total_validation = self._try_parallel_balance_total_validation(
            detail=detail,
            balance_data=balance_data,
            rule=rule,
            period_index=period_index,
            total_value=total_value,
            participant_sum=participant_sum,
            participants=participants,
        )
        if parallel_total_validation is not None:
            detail.update(parallel_total_validation)
            return detail

        detail["result"] = "fail"
        detail["reason"] = "校验未通过"
        detail["suspects"] = [
            {
                "code": total_code,
                "name": total_name,
                "source": "view_participant",
            },
            *[
                {
                    "code": item["code"],
                    "name": item["name"],
                    "source": "view_participant",
                }
                for item in participants
            ],
            *[
                {
                    "code": item["code"],
                    "name": item["name"],
                    "source": "missing_zero_candidate",
                }
                for item in zero_inferred_candidates
            ],
        ]
        parallel_component_validation = self._try_nested_parallel_component_validation(
            balance_data=balance_data,
            rule=rule,
            period_index=period_index,
        )
        if parallel_component_validation is not None:
            detail.update(parallel_component_validation)
            return detail
        semantic_attribution = self._try_semantic_balance_component_attribution(
            balance_data=balance_data,
            semantic_balance_data=semantic_balance_data,
            rule=rule,
            period_index=period_index,
            total_value=total_value,
            participant_sum=participant_sum,
            participants=participants,
        )
        if semantic_attribution is not None:
            detail["reason"] = semantic_attribution["reason"]
            detail["suspects"] = semantic_attribution["suspects"]
            detail["semantic_attribution"] = semantic_attribution["semantic_attribution"]
            return detail
        semantic_detail = self._try_semantic_balance_validation(
            base_detail=detail,
            balance_data=balance_data,
            semantic_balance_data=semantic_balance_data,
            rule=rule,
            period_index=period_index,
        )
        if semantic_detail is not None:
            self._apply_semantic_verified_component_exclusions(
                detail=semantic_detail,
                semantic_balance_data=semantic_balance_data,
                period_index=period_index,
                participants=participants,
            )
            return semantic_detail
        self._apply_semantic_verified_component_exclusions(
            detail=detail,
            semantic_balance_data=semantic_balance_data,
            period_index=period_index,
            participants=participants,
        )
        return detail

    def _try_parallel_balance_total_validation(
        self,
        *,
        detail: Dict[str, Any],
        balance_data: Dict[str, Any],
        rule: Dict[str, Any],
        period_index: int,
        total_value: Decimal,
        participant_sum: Decimal,
        participants: List[Dict[str, str]],
    ) -> Optional[Dict[str, Any]]:
        groups = NESTED_OR_PARALLEL_GROUPS_BY_PARENT_TOTAL_CODE.get(str(rule["total_code"]))
        if not groups:
            return None

        participant_codes = {str(item["code"]) for item in participants}
        parallel_components: List[Dict[str, str]] = []
        for group in groups:
            if str(group["aggregate_code"]) not in participant_codes:
                continue
            parallel_components.extend(
                self._extract_parallel_group_components(
                    balance_data=balance_data,
                    group=group,
                    period_index=period_index,
                    existing_codes=participant_codes,
                )
            )

        if not parallel_components:
            return None

        parallel_sum = participant_sum + sum(
            (_to_decimal(item["value"]) or Decimal("0"))
            for item in parallel_components
        )
        if abs(total_value - parallel_sum) > DECIMAL_TOLERANCE:
            return None

        components = dict(detail.get("components") or {})
        for item in parallel_components:
            components[item["code"]] = {
                "name": item["name"],
                "value": item["value"],
                **({"source": item["source"]} if item.get("source") != "view" else {}),
            }

        return {
            "result": "pass",
            "reason": "已按并列科目口径复核通过",
            "suspects": [],
            "components": components,
            "_participating_component_count": len(components),
            "expected": str(parallel_sum),
            "amounts": {
                "reported_total": str(total_value),
                "recomputed_total": str(parallel_sum),
                "single_component_track_total": str(participant_sum),
            },
            "attribution": {
                "mode": "parallel_components_match",
                "parent_total_code": str(rule["total_code"]),
                "parent_total_name": str(rule["name"]),
                "component_codes": [item["code"] for item in parallel_components],
                "component_names": [item["name"] for item in parallel_components],
                "candidate_sum": str(parallel_sum),
                "single_component_track_total": str(participant_sum),
            },
        }

    def _try_nested_parallel_component_validation(
        self,
        *,
        balance_data: Dict[str, Any],
        rule: Dict[str, Any],
        period_index: int,
    ) -> Optional[Dict[str, Any]]:
        if not rule.get("display_on_components"):
            return None

        group = NESTED_OR_PARALLEL_GROUP_BY_AGGREGATE_CODE.get(str(rule["total_code"]))
        if not group:
            return None

        parent_track = self._matched_nested_parent_total_track(
            balance_data=balance_data,
            group=group,
            period_index=period_index,
        )
        if parent_track is None:
            return None

        parent_name = str(group["parent_total_name"])
        track_mode = str(parent_track.get("mode") or "")
        if track_mode == "parallel_components_match":
            reason = f"已按{parent_name}并列科目口径复核通过"
        else:
            reason = f"已按{parent_name}单项科目口径复核通过"

        return {
            "result": "pass",
            "reason": reason,
            "suspects": [],
            "parallel_validation": parent_track,
        }

    def _matched_nested_parent_total_track(
        self,
        *,
        balance_data: Dict[str, Any],
        group: Dict[str, Any],
        period_index: int,
    ) -> Optional[Dict[str, Any]]:
        parent_total_code = str(group["parent_total_code"])
        parent_rule = self._balance_rule_by_total_code(parent_total_code)
        if parent_rule is None:
            return None

        parent_total = _extract_balance_period_value(
            balance_data.get(parent_total_code),
            period_index,
        )
        if parent_total is None:
            return None

        parent_participants, single_track_sum = self._collect_balance_rule_participants(
            balance_data=balance_data,
            rule=parent_rule,
            period_index=period_index,
        )
        if not parent_participants:
            return None

        parent_name = str(group["parent_total_name"])
        if abs(parent_total - single_track_sum) <= DECIMAL_TOLERANCE:
            return {
                "mode": "single_component_match",
                "parent_total_code": parent_total_code,
                "parent_total_name": parent_name,
                "aggregate_code": str(group["aggregate_code"]),
                "aggregate_name": str(group["aggregate_name"]),
                "component_codes": [str(code) for code, _name in group.get("components", [])],
                "component_names": [str(name) for _code, name in group.get("components", [])],
                "candidate_sum": str(single_track_sum),
            }

        participant_codes = {str(item["code"]) for item in parent_participants}
        if str(group["aggregate_code"]) not in participant_codes:
            return None

        parallel_components = self._extract_parallel_group_components(
            balance_data=balance_data,
            group=group,
            period_index=period_index,
            existing_codes=participant_codes,
        )
        if not parallel_components:
            return None

        parallel_sum = single_track_sum + sum(
            (_to_decimal(item["value"]) or Decimal("0"))
            for item in parallel_components
        )
        if abs(parent_total - parallel_sum) > DECIMAL_TOLERANCE:
            return None

        return {
            "mode": "parallel_components_match",
            "parent_total_code": parent_total_code,
            "parent_total_name": parent_name,
            "aggregate_code": str(group["aggregate_code"]),
            "aggregate_name": str(group["aggregate_name"]),
            "candidate_sum": str(parallel_sum),
            "single_component_track_total": str(single_track_sum),
            "component_codes": [item["code"] for item in parallel_components],
            "component_names": [item["name"] for item in parallel_components],
        }

    @staticmethod
    def _balance_rule_by_total_code(total_code: str) -> Optional[Dict[str, Any]]:
        for rule in BALANCE_BASIC_RULES:
            if str(rule.get("total_code") or "") == total_code:
                return rule
        return None

    def _collect_balance_rule_participants(
        self,
        *,
        balance_data: Dict[str, Any],
        rule: Dict[str, Any],
        period_index: int,
    ) -> tuple[List[Dict[str, str]], Decimal]:
        participants: List[Dict[str, str]] = []
        participant_sum = Decimal("0")
        for sign, code, name in _iter_signed_components(rule["components"]):
            value, value_state = _extract_balance_period_value_with_state(
                balance_data.get(code),
                period_index,
            )
            source = "view"
            if value is None:
                if value_state != "empty" or rule.get("display_on_components"):
                    continue
                value = Decimal("0")
                source = "empty"
            signed_value = value if sign != "-" else -value
            participants.append(
                {
                    "code": code,
                    "name": name,
                    "value": str(signed_value),
                    "source": source,
                    "operator": sign,
                }
            )
            participant_sum += signed_value
        return participants, participant_sum

    @staticmethod
    def _extract_parallel_group_components(
        *,
        balance_data: Dict[str, Any],
        group: Dict[str, Any],
        period_index: int,
        existing_codes: set[str],
    ) -> List[Dict[str, str]]:
        components: List[Dict[str, str]] = []
        for code, name in group.get("components", []):
            code = str(code)
            if code in existing_codes:
                continue
            value, value_state = _extract_balance_period_value_with_state(
                balance_data.get(code),
                period_index,
            )
            source = "view"
            if value is None:
                if value_state != "empty":
                    continue
                value = Decimal("0")
                source = "empty"
            components.append(
                {
                    "code": code,
                    "name": str(name),
                    "value": str(value),
                    "source": source,
                }
            )
        return components

    def _inspect_balance_hierarchical_rule(
        self,
        *,
        balance_data: Dict[str, Any],
        rule: Dict[str, Any],
        period_index: int,
        period_name: str,
        basic_details_by_key: Dict[tuple[int, str], Dict[str, Any]],
    ) -> Dict[str, Any]:
        check_name = f"{rule['name']}({period_name})"
        total_code = str(rule["total_code"])
        total_name = str(rule.get("total_name") or rule["name"])
        total_reported = _extract_balance_period_value(balance_data.get(total_code), period_index)

        components = []
        for code, name in rule["components"]:
            code = str(code)
            child_detail = basic_details_by_key.get((period_index, code), {})
            reported = _extract_balance_period_value(balance_data.get(code), period_index)
            inferred_total = _to_decimal(child_detail.get("_inferred_total"))
            recomputed = inferred_total or _to_decimal(child_detail.get("expected"))
            components.append(
                {
                    "code": code,
                    "name": name,
                    "reported": reported,
                    "recomputed": recomputed,
                    "result": child_detail.get("result", "skip"),
                }
            )

        detail = {
            "_table": "balance",
            "check": check_name,
            "period": period_name,
            "_period_index": period_index,
            "_rule_total_code": total_code,
            "components": {
                item["code"]: {
                    "name": item["name"],
                    "reported_value": _decimal_to_string(item["reported"]),
                    "recomputed_value": _decimal_to_string(item["recomputed"]),
                    "basic_result": item["result"],
                }
                for item in components
            },
            "_participating_component_count": len(components),
        }

        if total_reported is None:
            detail["result"] = "fail"
            detail["reason"] = "view中缺少资产总计，无法进行层级校验"
            detail["suspects"] = [
                {
                    "code": total_code,
                    "name": total_name,
                    "source": "missing_total",
                }
            ]
            return detail

        detail["total"] = {
            "code": total_code,
            "name": total_name,
            "value": str(total_reported),
        }
        detail["amounts"] = {
            "reported_total": str(total_reported),
            "recomputed_total": None,
        }

        reported_values = [item["reported"] for item in components]
        if any(value is None for value in reported_values):
            inferred_values = [
                item["recomputed"] if item["reported"] is None else item["reported"]
                for item in components
            ]
            if all(value is not None for value in inferred_values):
                inferred_sum = sum(inferred_values, Decimal("0"))
                detail["expected"] = str(inferred_sum)
                if abs(total_reported - inferred_sum) <= DECIMAL_TOLERANCE:
                    missing_components = [
                        item
                        for item in components
                        if item["reported"] is None and item["recomputed"] is not None
                    ]
                    detail["result"] = "pass"
                    detail["reason"] = "使用缺失下级合计的推导值后校验通过"
                    detail["suspects"] = []
                    detail["attribution"] = {
                        "mode": "missing_component_inferred_match",
                        "culprit_codes": [item["code"] for item in missing_components],
                        "culprit_names": [item["name"] for item in missing_components],
                        "candidate_sum": str(inferred_sum),
                    }
                    return detail

                mixed_attribution = self._try_missing_and_recomputed_hierarchical_attribution(
                    total_reported=total_reported,
                    total_name=total_name,
                    components=components,
                    reported_with_missing_inferred_sum=inferred_sum,
                )
                if mixed_attribution is not None:
                    detail.update(mixed_attribution)
                    return detail

                residual_attribution = self._try_missing_residual_hierarchical_attribution(
                    total_reported=total_reported,
                    total_name=total_name,
                    components=components,
                    reported_with_missing_inferred_sum=inferred_sum,
                )
                if residual_attribution is not None:
                    detail.update(residual_attribution)
                    for item in residual_attribution["attribution"].get(
                        "inferred_components",
                        [],
                    ):
                        component_detail = detail["components"].get(item["code"])
                        if isinstance(component_detail, dict):
                            component_detail["recomputed_value"] = item["inferred_value"]
                    return detail

            zero_inferred_attribution = self._try_missing_zero_hierarchical_attribution(
                total_reported=total_reported,
                total_name=total_name,
                components=components,
            )
            if zero_inferred_attribution is not None:
                for item in components:
                    component_detail = detail["components"].get(item["code"])
                    if isinstance(component_detail, dict):
                        component_detail["recomputed_value"] = _decimal_to_string(
                            item.get("recomputed")
                        )
                detail.update(zero_inferred_attribution)
                return detail

            detail["result"] = "skip"
            detail["reason"] = "view中缺少下级合计项，无法进行层级归因"
            detail["suspects"] = []
            return detail

        reported_sum = sum(reported_values, Decimal("0"))
        detail["expected"] = str(reported_sum)

        if abs(total_reported - reported_sum) <= DECIMAL_TOLERANCE:
            detail["result"] = "pass"
            detail["reason"] = "层级校验通过"
            detail["suspects"] = []
            return detail

        repaired_candidates = []
        for component in components:
            if component["result"] != "fail" or component["recomputed"] is None:
                continue
            candidate_sum = sum(
                (
                    other["recomputed"]
                    if other["code"] == component["code"]
                    else other["reported"]
                )
                for other in components
            )
            if abs(total_reported - candidate_sum) <= DECIMAL_TOLERANCE:
                repaired_candidates.append(
                    {
                        "code": component["code"],
                        "name": component["name"],
                        "recomputed_total": str(component["recomputed"]),
                        "candidate_sum": str(candidate_sum),
                    }
                )

        if all(component["result"] == "pass" for component in components):
            detail["result"] = "fail"
            detail["reason"] = f"下级合计均通过，但{total_name}与其和不一致，疑似{total_name}字段有误"
            detail["suspects"] = [
                {
                    "code": total_code,
                    "name": total_name,
                    "source": "hierarchical_total",
                }
            ]
            detail["attribution"] = {
                "culprit_code": total_code,
                "culprit_name": total_name,
                "mode": "reported_total_mismatch",
            }
            return detail

        recomputed_sum = sum(
            (
                item["recomputed"]
                if item["result"] == "fail" and item["recomputed"] is not None
                else item["reported"]
            )
            for item in components
        )

        if len(repaired_candidates) == 1:
            culprit = repaired_candidates[0]
            detail["result"] = "fail"
            detail["reason"] = (
                f"使用{culprit['name']}的子项重算值后等式成立，"
                f"疑似{culprit['name']}字段有误"
            )
            detail["suspects"] = [
                {
                    "code": culprit["code"],
                    "name": culprit["name"],
                    "source": "hierarchical_component",
                }
            ]
            detail["attribution"] = {
                "culprit_code": culprit["code"],
                "culprit_name": culprit["name"],
                "mode": "component_recomputed_match",
                "candidate_sum": culprit["candidate_sum"],
            }
            return detail

        failed_components = [
            item
            for item in components
            if item["result"] == "fail"
        ]
        if (
            len(failed_components) >= 2
            and abs(total_reported - recomputed_sum) <= DECIMAL_TOLERANCE
        ):
            detail["result"] = "fail"
            detail["reason"] = f"使用多个中间合计的子项重算值后等式成立，疑似这些中间合计字段有误，{total_name}大概率正确"
            detail["suspects"] = [
                {
                    "code": item["code"],
                    "name": item["name"],
                    "source": "hierarchical_component",
                }
                for item in failed_components
            ]
            detail["attribution"] = {
                "mode": "multiple_component_recomputed_match",
                "culprit_codes": [item["code"] for item in failed_components],
                "culprit_names": [item["name"] for item in failed_components],
                "candidate_sum": str(recomputed_sum),
            }
            return detail

        detail["result"] = "fail"
        detail["reason"] = "层级校验未通过，且无法单点归因，可能存在多个字段或明细项错误"
        detail["suspects"] = [
            {
                "code": total_code,
                "name": total_name,
                "source": "hierarchical_total",
            },
            *[
                {
                    "code": item["code"],
                    "name": item["name"],
                    "source": "hierarchical_component",
                }
                for item in components
                if item["result"] == "fail"
            ],
        ]
        if repaired_candidates:
            detail["attribution_candidates"] = repaired_candidates
        return detail

    @staticmethod
    def _apply_residual_inferred_balance_components(
        *,
        detail: Dict[str, Any],
        basic_details_by_key: Dict[tuple[int, str], Dict[str, Any]],
        inferred_balance_values: Dict[tuple[int, str], Decimal],
    ) -> None:
        attribution = detail.get("attribution")
        if not isinstance(attribution, dict):
            return
        if str(attribution.get("mode") or "").strip() != "missing_component_residual_inferred_match":
            return

        period_index = detail.get("_period_index")
        if not isinstance(period_index, int):
            return

        for item in attribution.get("inferred_components", []):
            if not isinstance(item, dict):
                continue
            code = str(item.get("code") or "").strip()
            inferred_value = _to_decimal(item.get("inferred_value"))
            if not code or inferred_value is None:
                continue

            inferred_balance_values[(period_index, code)] = inferred_value
            basic_detail = basic_details_by_key.get((period_index, code))
            if not isinstance(basic_detail, dict):
                continue

            previous_value = _to_decimal(basic_detail.get("_inferred_total"))
            if previous_value is None:
                previous_value = _to_decimal(basic_detail.get("expected"))
            basic_detail["_inferred_total"] = str(inferred_value)
            basic_detail["expected"] = str(inferred_value)
            basic_detail["reason"] = "合计项缺失，但可由上层差额推导"
            basic_attribution = dict(basic_detail.get("attribution") or {})
            basic_attribution["mode"] = "missing_total_inferred_from_components"
            basic_attribution["candidate_sum"] = str(inferred_value)
            basic_attribution["inference_source"] = "parent_residual"
            if previous_value is not None:
                basic_attribution["component_sum"] = str(previous_value)
                basic_attribution["diff"] = str(abs(inferred_value - previous_value))
            basic_detail["attribution"] = basic_attribution

    def _try_missing_residual_hierarchical_attribution(
        self,
        *,
        total_reported: Decimal,
        total_name: str,
        components: List[Dict[str, Any]],
        reported_with_missing_inferred_sum: Decimal,
    ) -> Optional[Dict[str, Any]]:
        missing_components = [
            item
            for item in components
            if item.get("reported") is None
        ]
        if len(missing_components) != 1:
            return None

        known_sum = Decimal("0")
        for component in components:
            reported = component.get("reported")
            if reported is None:
                continue
            known_sum += reported

        missing_component = missing_components[0]
        inferred_value = total_reported - known_sum
        component_recomputed = missing_component.get("recomputed")
        if (
            component_recomputed is not None
            and abs(inferred_value - component_recomputed) <= DECIMAL_TOLERANCE
        ):
            return None

        inferred_components = [
            {
                "code": missing_component["code"],
                "name": missing_component["name"],
                "inferred_value": str(inferred_value),
                "component_recomputed_value": _decimal_to_string(component_recomputed),
                "diff": (
                    str(abs(inferred_value - component_recomputed))
                    if component_recomputed is not None else
                    None
                ),
            }
        ]
        return {
            "result": "pass",
            "reason": "使用缺失下级合计的差额推导值后校验通过",
            "expected": str(total_reported),
            "amounts": {
                "reported_total": str(total_reported),
                "recomputed_total": str(total_reported),
                "reported_with_missing_inferred_sum": str(reported_with_missing_inferred_sum),
            },
            "suspects": [],
            "attribution": {
                "mode": "missing_component_residual_inferred_match",
                "culprit_codes": [missing_component["code"]],
                "culprit_names": [missing_component["name"]],
                "candidate_sum": str(total_reported),
                "inferred_components": inferred_components,
            },
        }

    def _try_missing_and_recomputed_hierarchical_attribution(
        self,
        *,
        total_reported: Decimal,
        total_name: str,
        components: List[Dict[str, Any]],
        reported_with_missing_inferred_sum: Decimal,
    ) -> Optional[Dict[str, Any]]:
        missing_inferred_components: List[Dict[str, Any]] = []
        recomputed_culprit_components: List[Dict[str, Any]] = []
        candidate_values: List[Decimal] = []

        for component in components:
            reported = component.get("reported")
            recomputed = component.get("recomputed")
            if reported is None:
                if recomputed is None:
                    return None
                missing_inferred_components.append(component)
                candidate_values.append(recomputed)
                continue

            if (
                component.get("result") == "fail"
                and recomputed is not None
                and abs(reported - recomputed) > DECIMAL_TOLERANCE
            ):
                recomputed_culprit_components.append(component)
                candidate_values.append(recomputed)
                continue

            candidate_values.append(reported)

        if not missing_inferred_components or not recomputed_culprit_components:
            return None

        candidate_sum = sum(candidate_values, Decimal("0"))
        if abs(total_reported - candidate_sum) > DECIMAL_TOLERANCE:
            return None

        culprit_names = self._join_component_names(recomputed_culprit_components)
        missing_names = self._join_component_names(missing_inferred_components)
        reason = (
            f"使用{culprit_names}的子项重算值和{missing_names}的推导值后等式成立，"
            f"异常归因至{culprit_names}层级，{total_name}大概率正确"
        )
        return {
            "result": "fail",
            "reason": reason,
            "expected": str(candidate_sum),
            "amounts": {
                "reported_total": str(total_reported),
                "recomputed_total": str(candidate_sum),
                "reported_with_missing_inferred_sum": str(reported_with_missing_inferred_sum),
            },
            "suspects": [
                {
                    "code": item["code"],
                    "name": item["name"],
                    "source": "hierarchical_component_recomputed",
                }
                for item in recomputed_culprit_components
            ],
            "attribution": {
                "mode": "missing_component_and_recomputed_component_match",
                "culprit_codes": [item["code"] for item in recomputed_culprit_components],
                "culprit_names": [item["name"] for item in recomputed_culprit_components],
                "validated_missing_component_codes": [
                    item["code"] for item in missing_inferred_components
                ],
                "validated_missing_component_names": [
                    item["name"] for item in missing_inferred_components
                ],
                "candidate_sum": str(candidate_sum),
                "reported_with_missing_inferred_sum": str(reported_with_missing_inferred_sum),
                "component_diffs": [
                    {
                        "code": item["code"],
                        "name": item["name"],
                        "reported_value": str(item["reported"]),
                        "recomputed_value": str(item["recomputed"]),
                        "diff": str(abs(item["recomputed"] - item["reported"])),
                    }
                    for item in recomputed_culprit_components
                ],
                "missing_components": [
                    {
                        "code": item["code"],
                        "name": item["name"],
                        "recomputed_value": str(item["recomputed"]),
                    }
                    for item in missing_inferred_components
                ],
            },
        }

    def _try_missing_zero_hierarchical_attribution(
        self,
        *,
        total_reported: Decimal,
        total_name: str,
        components: List[Dict[str, Any]],
    ) -> Optional[Dict[str, Any]]:
        missing_components = [
            item
            for item in components
            if item.get("reported") is None and item.get("recomputed") is None
        ]
        if not missing_components:
            return None

        candidate_values: List[Decimal] = []
        for component in components:
            reported = component.get("reported")
            recomputed = component.get("recomputed")
            if reported is not None:
                candidate_values.append(reported)
                continue
            if recomputed is not None:
                candidate_values.append(recomputed)
                continue
            candidate_values.append(Decimal("0"))

        candidate_sum = sum(candidate_values, Decimal("0"))
        if abs(total_reported - candidate_sum) > DECIMAL_TOLERANCE:
            return None

        for component in missing_components:
            component["recomputed"] = Decimal("0")

        reason = "使用缺失下级合计推定值0后校验通过"
        return {
            "result": "pass",
            "reason": reason,
            "expected": str(candidate_sum),
            "amounts": {
                "reported_total": str(total_reported),
                "recomputed_total": str(candidate_sum),
            },
            "suspects": [],
            "attribution": {
                "mode": "missing_component_zero_inferred_match",
                "culprit_codes": [item["code"] for item in missing_components],
                "culprit_names": [item["name"] for item in missing_components],
                "candidate_sum": str(candidate_sum),
                "inferred_zero_component_codes": [
                    item["code"] for item in missing_components
                ],
                "inferred_zero_component_names": [
                    item["name"] for item in missing_components
                ],
            },
        }

    def _try_missing_balance_total_from_components(
        self,
        *,
        rule: Dict[str, Any],
        participants: List[Dict[str, str]],
        participant_sum: Decimal,
    ) -> Optional[Dict[str, Any]]:
        if not participants:
            return None

        total_code = str(rule["total_code"])
        total_name = str(rule["name"])
        return {
            "result": "fail",
            "reason": "合计项缺失，但可由已提取子项推导",
            "suspects": [
                {
                    "code": total_code,
                    "name": total_name,
                    "source": "missing_total_inferred_from_components",
                }
            ],
            "expected": str(participant_sum),
            "_inferred_total": str(participant_sum),
            "attribution": {
                "mode": "missing_total_inferred_from_components",
                "culprit_code": total_code,
                "culprit_name": total_name,
                "candidate_sum": str(participant_sum),
            },
        }

    def _try_semantic_balance_validation(
        self,
        *,
        base_detail: Dict[str, Any],
        balance_data: Dict[str, Any],
        semantic_balance_data: Dict[str, Any],
        rule: Dict[str, Any],
        period_index: int,
    ) -> Optional[Dict[str, Any]]:
        if (
            not semantic_balance_data
            or str(rule.get("total_code") or "").strip() != "ZY2015058"
        ):
            return None

        base_components = base_detail.get("components")
        if not isinstance(base_components, dict) or not base_components:
            return None

        participants: List[Dict[str, str]] = []
        participant_sum = Decimal("0")
        for code, component in base_components.items():
            if not isinstance(component, dict):
                continue
            value = _to_decimal(component.get("value"))
            if value is None:
                continue
            participants.append(
                {
                    "code": str(code),
                    "name": str(component.get("name") or code),
                    "value": str(value),
                    "source": str(component.get("source") or "view"),
                }
            )
            participant_sum += value

        if not participants:
            return None

        old_standard_candidate = self._build_old_standard_non_current_assets_candidate(
            balance_data=balance_data,
            semantic_balance_data=semantic_balance_data,
            period_index=period_index,
            participants=participants,
            participant_sum=participant_sum,
        )
        if old_standard_candidate is None:
            return None

        candidate_total = old_standard_candidate["total"]
        if abs(candidate_total - participant_sum) <= DECIMAL_TOLERANCE:
            return None

        semantic_detail = dict(base_detail)
        semantic_detail["components"] = {
            item["code"]: {
                "name": item["name"],
                "value": item["value"],
                **({"source": item["source"]} if item.get("source") != "view" else {}),
            }
            for item in old_standard_candidate["participants"]
        }
        semantic_detail["_participating_component_count"] = len(old_standard_candidate["participants"])
        semantic_detail["expected"] = str(candidate_total)
        semantic_detail["semantic_validation"] = {
            "mode": "old_standard_hidden_subtotals",
            "component_codes": [item["code"] for item in old_standard_candidate["participants"]],
            "component_names": [item["name"] for item in old_standard_candidate["participants"]],
        }
        validated_components = old_standard_candidate.get("validated_components") or []
        if validated_components:
            semantic_detail["validated_components"] = validated_components
        invalid_components = old_standard_candidate.get("invalid_components") or []
        if invalid_components:
            semantic_detail["invalid_components"] = invalid_components

        attribution = base_detail.get("attribution")
        total = base_detail.get("total")
        total_value = None
        if isinstance(total, dict):
            total_value = _to_decimal(total.get("value"))

        if total_value is None:
            if isinstance(attribution, dict):
                updated_attribution = dict(attribution)
                updated_attribution["candidate_sum"] = str(candidate_total)
                semantic_detail["attribution"] = updated_attribution
            semantic_detail["_inferred_total"] = str(candidate_total)
            semantic_detail["reason"] = "合计项缺失，但可由旧准则口径推导"
            return semantic_detail

        if abs(total_value - candidate_total) > DECIMAL_TOLERANCE:
            return None

        semantic_detail["result"] = "pass"
        semantic_detail["reason"] = "已按旧准则口径复核通过"
        semantic_detail["suspects"] = []
        semantic_detail["amounts"] = {
            "reported_total": str(total_value),
            "recomputed_total": str(candidate_total),
        }
        semantic_detail.pop("_inferred_total", None)
        semantic_detail.pop("attribution", None)
        return semantic_detail

    def _build_old_standard_non_current_assets_candidate(
        self,
        *,
        balance_data: Dict[str, Any],
        semantic_balance_data: Dict[str, Any],
        period_index: int,
        participants: List[Dict[str, str]],
        participant_sum: Decimal,
    ) -> Optional[Dict[str, Any]]:
        participant_by_code = {str(item["code"]): item for item in participants}
        hidden_subtotals = [
            subtotal
            for subtotal in [
                self._resolve_long_term_investment_subtotal(
                    balance_data=balance_data,
                    semantic_balance_data=semantic_balance_data,
                    period_index=period_index,
                    participant_by_code=participant_by_code,
                ),
                self._resolve_old_standard_subtotal(
                    total_code="Z01030010",
                    total_name="固定资产合计",
                    component_codes=FIXED_ASSET_TOTAL_COMPONENT_CODES,
                    balance_data=balance_data,
                    semantic_balance_data=semantic_balance_data,
                    period_index=period_index,
                    participant_by_code=participant_by_code,
                ),
                self._resolve_old_standard_subtotal(
                    total_code="Z01040000",
                    total_name="无形资产及其他资产合计",
                    component_codes=INTANGIBLE_AND_OTHER_ASSET_COMPONENT_CODES,
                    balance_data=balance_data,
                    semantic_balance_data=semantic_balance_data,
                    period_index=period_index,
                    participant_by_code=participant_by_code,
                ),
            ]
            if subtotal is not None
        ]
        if not hidden_subtotals:
            return None

        covered_codes = {
            code
            for subtotal in hidden_subtotals
            for code in subtotal.get("covered_codes", set())
        }
        candidate_participants = [
            item
            for item in participants
            if item["code"] not in covered_codes
        ]
        candidate_participants.extend(
            {
                "code": subtotal["code"],
                "name": subtotal["name"],
                "value": str(subtotal["value"]),
                "source": subtotal["source"],
            }
            for subtotal in hidden_subtotals
        )
        candidate_total = sum(
            (_to_decimal(item.get("value")) or Decimal("0"))
            for item in candidate_participants
        )
        if abs(candidate_total - participant_sum) <= DECIMAL_TOLERANCE:
            return None

        validated_codes: set[str] = set()
        invalid_components: List[Dict[str, str]] = []
        for item in candidate_participants:
            code = str(item["code"])
            if code in participant_by_code:
                validated_codes.add(code)
        for subtotal in hidden_subtotals:
            for component in subtotal.get("validated_components", []):
                code = str(component.get("code") or "").strip()
                if code:
                    validated_codes.add(code)
            for component in subtotal.get("invalid_components", []):
                if isinstance(component, dict):
                    invalid_components.append(component)

        return {
            "participants": candidate_participants,
            "total": candidate_total,
            "validated_components": self._validated_visible_components_for_codes(
                validated_codes,
                participant_by_code,
            ),
            "invalid_components": invalid_components,
        }

    def _resolve_long_term_investment_subtotal(
        self,
        *,
        balance_data: Dict[str, Any],
        semantic_balance_data: Dict[str, Any],
        period_index: int,
        participant_by_code: Dict[str, Dict[str, str]],
    ) -> Optional[Dict[str, Any]]:
        direct_value = _extract_balance_period_value(
            semantic_balance_data.get("Z01020100"),
            period_index,
        )
        if direct_value is not None:
            covered_codes = {
                code
                for variant in LONG_TERM_INVESTMENT_COMPONENT_VARIANTS
                for code in variant
                if code in participant_by_code
            }
            validated_codes = self._resolve_long_term_investment_replacement_codes(
                balance_data=balance_data,
                semantic_balance_data=semantic_balance_data,
                period_index=period_index,
                aggregate_value=direct_value,
            )
            invalid_components = self._resolve_long_term_investment_mismatch_components(
                balance_data=balance_data,
                period_index=period_index,
                aggregate_value=direct_value,
                participant_by_code=participant_by_code,
            )
            return {
                "code": "Z01020100",
                "name": "长期投资",
                "value": direct_value,
                "source": "semantic",
                "covered_codes": covered_codes,
                "validated_components": self._validated_visible_components_for_codes(
                    validated_codes,
                    participant_by_code,
                ),
                "invalid_components": invalid_components,
            }

        for variant in LONG_TERM_INVESTMENT_COMPONENT_VARIANTS:
            component_items = []
            for code in variant:
                resolved = self._resolve_old_standard_component_value(
                    code=code,
                    name=code,
                    balance_data=balance_data,
                    semantic_balance_data=semantic_balance_data,
                    period_index=period_index,
                    participant_by_code=participant_by_code,
                )
                if resolved is not None:
                    component_items.append(resolved)
            if not component_items:
                continue
            value = sum(item["value"] for item in component_items)
            covered_codes = {
                item["code"]
                for item in component_items
                if item["code"] in participant_by_code
            }
            return {
                "code": "Z01020100",
                "name": "长期投资",
                "value": value,
                "source": "derived",
                "covered_codes": covered_codes,
                "validated_components": self._validated_visible_components_for_codes(
                    covered_codes,
                    participant_by_code,
                ),
            }
        return None

    def _resolve_old_standard_subtotal(
        self,
        *,
        total_code: str,
        total_name: str,
        component_codes: List[tuple[str, str]],
        balance_data: Dict[str, Any],
        semantic_balance_data: Dict[str, Any],
        period_index: int,
        participant_by_code: Dict[str, Dict[str, str]],
    ) -> Optional[Dict[str, Any]]:
        component_items = []
        for code, name in component_codes:
            item = self._resolve_old_standard_component_value(
                code=code,
                name=name,
                balance_data=balance_data,
                semantic_balance_data=semantic_balance_data,
                period_index=period_index,
                participant_by_code=participant_by_code,
            )
            if item is not None:
                component_items.append(item)
        covered_codes = {
            item["code"]
            for item in component_items
            if item["code"] in participant_by_code
        }

        direct_value = _extract_balance_period_value(
            semantic_balance_data.get(total_code),
            period_index,
        )
        if direct_value is not None:
            visible_sum = sum(
                item["value"]
                for item in component_items
                if item["code"] in participant_by_code
            )
            validated_components = []
            if covered_codes and abs(visible_sum - direct_value) <= DECIMAL_TOLERANCE:
                validated_components = self._validated_visible_components_for_codes(
                    covered_codes,
                    participant_by_code,
                )
            return {
                "code": total_code,
                "name": total_name,
                "value": direct_value,
                "source": "semantic",
                "covered_codes": covered_codes,
                "validated_components": validated_components,
            }

        if not component_items:
            return None

        return {
            "code": total_code,
            "name": total_name,
            "value": sum(item["value"] for item in component_items),
            "source": "derived",
            "covered_codes": covered_codes,
            "validated_components": self._validated_visible_components_for_codes(
                covered_codes,
                participant_by_code,
            ),
        }

    def _resolve_old_standard_component_value(
        self,
        *,
        code: str,
        name: str,
        balance_data: Dict[str, Any],
        semantic_balance_data: Dict[str, Any],
        period_index: int,
        participant_by_code: Dict[str, Dict[str, str]],
    ) -> Optional[Dict[str, Any]]:
        participant = participant_by_code.get(code)
        if participant is not None:
            value = _to_decimal(participant.get("value"))
            if value is not None:
                return {
                    "code": code,
                    "name": str(participant.get("name") or name),
                    "value": value,
                    "source": str(participant.get("source") or "view"),
                }

        value = _extract_balance_period_value(balance_data.get(code), period_index)
        source = "view"
        if value is None and code == "Z01030000":
            inferred = self._infer_semantic_balance_component_value(
                view_code=code,
                semantic_balance_data=semantic_balance_data,
                period_index=period_index,
            )
            value = _to_decimal(inferred.get("value")) if inferred else None
            source = "semantic_formula"
        if value is None:
            value = _extract_balance_period_value(
                semantic_balance_data.get(code),
                period_index,
            )
            source = "semantic"
        if value is None:
            return None
        return {
            "code": code,
            "name": name,
            "value": value,
            "source": source,
        }

    @staticmethod
    def _validated_visible_components_for_codes(
        codes: set[str],
        participant_by_code: Dict[str, Dict[str, str]],
    ) -> List[Dict[str, str]]:
        return [
            {
                "code": code,
                "name": str(participant.get("name") or code),
            }
            for code, participant in participant_by_code.items()
            if code in codes
        ]

    def _resolve_long_term_investment_replacement_codes(
        self,
        *,
        balance_data: Dict[str, Any],
        semantic_balance_data: Dict[str, Any],
        period_index: int,
        aggregate_value: Decimal,
    ) -> set[str]:
        for variant in LONG_TERM_INVESTMENT_COMPONENT_VARIANTS:
            basis_sum = Decimal("0")
            has_value = False
            for code in variant:
                value = _extract_balance_period_value(balance_data.get(code), period_index)
                if value is None:
                    value = _extract_balance_period_value(
                        semantic_balance_data.get(code),
                        period_index,
                    )
                if value is None:
                    continue
                basis_sum += value
                has_value = True
            if not has_value or abs(aggregate_value - basis_sum) > DECIMAL_TOLERANCE:
                continue
            return {
                code
                for code in variant
                if _extract_balance_period_value(balance_data.get(code), period_index) is not None
            }
        return set()

    def _resolve_long_term_investment_mismatch_components(
        self,
        *,
        balance_data: Dict[str, Any],
        period_index: int,
        aggregate_value: Decimal,
        participant_by_code: Dict[str, Dict[str, str]],
    ) -> List[Dict[str, str]]:
        selected_variant: tuple[str, ...] = ()
        selected_presence = -1
        for variant in LONG_TERM_INVESTMENT_COMPONENT_VARIANTS:
            presence = sum(1 for code in variant if code in balance_data)
            if presence > selected_presence:
                selected_variant = variant
                selected_presence = presence

        if not selected_variant or selected_presence <= 0:
            return []

        component_sum = Decimal("0")
        for code in selected_variant:
            value = _extract_balance_period_value(balance_data.get(code), period_index)
            if value is not None:
                component_sum += value

        if abs(component_sum - aggregate_value) <= DECIMAL_TOLERANCE:
            return []

        return [
            {
                "code": code,
                "name": str(
                    participant_by_code.get(code, {}).get("name")
                    or LONG_TERM_INVESTMENT_COMPONENT_NAMES.get(code)
                    or code
                ),
                "aggregate_code": "Z01020100",
                "aggregate_name": "长期投资",
                "aggregate_value": str(aggregate_value),
                "component_sum": str(component_sum),
            }
            for code in selected_variant
            if code in balance_data
        ]

    @staticmethod
    def _join_component_names(components: List[Dict[str, Any]]) -> str:
        return "、".join(str(item.get("name") or "").strip() for item in components if str(item.get("name") or "").strip())

    def _try_missing_non_current_assets_attribution(
        self,
        *,
        balance_data: Dict[str, Any],
        semantic_balance_data: Dict[str, Any],
        rule: Dict[str, Any],
        period_index: int,
        participants: List[Dict[str, str]],
        participant_sum: Decimal,
    ) -> Optional[Dict[str, Any]]:
        if not semantic_balance_data or str(rule.get("total_code")) != "ZY2015058":
            return None

        repaired_candidates = []
        for participant in participants:
            inferred = self._infer_semantic_balance_component_value(
                view_code=str(participant["code"]),
                semantic_balance_data=semantic_balance_data,
                period_index=period_index,
            )
            if inferred is None:
                continue

            reported_value = _to_decimal(participant.get("value"))
            inferred_value = _to_decimal(inferred.get("value"))
            if reported_value is None or inferred_value is None:
                continue
            if abs(reported_value - inferred_value) <= DECIMAL_TOLERANCE:
                continue

            candidate_sum = participant_sum - reported_value + inferred_value
            repaired_candidates.append(
                {
                    "code": str(participant["code"]),
                    "name": str(participant["name"]),
                    "inferred_value": str(inferred_value),
                    "candidate_sum": str(candidate_sum),
                    "trace": inferred.get("trace", {}),
                }
            )

        if len(repaired_candidates) != 1:
            return None

        culprit = repaired_candidates[0]
        inferred_total = _to_decimal(culprit["candidate_sum"])
        if inferred_total is None:
            return None

        asset_total = _extract_balance_period_value(balance_data.get("Z01000001"), period_index)
        current_assets_total = _extract_balance_period_value(balance_data.get("Z01010001"), period_index)
        grandparent_supported = None
        if asset_total is not None and current_assets_total is not None:
            grandparent_supported = abs(asset_total - (current_assets_total + inferred_total)) <= DECIMAL_TOLERANCE
        if grandparent_supported is not True:
            return None

        return {
            "result": "fail",
            "reason": "合计项缺失，但使用子项推导值可通过上层校验",
            "suspects": [
                {
                    "code": str(rule["total_code"]),
                    "name": str(rule["name"]),
                    "source": "missing_total",
                },
                {
                    "code": culprit["code"],
                    "name": culprit["name"],
                    "source": "semantic_inference",
                },
            ],
            "expected": culprit["candidate_sum"],
            "_inferred_total": culprit["candidate_sum"],
            "semantic_attribution": {
                "culprit_code": culprit["code"],
                "culprit_name": culprit["name"],
                "mode": "semantic_component_inference_with_missing_parent",
                "inferred_value": culprit["inferred_value"],
                "candidate_sum": culprit["candidate_sum"],
                "missing_total_code": str(rule["total_code"]),
                "missing_total_name": str(rule["name"]),
                "trace": culprit["trace"],
                "validation_chain": {
                    "supports_parent_check": None,
                    "parent_check": {
                        "rule": f"{rule['name']} = 子项求和",
                        "total_code": str(rule["total_code"]),
                        "reported_total": None,
                        "recomputed_total_after_repair": culprit["candidate_sum"],
                        "passed_after_repair": None,
                    },
                    "supports_grandparent_check": grandparent_supported,
                    "grandparent_check": {
                        "rule": "资产总计 = 流动资产合计 + 非流动资产合计",
                        "reported_total": _decimal_to_string(asset_total),
                        "recomputed_total_after_repair": (
                            str(current_assets_total + inferred_total)
                            if asset_total is not None and current_assets_total is not None
                            else None
                        ),
                        "passed_after_repair": grandparent_supported,
                    },
                },
            },
        }

    def _try_semantic_balance_component_attribution(
        self,
        *,
        balance_data: Dict[str, Any],
        semantic_balance_data: Dict[str, Any],
        rule: Dict[str, Any],
        period_index: int,
        total_value: Decimal,
        participant_sum: Decimal,
        participants: List[Dict[str, str]],
    ) -> Optional[Dict[str, Any]]:
        if not semantic_balance_data or str(rule.get("total_code")) != "ZY2015058":
            return None

        repaired_candidates = []
        for participant in participants:
            inferred = self._infer_semantic_balance_component_value(
                view_code=str(participant["code"]),
                semantic_balance_data=semantic_balance_data,
                period_index=period_index,
            )
            if inferred is None:
                continue

            reported_value = _to_decimal(participant.get("value"))
            inferred_value = _to_decimal(inferred.get("value"))
            if reported_value is None or inferred_value is None:
                continue
            if abs(reported_value - inferred_value) <= DECIMAL_TOLERANCE:
                continue

            candidate_sum = participant_sum - reported_value + inferred_value
            if abs(total_value - candidate_sum) > DECIMAL_TOLERANCE:
                continue

            repaired_candidates.append(
                {
                    "code": str(participant["code"]),
                    "name": str(participant["name"]),
                    "inferred_value": str(inferred_value),
                    "candidate_sum": str(candidate_sum),
                    "trace": inferred.get("trace", {}),
                }
            )

        if len(repaired_candidates) != 1:
            return None

        culprit = repaired_candidates[0]
        validation_chain = self._build_semantic_validation_chain(
            balance_data=balance_data,
            rule=rule,
            period_index=period_index,
            parent_total=total_value,
            repaired_component=culprit,
        )
        return {
            "reason": f"使用{culprit['name']}内部勾稽推理值后等式成立，疑似{culprit['name']}字段有误",
            "suspects": [
                {
                    "code": culprit["code"],
                    "name": culprit["name"],
                    "source": "semantic_inference",
                }
            ],
            "semantic_attribution": {
                "culprit_code": culprit["code"],
                "culprit_name": culprit["name"],
                "mode": "semantic_component_inference_match",
                "inferred_value": culprit["inferred_value"],
                "candidate_sum": culprit["candidate_sum"],
                "trace": culprit["trace"],
                "validation_chain": validation_chain,
            },
        }

    def _apply_semantic_verified_component_exclusions(
        self,
        *,
        detail: Dict[str, Any],
        semantic_balance_data: Dict[str, Any],
        period_index: int,
        participants: List[Dict[str, str]],
    ) -> None:
        if (
            detail.get("result") != "fail"
            or not semantic_balance_data
            or str(detail.get("_rule_total_code") or "").strip() != "ZY2015058"
        ):
            return

        verified_components = []
        for participant in participants:
            code = str(participant.get("code") or "").strip()
            inferred = self._infer_semantic_balance_component_value(
                view_code=code,
                semantic_balance_data=semantic_balance_data,
                period_index=period_index,
            )
            if inferred is None:
                continue

            reported_value = _to_decimal(participant.get("value"))
            inferred_value = _to_decimal(inferred.get("value"))
            if reported_value is None or inferred_value is None:
                continue
            if abs(reported_value - inferred_value) > DECIMAL_TOLERANCE:
                continue

            verified_components.append(
                {
                    "code": code,
                    "name": str(participant.get("name") or code),
                    "source": "semantic_formula",
                    "inferred_value": str(inferred_value),
                    "trace": inferred.get("trace", {}),
                }
            )

        if not verified_components:
            return

        verified_codes = {
            str(component.get("code") or "").strip()
            for component in verified_components
            if str(component.get("code") or "").strip()
        }
        suspects = detail.get("suspects")
        if isinstance(suspects, list):
            detail["suspects"] = [
                suspect
                for suspect in suspects
                if not (
                    isinstance(suspect, dict)
                    and str(suspect.get("code") or "").strip() in verified_codes
                )
            ]

        existing_verified = detail.get("verified_components")
        if not isinstance(existing_verified, list):
            existing_verified = []
        existing_codes = {
            str(component.get("code") or "").strip()
            for component in existing_verified
            if isinstance(component, dict)
        }
        detail["verified_components"] = [
            *existing_verified,
            *[
                component
                for component in verified_components
                if component["code"] not in existing_codes
            ],
        ]

    def _build_semantic_validation_chain(
        self,
        *,
        balance_data: Dict[str, Any],
        rule: Dict[str, Any],
        period_index: int,
        parent_total: Decimal,
        repaired_component: Dict[str, Any],
    ) -> Dict[str, Any]:
        parent_supported = abs(parent_total - _to_decimal(repaired_component["candidate_sum"])) <= DECIMAL_TOLERANCE
        chain: Dict[str, Any] = {
            "supports_parent_check": parent_supported,
            "parent_check": {
                "rule": f"{rule['name']} = 子项求和",
                "total_code": str(rule["total_code"]),
                "reported_total": str(parent_total),
                "recomputed_total_after_repair": repaired_component["candidate_sum"],
                "passed_after_repair": parent_supported,
            },
        }

        if str(rule.get("total_code")) != "ZY2015058":
            return chain

        asset_total = _extract_balance_period_value(balance_data.get("Z01000001"), period_index)
        current_assets_total = _extract_balance_period_value(balance_data.get("Z01010001"), period_index)
        repaired_non_current_assets = _to_decimal(repaired_component["candidate_sum"])
        if (
            asset_total is None
            or current_assets_total is None
            or repaired_non_current_assets is None
        ):
            chain["supports_grandparent_check"] = None
            chain["grandparent_check"] = {
                "rule": "资产总计 = 流动资产合计 + 非流动资产合计",
                "passed_after_repair": None,
            }
            return chain

        grandparent_expected = current_assets_total + repaired_non_current_assets
        grandparent_supported = abs(asset_total - grandparent_expected) <= DECIMAL_TOLERANCE
        chain["supports_grandparent_check"] = grandparent_supported
        chain["grandparent_check"] = {
            "rule": "资产总计 = 流动资产合计 + 非流动资产合计",
            "reported_total": str(asset_total),
            "recomputed_total_after_repair": str(grandparent_expected),
            "passed_after_repair": grandparent_supported,
        }
        return chain

    def _infer_semantic_balance_component_value(
        self,
        *,
        view_code: str,
        semantic_balance_data: Dict[str, Any],
        period_index: int,
    ) -> Optional[Dict[str, Any]]:
        if view_code != "Z01030000":
            return None

        original_cost = _extract_balance_period_value(semantic_balance_data.get("Z01030001"), period_index)
        accumulated_depreciation = _extract_balance_period_value(semantic_balance_data.get("Z01030002"), period_index)
        net_value = _extract_balance_period_value(semantic_balance_data.get("Z01030003"), period_index)
        impairment = _extract_balance_period_value(semantic_balance_data.get("Z01030004"), period_index)
        net_amount = _extract_balance_period_value(semantic_balance_data.get("Z01030005"), period_index)

        computed_net_value = None
        if original_cost is not None and accumulated_depreciation is not None:
            computed_net_value = original_cost - accumulated_depreciation

        resolved_net_value = net_value if net_value is not None else computed_net_value
        if resolved_net_value is None:
            return None

        effective_impairment = impairment if impairment is not None else Decimal("0")
        inferred_net_amount = resolved_net_value - effective_impairment

        return {
            "value": str(inferred_net_amount),
            "trace": {
                "formula": "固定资产净额 = 固定资产净值 - 固定资产减值准备; 固定资产净值 = 固定资产原价 - 累计折旧",
                "original_cost": _decimal_to_string(original_cost),
                "accumulated_depreciation": _decimal_to_string(accumulated_depreciation),
                "reported_net_value": _decimal_to_string(net_value),
                "reported_impairment": _decimal_to_string(impairment),
                "reported_net_amount": _decimal_to_string(net_amount),
                "computed_net_value": _decimal_to_string(computed_net_value),
                "inferred_value": str(inferred_net_amount),
            },
        }

    def _inspect_cashflow_rule(
        self,
        *,
        cashflow_data: Dict[str, Any],
        rule: Dict[str, Any],
        inferred_cashflow_values: Optional[Dict[str, Decimal]] = None,
    ) -> Dict[str, Any]:
        check_name = str(rule["name"])
        total_code = str(rule["total_code"])
        total_name = str(rule.get("total_name") or rule["name"])
        total_value, total_state = _extract_current_period_value_with_state(
            cashflow_data.get(total_code)
        )
        if total_value is None and total_state == "empty":
            total_value = Decimal("0")
        inferred_cashflow_values = inferred_cashflow_values or {}

        participants = []
        participant_sum = Decimal("0")
        for component in rule["components"]:
            if len(component) == 3:
                sign, code, name = component
            else:
                sign = "+"
                code, name = component
            value, value_state = _extract_current_period_value_with_state(
                cashflow_data.get(code)
            )
            source = "view"
            if value is None and value_state == "empty":
                value = Decimal("0")
                source = "empty"
            elif value is None and code in inferred_cashflow_values:
                value = inferred_cashflow_values[code]
                source = "inferred"
            if value is None:
                continue
            participants.append(
                {
                    "sign": sign,
                    "code": code,
                    "name": name,
                    "value": str(value),
                    "source": source,
                }
            )
            participant_sum += value if sign == "+" else -value

        detail = {
            "_table": "cashflow",
            "check": check_name,
            "_rule_total_code": total_code,
            "components": {
                item["code"]: {
                    "name": item["name"],
                    "sign": item["sign"],
                    "value": item["value"],
                    **({"source": item["source"]} if item.get("source") != "view" else {}),
                }
                for item in participants
            },
            "_participating_component_count": len(participants),
        }

        if total_value is None:
            if participants:
                detail["result"] = "fail"
                detail["reason"] = "合计项缺失，但可由已提取子项推导"
                detail["expected"] = str(participant_sum)
                detail["_inferred_total"] = str(participant_sum)
                detail["suspects"] = [
                    {
                        "code": total_code,
                        "name": total_name,
                        "source": "missing_total_inferred_from_components",
                    }
                ]
                detail["attribution"] = {
                    "mode": "missing_total_inferred_from_components",
                    "culprit_code": total_code,
                    "culprit_name": total_name,
                    "candidate_sum": str(participant_sum),
                }
                return detail
            detail["result"] = "fail"
            detail["reason"] = "view中缺少合计项，无法校验"
            detail["suspects"] = [
                {
                    "code": total_code,
                    "name": total_name,
                    "source": "missing_total",
                }
            ]
            return detail

        if not participants:
            detail["result"] = "skip"
            detail["reason"] = "view中缺少足够组成项，无法校验"
            detail["suspects"] = []
            return detail

        detail["total"] = {
            "code": total_code,
            "name": total_name,
            "value": str(total_value),
        }
        detail["expected"] = str(participant_sum)
        detail["amounts"] = {
            "reported_total": str(total_value),
            "recomputed_total": str(participant_sum),
        }

        if abs(total_value - participant_sum) <= DECIMAL_TOLERANCE:
            detail["result"] = "pass"
            detail["reason"] = "校验通过"
            detail["suspects"] = []
            return detail

        detail["result"] = "fail"
        detail["reason"] = "校验未通过"
        detail["suspects"] = [
            {
                "code": total_code,
                "name": total_name,
                "source": "view_participant",
            },
            *[
                {
                    "code": item["code"],
                    "name": item["name"],
                    "source": "view_participant",
                }
                for item in participants
            ],
        ]
        return detail

    @staticmethod
    def _cashflow_rule_applies(
        cashflow_data: Dict[str, Any],
        rule: Dict[str, Any],
    ) -> bool:
        if not rule.get("applies_if_total_present"):
            return True

        total_value, total_state = _extract_current_period_value_with_state(
            cashflow_data.get(str(rule["total_code"]))
        )
        return total_value is not None or total_state == "empty"

    def _apply_cashflow_zero_residual_inferences(
        self,
        cashflow_data: Dict[str, Any],
        cashflow_details: List[Dict[str, Any]],
    ) -> None:
        details_by_total_code: Dict[str, Dict[str, Any]] = {}
        values: Dict[str, Decimal] = {}

        for code, raw_value in cashflow_data.items():
            code = str(code)
            value, state = _extract_current_period_value_with_state(raw_value)
            if value is None and state == "empty":
                value = Decimal("0")
            if value is not None:
                values[code] = value

        for detail in cashflow_details:
            total_code = str(detail.get("_rule_total_code") or "").strip()
            if total_code:
                details_by_total_code[total_code] = detail

            total = detail.get("total")
            total_value = None
            if isinstance(total, dict):
                total_value = _to_decimal(total.get("value"))
            if total_value is None:
                total_value = _to_decimal(detail.get("_inferred_total"))
            if total_code and total_value is not None:
                values.setdefault(total_code, total_value)

        changed = True
        while changed:
            changed = False
            for rule in CASHFLOW_BASIC_RULES:
                total_code = str(rule.get("total_code") or "").strip()
                total_value = values.get(total_code)
                if not total_code or total_value is None:
                    continue

                known_sum = Decimal("0")
                missing_components: List[Dict[str, str]] = []
                for sign, code, name in _iter_signed_components(rule.get("components", [])):
                    value = values.get(code)
                    if value is None:
                        missing_components.append(
                            {
                                "sign": sign,
                                "code": code,
                                "name": name,
                            }
                        )
                        continue
                    known_sum += value if sign == "+" else -value

                if abs(total_value - known_sum) > DECIMAL_TOLERANCE:
                    continue

                parent_name = str(rule.get("total_name") or rule.get("name") or total_code)
                for _sign, code, name in _iter_signed_components(rule.get("components", [])):
                    value = values.get(code)
                    if value is None or abs(value) > DECIMAL_TOLERANCE:
                        continue

                    child_detail = details_by_total_code.get(code)
                    if child_detail is None:
                        continue
                    if str(child_detail.get("result") or "").strip() != "skip":
                        continue
                    if int(child_detail.get("_participating_component_count") or 0) > 0:
                        continue

                    self._mark_cashflow_zero_detail_as_supported(
                        detail=child_detail,
                        code=code,
                        name=name,
                        parent_code=total_code,
                        parent_name=parent_name,
                    )

                if not missing_components:
                    continue

                for component in missing_components:
                    code = component["code"]
                    if code in values:
                        continue
                    values[code] = Decimal("0")
                    changed = True
                    child_detail = details_by_total_code.get(code)
                    if child_detail is not None:
                        self._mark_cashflow_detail_as_inferred_zero(
                            detail=child_detail,
                            inferred_code=code,
                            inferred_name=component["name"],
                            parent_code=total_code,
                            parent_name=parent_name,
                        )

    @staticmethod
    def _mark_cashflow_detail_as_inferred_zero(
        *,
        detail: Dict[str, Any],
        inferred_code: str,
        inferred_name: str,
        parent_code: str,
        parent_name: str,
    ) -> None:
        detail["result"] = "pass"
        detail["reason"] = f"已由{parent_name}交叉校验推定为0"
        detail["total"] = {
            "code": inferred_code,
            "name": inferred_name,
            "value": "0",
        }
        detail["expected"] = detail.get("expected") or "0"
        detail["_inferred_total"] = "0"
        detail["amounts"] = {
            "reported_total": "0",
            "recomputed_total": str(detail.get("expected") or "0"),
        }
        detail["suspects"] = []
        detail["attribution"] = {
            "mode": "cashflow_zero_residual_inferred",
            "culprit_code": inferred_code,
            "culprit_name": inferred_name,
            "candidate_sum": "0",
            "supporting_code": parent_code,
            "supporting_name": parent_name,
        }

    @staticmethod
    def _mark_cashflow_zero_detail_as_supported(
        *,
        detail: Dict[str, Any],
        code: str,
        name: str,
        parent_code: str,
        parent_name: str,
    ) -> None:
        detail["result"] = "pass"
        detail["reason"] = f"小计为0，已由{parent_name}交叉校验确认"
        detail["total"] = {
            "code": code,
            "name": name,
            "value": "0",
        }
        detail["expected"] = "0"
        detail["amounts"] = {
            "reported_total": "0",
            "recomputed_total": "0",
        }
        detail["suspects"] = []
        detail["attribution"] = {
            "mode": "cashflow_reported_zero_supported_by_parent",
            "culprit_code": code,
            "culprit_name": name,
            "candidate_sum": "0",
            "supporting_code": parent_code,
            "supporting_name": parent_name,
        }

    def _attach_cashflow_subtotal_confirmations(
        self,
        cashflow_details: List[Dict[str, Any]],
    ) -> None:
        details_by_total_code: Dict[str, Dict[str, Any]] = {}
        for detail in cashflow_details:
            total = detail.get("total")
            total_code = ""
            if isinstance(total, dict):
                total_code = str(total.get("code") or "").strip()
            if not total_code:
                total_code = str(detail.get("_rule_total_code") or "").strip()
            if total_code:
                details_by_total_code[total_code] = detail

        for detail in cashflow_details:
            if str(detail.get("result") or "").strip() != "fail":
                continue

            total = detail.get("total")
            if not isinstance(total, dict):
                continue

            subtotal_code = str(total.get("code") or "").strip()
            subtotal_name = str(total.get("name") or detail.get("check") or "").strip()
            subtotal_value = _to_decimal(total.get("value"))
            component_sum = _to_decimal(detail.get("expected"))
            if not subtotal_code or subtotal_value is None or component_sum is None:
                continue

            net_rule = self._cashflow_net_rule_containing_subtotal(subtotal_code)
            if net_rule is None:
                continue

            net_code = str(net_rule["total_code"])
            net_name = str(net_rule.get("total_name") or net_rule["name"])
            net_detail = details_by_total_code.get(net_code)
            if not isinstance(net_detail, dict):
                continue

            net_components = net_detail.get("components")
            if not isinstance(net_components, dict):
                continue
            net_subtotal_component = net_components.get(subtotal_code)
            if not isinstance(net_subtotal_component, dict):
                continue
            net_total = net_detail.get("total")
            net_total_value = (
                _to_decimal(net_total.get("value"))
                if isinstance(net_total, dict)
                else None
            )
            if net_total_value is None:
                continue

            component_suspects = self._cashflow_component_suspects_for_total(subtotal_code)
            if not component_suspects:
                continue

            component_diff = subtotal_value - component_sum
            net_subtotal_value = _to_decimal(net_subtotal_component.get("value"))
            if (
                str(net_detail.get("result") or "").strip() == "pass"
                and str(net_subtotal_component.get("source") or "view").strip() == "view"
                and net_subtotal_value is not None
                and abs(net_subtotal_value - subtotal_value) <= DECIMAL_TOLERANCE
            ):
                detail["reason"] = (
                    f"已由{net_name}交叉确认{subtotal_name}正确，"
                    f"差异来自{subtotal_name}子项"
                )
                detail["suspects"] = component_suspects
                detail["semantic_attribution"] = {
                    "mode": "cashflow_subtotal_confirmed_by_net_amount",
                    "subtotal_code": subtotal_code,
                    "subtotal_name": subtotal_name,
                    "subtotal_value": str(subtotal_value),
                    "component_sum": str(component_sum),
                    "component_diff": str(abs(component_diff)),
                    "confirmation_code": net_code,
                    "confirmation_name": net_name,
                    "confirmation_value": str(net_total_value),
                    "component_suspects": component_suspects,
                }
                continue

            inferred_net_value = self._cashflow_net_value_with_subtotal_replacement(
                net_rule=net_rule,
                net_detail=net_detail,
                subtotal_code=subtotal_code,
                replacement_value=component_sum,
            )
            if (
                inferred_net_value is None
                or abs(inferred_net_value - net_total_value) > DECIMAL_TOLERANCE
            ):
                continue

            detail["reason"] = (
                f"按子项和推测{subtotal_name}为{component_sum}，"
                f"且{net_name}交叉校验通过，疑似{subtotal_name}字段识别错误"
            )
            detail["suspects"] = [
                {
                    "code": subtotal_code,
                    "name": subtotal_name,
                    "source": "self_total",
                }
            ]
            inferred_attribution = {
                "mode": "cashflow_subtotal_inferred_by_net_amount",
                "culprit_code": subtotal_code,
                "culprit_name": subtotal_name,
                "inferred_value": str(component_sum),
                "reported_value": str(subtotal_value),
                "component_diff": str(abs(component_diff)),
                "confirmation_code": net_code,
                "confirmation_name": net_name,
                "confirmation_value": str(net_total_value),
            }
            detail["attribution"] = inferred_attribution
            detail["semantic_attribution"] = inferred_attribution
            net_subtotal_component["value"] = str(component_sum)
            net_subtotal_component["source"] = "inferred"
            net_detail["result"] = "pass"
            net_detail["reason"] = f"使用推测的{subtotal_name}值后，{net_name}校验通过"
            net_detail["expected"] = str(inferred_net_value)
            amounts = net_detail.get("amounts")
            if not isinstance(amounts, dict):
                amounts = {}
                net_detail["amounts"] = amounts
            amounts["recomputed_total"] = str(inferred_net_value)

    @staticmethod
    def _cashflow_net_rule_containing_subtotal(
        subtotal_code: str,
    ) -> Optional[Dict[str, Any]]:
        for rule in CASHFLOW_BASIC_RULES:
            for component in rule.get("components", []):
                if len(component) != 3:
                    continue
                _sign, component_code, _name = component
                if str(component_code) == subtotal_code:
                    return rule
        return None

    @staticmethod
    def _cashflow_net_value_with_subtotal_replacement(
        *,
        net_rule: Dict[str, Any],
        net_detail: Dict[str, Any],
        subtotal_code: str,
        replacement_value: Decimal,
    ) -> Optional[Decimal]:
        components = net_detail.get("components")
        if not isinstance(components, dict):
            return None

        total = Decimal("0")
        for component in net_rule.get("components", []):
            if len(component) != 3:
                continue
            sign, code, _name = component
            code = str(code)
            if code == subtotal_code:
                value = replacement_value
            else:
                component_detail = components.get(code)
                if not isinstance(component_detail, dict):
                    return None
                value = _to_decimal(component_detail.get("value"))
                if value is None:
                    return None
            total += value if sign == "+" else -value
        return total

    @staticmethod
    def _cashflow_component_suspects_for_total(
        total_code: str,
    ) -> List[Dict[str, str]]:
        for rule in CASHFLOW_BASIC_RULES:
            if str(rule.get("total_code") or "") != total_code:
                continue
            suspects: List[Dict[str, str]] = []
            for component in rule.get("components", []):
                if len(component) == 3:
                    _sign, code, name = component
                else:
                    code, name = component
                suspects.append(
                    {
                        "code": str(code),
                        "name": str(name),
                        "source": "confirmed_subtotal_component",
                    }
                )
            return suspects
        return []

    def _inspect_profit_rule(
        self,
        *,
        profit_data: Dict[str, Any],
        semantic_profit_data: Dict[str, Any],
        rule: Dict[str, Any],
        inferred_profit_values: Optional[Dict[str, Decimal]] = None,
    ) -> Dict[str, Any]:
        check_name = str(rule["name"])
        total_code = str(rule["total_code"])
        total_name = _resolve_profit_total_name(total_code)
        total_value = _extract_current_period_value(profit_data.get(total_code))
        inferred_profit_values = inferred_profit_values or {}

        participants = []
        participant_sum = Decimal("0")
        for sign, code, name in rule["components"]:
            value = _extract_current_period_value(profit_data.get(code))
            source = "view"
            if value is None and code in inferred_profit_values:
                value = inferred_profit_values[code]
                source = "inferred"
            if value is None:
                continue
            participants.append(
                {
                    "sign": sign,
                    "code": code,
                    "name": name,
                    "value": str(value),
                    "source": source,
                }
            )
            participant_sum += value if sign == "+" else -value

        detail = {
            "_table": "profit",
            "check": check_name,
            "components": {
                item["code"]: {
                    "name": item["name"],
                    "sign": item["sign"],
                    "value": item["value"],
                    **({"source": item["source"]} if item.get("source") != "view" else {}),
                }
                for item in participants
            },
            "_participating_component_count": len(participants),
        }

        if total_value is None:
            if participants:
                detail["result"] = "fail"
                detail["reason"] = "合计项缺失，但可由已提取子项推导"
                detail["expected"] = str(participant_sum)
                detail["_inferred_total"] = str(participant_sum)
                detail["suspects"] = [
                    {
                        "code": total_code,
                        "name": total_name,
                        "source": "missing_total_inferred_from_components",
                    }
                ]
                detail["attribution"] = {
                    "mode": "missing_total_inferred_from_components",
                    "culprit_code": total_code,
                    "culprit_name": total_name,
                    "candidate_sum": str(participant_sum),
                }
                semantic_detail = self._try_semantic_profit_validation(
                    base_detail=detail,
                    semantic_profit_data=semantic_profit_data,
                    total_code=total_code,
                    total_name=total_name,
                    total_value=total_value,
                    inferred_profit_values=inferred_profit_values,
                )
                if semantic_detail is not None:
                    return semantic_detail
                return detail

            detail["result"] = "fail"
            detail["reason"] = "view中缺少合计项，无法校验"
            detail["suspects"] = [
                {
                    "code": total_code,
                    "name": total_name,
                    "source": "missing_total",
                }
            ]
            semantic_detail = self._try_semantic_profit_validation(
                base_detail=detail,
                semantic_profit_data=semantic_profit_data,
                total_code=total_code,
                total_name=total_name,
                total_value=total_value,
                inferred_profit_values=inferred_profit_values,
            )
            if semantic_detail is not None:
                return semantic_detail
            return detail

        if not participants:
            detail["result"] = "skip"
            detail["reason"] = "view中缺少足够组成项，无法校验"
            detail["suspects"] = []
            semantic_detail = self._try_semantic_profit_validation(
                base_detail=detail,
                semantic_profit_data=semantic_profit_data,
                total_code=total_code,
                total_name=total_name,
                total_value=total_value,
                inferred_profit_values=inferred_profit_values,
            )
            if semantic_detail is not None:
                return semantic_detail
            return detail

        detail["total"] = {
            "code": total_code,
            "name": total_name,
            "value": str(total_value),
        }
        detail["expected"] = str(participant_sum)
        detail["amounts"] = {
            "reported_total": str(total_value),
            "recomputed_total": str(participant_sum),
        }

        if abs(total_value - participant_sum) <= DECIMAL_TOLERANCE:
            detail["result"] = "pass"
            detail["reason"] = "校验通过"
            detail["suspects"] = []
            return detail

        detail["result"] = "fail"
        detail["reason"] = "校验未通过"
        detail["suspects"] = [
            {
                "code": total_code,
                "name": total_name,
                "source": "view_participant",
            },
            *[
                {
                    "code": item["code"],
                    "name": item["name"],
                    "source": "view_participant",
                }
                for item in participants
            ],
        ]
        attribution_detail = self._try_profit_cross_validation_attribution(
            base_detail=detail,
            profit_data=profit_data,
            semantic_profit_data=semantic_profit_data,
            rule=rule,
            total_code=total_code,
            total_name=total_name,
            total_value=total_value,
            participant_sum=participant_sum,
            participants=participants,
        )
        if attribution_detail is not None:
            return attribution_detail

        self._attach_profit_single_field_repair_candidates(
            detail=detail,
            total_code=total_code,
            total_name=total_name,
            total_value=total_value,
            participant_sum=participant_sum,
            participants=participants,
        )
        semantic_detail = self._try_semantic_profit_validation(
            base_detail=detail,
            semantic_profit_data=semantic_profit_data,
            total_code=total_code,
            total_name=total_name,
            total_value=total_value,
            inferred_profit_values=inferred_profit_values,
        )
        if semantic_detail is not None:
            return semantic_detail
        return detail

    def _try_profit_cross_validation_attribution(
        self,
        *,
        base_detail: Dict[str, Any],
        profit_data: Dict[str, Any],
        semantic_profit_data: Dict[str, Any],
        rule: Dict[str, Any],
        total_code: str,
        total_name: str,
        total_value: Decimal,
        participant_sum: Decimal,
        participants: List[Dict[str, str]],
    ) -> Optional[Dict[str, Any]]:
        semantic_attribution = self._try_semantic_profit_single_field_attribution(
            base_detail=base_detail,
            semantic_profit_data=semantic_profit_data,
            total_code=total_code,
            total_name=total_name,
            total_value=total_value,
            participant_sum=participant_sum,
            participants=participants,
        )
        if semantic_attribution is not None:
            return semantic_attribution

        subtotal_attribution = self._try_operating_cost_subtotal_attribution(
            base_detail=base_detail,
            profit_data=profit_data,
            semantic_profit_data=semantic_profit_data,
            rule=rule,
            total_code=total_code,
            total_value=total_value,
            participant_sum=participant_sum,
            participants=participants,
        )
        if subtotal_attribution is not None:
            return subtotal_attribution

        return None

    def _try_semantic_profit_single_field_attribution(
        self,
        *,
        base_detail: Dict[str, Any],
        semantic_profit_data: Dict[str, Any],
        total_code: str,
        total_name: str,
        total_value: Decimal,
        participant_sum: Decimal,
        participants: List[Dict[str, str]],
    ) -> Optional[Dict[str, Any]]:
        if not semantic_profit_data:
            return None

        candidates = []
        semantic_total = _extract_current_period_value(semantic_profit_data.get(total_code))
        if (
            semantic_total is not None
            and abs(semantic_total - total_value) > DECIMAL_TOLERANCE
            and abs(semantic_total - participant_sum) <= DECIMAL_TOLERANCE
        ):
            candidates.append(
                {
                    "code": total_code,
                    "name": total_name,
                    "source": "semantic_total",
                    "current_value": str(total_value),
                    "validated_value": str(semantic_total),
                    "candidate_sum": str(participant_sum),
                }
            )

        for participant in participants:
            code = str(participant.get("code") or "")
            current_value = _to_decimal(participant.get("value"))
            semantic_value = _extract_current_period_value(semantic_profit_data.get(code))
            if current_value is None or semantic_value is None:
                continue
            if abs(semantic_value - current_value) <= DECIMAL_TOLERANCE:
                continue

            sign = str(participant.get("sign") or "+")
            factor = Decimal("-1") if sign == "-" else Decimal("1")
            candidate_sum = participant_sum - factor * current_value + factor * semantic_value
            if abs(total_value - candidate_sum) > DECIMAL_TOLERANCE:
                continue

            candidates.append(
                {
                    "code": code,
                    "name": str(participant.get("name") or code),
                    "source": "semantic_component",
                    "current_value": str(current_value),
                    "validated_value": str(semantic_value),
                    "candidate_sum": str(candidate_sum),
                }
            )

        if len(candidates) != 1:
            return None

        culprit = candidates[0]
        detail = dict(base_detail)
        detail["reason"] = f"使用{culprit['name']}的canonical值后等式成立，疑似{culprit['name']}字段有误"
        detail["suspects"] = [
            {
                "code": culprit["code"],
                "name": culprit["name"],
                "source": culprit["source"],
            }
        ]
        detail["semantic_attribution"] = {
            "mode": "semantic_single_field_match",
            "culprit_code": culprit["code"],
            "culprit_name": culprit["name"],
            "current_value": culprit["current_value"],
            "validated_value": culprit["validated_value"],
            "candidate_sum": culprit["candidate_sum"],
            "residual": str(total_value - participant_sum),
        }
        return detail

    def _try_operating_cost_subtotal_attribution(
        self,
        *,
        base_detail: Dict[str, Any],
        profit_data: Dict[str, Any],
        semantic_profit_data: Dict[str, Any],
        rule: Dict[str, Any],
        total_code: str,
        total_value: Decimal,
        participant_sum: Decimal,
        participants: List[Dict[str, str]],
    ) -> Optional[Dict[str, Any]]:
        if total_code != "L04010000" or str(rule.get("name") or "") != "营业利润":
            return None

        operating_cost_total = _extract_current_period_value(
            profit_data.get(OPERATING_COST_TOTAL_CODE)
        )
        operating_cost_source = "view"
        if operating_cost_total is None:
            operating_cost_total = _extract_current_period_value(
                semantic_profit_data.get(OPERATING_COST_TOTAL_CODE)
            )
            operating_cost_source = "semantic"
        if operating_cost_total is None:
            return None

        participant_by_code = {
            str(item.get("code") or ""): item
            for item in participants
        }
        missing_cost_codes = [
            code
            for code, _name in OPERATING_COST_COMPONENTS
            if code not in participant_by_code
        ]
        if missing_cost_codes:
            return None

        operating_cost_sum = Decimal("0")
        for code, _name in OPERATING_COST_COMPONENTS:
            value = _to_decimal(participant_by_code[code].get("value"))
            if value is None:
                return None
            operating_cost_sum += value

        if abs(operating_cost_total - operating_cost_sum) <= DECIMAL_TOLERANCE:
            return None

        non_cost_sum = Decimal("0")
        for participant in participants:
            code = str(participant.get("code") or "")
            if code in OPERATING_COST_COMPONENT_CODES:
                continue
            value = _to_decimal(participant.get("value"))
            if value is None:
                continue
            sign = str(participant.get("sign") or "+")
            non_cost_sum += value if sign == "+" else -value

        subtotal_based_sum = non_cost_sum - operating_cost_total
        if abs(total_value - subtotal_based_sum) > DECIMAL_TOLERANCE:
            return None

        detail = dict(base_detail)
        detail["reason"] = "按营业总成本独立合计复核营业利润通过，差异来自营业总成本明细，无法单点定位"
        detail["suspects"] = [
            {
                "code": code,
                "name": name,
                "source": "supporting_subtotal_component",
            }
            for code, name in OPERATING_COST_COMPONENTS
        ]
        cost_candidates = self._build_profit_component_repair_candidates(
            total_value=operating_cost_total,
            participant_sum=operating_cost_sum,
            participants=[
                {
                    "sign": "+",
                    "code": code,
                    "name": name,
                    "value": str(_to_decimal(participant_by_code[code].get("value"))),
                    "source": str(participant_by_code[code].get("source") or "view"),
                }
                for code, name in OPERATING_COST_COMPONENTS
            ],
        )
        detail["semantic_attribution"] = {
            "mode": "supporting_subtotal_match",
            "subtotal_code": OPERATING_COST_TOTAL_CODE,
            "subtotal_name": OPERATING_COST_TOTAL_NAME,
            "subtotal_source": operating_cost_source,
            "subtotal_value": str(operating_cost_total),
            "component_sum": str(operating_cost_sum),
            "component_diff": str(operating_cost_total - operating_cost_sum),
            "subtotal_based_sum": str(subtotal_based_sum),
            "residual": str(total_value - participant_sum),
            "repair_candidates": cost_candidates,
        }
        self._attach_profit_single_field_repair_candidates(
            detail=detail,
            total_code=total_code,
            total_name=_resolve_profit_total_name(total_code),
            total_value=total_value,
            participant_sum=participant_sum,
            participants=participants,
        )
        return detail

    def _attach_profit_single_field_repair_candidates(
        self,
        *,
        detail: Dict[str, Any],
        total_code: str,
        total_name: str,
        total_value: Decimal,
        participant_sum: Decimal,
        participants: List[Dict[str, str]],
    ) -> None:
        detail["attribution_candidates"] = {
            "mode": "single_field_residual_candidates",
            "reported_total": str(total_value),
            "recomputed_total": str(participant_sum),
            "residual": str(total_value - participant_sum),
            "candidates": [
                {
                    "code": total_code,
                    "name": total_name,
                    "source": "reported_total",
                    "current_value": str(total_value),
                    "corrected_value": str(participant_sum),
                    "required_delta": str(participant_sum - total_value),
                },
                *self._build_profit_component_repair_candidates(
                    total_value=total_value,
                    participant_sum=participant_sum,
                    participants=participants,
                ),
            ],
        }

    @staticmethod
    def _build_profit_component_repair_candidates(
        *,
        total_value: Decimal,
        participant_sum: Decimal,
        participants: List[Dict[str, str]],
    ) -> List[Dict[str, str]]:
        delta_to_target = total_value - participant_sum
        candidates: List[Dict[str, str]] = []
        for participant in participants:
            current_value = _to_decimal(participant.get("value"))
            if current_value is None:
                continue
            sign = str(participant.get("sign") or "+")
            factor = Decimal("-1") if sign == "-" else Decimal("1")
            required_delta = delta_to_target / factor
            candidates.append(
                {
                    "code": str(participant.get("code") or ""),
                    "name": str(participant.get("name") or participant.get("code") or ""),
                    "source": "component",
                    "sign": sign,
                    "current_value": str(current_value),
                    "corrected_value": str(current_value + required_delta),
                    "required_delta": str(required_delta),
                }
            )
        return candidates

    def _try_semantic_profit_validation(
        self,
        *,
        base_detail: Dict[str, Any],
        semantic_profit_data: Dict[str, Any],
        total_code: str,
        total_name: str,
        total_value: Optional[Decimal],
        inferred_profit_values: Dict[str, Decimal],
    ) -> Optional[Dict[str, Any]]:
        if not semantic_profit_data:
            return None

        semantic_rule = PROFIT_SEMANTIC_RULES_BY_TOTAL_CODE.get(total_code)
        if not isinstance(semantic_rule, dict):
            return None

        semantic_candidate = self._select_semantic_profit_variant(
            semantic_profit_data=semantic_profit_data,
            rule=semantic_rule,
            inferred_profit_values=inferred_profit_values,
            target_total_value=total_value,
        )
        if semantic_candidate is None:
            return None

        candidate_total = semantic_candidate["candidate_total"]
        semantic_detail = dict(base_detail)
        semantic_detail["components"] = {
            item["code"]: {
                "name": item["name"],
                "sign": item["sign"],
                "value": item["value"],
                **({"source": item["source"]} if item.get("source") != "view" else {}),
            }
            for item in semantic_candidate["participants"]
        }
        semantic_detail["_participating_component_count"] = len(semantic_candidate["participants"])
        semantic_detail["expected"] = str(candidate_total)
        semantic_detail["semantic_validation"] = {
            "mode": "canonical_formula",
            "total_code": total_code,
            "total_name": total_name,
            "component_codes": [item["code"] for item in semantic_candidate["participants"]],
            "component_names": [item["name"] for item in semantic_candidate["participants"]],
        }

        if total_value is None:
            semantic_detail["result"] = "fail"
            semantic_detail["reason"] = "合计项缺失，但可由canonical语义推导"
            semantic_detail["_inferred_total"] = str(candidate_total)
            semantic_detail["suspects"] = [
                {
                    "code": total_code,
                    "name": total_name,
                    "source": "missing_total_inferred_from_components",
                }
            ]
            semantic_detail["attribution"] = {
                "mode": "missing_total_inferred_from_components",
                "culprit_code": total_code,
                "culprit_name": total_name,
                "candidate_sum": str(candidate_total),
            }
            return semantic_detail

        semantic_detail["total"] = {
            "code": total_code,
            "name": total_name,
            "value": str(total_value),
        }
        semantic_detail["amounts"] = {
            "reported_total": str(total_value),
            "recomputed_total": str(candidate_total),
        }

        if abs(total_value - candidate_total) <= DECIMAL_TOLERANCE:
            semantic_detail["result"] = "pass"
            semantic_detail["reason"] = "已按canonical语义复核通过"
            semantic_detail["suspects"] = []
            semantic_detail.pop("_inferred_total", None)
            semantic_detail.pop("attribution", None)
            return semantic_detail

        semantic_detail["result"] = "fail"
        semantic_detail["reason"] = "校验未通过"
        semantic_detail["_inferred_total"] = str(candidate_total)
        semantic_detail["suspects"] = [
            {
                "code": total_code,
                "name": total_name,
                "source": "view_participant",
            },
            *[
                {
                    "code": item["code"],
                    "name": item["name"],
                    "source": "view_participant",
                }
                for item in semantic_candidate["participants"]
            ],
        ]
        return semantic_detail

    def _select_semantic_profit_variant(
        self,
        *,
        semantic_profit_data: Dict[str, Any],
        rule: Dict[str, Any],
        inferred_profit_values: Dict[str, Decimal],
        target_total_value: Optional[Decimal],
        stack: Optional[set[str]] = None,
        semantic_cache: Optional[Dict[str, Optional[Dict[str, Any]]]] = None,
    ) -> Optional[Dict[str, Any]]:
        variants = rule.get("variants")
        if not isinstance(variants, list) or not variants:
            return None

        if semantic_cache is None:
            semantic_cache = {}
        stack = set(stack or set())
        total_code = str(rule.get("total_code") or "")
        candidates = []

        for components in variants:
            if not isinstance(components, list) or not components:
                continue

            participants = []
            participant_sum = Decimal("0")
            available = True
            for sign, code, name in components:
                resolved = self._resolve_semantic_profit_value(
                    semantic_profit_data=semantic_profit_data,
                    code=str(code),
                    inferred_profit_values=inferred_profit_values,
                    stack=stack | ({total_code} if total_code else set()),
                    semantic_cache=semantic_cache,
                )
                if resolved is None:
                    available = False
                    break

                value = resolved["value"]
                participants.append(
                    {
                        "sign": sign,
                        "code": str(code),
                        "name": name,
                        "value": str(value),
                        "source": resolved["source"],
                    }
                )
                participant_sum += value if sign == "+" else -value

            if not available:
                continue

            matches_target = (
                target_total_value is not None
                and abs(participant_sum - target_total_value) <= DECIMAL_TOLERANCE
            )
            candidates.append(
                {
                    "participants": participants,
                    "candidate_total": participant_sum,
                    "matches_target": matches_target,
                }
            )

        if not candidates:
            return None

        return max(
            candidates,
            key=lambda item: (
                item["matches_target"],
                len(item["participants"]),
            ),
        )

    def _resolve_semantic_profit_value(
        self,
        *,
        semantic_profit_data: Dict[str, Any],
        code: str,
        inferred_profit_values: Dict[str, Decimal],
        stack: set[str],
        semantic_cache: Dict[str, Optional[Dict[str, Any]]],
    ) -> Optional[Dict[str, Any]]:
        direct_value = _extract_current_period_value(semantic_profit_data.get(code))
        if direct_value is not None:
            return {
                "value": direct_value,
                "source": "semantic",
            }

        inferred_value = inferred_profit_values.get(code)
        if inferred_value is not None:
            return {
                "value": inferred_value,
                "source": "inferred",
            }

        if code in semantic_cache:
            return semantic_cache[code]
        if code in stack:
            return None

        semantic_rule = PROFIT_SEMANTIC_RULES_BY_TOTAL_CODE.get(code)
        if not isinstance(semantic_rule, dict):
            semantic_cache[code] = None
            return None

        nested_candidate = self._select_semantic_profit_variant(
            semantic_profit_data=semantic_profit_data,
            rule={
                **semantic_rule,
                "total_code": code,
            },
            inferred_profit_values=inferred_profit_values,
            target_total_value=None,
            stack=stack | {code},
            semantic_cache=semantic_cache,
        )
        if nested_candidate is None:
            semantic_cache[code] = None
            return None

        resolved = {
            "value": nested_candidate["candidate_total"],
            "source": "semantic_formula",
        }
        semantic_cache[code] = resolved
        return resolved


def _iter_signed_components(components: List[Any]):
    for component in components:
        if not isinstance(component, tuple):
            continue
        if len(component) == 3 and component[0] in {"+", "-"}:
            sign, code, name = component
        elif len(component) == 2:
            sign = "+"
            code, name = component
        else:
            continue
        yield str(sign), str(code), str(name)


def _extract_balance_period_value(value: Any, period_index: int) -> Optional[Decimal]:
    if isinstance(value, list):
        if period_index >= len(value):
            return None
        return _to_decimal(value[period_index])
    return _to_decimal(value)


def _extract_balance_period_value_with_state(
    value: Any,
    period_index: int,
) -> tuple[Optional[Decimal], str]:
    if isinstance(value, list):
        if period_index >= len(value):
            return None, "excluded"
        raw_value = value[period_index]
    else:
        raw_value = value

    if raw_value is None:
        return None, "excluded"
    if raw_value == "":
        return None, "empty"

    parsed_value = _to_decimal(raw_value)
    if parsed_value is None:
        return None, "excluded"
    return parsed_value, "value"


def _extract_current_period_value(value: Any) -> Optional[Decimal]:
    if isinstance(value, list):
        if not value:
            return None
        return _to_decimal(value[-1])
    return _to_decimal(value)


def _extract_current_period_value_with_state(
    value: Any,
) -> tuple[Optional[Decimal], str]:
    if isinstance(value, list):
        if not value:
            return None, "excluded"
        raw_value = value[-1]
    else:
        raw_value = value

    if raw_value is None:
        return None, "excluded"
    if raw_value == "":
        return None, "empty"

    parsed_value = _to_decimal(raw_value)
    if parsed_value is None:
        return None, "excluded"
    return parsed_value, "value"


def _to_decimal(value: Any) -> Optional[Decimal]:
    if value in (None, ""):
        return None
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value).strip())
    except (InvalidOperation, ValueError):
        return None


def _decimal_to_string(value: Optional[Decimal]) -> Optional[str]:
    if value is None:
        return None
    return str(value)


def _resolve_profit_total_name(total_code: str) -> str:
    for rule in PROFIT_BASIC_RULES:
        if str(rule["total_code"]) != total_code:
            continue
        for _, code, name in rule["components"]:
            if code == total_code:
                return name

    return {
        "L04010000": "营业利润",
        "L05010000": "利润总额",
        "L06010000": "净利润",
        "L07000000": "综合收益总额",
    }.get(total_code, total_code)
