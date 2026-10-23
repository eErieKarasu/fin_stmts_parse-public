#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
科目编码映射器

职责：根据 YAML 配置文件，将字典数据中的科目名称映射到标准科目编码
- 从字典 {科目名: 金额} 映射到 {科目编码: 金额}
- 支持多种匹配策略（精确匹配、别名匹配、模糊匹配）
- 支持新旧会计准则科目名称差异

处理流程：
Dict{科目名: 金额} + YAML配置 → AccountCodeMapper → Dict{科目编码: 金额}
"""

import os
import re
import html
from typing import Any, Dict, List, Optional, Tuple
from decimal import Decimal
from difflib import SequenceMatcher
from pathlib import Path
import yaml
from fin_stmts_parse.utils.logger import logger
from fin_stmts_parse.src.account_aliases import ACCOUNT_ALIASES as ACCOUNT_ALIASES_MAP
from fin_stmts_parse.utils.str_util import replace_excel_escaped_control_chars

NO_FUZZY_MATCH_ITEMS = {
    "经营活动现金流入小计",
    "经营活动现金流出小计",
    "经营活动产生的现金流量净额",
    "投资活动现金流入小计",
    "投资活动现金流出小计",
    "投资活动产生的现金流量净额",
    "筹资活动现金流入小计",
    "筹资活动现金流出小计",
    "筹资活动产生的现金流量净额",
}

CASHFLOW_STRUCTURED_FUZZY_ITEMS = {
    "收到的其他与经营活动有关的现金",
    "支付其他与经营活动有关的现金",
    "收到的其他与投资活动有关的现金",
    "支付其他与投资活动有关的现金",
    "收到的其他与筹资活动有关的现金",
    "支付其他与筹资活动有关的现金",
}


class AccountCodeMapper:
    """
    科目编码映射器
    
    将财务数据字典中的科目名称映射到标准科目编码
    """
    
    # 科目名称别名映射表（支持新旧会计准则、不同表述方式）
    ACCOUNT_ALIASES = ACCOUNT_ALIASES_MAP
    
    def __init__(self, semantic_config_path: str):
        """
        初始化映射器
        
        Args:
            semantic_config_path: semantic.yaml 配置文件路径
        """
        self.logger = logger
        self.config_path = semantic_config_path
        self.config = self._load_yaml_config()
        self.mapping_rules = list(self.config.get("semantic_items", []))
        
        # 构建反向别名索引（从别名到标准名称）
        self.alias_to_standard = {}
        self.normalized_account_aliases = {}
        for standard_name, aliases in self.ACCOUNT_ALIASES.items():
            norm_standard_name = self._normalize_item_name(standard_name)
            self.normalized_account_aliases[norm_standard_name] = aliases
            for alias in aliases:
                norm_alias = self._normalize_item_name(alias)
                self.alias_to_standard[norm_alias] = standard_name
        self.no_fuzzy_match_items = {
            self._normalize_item_name(item_name)
            for item_name in NO_FUZZY_MATCH_ITEMS
        }
        self.structured_cashflow_fuzzy_items = {
            self._normalize_item_name(item_name)
            for item_name in CASHFLOW_STRUCTURED_FUZZY_ITEMS
        }
                
    def _load_yaml_config(self) -> Dict[str, Any]:
        """加载 semantic YAML 配置文件"""
        try:
            with open(self.config_path, 'r', encoding='utf-8') as f:
                config = yaml.safe_load(f)
            
            if not config:
                self.logger.warning(f"配置文件为空: {self.config_path}")
                return {"semantic_items": []}
            
            # 兼容单一顶层 key + list 的旧格式，统一提升为 semantic_items
            if isinstance(config, dict):
                semantic_items = config.get("semantic_items")
                if isinstance(semantic_items, list):
                    self.logger.info(
                        f"成功加载 semantic 配置文件: {self.config_path}, 共 {len(semantic_items)} 个语义规则"
                    )
                    return config

                values = list(config.values())
                if len(values) == 1 and isinstance(values[0], list):
                    semantic_items = values[0]
                    self.logger.info(
                        f"成功加载旧格式 semantic 配置文件: {self.config_path}, 共 {len(semantic_items)} 个语义规则"
                    )
                    return {"semantic_items": semantic_items}

            self.logger.warning(f"配置文件格式异常: {self.config_path}")
            return {"semantic_items": []}
            
        except Exception as e:
            self.logger.error(f"加载配置文件失败 {self.config_path}: {e}")
            return {"semantic_items": []}

    def map_data(self, raw_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        将原始数据映射到科目编码
        
        Args:
            raw_data: 原始数据字典 {'项目名': 金额值, ...}
                     金额值可能是单个数值或列表 [年初数, 期末数]（资产负债表）
            
        Returns:
            映射后的数据 {'科目编码': Decimal金额/列表/""/None, ...}
            - 原始表中未解析出该项: None
            - 原始表中匹配到但值为空: ""
        """
        canonical_data = {}
        
        total_rules = 0
        
        # 统计信息
        matched_with_value = []
        matched_with_null = []
        not_matched = []
        
        # 为每个映射规则尝试匹配
        for rule in self.mapping_rules:
            code = rule.get('code', '')
            expected_name = rule.get('name', '')
            
            if not code or not expected_name:
                continue
            
            total_rules += 1
            
            # 在原始数据字典中查找与yaml配置匹配的项目
            found, matched_value = self._find_matching_value(raw_data, expected_name)
            
            if found:
                parsed_amount = self._parse_amount_or_list(matched_value)
                
                is_empty = self._is_empty_value(parsed_amount)
                
                if is_empty:
                    matched_with_null.append((expected_name, code))
                    self.logger.debug(f"✓ 匹配(空值): {expected_name} → {code} = {parsed_amount}")
                else:
                    matched_with_value.append((expected_name, code))
                    self.logger.debug(f"✓ 匹配(有值): {expected_name} → {code} = {parsed_amount}")
                
                canonical_data[code] = parsed_amount
            else:
                not_matched.append((expected_name, code))
                self.logger.debug(f"✗ 未匹配(原始表中未解析出该项): {expected_name} → {code}")
                canonical_data[code] = None
        
        # 输出详细的映射统计信息
        total_count = total_rules
        matched_value_count = len(matched_with_value)
        matched_null_count = len(matched_with_null)
        not_matched_count = len(not_matched)
        matched_total = matched_value_count + matched_null_count
        return_count = len(canonical_data)
        
        self.logger.info(f"========== 映射统计 ==========")
        self.logger.info(f"YAML配置项总数: {total_count}")
        self.logger.info(f"返回结果项数: {return_count} 个")
        self.logger.info(f"")
        self.logger.info(f"✓ 匹配到的项目: {matched_total} 个 ({matched_total/total_count*100:.1f}%)" if total_count else f"✓ 匹配到的项目: 0 个")
        self.logger.info(f"   ├─ 非空值项目: {matched_value_count} 个 (原始表有该项且值非空)")
        self.logger.info(f"   └─ 空值项目: {matched_null_count} 个 (原始表有该项但值为空)")
        self.logger.info(f"")
        self.logger.info(f"✗ 未匹配的项目: {not_matched_count} 个 ({not_matched_count/total_count*100:.1f}%)" if total_count else f"✗ 未匹配的项目: 0 个")
        
        if matched_with_null:
            self.logger.info(f"")
            self.logger.info(f"【匹配到但值为空项目明细】({matched_null_count}个):")
            for name, code in matched_with_null[:10]:
                self.logger.info(f"  - {name} ({code})")
            if matched_null_count > 10:
                self.logger.info(f"  ... 还有 {matched_null_count - 10} 个")
        
        if not_matched:
            self.logger.info(f"")
            self.logger.info(f"【未匹配项目明细】({not_matched_count}个):")
            for name, code in not_matched[:20]:
                self.logger.info(f"  - {name} ({code})")
            if not_matched_count > 20:
                self.logger.info(f"  ... 还有 {not_matched_count - 20} 个")
        
        self.logger.info(f"==============================")
        
        return canonical_data
    
    def _is_empty_value(self, value: any) -> bool:
        """判断值是否为空"""
        if value == "":
            return True
        if value is None:
            return True
        if isinstance(value, list):
            return all(item is None or item == "" for item in value)
        return False
    
    def _parse_amount_or_list(self, value: any):
        """解析金额值或金额列表"""
        if isinstance(value, list):
            parsed_list = []
            for item in value:
                if item is None:
                    parsed_list.append(None)
                    continue
                parsed = self._parse_amount(item)
                parsed_list.append(parsed)
            return parsed_list
        else:
            return self._parse_amount(value)

    def _calculate_similarity(self, str1: str, str2: str) -> float:
        """计算两个字符串的相似度"""
        return SequenceMatcher(None, str1, str2).ratio()

    def _passes_structured_fuzzy_validation(self, norm_expected: str, norm_key: str) -> bool:
        """
        对现金流量表模糊匹配候选做结构化校验。

        普通相似度会弱化“收到/支付”“经营/投资/筹资”这类关键差异；
        这些维度一旦冲突，即使字符串相似度很高也不能作为候选。
        """
        expected_direction = self._extract_cashflow_direction(norm_expected)
        candidate_direction = self._extract_cashflow_direction(norm_key)
        if (
            expected_direction
            and candidate_direction
            and expected_direction != candidate_direction
        ):
            return False

        expected_activity = self._extract_cashflow_activity(norm_expected)
        candidate_activity = self._extract_cashflow_activity(norm_key)
        if expected_activity and candidate_activity and expected_activity != candidate_activity:
            return False

        if norm_expected in self.structured_cashflow_fuzzy_items:
            return (
                candidate_direction == expected_direction
                and candidate_activity == expected_activity
                and "其他" in norm_key
            )

        return True

    @staticmethod
    def _extract_cashflow_direction(norm_name: str) -> Optional[str]:
        has_inflow = "收到" in norm_name or "收取" in norm_name
        has_outflow = "支付" in norm_name
        if has_inflow == has_outflow:
            return None
        return "收到" if has_inflow else "支付"

    @staticmethod
    def _extract_cashflow_activity(norm_name: str) -> Optional[str]:
        activities = []
        if "经营" in norm_name:
            activities.append("经营")
        if "投资" in norm_name:
            activities.append("投资")
        if "筹资" in norm_name or "融资" in norm_name:
            activities.append("筹资")
        return activities[0] if len(activities) == 1 else None
    
    def _find_matching_value(self, raw_data: Dict, expected_name: str) -> Tuple[bool, Optional[any]]:
        """
        在原始数据中查找匹配的值（使用多层匹配策略）
        
        匹配策略优先级：
        1. 精确匹配
        2. 别名匹配
        3. 模糊匹配
        """
        norm_expected = self._normalize_item_name(expected_name)
        
        # 1. 精确匹配
        exact_match = self._pick_matching_value(raw_data, [norm_expected])
        if exact_match is not None:
            key, value = exact_match
            self.logger.debug(f"✓ 精确匹配: {key} → {expected_name}")
            return (True, value)
        
        # 2. 别名匹配
        aliases = self.normalized_account_aliases.get(norm_expected, [])
        if aliases:
            # 严格按别名列表顺序匹配，避免结果受 raw_data 字典遍历顺序影响
            for alias in aliases:
                norm_alias = self._normalize_item_name(alias)
                alias_match = self._pick_matching_value(raw_data, [norm_alias])
                if alias_match is not None:
                    key, value = alias_match
                    self.logger.debug(f"✓ 别名匹配: {key} → {expected_name} (通过别名: {alias})")
                    return (True, value)
        
        for key, value in raw_data.items():
            norm_key = self._normalize_item_name(str(key))
            if norm_key in self.alias_to_standard:
                standard = self.alias_to_standard[norm_key]
                norm_standard = self._normalize_item_name(standard)
                if norm_standard == norm_expected:
                    self.logger.debug(f"✓ 反向别名匹配: {key} → {expected_name} (通过标准名: {standard})")
                    return (True, value)
        
        
        # 3. 模糊匹配（短字符串禁用，避免少量字面差异导致误匹配）
        if norm_expected in self.no_fuzzy_match_items:
            return (False, None)

        min_fuzzy_length = 10
        if len(norm_expected) < min_fuzzy_length:
            return (False, None)

        best_match_fuzzy = None
        best_similarity = 0
        threshold = 0.8
        
        for key, value in raw_data.items():
            norm_key = self._normalize_item_name(str(key))
            if not self._passes_structured_fuzzy_validation(norm_expected, norm_key):
                self.logger.debug(f"跳过结构化冲突的模糊候选: {key} → {expected_name}")
                continue
            similarity = self._calculate_similarity(norm_expected, norm_key)
            
            if similarity > best_similarity:
                best_similarity = similarity
                best_match_fuzzy = (key, value)
        
        if best_similarity >= threshold:
            key, value = best_match_fuzzy
            self.logger.debug(
                f"✓ 模糊匹配: {key} → {expected_name} "
                f"(相似度: {best_similarity:.1%})"
            )
            return (True, value)
        
        return (False, None)

    def _pick_matching_value(self, raw_data: Dict, normalized_names: List[str]) -> Optional[Tuple[str, any]]:
        first_non_empty_match = None
        first_empty_match = None
        for key, value in raw_data.items():
            norm_key = self._normalize_item_name(str(key))
            if norm_key not in normalized_names:
                continue
            if not self._is_empty_value(value):
                if not self._looks_like_heading_key(key):
                    return (key, value)
                if first_non_empty_match is None:
                    first_non_empty_match = (key, value)
                continue
            if first_empty_match is None:
                first_empty_match = (key, value)
        return first_non_empty_match or first_empty_match

    @staticmethod
    def _looks_like_heading_key(key: Any) -> bool:
        return str(key or "").strip().endswith((":", "："))
    
    def _normalize_item_name(self, name: str) -> str:
        """标准化项目名称"""
        name = html.unescape(replace_excel_escaped_control_chars(name))
        name = re.sub(r'\s+', '', name)  # \s 包含了普通空格、\t、\n、\r 以及 \xa0 等各种 Unicode 空白符
        latex_marker_pattern = r'^\$?\^(?:\{\{[^{}]*\}\}|\{[^{}]*\})'
        name = re.sub(latex_marker_pattern, '', name).strip('$')
        name = name.replace('**', '').replace('*', '')
        name = name.lstrip('△☆')
        name = re.sub(r'^(加|减|其中)[:：]', '', name)
        name = re.sub(r'^[一二三四五六七八九十\d]+[、,\.．:：\s]+', '', name)
        name = re.sub(latex_marker_pattern, '', name).strip('$')
        name = name.lstrip('△☆')
        name = re.sub(r'[（(].*?[)）]', '', name)
        name = name.replace('：', ':').replace('，', ',')
        name = name.replace('、', ',')
        name = re.sub(r'（损失以.*?号填列）', '', name)
        name = re.sub(r'\(损失以.*?号填列\)', '', name)

        name = re.sub(r'^[一二三四五六七八九十\d]+[、\.．:：\s]+', '', name)
        name = name.lstrip('△☆')
        name = name.rstrip(':：。，、,')
        name = name.replace('帐', '账')
        name = name.replace('彙', '汇')
        name = name.replace('僱', '雇')
        name = name.replace('其它', '其他')
        name = name.replace('以及', '及')
        
        return name.strip()
    
    def _parse_amount(self, value: any):
        """解析金额值"""
        if value is None:
            return ""
        
        value_str = str(value).strip()
        value_str = value_str.replace('**', '').replace('*', '').strip()
        
        empty_values = ['', '-', '—', '－', 'nan', 'NaN', 'None', 'null', 'N/A', 'n/a']
        if value_str in empty_values:
            return ""
        
        if value_str.startswith('#') or '##' in value_str:
            self.logger.debug(f"跳过标题行: '{value_str}'")
            return ""
        
        if value_str.endswith('：') or value_str.endswith(':'):
            self.logger.debug(f"跳过标题: '{value_str}'")
            return ""
        
        if not re.search(r'\d', value_str):
            self.logger.debug(f"跳过非数值文本: '{value_str}'")
            return ""
        
        try:
            cleaned = value_str.replace(',', '').replace(' ', '').replace('\u3000', '')
            
            if cleaned.startswith('(') and cleaned.endswith(')'):
                cleaned = '-' + cleaned[1:-1]
            
            if cleaned.endswith('%'):
                cleaned = cleaned[:-1]
            
            cleaned = re.sub(r'[元万亿]$', '', cleaned)
            
            return Decimal(cleaned)
            
        except Exception as e:
            if re.search(r'[a-zA-Z\u4e00-\u9fff]', value_str):
                self.logger.debug(f"跳过含文字的值: '{value_str}'")
            else:
                self.logger.warning(f"解析金额失败: '{value_str}', 错误: {type(e).__name__}")
            return ""


# 保持向后兼容的别名
FinancialDataMapper = AccountCodeMapper


def map_financial_data(
    raw_data: Dict[str, any],
    yaml_config_path: str
) -> Dict[str, Optional[Decimal]]:
    """
    便捷函数：映射财务数据
    
    Args:
        raw_data: 原始数据字典
        yaml_config_path: YAML 配置文件路径
        
    Returns:
        映射后的数据
    """
    mapper = AccountCodeMapper(yaml_config_path)
    return mapper.map_data(raw_data)


if __name__ == "__main__":
    # 测试代码
    test_data = {
        "营业收入": "1591467528.75",
        "营业成本": "1547723502.89",
        "税金及附加": "578930.97",
        "其中城市维护建设税": "0.0",
        "教育费附加矿产资源补偿费排污费": "0.0",
        "销售费用": "2888644.16",
        "其中商品维修费": "0.0",
        "广告费和业务宣传费": "0.0",
        "管理费用": "11283421.0",
        "其中业务招待费": "0.0",
        "研究费用": "1251028.73",
        "财务费用": "3903631.91",
        "其中利息费用(收入以“-”号填列)": "0.0",
        "投资收益(损失以“-”号填列)": "11694.28",
        "营业利润(亏损以“-”号填列)": "25101092.1",
        "营业外收入": "25820.69",
        "营业外支出": "116019.46",
        "其中坏账损失": "0.0",
        "税收滞纳金": "0.0",
        "利润总额(亏损总额以“-”号填列)": "25010893.33",
        "所得税费用": "368443.35",
        "净利润(净亏损以“-”号填列)": "24642449.98"
    }
    
    config_path = str(
        Path(__file__).resolve().parents[1]
        / "config"
        / "mappings"
        / "profit"
        / "standalone"
        / "semantic.yaml"
    )
    
    mapper = AccountCodeMapper(config_path)
    result = mapper.map_data(test_data)
    
    print("\n✅ 匹配成功的科目:")
    matched = [(code, amount) for code, amount in result.items() if amount is not None]
    for code, amount in matched:
        print(f"  {code}: {amount}")
    
    print(f"\n总计: {len(matched)}/{len(result)} 个科目有数据")
