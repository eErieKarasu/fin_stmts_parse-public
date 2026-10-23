#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Markdown 表格数据提取器

职责：从 Markdown/HTML 表格中提取财务数据，转换为字典格式
- 解析 Markdown 表格 → {科目名: 金额}
- 解析 HTML 表格 → {科目名: 金额}  
- 提取元数据（日期、单位）
- 清理科目名称

处理流程：
VL大模型识别结果(Markdown) → MarkdownTableExtractor → Dict{科目名: 金额}
"""

import re
import pandas as pd
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple
import calendar
import html
import io

from fin_stmts_parse.utils.logger import logger as _default_logger
from fin_stmts_parse.utils.str_util import replace_excel_escaped_control_chars


class MarkdownTableExtractor:
    """
    Markdown 表格数据提取器
    
    将 VL 大模型输出的 Markdown/HTML 表格转换为结构化字典数据
    支持资产负债表（双时点数据）、利润表/现金流量表（上期/本期数据）
    """
    
    def __init__(self, logger=None, llm_client=None):
        """
        初始化提取器
        
        Args:
            logger: 日志记录器（可选，默认使用全局 Loguru logger）
            llm_client: LLMClient 实例（可选），用于 LLM 辅助表格结构识别
        """
        self.logger = logger or _default_logger
        self.llm = llm_client

    @staticmethod
    def _canonical_statement_type(table_type: str = None) -> str:
        normalized = str(table_type or "").strip().lower()
        compact = re.sub(r"[\s_-]+", "", normalized)
        if not compact:
            return ""
        if "现金流量表" in compact or compact in {"cashflow", "cashflowstatement"}:
            return "cashflow"
        if "资产负债表" in compact or compact in {"balance", "balancesheet"}:
            return "balance"
        if "利润表" in compact or compact in {"profit", "incomestatement"}:
            return "profit"
        return compact

    def _is_balance_sheet_type(self, table_type: str = None) -> bool:
        return self._canonical_statement_type(table_type) == "balance"

    def _is_cashflow_statement_type(self, table_type: str = None) -> bool:
        return self._canonical_statement_type(table_type) == "cashflow"

    def _is_period_pair_statement_type(self, table_type: str = None) -> bool:
        return self._canonical_statement_type(table_type) in {"profit", "cashflow"}

    # ==================== 合并/母公司横向对比表拆分 ====================

    def try_split_dual_entity_comparative_statement(
        self,
        markdown_content: str,
        table_type: str = None,
    ) -> List[Dict[str, Any]]:
        """
        将同一物理表内的“合并/母公司”横向对比列拆成两张逻辑报表。

        命中条件保持保守：必须同时识别到合并列、母公司列和期间列。
        未命中时返回空列表，调用方应继续使用原解析逻辑。
        """
        statement_type = self._canonical_statement_type(table_type)
        base_table_names = {
            "balance": "资产负债表",
            "profit": "利润表",
            "cashflow": "现金流量表",
        }
        base_table_name = base_table_names.get(statement_type)
        if not base_table_name or not markdown_content:
            return []

        try:
            all_tables = self.extract_all_tables_from_markdown(markdown_content)
        except Exception as e:
            self.logger.warning(f"双实体对比表拆分：提取表格失败，跳过: {e}")
            return []

        consolidated_data = {}
        standalone_data = {}

        for table_info in all_tables:
            rows = self._rows_from_table_info(table_info)
            if not rows:
                continue

            split_data = self._split_dual_entity_rows(rows, statement_type)
            if not split_data:
                continue

            consolidated_data.update(split_data["consolidated"])
            standalone_data.update(split_data["standalone"])

        if not self._dual_entity_data_is_usable(consolidated_data, statement_type):
            return []
        if not self._dual_entity_data_is_usable(standalone_data, statement_type):
            return []

        return [
            {
                "table_type": f"合并{base_table_name}",
                "is_consolidated": True,
                "is_split_variant": True,
                "data": consolidated_data,
            },
            {
                "table_type": base_table_name,
                "is_consolidated": False,
                "is_split_variant": True,
                "data": standalone_data,
            },
        ]

    def _rows_from_table_info(self, table_info: Dict[str, Any]) -> List[List[str]]:
        table_type = table_info.get("type")
        content = table_info.get("content", "")
        if table_type == "markdown":
            return self._markdown_table_to_rows(content)
        if table_type == "html":
            return self._html_table_to_rows(content)
        return []

    def _markdown_table_to_rows(self, markdown_table: str) -> List[List[str]]:
        rows = []
        for line in markdown_table.splitlines():
            stripped = line.strip()
            if not stripped.startswith("|"):
                continue
            if re.match(r'^\|[\s\-:|]+\|$', stripped):
                continue
            rows.append([cell.strip() for cell in stripped.split("|")[1:-1]])
        return rows

    def _html_table_to_rows(self, html_table: str) -> List[List[str]]:
        try:
            dfs = pd.read_html(io.StringIO(html_table), header=None)
        except Exception:
            return []

        if not dfs:
            return []

        df = dfs[0]
        rows = []
        for _, row in df.iterrows():
            rows.append([str(cell).strip() if pd.notna(cell) else "" for cell in row])
        return rows

    def _split_dual_entity_rows(
        self,
        rows: List[List[str]],
        statement_type: str,
    ) -> Optional[Dict[str, Dict]]:
        max_cols = max((len(row) for row in rows), default=0)
        if max_cols == 0:
            return None

        padded_rows = [row + [""] * (max_cols - len(row)) for row in rows]
        header_end_idx = self._find_dual_entity_header_end(padded_rows)
        if header_end_idx is None:
            return None

        header_rows = padded_rows[:header_end_idx + 1]
        data_rows = padded_rows[header_end_idx + 1:]
        if not data_rows:
            return None

        combined_headers = self._combine_dual_entity_headers(header_rows, max_cols)
        entity_period_columns = self._detect_dual_entity_value_columns(combined_headers)
        if not entity_period_columns["consolidated"] or not entity_period_columns["standalone"]:
            return None

        selected_cols = self._select_dual_entity_columns(entity_period_columns, statement_type)
        if not selected_cols:
            return None

        item_col_idx = self._detect_dual_entity_item_column(
            combined_headers,
            data_rows,
            selected_cols,
        )
        if item_col_idx is None:
            return None

        return self._build_dual_entity_data(
            data_rows,
            item_col_idx,
            selected_cols,
            statement_type,
        )

    def _find_dual_entity_header_end(self, rows: List[List[str]]) -> Optional[int]:
        header_scan_rows = rows[: min(5, len(rows))]
        header_end_idx = None
        has_entity_header = False
        has_period_header = False

        for idx, row in enumerate(header_scan_rows):
            row_text = self._compact_text("".join(row))
            row_has_entity = "合并" in row_text or self._has_standalone_entity_label(row_text)
            row_looks_like_data = self._dual_entity_row_looks_like_data(row)
            row_has_period = any(
                self._parse_date_from_header_safely(
                    str(cell),
                    allow_plain_numeric_date=not row_looks_like_data,
                )
                for cell in row
            )
            row_has_header_keyword = any(
                keyword in row_text
                for keyword in ("项目", "行次", "注释号", "附注")
            )

            if row_has_entity:
                has_entity_header = True
                header_end_idx = idx
            elif header_end_idx is not None and (row_has_period or row_has_header_keyword):
                header_end_idx = idx

            has_period_header = has_period_header or row_has_period

        if header_end_idx is None or not has_entity_header or not has_period_header:
            return None
        return header_end_idx

    def _combine_dual_entity_headers(
        self,
        header_rows: List[List[str]],
        max_cols: int,
    ) -> List[str]:
        period_by_col = {}

        for row in header_rows:
            row_looks_like_data = self._dual_entity_row_looks_like_data(row)
            current_period = ""
            for col_idx in range(max_cols):
                cell = str(row[col_idx]).strip() if col_idx < len(row) else ""
                if self._parse_date_from_header_safely(
                    cell,
                    allow_plain_numeric_date=not row_looks_like_data,
                ):
                    current_period = cell
                    period_by_col[col_idx] = cell
                elif not cell and current_period:
                    period_by_col[col_idx] = current_period

        combined_headers = []
        for col_idx in range(max_cols):
            parts = []
            period_text = period_by_col.get(col_idx, "")
            if period_text:
                parts.append(period_text)

            for row in header_rows:
                cell = str(row[col_idx]).strip() if col_idx < len(row) else ""
                if not cell:
                    continue
                if period_text and self._compact_text(cell) == self._compact_text(period_text):
                    continue
                parts.append(cell)

            combined_headers.append(" ".join(parts).strip())

        return combined_headers

    def _detect_dual_entity_value_columns(
        self,
        combined_headers: List[str],
    ) -> Dict[str, List[Tuple[datetime, int]]]:
        entity_period_columns = {
            "consolidated": [],
            "standalone": [],
        }

        for col_idx, header in enumerate(combined_headers):
            compact_header = self._compact_text(header)
            period = self._parse_date_from_header_safely(compact_header)
            if not period:
                continue
            if "合并" in compact_header:
                entity_period_columns["consolidated"].append((period, col_idx))
            elif self._has_standalone_entity_label(compact_header):
                entity_period_columns["standalone"].append((period, col_idx))

        for entity in entity_period_columns:
            entity_period_columns[entity].sort(key=lambda item: item[0])

        return entity_period_columns

    def _parse_date_from_header_safely(
        self,
        header_text: str,
        allow_plain_numeric_date: bool = True,
    ) -> Optional[datetime]:
        try:
            return self.parse_date_from_header(
                header_text,
                allow_plain_numeric_date=allow_plain_numeric_date,
            )
        except ValueError as e:
            self.logger.warning(f"忽略无效日期表头: {e}")
            return None

    def _dual_entity_row_looks_like_data(self, row: List[str]) -> bool:
        compact_cells = [self._compact_text(str(cell)) for cell in row]
        non_empty_cells = [cell for cell in compact_cells if cell]
        if not non_empty_cells:
            return False

        row_text = "".join(non_empty_cells)
        if any(keyword in row_text for keyword in ("项目", "行次", "注释", "附注", "合并", "母公司")):
            return False

        has_numeric_cell = any(self._looks_like_plain_numeric_cell(cell) for cell in non_empty_cells)
        has_item_like_cell = any(re.search(r'[\u4e00-\u9fa5]', cell) for cell in non_empty_cells)
        return has_item_like_cell and has_numeric_cell

    def _select_dual_entity_columns(
        self,
        entity_period_columns: Dict[str, List[Tuple[datetime, int]]],
        statement_type: str,
    ) -> Optional[Dict[str, Dict[str, int]]]:
        consolidated_dates = {date_value for date_value, _ in entity_period_columns["consolidated"]}
        standalone_dates = {date_value for date_value, _ in entity_period_columns["standalone"]}
        common_dates = sorted(consolidated_dates.intersection(standalone_dates))

        if statement_type == "balance":
            if len(common_dates) < 2:
                return None
            previous_date = common_dates[-2]
            latest_date = common_dates[-1]
            return {
                "consolidated": {
                    "previous": self._column_for_period(entity_period_columns["consolidated"], previous_date),
                    "latest": self._column_for_period(entity_period_columns["consolidated"], latest_date),
                },
                "standalone": {
                    "previous": self._column_for_period(entity_period_columns["standalone"], previous_date),
                    "latest": self._column_for_period(entity_period_columns["standalone"], latest_date),
                },
            }

        if not common_dates:
            return None
        latest_date = common_dates[-1]
        selected_cols = {
            "consolidated": {
                "latest": self._column_for_period(entity_period_columns["consolidated"], latest_date),
            },
            "standalone": {
                "latest": self._column_for_period(entity_period_columns["standalone"], latest_date),
            },
        }
        if statement_type in {"profit", "cashflow"} and len(common_dates) >= 2:
            previous_date = common_dates[-2]
            selected_cols["consolidated"]["previous"] = self._column_for_period(
                entity_period_columns["consolidated"],
                previous_date,
            )
            selected_cols["standalone"]["previous"] = self._column_for_period(
                entity_period_columns["standalone"],
                previous_date,
            )
        return selected_cols

    @staticmethod
    def _column_for_period(columns: List[Tuple[datetime, int]], period: datetime) -> Optional[int]:
        for date_value, col_idx in columns:
            if date_value == period:
                return col_idx
        return None

    def _detect_dual_entity_item_column(
        self,
        combined_headers: List[str],
        data_rows: List[List[str]],
        selected_cols: Dict[str, Dict[str, int]],
    ) -> Optional[int]:
        value_columns = [
            col_idx
            for entity_cols in selected_cols.values()
            for col_idx in entity_cols.values()
            if col_idx is not None
        ]
        if not value_columns:
            return None

        first_value_col = min(value_columns)
        excluded_keywords = ("注释", "附注", "行次", "序号", "行号")
        preferred_columns = []
        fallback_columns = []

        for col_idx in range(first_value_col):
            header = self._compact_text(combined_headers[col_idx] if col_idx < len(combined_headers) else "")
            if any(keyword in header for keyword in excluded_keywords):
                continue
            if "项目" in header or "科目" in header:
                preferred_columns.append(col_idx)
                continue
            if self._dual_entity_column_looks_like_item(data_rows, col_idx):
                fallback_columns.append(col_idx)

        if preferred_columns:
            return preferred_columns[0]
        if fallback_columns:
            return fallback_columns[0]
        return None

    def _dual_entity_column_looks_like_item(
        self,
        rows: List[List[str]],
        col_idx: int,
    ) -> bool:
        non_empty_count = 0
        chinese_count = 0
        numeric_count = 0

        for row in rows[:12]:
            if col_idx >= len(row):
                continue
            cell = self.clean_item_text(str(row[col_idx]).strip())
            if not cell:
                continue
            non_empty_count += 1
            if re.search(r'[\u4e00-\u9fa5]', cell):
                chinese_count += 1
            if self.extract_numeric_value(cell) is not None:
                numeric_count += 1

        if non_empty_count == 0:
            return False
        return chinese_count >= 2 and numeric_count == 0

    def _build_dual_entity_data(
        self,
        rows: List[List[str]],
        item_col_idx: int,
        selected_cols: Dict[str, Dict[str, int]],
        statement_type: str,
    ) -> Optional[Dict[str, Dict]]:
        consolidated_data = {}
        standalone_data = {}
        cashflow_section = ""

        for row in rows:
            if item_col_idx >= len(row):
                continue

            item_name = self.clean_item_text(str(row[item_col_idx]).strip())
            if not self._is_valid_dual_entity_item_name(item_name):
                continue

            if statement_type == "cashflow":
                item_name, cashflow_section = self._contextualize_dual_entity_cashflow_item(
                    item_name,
                    cashflow_section,
                )

            if statement_type == "balance":
                consolidated_value = [
                    self._cell_numeric_at(row, selected_cols["consolidated"].get("previous")),
                    self._cell_numeric_at(row, selected_cols["consolidated"].get("latest")),
                ]
                standalone_value = [
                    self._cell_numeric_at(row, selected_cols["standalone"].get("previous")),
                    self._cell_numeric_at(row, selected_cols["standalone"].get("latest")),
                ]
            elif statement_type in {"profit", "cashflow"}:
                consolidated_value = [
                    self._cell_numeric_at(row, selected_cols["consolidated"].get("previous")),
                    self._cell_numeric_at(row, selected_cols["consolidated"].get("latest")),
                ]
                standalone_value = [
                    self._cell_numeric_at(row, selected_cols["standalone"].get("previous")),
                    self._cell_numeric_at(row, selected_cols["standalone"].get("latest")),
                ]
            else:
                consolidated_value = self._cell_numeric_at(
                    row,
                    selected_cols["consolidated"].get("latest"),
                )
                standalone_value = self._cell_numeric_at(
                    row,
                    selected_cols["standalone"].get("latest"),
                )

            consolidated_data[item_name] = consolidated_value
            standalone_data[item_name] = standalone_value

        return {
            "consolidated": consolidated_data,
            "standalone": standalone_data,
        }

    def _contextualize_dual_entity_cashflow_item(
        self,
        item_name: str,
        current_section: str,
    ) -> Tuple[str, str]:
        normalized = self._normalize_dual_entity_cashflow_text(item_name)
        if "净额" not in normalized:
            if normalized in {"经营活动产生的现金流量", "经营活动现金流量"}:
                current_section = "经营活动"
            elif normalized in {"投资活动产生的现金流量", "投资活动现金流量"}:
                current_section = "投资活动"
            elif normalized in {"筹资活动产生的现金流量", "筹资活动现金流量"}:
                current_section = "筹资活动"

        if normalized in {"现金流入小计", "现金流出小计"} and current_section:
            return f"{current_section}{normalized}", current_section
        return item_name, current_section

    @staticmethod
    def _normalize_dual_entity_cashflow_text(text: str) -> str:
        normalized = html.unescape(str(text).strip())
        normalized = normalized.replace('**', '').replace('*', '')
        normalized = re.sub(r'\s+', '', normalized)
        normalized = re.sub(r'^[一二三四五六七八九十\d]+[、,\.．]', '', normalized)
        return normalized.replace('：', ':').rstrip(':：。，、,')

    def _is_valid_dual_entity_item_name(self, item_name: str) -> bool:
        if not item_name:
            return False
        compact_item = self._compact_text(item_name)
        if compact_item in {"项目", "科目", "资产", "负债和所有者权益"}:
            return False
        if any(keyword in compact_item for keyword in ("注释号", "附注", "行次")):
            return False
        return re.search(r'[\u4e00-\u9fa5]', compact_item) is not None

    def _cell_numeric_at(self, row: List[str], col_idx: Optional[int]):
        if col_idx is None or col_idx < 0 or col_idx >= len(row):
            return None
        return self.extract_numeric_value(row[col_idx])

    def _dual_entity_data_is_usable(self, data: Dict, statement_type: str) -> bool:
        if len(data) < 2:
            return False

        usable_count = 0
        for value in data.values():
            if isinstance(value, list):
                if statement_type == "balance":
                    if len(value) >= 2 and value[0] is not None and value[1] is not None:
                        usable_count += 1
                elif any(item is not None for item in value):
                    usable_count += 1
            elif value is not None:
                usable_count += 1

        return usable_count >= 2

    @staticmethod
    def _compact_text(text: str) -> str:
        compact = html.unescape(str(text or ""))
        compact = compact.replace('**', '').replace('*', '')
        compact = compact.replace('（', '(').replace('）', ')')
        return re.sub(r'\s+', '', compact)

    @staticmethod
    def _has_standalone_entity_label(text: str) -> bool:
        compact = re.sub(r'\s+', '', str(text or ""))
        return any(label in compact for label in ("母公司", "公司", "本部"))
    
    # ==================== 元数据提取 ====================
    
    def extract_metadata_from_markdown(self, markdown_content: str) -> Dict:
        """
        从markdown内容中提取元数据（日期、单位）
        
        Args:
            markdown_content: markdown内容字符串
            
        Returns:
            包含日期和单位的字典
        """
        metadata = {
            '日期': 'N/A',
            '单位': 'N/A'
        }
        
        # 提取日期
        period_match = re.search(
            r'\d{4}\s*年\s*第?\s*\d{1,2}\s*期',
            markdown_content,
        )
        if period_match:
            try:
                parsed_date = self.parse_date_from_header(period_match.group(0))
                if parsed_date:
                    metadata['日期'] = parsed_date.strftime('%Y%m')
            except Exception:
                pass

        range_match = re.search(
            r'\d{4}\s*年\s*\d{1,2}\s*[\-~至到－—–～]\s*\d{1,2}\s*月',
            markdown_content,
        )
        if range_match:
            try:
                parsed_date = self.parse_date_from_header(range_match.group(0))
                if parsed_date:
                    metadata['日期'] = parsed_date.strftime('%Y%m')
            except Exception:
                pass

        date_patterns = [
            r'\d{4}年\d{1,2}月\d{1,2}日',
            r'\d{4}年\d{1,2}月',
            r'\d{4}年',
            r'\d{4}-\d{1,2}-\d{1,2}',
            r'\d{4}-\d{1,2}',
            r'\d{8}',
            r'\d{6}'
        ]
        
        date_formats = [
            ('%Y年%m月%d日', '%Y%m'),
            ('%Y年%m月', '%Y%m'),
            ('%Y年', '%Y12'),
            ('%Y-%m-%d', '%Y%m'),
            ('%Y-%m', '%Y%m'),
            ('%Y%m%d', '%Y%m'),
            ('%Y%m', '%Y%m')
        ]
        
        if metadata['日期'] == 'N/A' and not period_match:
            for i, pattern in enumerate(date_patterns):
                match = re.search(pattern, markdown_content)
                if match:
                    date_str = match.group(0)
                    try:
                        in_fmt, out_fmt = date_formats[i]
                        parsed_date = datetime.strptime(date_str, in_fmt)
                        metadata['日期'] = parsed_date.strftime(out_fmt)
                        break
                    except:
                        pass
        
        # 提取单位
        unit_patterns = [
            r'单位[：:]\s*([亿万]?元)',
            r'金额单位[：:]\s*([亿万]?元)',
            r'单位为([亿万]?元)',
            r'(\b[亿万]?元\b)'
        ]
        
        for pattern in unit_patterns:
            match = re.search(pattern, markdown_content)
            if match:
                metadata['单位'] = match.group(1)
                break
        
        return metadata
    
    # ==================== 日期识别 ====================


    def is_date_header(self, header_text: str) -> bool:
        """
        判断表头是否包含日期
        支持格式：
        1. 区间：2025年1-9月, 2025年1~6月
        2. 期数：2025年第3期, 2025年3期
        3. 标准：2025年6月, 2025年6月30日
        4. 符号：2025-06, 2025.06, 2025/06
        5. 周期：2025年度, 2025半年度, 2025一季度
        6. 年份+常见后缀（如2024年发生额， 2024年金额）
        """
        text = str(header_text or "").strip()
        if not text or len(text) < 4:
            return False
        try:
            return self.parse_date_from_header(text) is not None
        except ValueError:
            return False

    @staticmethod
    def _looks_like_plain_numeric_cell(text: str) -> bool:
        normalized = str(text or "").strip()
        if not normalized:
            return False
        normalized = normalized.replace(",", "").replace("，", "")
        return bool(re.fullmatch(r'[+-]?\d+(?:\.\d+)?', normalized))

    def parse_date_from_header(
        self,
        header_text: str,
        allow_plain_numeric_date: bool = True,
    ):
        """
        解析日期核心逻辑（优先级漏斗）
        """
        text = str(header_text or "").strip()
        if not allow_plain_numeric_date and self._looks_like_plain_numeric_cell(text):
            return None

        def build_datetime(year: int, month: int, day: int) -> datetime:
            try:
                return datetime(year, month, day)
            except ValueError as e:
                raise ValueError(f"{e}; 触发原文={text!r}") from e

        def get_month_last_day(year: int, month: int) -> int:
            try:
                return calendar.monthrange(year, month)[1]
            except Exception as e:
                raise ValueError(f"{e}; 触发原文={text!r}") from e
        
        # ====================================================
        # 优先级 1：特殊中文周期（语义优先）
        # 格式：2023半年度, 2023年三季度, 2023年度
        # ====================================================
        match_special = re.search(r'(\d{4})\s*(?:年)?.*?(半年度|上半年|下半年|([一二三四])季度|年度)', text)
        if match_special:
            year = int(match_special.group(1))
            suffix = match_special.group(2)
            
            month, day = 12, 31 # 默认年底
            
            if '半年度' in suffix or '上半年' in suffix:
                month, day = 6, 30
            elif '下半年' in suffix:
                month, day = 12, 31
            elif '季度' in suffix:
                q_map = {'一': (3, 31), '二': (6, 30), '三': (9, 30), '四': (12, 31)}
                q_key = match_special.group(3) # 获取具体的数字一二三四
                if q_key in q_map:
                    month, day = q_map[q_key]
            elif '年度' in suffix:
                month, day = 12, 31

            return build_datetime(year, month, day)

        # ====================================================
        # 优先级 2：期数格式
        # 格式：2025年第3期, 2025年3期；业务语义为第 N 期 = 第 N 月
        # ====================================================
        match_period = re.search(r'(\d{4})\s*年\s*第?\s*(\d{1,2})\s*期', text)
        if match_period:
            year = int(match_period.group(1))
            month = int(match_period.group(2))
            if not 1 <= month <= 12:
                raise ValueError(f"期数月份超出范围: {month}; 触发原文={text!r}")
            last_day = get_month_last_day(year, month)
            return build_datetime(year, month, last_day)

        # ====================================================
        # 优先级 3：区间格式 (处理 "1-9月" 这种累计数据)
        # 格式：2025年1-9月, 2025年1至9月
        # ====================================================
        match_range = re.search(r'(\d{4})\s*年\s*\d{1,2}\s*[\-~至到－—–～]\s*(\d{1,2})\s*月', text)
        if match_range:
            year = int(match_range.group(1))
            end_month = int(match_range.group(2))
            
            # 逻辑：获取该月最后一天 (自动处理2月闰年、30/31日)
            last_day = get_month_last_day(year, end_month)
            return build_datetime(year, end_month, last_day)

        # ====================================================
        # 优先级 4：标准中文年月日
        # 格式：2024年12月31日, 2024年6月
        # ====================================================
        match_cn = re.search(r'(\d{4})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})?\s*日?', text)
        if match_cn:
            year, month = int(match_cn.group(1)), int(match_cn.group(2))
            day = match_cn.group(3)
            # 逻辑：如果有具体日期则使用，否则默认为1号（或可根据需求改为月底）
            return build_datetime(year, month, int(day) if day else 1)
        
        # ====================================================
        # 优先级 4：分隔符格式
        # 格式：2024-12-31, 2024/12, 2024.12
        # ====================================================
        match_dash = re.search(r'(?<!\d)(\d{4})[-/\.]\s*(\d{1,2})(?:[-/\.]\s*(\d{1,2}))?(?!\d)', text)
        if match_dash:
            year, month = int(match_dash.group(1)), int(match_dash.group(2))
            day = match_dash.group(3)
            return build_datetime(year, month, int(day) if day else 1)

        # ====================================================
        # 优先级 5：纯年份 (兜底)
        # 匹配 "2024年发生额" 或 纯 "2024年"
        # 只要以年份开头，且包含"年"，并没有具体的月日，就默认为该年年底
        # ====================================================
        match_year_text = re.search(r'^(\d{4})\s*年', text)
        if match_year_text:
            year = int(match_year_text.group(1))
            return build_datetime(year, 12, 31)
        
        return None
    
    # ==================== 多表格识别与提取 ====================
    
    def extract_html_tables(self, content: str) -> List[str]:
        """
        从内容中提取所有HTML表格
        
        Args:
            content: markdown内容字符串
            
        Returns:
            HTML表格片段列表
        """
        html_tables = []
        
        # 使用正则表达式匹配所有 <table>...</table>（支持多行和嵌套）
        pattern = r'<table[^>]*?>.*?</table>'
        matches = re.finditer(pattern, content, re.DOTALL | re.IGNORECASE)
        
        for match in matches:
            html_tables.append(match.group(0))
        
        self.logger.info(f"提取到 {len(html_tables)} 个HTML表格")
        return html_tables
    
    def extract_markdown_tables(self, content: str) -> List[str]:
        """
        从内容中提取所有markdown表格
        
        Args:
            content: 已移除HTML表格的内容字符串
            
        Returns:
            markdown表格文本列表
        """
        markdown_tables = []
        
        # 移除所有的```标记
        lines = content.split('\n')
        filtered_lines = []
        
        for line in lines:
            stripped = line.strip()
            if stripped.startswith('```') or stripped == '```':
                continue
            filtered_lines.append(stripped)
        
        # 查找所有markdown表格（以空行分隔）
        current_table = []
        in_table = False
        
        for line in filtered_lines:
            if line.startswith('|'):
                current_table.append(line)
                in_table = True
            elif in_table:
                # 遇到非表格行
                if not line:  # 空行，表格结束
                    if current_table:
                        markdown_tables.append('\n'.join(current_table))
                        current_table = []
                    in_table = False
                else:
                    # 非空行但不是表格行，表格也结束
                    if current_table:
                        markdown_tables.append('\n'.join(current_table))
                        current_table = []
                    in_table = False
        
        # 处理最后一个表格（如果文件末尾没有空行）
        if current_table:
            markdown_tables.append('\n'.join(current_table))
        
        self.logger.info(f"提取到 {len(markdown_tables)} 个Markdown表格")
        return markdown_tables
    
    def extract_all_tables_from_markdown(self, markdown_content: str) -> List[Dict]:
        """
        从markdown内容中提取所有表格（HTML和markdown混合）
        
        Args:
            markdown_content: markdown内容字符串
            
        Returns:
            表格列表，每个元素为 {'type': 'html'/'markdown', 'content': '...', 'index': 序号}
        """
        all_tables = []
        
        # 1. 先提取HTML表格
        html_tables = self.extract_html_tables(markdown_content)
        
        # 2. 移除HTML表格后，提取markdown表格
        content_without_html = markdown_content
        for html_table in html_tables:
            content_without_html = content_without_html.replace(html_table, '', 1)
        
        markdown_tables = self.extract_markdown_tables(content_without_html)
        
        # 3. 合并到统一列表（保持原始顺序）
        # 为了保持顺序，我们需要记录每个表格在原文中的位置
        for html_table in html_tables:
            pos = markdown_content.find(html_table)
            all_tables.append({
                'type': 'html',
                'content': html_table,
                'position': pos
            })
        
        for md_table in markdown_tables:
            pos = content_without_html.find(md_table)
            all_tables.append({
                'type': 'markdown',
                'content': md_table,
                'position': pos
            })
        
        # 按位置排序，保持原始顺序
        all_tables.sort(key=lambda x: x['position'])
        
        # 添加索引号
        for i, table in enumerate(all_tables):
            table['index'] = i + 1
            del table['position']  # 删除临时的位置字段
        
        self.logger.info(f"共提取 {len(all_tables)} 张表格（HTML: {len(html_tables)}, Markdown: {len(markdown_tables)}）")
        
        return all_tables
    
    # ==================== 表格解析入口 ====================
    
    def parse_markdown_table_to_dict(self, markdown_content: str, table_type: str = None) -> Dict:
        """
        将markdown或HTML表格内容解析为字典格式（支持多表格混合场景）
        
        Args:
            markdown_content: markdown或HTML表格内容（可能包含多张表格）
            table_type: 表格类型（用于特殊处理，如资产负债表需要提取两个时点的数据）
            
        Returns:
            科目-数值的字典（多张表格合并后的结果）
            - 对于资产负债表：值为列表 [年初数, 期末数]
            - 对于其他报表：值为单个数值
        """
        data_dict = {}
        
        try:
            # 1. 提取所有表格（HTML + Markdown）
            all_tables = self.extract_all_tables_from_markdown(markdown_content)
            
            if not all_tables:
                self.logger.warning("未找到任何表格")
                return data_dict
            
            # 2. 解析每张表格
            table_dicts = []
            
            for table_info in all_tables:
                table_idx = table_info['index']
                table_content_type = table_info['type']
                table_content = table_info['content']
                
                self.logger.info(f"正在解析第 {table_idx} 张表格（类型: {table_content_type}）")
                
                try:
                    if table_content_type == 'html':
                        # 解析HTML表格
                        parsed_dict = self.parse_single_html_table_to_dict(table_content, table_type)
                    else:
                        # 解析Markdown表格
                        parsed_dict = self.parse_single_markdown_table_to_dict(table_content, table_type)
                    
                    if parsed_dict:
                        table_dicts.append(parsed_dict)
                        self.logger.info(f"第 {table_idx} 张表格解析成功，包含 {len(parsed_dict)} 个科目")
                    else:
                        self.logger.warning(f"第 {table_idx} 张表格解析结果为空")
                        
                except Exception as e:
                    self.logger.error(f"解析第 {table_idx} 张表格失败: {e}")
                    import traceback
                    self.logger.error(traceback.format_exc())
            
            # 3. 合并所有表格的结果
            if table_dicts:
                data_dict = self.merge_table_dicts(table_dicts, table_type)
            else:
                self.logger.warning("所有表格解析后均为空")
            
        except Exception as e:
            self.logger.error(f"解析markdown表格失败: {e}")
            import traceback
            self.logger.error(traceback.format_exc())
        return data_dict
    
    def find_header_row(self, df, max_rows_to_check: int = 3):
        """
        在前N行中查找最可能的表头行
        
        Args:
            df: pandas DataFrame
            max_rows_to_check: 最多检查前几行
            
        Returns:
            (header_row_index, headers, score) 或 None
        """
        header_keywords = ['资产', '负债', '项目', '行次', '年初', '期初', '期末', '金额', '科目', '行数']
        # 表头特征词（这些词出现在表头的概率更高）
        header_feature_keywords = ['行次', '年初', '期初', '期末', '金额']
        
        best_match = None
        best_score = 0
        
        # 检查前 N 行
        rows_to_check = min(max_rows_to_check, len(df))
        for row_idx in range(rows_to_check):
            row_data = [str(cell).strip() if pd.notna(cell) else '' for cell in df.iloc[row_idx]]
            
            # 跳过所有单元格内容都相同的行（通常是合并单元格的标题行）
            unique_cells = set(cell for cell in row_data if cell)
            if len(unique_cells) == 1:
                self.logger.info(f"第 {row_idx} 行跳过（所有单元格内容相同）: {row_data[:4]}...")
                continue
            
            # 基础分数：匹配的单元格数量
            base_score = sum(1 for cell in row_data 
                            if any(keyword in cell for keyword in header_keywords))
            
            # 特征加分：包含表头特征词
            feature_bonus = sum(2 for cell in row_data 
                               if any(keyword in cell for keyword in header_feature_keywords))
            
            # 总分 = 基础分 + 特征加分
            score = base_score + feature_bonus
            
            self.logger.info(f"第 {row_idx} 行匹配分数: {score} (基础:{base_score}, 特征:{feature_bonus}), 内容: {row_data[:4]}...")
            
            # 如果这一行匹配度更高，或者分数相同但行号更大（优先选择后面的行），记录下来
            if score > best_score or (score == best_score and best_match and row_idx > best_match[0]):
                best_score = score
                best_match = (row_idx, row_data, score)
        
        # 如果找到了匹配的行（至少匹配1个关键词）
        if best_score > 0:
            self.logger.info(f"✅ 选择第 {best_match[0]} 行作为表头，总分数: {best_score}")
            return best_match
        
        return None
    
    # ==================== 单表格解析方法 ====================
    
    def parse_single_markdown_table_to_dict(self, markdown_table: str, table_type: str = None) -> Dict:
        """
        解析单张markdown表格为字典格式
        
        Args:
            markdown_table: 单张markdown表格内容（不包含HTML）
            table_type: 表格类型
            
        Returns:
            科目-数值的字典
        """
        data_dict = {}
        
        # 判断是否为资产负债表
        is_balance_sheet = self._is_balance_sheet_type(table_type)
        
        try:
            # 移除所有的```标记
            lines = markdown_table.split('\n')
            filtered_lines = []
            
            for line in lines:
                stripped = line.strip()
                if stripped.startswith('```') or stripped == '```':
                    continue
                filtered_lines.append(stripped)
            
            # 提取表格行（只处理以|开头的行）
            table_lines = []
            for line in filtered_lines:
                if line.startswith('|'):
                    table_lines.append(line)
            
            if not table_lines:
                self.logger.warning("未找到有效的markdown表格行")
                return data_dict
            
            # 解析所有非分隔行为单元格数组
            all_rows = []
            for line in table_lines:
                # 跳过分隔行
                if re.match(r'^\|[\s\-:|]+\|$', line):
                    continue
                # 分割单元格
                cells = [cell.strip() for cell in line.split('|')[1:-1]]
                all_rows.append(cells)
            
            if not all_rows:
                self.logger.warning("未找到有效的数据行")
                return data_dict
            
            # 使用 find_header_row 在前几行中查找最佳表头（与HTML表格解析逻辑一致）
            df = pd.DataFrame(all_rows)
            header_info = self.find_header_row(df, max_rows_to_check=3)
            
            if header_info:
                header_row_idx, headers, score = header_info
                rows = all_rows[header_row_idx + 1:]
            else:
                # 未找到合适的表头，默认第一行为表头
                self.logger.warning("未在前3行找到合适的表头，默认使用第一行")
                headers = all_rows[0]
                rows = all_rows[1:]
            
            # 调用统一的表格解析逻辑（快速路径）
            data_dict, needs_rescue, rescue_reason = self.parse_table_rows(
                headers, rows, is_balance_sheet, table_type
                )
            
            # ==================== LLM Fallback ====================
            # rescue信号 或者 结果不足时, 用完整 all_rows 触发 LLM
            if (needs_rescue or len(data_dict) < 10) and self.llm and table_type:
                self.logger.info(
                    f"触发LLM辅助，原因:{rescue_reason or '结果不足'}，当前结果：（{len(data_dict)} 条）"
                )
                llm_result = self._llm_detect_table_structure(all_rows, table_type)
                if llm_result:
                    llm_header_row = llm_result.get("header_row", -1)
                    llm_mapping = llm_result.get("column_mapping", [])
                    if 0 <= llm_header_row < len(all_rows) and llm_mapping:
                        llm_headers = all_rows[llm_header_row]
                        llm_rows = all_rows[llm_header_row + 1:]
                        llm_data_dict, _, _ = self.parse_table_rows(
                            llm_headers, llm_rows, is_balance_sheet, table_type,
                            column_mapping=llm_mapping
                        )
                        
                        self.logger.info(
                            f"LLM 辅助解析完成,直接使用LLM结果({len(llm_data_dict)} 条)"
                        )
                        data_dict = llm_data_dict
            
            return data_dict
            
        except Exception as e:
            self.logger.error(f"解析单张markdown表格失败: {e}")
            import traceback
            self.logger.error(traceback.format_exc())
        
        return data_dict
    
    def parse_single_html_table_to_dict(self, html_table: str, table_type: str = None) -> Dict:
        """
        解析单张HTML表格为字典格式（使用pandas）
        
        Args:
            html_table: 单张HTML表格内容
            table_type: 表格类型
            
        Returns:
            科目-数值的字典
        """
        data_dict = {}
        
        is_balance_sheet = self._is_balance_sheet_type(table_type)
        
        try:
            dfs = pd.read_html(io.StringIO(html_table))
            
            if not dfs:
                self.logger.warning("未从HTML中解析到表格")
                return data_dict
            
            df = dfs[0]
            self.logger.info(f"成功解析HTML表格，大小: {df.shape}")
            
            # 在前3行中查找最佳表头
            header_info = self.find_header_row(df, max_rows_to_check=3)
            
            # 将 DataFrame 转为 all_rows（统一格式，供 LLM fallback 使用）
            all_rows = []
            for idx in range(len(df)):
                all_rows.append([str(cell).strip() if pd.notna(cell) else '' for cell in df.iloc[idx]])
            
            if header_info:
                # 找到了表头行
                header_row_idx, headers, score = header_info
                rows = all_rows[header_row_idx + 1:]
            else:
                # 未找到合适的表头，使用 DataFrame 的列名
                self.logger.warning("未在前3行找到合适的表头，使用 pandas 列名")
                headers = [str(col).strip() for col in df.columns]
                rows = all_rows
            
            # 快速路径
            data_dict, needs_rescue, rescue_reason = self.parse_table_rows(
                headers, rows, is_balance_sheet, table_type
                )
            
            # ==================== LLM Fallback ====================
            if (needs_rescue or len(data_dict) < 10) and self.llm and table_type and all_rows:
                self.logger.info(
                    f"触发LLM辅助，原因:{rescue_reason or '结果不足'}，当前结果：（{len(data_dict)} 条）"
                )
                llm_result = self._llm_detect_table_structure(all_rows, table_type)
                if llm_result:
                    llm_header_row = llm_result.get("header_row", -1)
                    llm_mapping = llm_result.get("column_mapping", [])
                    if 0 <= llm_header_row < len(all_rows) and llm_mapping:
                        llm_headers = all_rows[llm_header_row]
                        llm_rows = all_rows[llm_header_row + 1:]
                        llm_data_dict, _, _ = self.parse_table_rows(
                            llm_headers, llm_rows, is_balance_sheet, table_type,
                            column_mapping=llm_mapping
                        )
                        self.logger.info(
                            f"LLM 辅助解析完成,直接使用LLM结果({len(llm_data_dict)} 条)"
                        )
                        data_dict = llm_data_dict
            
            return data_dict
            
        except Exception as e:
            self.logger.error(f"解析单张HTML表格失败: {e}")
            import traceback
            self.logger.error(traceback.format_exc())
        
        return data_dict
    
    def merge_table_dicts(self, table_dicts: List[Dict], table_type: str = None) -> Dict:
        """
        合并多张表格的字典数据
        
        Args:
            table_dicts: 表格字典列表
            table_type: 表格类型
            
        Returns:
            合并后的字典
            
        合并策略：
            - 相同科目的值取最后出现的值（覆盖）
            - 对于资产负债表：[年初, 期末] 整体覆盖
            - 对于其他报表：单值覆盖
        """
        if not table_dicts:
            return {}
        
        if len(table_dicts) == 1:
            return table_dicts[0]
        
        # 合并所有字典（后面的覆盖前面的）
        merged_dict = {}
        
        for i, table_dict in enumerate(table_dicts):
            self.logger.info(f"合并第 {i+1} 张表格，包含 {len(table_dict)} 个科目")
            
            for key, value in table_dict.items():
                # 后面的值覆盖前面的值
                merged_dict[key] = value
        
        self.logger.info(f"合并完成，最终包含 {len(merged_dict)} 个科目")
        
        return merged_dict
    
    # ==================== 核心解析逻辑 ====================
    
    def _llm_detect_table_structure(self, all_rows: List[List[str]], table_type: str) -> Optional[Dict]:
        """
        通过 LLM 识别表头行和列映射关系
        
        当关键词匹配和内容分析都无法正确识别表格结构时（如 OCR 严重损坏表头），
        使用 LLM 结合表头和数据行内容进行综合判断。
        
        Args:
            all_rows: 所有行数据（含表头），每行是字符串列表
            table_type: 表格类型（如"资产负债表""利润表""现金流量表"）
            
        Returns:
            {"header_row": int, "column_mapping": list} 或 None（失败时）
            column_mapping 为数组格式: [{"col_index": int, "original_header": str, "mapped_to": str}, ...]
        """
        if not self.llm or not all_rows or not table_type:
            return None
        
        try:
            from fin_stmts_parse.config.prompts import PROMPTS
            from fin_stmts_parse.utils.str_util import extract_llm_json
            
            # 1. 根据表类型选择对应的 prompt
            prompt_map = {
                "balance": "SP_MD_BS_DETECT",
                "profit": "SP_MD_IS_DETECT",
                "cashflow": "SP_MD_CS_DETECT",
            }
            prompt_key = prompt_map.get(self._canonical_statement_type(table_type))
            
            if not prompt_key or prompt_key not in PROMPTS:
                self.logger.warning(f"LLM 表格结构检测：未知的表类型 '{table_type}'，跳过")
                return None
            
            # 2. 格式化输入数据（取前 N 行：表头候选 + 数据行上下文）
            # 每个单元格带列索引前缀，便于LLM返回col_index
            max_rows = min(8, len(all_rows))
            rows_text = []
            for idx in range(max_rows):
                row = all_rows[idx]
                cells_repr = ", ".join(
                    f'col{col_i}:"{cell.strip()}"' if cell.strip() else f'col{col_i}:""'
                    for col_i, cell in enumerate(row)
                )
                rows_text.append(f"第{idx}行: [{cells_repr}]")
            
            user_message = "\n".join(rows_text)
            self.logger.info(f"LLM 表格结构检测：调用 LLM，表类型={table_type}，输入行数={max_rows}")
            self.logger.debug(f"LLM 输入数据:\n{user_message}")
            
            # 3. 调用 LLM
            result = self.llm.chat(
                system_prompt=PROMPTS[prompt_key],
                user_message=user_message
            )
            
            # 4. 解析 LLM 返回的 JSON
            parsed = extract_llm_json(result)

            self.logger.debug(f"提示词: {PROMPTS[prompt_key]}")
            self.logger.debug(f"LLM 返回:\n{result}")
            
            header_row = parsed.get("header_row", -1)
            column_mapping = parsed.get("column_mapping", [])
            
            if header_row < 0 or not column_mapping:
                self.logger.warning(f"LLM 表格结构检测：LLM 未能识别表头行（header_row={header_row}）")
                return None
            
            # 5. 校验 column_mapping 格式（每个元素必须包含 col_index 和 mapped_to）
            valid_entries = []
            for entry in column_mapping:
                if isinstance(entry, dict) and "col_index" in entry and "mapped_to" in entry:
                    entry["col_index"] = int(entry["col_index"])
                    valid_entries.append(entry)
            
            if not valid_entries:
                self.logger.warning("LLM 表格结构检测：column_mapping 格式无效，无有效条目")
                return None
            
            self.logger.info(
                f"LLM 表格结构检测成功：header_row={header_row}, "
                f"column_mapping={valid_entries}"
            )
            return {"header_row": header_row, "column_mapping": column_mapping}
            
        except Exception as e:
            self.logger.error(f"LLM 表格结构检测失败: {e}")
            import traceback
            self.logger.error(traceback.format_exc())
            return None

    @staticmethod
    def _column_in_regions(col_idx: int, regions: List[Tuple[int, int]]) -> bool:
        return any(start <= col_idx < end for start, end in regions)

    @staticmethod
    def _cashflow_supplement_column_regions(
        cleaned_headers: List[str],
        item_like_columns: List[int],
    ) -> Tuple[List[int], List[Tuple[int, int]]]:
        supplement_item_columns = [
            idx for idx, header in enumerate(cleaned_headers)
            if '补充资料' in header
        ]
        supplement_regions = []
        if not supplement_item_columns:
            return supplement_item_columns, supplement_regions

        all_item_like_columns = sorted(set(item_like_columns + supplement_item_columns))
        for supplement_col in supplement_item_columns:
            next_item_col = next(
                (
                    col_idx for col_idx in all_item_like_columns
                    if col_idx > supplement_col
                ),
                len(cleaned_headers),
            )
            supplement_regions.append((supplement_col, next_item_col))

        return supplement_item_columns, supplement_regions

    def _apply_column_mapping(
        self,
        headers: List,
        cleaned_headers: List,
        column_mapping: List,
        is_balance_sheet: bool,
        table_type: str = None,
    ):
        """
        根据 LLM 返回的 column_mapping 直接定位项目列和数值列
        
        Args:
            headers: 原始表头列表
            cleaned_headers: 清洗后的表头列表
            column_mapping: LLM 返回的数组格式映射，每个元素为
                            {"col_index": int, "original_header": str, "mapped_to": str}
            is_balance_sheet: 是否为资产负债表
            table_type: 表格类型
            
        Returns:
            (item_name_columns, beginning_balance_cols, ending_balance_cols) 三元组
        """
        item_name_columns = []
        beginning_balance_cols = []
        ending_balance_cols = []
        
        item_field_names = {'项目', '资产', '负债和所有者权益'}
        beginning_field_names = {
            '期初余额',
            '上年累计金额',
            '上年累计数',
            '上年同期金额',
            '上年同期数',
            '上期金额',
            '上期数',
        }
        ending_field_names = {'期末余额', '本年累计金额', '本期金额', '累计金额'}
        ending_field_priorities = {
            '本年累计金额': 1,
            '累计金额': 1,
            '本期金额': 2,
            '期末余额': 2,
        }
        is_cashflow_statement = self._is_cashflow_statement_type(table_type)
        is_period_pair_statement = self._is_period_pair_statement_type(table_type)
        mapped_item_like_columns = []
        ending_candidates = []
        for entry in column_mapping:
            idx = entry.get("col_index")
            standard_field = entry.get("mapped_to", "")
            if idx is None or standard_field not in item_field_names:
                continue
            if 0 <= idx < len(headers):
                mapped_item_like_columns.append(idx)

        supplement_item_columns, supplement_regions = [], []
        if is_cashflow_statement:
            supplement_item_columns, supplement_regions = self._cashflow_supplement_column_regions(
                cleaned_headers,
                mapped_item_like_columns,
            )
            if supplement_item_columns:
                self.logger.info(
                    f"LLM 引导模式识别补充资料列: {supplement_item_columns}, "
                    f"补充资料区间: {supplement_regions}"
                )

        for entry in column_mapping:
            idx = entry.get("col_index")
            standard_field = entry.get("mapped_to", "")
            if idx is None or not standard_field:
                continue
            if idx < 0 or idx >= len(headers):
                self.logger.warning(f"LLM 引导模式：col_index={idx} 超出表头范围（0~{len(headers)-1}），跳过")
                continue
            if self._column_in_regions(idx, supplement_regions):
                continue

            if standard_field in item_field_names:
                item_name_columns.append(idx)
            elif standard_field in beginning_field_names:
                beginning_balance_cols.append(idx)
            elif standard_field in ending_field_names:
                ending_balance_cols.append(idx)
                ending_candidates.append((idx, ending_field_priorities.get(standard_field, 99)))

        if not is_balance_sheet and ending_candidates:
            best_priority = min(priority for _idx, priority in ending_candidates)
            ending_balance_cols = [
                idx for idx, priority in ending_candidates if priority == best_priority
            ]

        if is_period_pair_statement:
            previous_keywords = [
                '上年累计',
                '上年同期',
                '上期累计',
                '上期金额',
                '上期数',
                '上期',
                '上年数',
                '上年金额',
                '上年',
            ]
            for idx, header in enumerate(cleaned_headers):
                if idx in item_name_columns or idx in beginning_balance_cols:
                    continue
                if self._column_in_regions(idx, supplement_regions):
                    continue
                if any(keyword in header for keyword in previous_keywords):
                    beginning_balance_cols.append(idx)
        
        item_name_columns.sort()
        beginning_balance_cols.sort()
        ending_balance_cols.sort()
        
        self.logger.info(
            f"LLM 引导模式 - 项目列: {item_name_columns}, "
            f"期初列: {beginning_balance_cols}, 期末列: {ending_balance_cols}"
        )
        
        return item_name_columns, beginning_balance_cols, ending_balance_cols
    
    def _autonomous_column_detection(
        self,
        headers: List,
        cleaned_headers: List,
        rows: List,
        is_balance_sheet: bool,
        table_type: str = None,
    ):
        """
        自主模式：通过关键词匹配 + 内容分析定位项目列和数值列
        
        Args:
            headers: 原始表头列表
            cleaned_headers: 清洗后的表头列表
            rows: 数据行列表
            is_balance_sheet: 是否为资产负债表
            table_type: 表格类型
            
        Returns:
            (item_name_columns, beginning_balance_cols, ending_balance_cols) 三元组
        """
        def column_looks_like_item_name(col_idx: int) -> bool:
            non_empty_count = 0
            text_like_count = 0

            for row in rows[:12]:
                if col_idx >= len(row):
                    continue
                cell_text = self.clean_item_text(str(row[col_idx]).strip())
                if not cell_text:
                    continue

                non_empty_count += 1
                if not looks_like_numeric_cell(cell_text):
                    text_like_count += 1

            if non_empty_count == 0:
                return False
            return text_like_count >= 2 or (text_like_count / non_empty_count) >= 0.6

        def column_is_identifier_column(col_idx: int) -> bool:
            if col_idx < 0 or col_idx >= len(cleaned_headers):
                return False
            header = cleaned_headers[col_idx]
            identifier_keywords = ['附注', '注释', '注释号', '行次', '行号', '序号']
            return any(keyword in header for keyword in identifier_keywords)

        def looks_like_identifier_marker(cell_text: str) -> bool:
            marker = str(cell_text or "").strip()
            marker = marker.replace('（', '(').replace('）', ')')
            marker = re.sub(r'\s+', '', marker)
            if not marker or marker in {'-', '—', '－'}:
                return False
            if looks_like_numeric_cell(marker):
                return True

            chinese_num = r'一二三四五六七八九十百千万零〇'
            roman_num = r'ivxlcdmIVXLCDM'
            marker_pattern = (
                rf'^(?:附注|注释)?'
                rf'\(?[{chinese_num}{roman_num}\d]+\)?'
                rf'(?:[、.．-]?\(?[{chinese_num}{roman_num}\d]+\)?)*$'
            )
            return bool(re.fullmatch(marker_pattern, marker))

        def column_looks_like_identifier_values(col_idx: int) -> bool:
            non_empty_count = 0
            identifier_count = 0
            descriptive_count = 0

            for row in rows[:30]:
                if col_idx >= len(row):
                    continue
                cell_text = str(row[col_idx]).strip()
                if not cell_text or cell_text in {'-', '—', '－'}:
                    continue

                non_empty_count += 1
                if looks_like_identifier_marker(cell_text):
                    identifier_count += 1
                elif re.search(r'[\u4e00-\u9fa5]', self.clean_item_text(cell_text)):
                    descriptive_count += 1

            if non_empty_count == 0:
                return False
            return (
                identifier_count >= 2
                and identifier_count / non_empty_count >= 0.6
                and descriptive_count == 0
            )

        def looks_like_numeric_cell(cell_text: str) -> bool:
            value_str = str(cell_text).strip()
            value_str = value_str.replace('**', '').replace('*', '')
            value_str = value_str.replace(',', '').replace('，', '')
            value_str = value_str.strip()
            if not value_str or value_str == '-':
                return False
            try:
                float(value_str)
                return True
            except Exception:
                return False

        def infer_balance_sheet_item_columns(
            current_item_columns: List[int],
            current_beginning_cols: List[int],
            current_ending_cols: List[int],
        ) -> List[int]:
            inferred_columns = list(current_item_columns)
            if not current_beginning_cols or not current_ending_cols:
                return sorted(set(inferred_columns))

            pair_count = min(len(current_beginning_cols), len(current_ending_cols))
            occupied_columns = set(current_item_columns + current_beginning_cols + current_ending_cols)
            previous_pair_end = 0

            for pair_idx in range(pair_count):
                pair_start = min(current_beginning_cols[pair_idx], current_ending_cols[pair_idx])
                candidate_column = None

                for col_idx in range(pair_start - 1, previous_pair_end - 1, -1):
                    if col_idx in occupied_columns:
                        continue
                    if column_is_identifier_column(col_idx):
                        continue
                    if column_looks_like_identifier_values(col_idx):
                        continue
                    if column_looks_like_item_name(col_idx):
                        candidate_column = col_idx
                        break

                if candidate_column is not None:
                    inferred_columns.append(candidate_column)
                    occupied_columns.add(candidate_column)

                previous_pair_end = max(current_beginning_cols[pair_idx], current_ending_cols[pair_idx]) + 1

            if 0 not in inferred_columns and column_looks_like_item_name(0):
                inferred_columns.append(0)

            return sorted(set(inferred_columns))

        is_cashflow_statement = self._is_cashflow_statement_type(table_type)
        is_period_pair_statement = self._is_period_pair_statement_type(table_type)

        # ==================== 步骤2：定位项目列 ====================
        # --- 方法：基于表头关键词检测 ---
        item_name_columns = []
        item_name_keywords = [
            '项目', '资产', '资', '负债', '所有者权益', '股东权益', '权益', '科目', '补充资料'
        ]
        
        for idx, header in enumerate(cleaned_headers):
            # 严格匹配关键词
            if any(keyword in header for keyword in item_name_keywords):
                item_name_columns.append(idx)
        
        self.logger.info(f"表头关键词检测项目列: {item_name_columns}")

        supplement_item_columns = []
        supplement_regions = []
        if is_cashflow_statement:
            supplement_item_columns, supplement_regions = self._cashflow_supplement_column_regions(
                cleaned_headers,
                item_name_columns,
            )
            if supplement_item_columns:
                item_name_columns = [
                    col_idx for col_idx in item_name_columns
                    if col_idx not in supplement_item_columns
                ]
                self.logger.info(
                    f"现金流量表识别补充资料列: {supplement_item_columns}, "
                    f"补充资料区间: {supplement_regions}, 主表项目列: {item_name_columns}"
                )

        if len(item_name_columns) > 1:
            filtered_item_columns = [
                col_idx
                for col_idx in item_name_columns
                if not column_looks_like_identifier_values(col_idx)
            ]
            if filtered_item_columns and filtered_item_columns != item_name_columns:
                self.logger.info(
                    f"根据列内容剔除附注/行次类伪项目列: "
                    f"{sorted(set(item_name_columns) - set(filtered_item_columns))}"
                )
                item_name_columns = filtered_item_columns

        # --- 兜底：如果仍未找到，默认第一列为项目列 ---
        if not item_name_columns:
            if is_cashflow_statement and supplement_item_columns:
                self.logger.info("现金流量表仅识别到补充资料列，跳过主表项目列兜底")
            else:
                item_name_columns = [0]
        
        self.logger.info(f"最终识别项目列: {item_name_columns}")
        
        # ==================== 步骤3：定位数值列 ====================
        beginning_balance_cols = []
        ending_balance_cols = []
        date_columns = []
        
        if is_balance_sheet:
            beginning_keywords = ['年初数', '年初金额', '期初余额', '期初数', '期初金额', '上年年末余额', '上年末余额', '上年末', '年初余额', '年初值']
            ending_keywords = ['期末余额', '期末数', '期末金额', '年末数', '年末余额', '年末', '期末值']
            
            for idx, header in enumerate(cleaned_headers):
                if idx in item_name_columns:
                    continue
                is_beginning_header = any(keyword in header for keyword in beginning_keywords)
                if is_beginning_header:
                    beginning_balance_cols.append(idx)
                elif any(keyword in header for keyword in ending_keywords):
                    ending_balance_cols.append(idx)
                if self.is_date_header(header):
                    date_value = self._parse_date_from_header_safely(header)
                    if date_value:
                        date_columns.append((idx, date_value))
            
            if not beginning_balance_cols and not ending_balance_cols and date_columns:
                date_columns.sort(key=lambda x: x[1])
                if date_columns:
                    min_date = date_columns[0][1]
                    max_date = date_columns[-1][1]
                    beginning_balance_cols = [col[0] for col in date_columns if col[1] == min_date]
                    ending_balance_cols = [col[0] for col in date_columns if col[1] == max_date]
                    
            self.logger.info(f"资产负债表 - 期初列：{beginning_balance_cols}, 期末列: {ending_balance_cols}")
        
        else:
            previous_keywords_priority = [
                (
                    [
                        '上年累计',
                        '上年累计金额',
                        '上年累计数',
                        '上年同期',
                        '上年同期金额',
                        '上年同期数',
                        '上期累计',
                        '上期累计金额',
                        '上期累计数',
                    ],
                    1,
                ),
                (
                    [
                        '上期金额',
                        '上期数',
                        '上期',
                        '上月数',
                        '上月金额',
                        '上年数',
                        '上年金额',
                        '上年发生额',
                        '上年',
                    ],
                    2,
                ),
            ]
            ending_keywords_priority = [
                (['本年累计', '本年累计金额', '本年累计数', '年初至报告期末', '年初至本期末', '本年数', '本年金额', "本年发生额", "全年累计", "累计金额"], 1),
                (['本期金额', '本期数', '本期累计', '本期累计数', '本期', '本月数', '本月金额', '期末金额', '期末数', '期末余额', '期末值', '期末', '年末数', '年末金额', '年末余额', '年末'], 2),
                (['金额'], 3),
            ]

            previous_candidates = []
            ending_candidates = []

            for idx, header in enumerate(cleaned_headers):
                if idx in item_name_columns:
                    continue
                if self._column_in_regions(idx, supplement_regions):
                    continue
                if is_period_pair_statement:
                    for keywords, priority in previous_keywords_priority:
                        if any(keyword in header for keyword in keywords):
                            previous_candidates.append((idx, priority))
                            break
                if '上年' in header or '上期' in header:
                    continue
                for keywords, priority in ending_keywords_priority:
                    if any(keyword in header for keyword in keywords):
                        ending_candidates.append((idx, priority))
                        break
                else:
                    if self.is_date_header(header):
                        date_value = self._parse_date_from_header_safely(header)
                        if date_value:
                            date_columns.append((idx, date_value))

            if previous_candidates:
                previous_candidates.sort(key=lambda x: x[1])
                best_priority = previous_candidates[0][1]
                beginning_balance_cols = [col[0] for col in previous_candidates if col[1] == best_priority]
                self.logger.info(f"选择上期列: 索引{beginning_balance_cols}, 优先级{best_priority}")

            if ending_candidates:
                ending_candidates.sort(key=lambda x: x[1])
                best_priority = ending_candidates[0][1]
                ending_balance_cols = [col[0] for col in ending_candidates if col[1] == best_priority]
                self.logger.info(f"选择期末列: 索引{ending_balance_cols}, 优先级{best_priority}")
            
            if not ending_balance_cols and date_columns:
                max_date = max(date_columns, key=lambda x: x[1])[1]
                ending_balance_cols = [col[0] for col in date_columns if col[1] == max_date]
                self.logger.info(f"使用日期列作为期末: 索引{ending_balance_cols}")

            if is_period_pair_statement and not beginning_balance_cols and date_columns:
                unique_dates = sorted({date_value for _idx, date_value in date_columns})
                if len(unique_dates) >= 2:
                    previous_date = unique_dates[-2]
                    beginning_balance_cols = [
                        col_idx for col_idx, date_value in date_columns if date_value == previous_date
                    ]
                    self.logger.info(f"使用日期列作为上期: 索引{beginning_balance_cols}")
            
            self.logger.info(f"其他报表 - 上期列: {beginning_balance_cols}, 期末列: {ending_balance_cols}")

        if is_balance_sheet and len(beginning_balance_cols) == len(ending_balance_cols):
            inferred_item_columns = infer_balance_sheet_item_columns(
                item_name_columns,
                beginning_balance_cols,
                ending_balance_cols,
            )
            if inferred_item_columns != item_name_columns:
                self.logger.info(f"基于列内容补充项目列: {inferred_item_columns}")
                item_name_columns = inferred_item_columns
        elif 0 not in item_name_columns and column_looks_like_item_name(0):
            item_name_columns.append(0)
            item_name_columns.sort()
            self.logger.info(f"基于列内容补充首列为项目列: {item_name_columns}")
        
        return item_name_columns, beginning_balance_cols, ending_balance_cols
    
    def parse_table_rows(self, headers: List, rows: List, is_balance_sheet: bool, table_type: str = None, column_mapping: List = None) -> Tuple[Dict, bool, str]:
        """
        解析表格的headers和rows，统一处理逻辑
        
        支持两种模式：
        - 自主模式（column_mapping=None）：通过关键词匹配+内容分析定位列
        - LLM引导模式（column_mapping有值）：直接使用LLM提供的列映射
        
        Returns:
            (data_dict, needs_rescue, rescue_reason)
            - data_dict: 科目-数值字典
            - needs_rescue: 列识别是否失败，建议调用方触发 LLM 补救
            - rescue_reason: 失败原因（"no_item_col" / "bs_missing_col" / "no_value_col" / ""）
        """
        data_dict = {}
        needs_rescue = False
        rescue_reason = ""
        is_cashflow_statement = self._is_cashflow_statement_type(table_type)
        is_period_pair_statement = self._is_period_pair_statement_type(table_type)
        cashflow_section_by_col = {}

        def value_has_content(value) -> bool:
            if isinstance(value, list):
                return any(item is not None and item != "" for item in value)
            return value is not None and value != ""

        def set_item_value(item_name: str, value) -> None:
            existing_value = data_dict.get(item_name)
            if (
                item_name in data_dict
                and value_has_content(existing_value)
                and not value_has_content(value)
            ):
                return
            data_dict[item_name] = value

        def normalize_cashflow_text(text: str) -> str:
            normalized = html.unescape(str(text).strip())
            normalized = normalized.replace('**', '').replace('*', '')
            normalized = re.sub(r'\s+', '', normalized)
            normalized = normalized.replace('：', ':')
            normalized = re.sub(r'^[一二三四五六七八九十\d]+[、,\.．]', '', normalized)
            return normalized.rstrip(':：。，、,')

        def update_cashflow_section(item_name: str, name_col_idx: int) -> None:
            if not is_cashflow_statement:
                return
            normalized = normalize_cashflow_text(item_name)
            if "净额" in normalized:
                return
            if normalized in {"经营活动产生的现金流量", "经营活动现金流量"}:
                cashflow_section_by_col[name_col_idx] = "经营活动"
            elif normalized in {"投资活动产生的现金流量", "投资活动现金流量"}:
                cashflow_section_by_col[name_col_idx] = "投资活动"
            elif normalized in {"筹资活动产生的现金流量", "筹资活动现金流量"}:
                cashflow_section_by_col[name_col_idx] = "筹资活动"

        def contextualize_cashflow_item(item_name: str, name_col_idx: int) -> str:
            if not is_cashflow_statement:
                return item_name
            normalized = normalize_cashflow_text(item_name)
            if normalized in {"现金流入小计", "现金流出小计"}:
                section = cashflow_section_by_col.get(name_col_idx)
                if section:
                    return f"{section}{normalized}"
            return item_name

        try:
            # ==================== 步骤1：清洗表头 ====================
            cleaned_headers = []
            for header in headers:
                cleaned = html.unescape(str(header).strip())
                cleaned = cleaned.replace('**', '').replace('*', '')
                cleaned = cleaned.replace(':', '').replace('：', '')
                cleaned = re.sub(r'\s+', '', cleaned)
                cleaned_headers.append(cleaned)
            
            self.logger.info(f"表头清洗完成: {cleaned_headers}")
            
            # ==================== LLM引导模式：通过column_mapping直接定位列 ====================
            if column_mapping:
                self.logger.info(f"使用 LLM 引导模式，column_mapping: {column_mapping}")

                item_name_columns, beginning_balance_cols, ending_balance_cols = \
                    self._apply_column_mapping(
                        headers,
                        cleaned_headers,
                        column_mapping,
                        is_balance_sheet,
                        table_type,
                    )
                
            else:
                # ==================== 自主模式：步骤2+3 ====================
                item_name_columns, beginning_balance_cols, ending_balance_cols = \
                    self._autonomous_column_detection(
                        headers,
                        cleaned_headers,
                        rows,
                        is_balance_sheet,
                        table_type,
                    )

                # ==================== 列完整性校验 ====================
                if not item_name_columns:
                    self.logger.warning("自主检测：未找到项目列，建议 LLM 补救")
                    needs_rescue = True
                    rescue_reason = "no_item_col"
                elif is_balance_sheet:
                    if not beginning_balance_cols or not ending_balance_cols:
                        self.logger.warning(
                            f"自主检测：资产负债表缺少必要列"
                            f"（期初={beginning_balance_cols}，期末={ending_balance_cols}），建议 LLM 补救"
                        )
                        needs_rescue = True
                        rescue_reason = "bs_missing_col"
                    elif len(beginning_balance_cols) != len(ending_balance_cols):
                        self.logger.warning(
                            f"自主检测：资产负债表期初/期末列数量不一致"
                            f"（项目列={item_name_columns}，期初={beginning_balance_cols}，期末={ending_balance_cols}），建议 LLM 补救"
                        )
                        needs_rescue = True
                        rescue_reason = "bs_ambiguous_col"
                    elif len(item_name_columns) == 1 and (
                        len(beginning_balance_cols) != 1 or len(ending_balance_cols) != 1
                    ):
                        self.logger.warning(
                            f"自主检测：单个项目列却匹配到多对期初/期末列"
                            f"（项目列={item_name_columns}，期初={beginning_balance_cols}，期末={ending_balance_cols}），建议 LLM 补救"
                        )
                        needs_rescue = True
                        rescue_reason = "bs_ambiguous_col"
                    elif len(item_name_columns) < len(beginning_balance_cols):
                        self.logger.warning(
                            f"自主检测：项目列数量少于期初/期末列对数"
                            f"（项目列={item_name_columns}，期初={beginning_balance_cols}，期末={ending_balance_cols}），建议 LLM 补救"
                        )
                        needs_rescue = True
                        rescue_reason = "bs_ambiguous_col"
                else:
                    if not ending_balance_cols:
                        self.logger.warning("自主检测：未找到数值列，建议 LLM 补救")
                        needs_rescue = True
                        rescue_reason = "no_value_col"
                    elif len(item_name_columns) == 1 and len(ending_balance_cols) != 1:
                        self.logger.warning(
                            f"自主检测：单个项目列却匹配到多个数值列"
                            f"（项目列={item_name_columns}，数值列={ending_balance_cols}），建议 LLM 补救"
                        )
                        needs_rescue = True
                        rescue_reason = "value_col_mismatch"
                    elif len(item_name_columns) < len(ending_balance_cols):
                        self.logger.warning(
                            f"自主检测：项目列数量少于数值列数量"
                            f"（项目列={item_name_columns}，数值列={ending_balance_cols}），建议 LLM 补救"
                        )
                        needs_rescue = True
                        rescue_reason = "value_col_mismatch"

                if needs_rescue:
                    self.logger.info(f"列完整性校验未通过, 直接返回空结果等待LLM补救:{rescue_reason}")
                    return {}, needs_rescue, rescue_reason
            
            # ==================== 步骤4：构建数据字典 ====================
            for row in rows:
                if len(row) < 2:
                    continue
                
                # 遍历每个项目列（支持双栏）
                for name_col_idx in item_name_columns:
                    if name_col_idx >= len(row):
                        continue
                    
                    # 获取并清洗项目名称
                    raw_text = row[name_col_idx].strip()
                    item_name = self.clean_item_text(raw_text)

                    if not item_name:
                        continue

                    update_cashflow_section(item_name, name_col_idx)
                    item_name = contextualize_cashflow_item(item_name, name_col_idx)

                    # 确定当前项目列的数值搜索范围
                    search_start = name_col_idx
                    search_end = len(row)
                    
                    # 如果有下一个项目列，限制搜索范围
                    for next_name_col in item_name_columns:
                        if next_name_col > name_col_idx:
                            search_end = next_name_col
                            break
                    
                    # 精准提取目标列的数值
                    if is_balance_sheet:
                        # 资产负债表：提取期初和期末
                        beginning_value = None
                        ending_value = None
                        
                        for col_idx in beginning_balance_cols:
                            if search_start < col_idx < search_end:
                                beginning_value = self.extract_numeric_value(row[col_idx])
                                if beginning_value is not None:
                                    break
                        
                        for col_idx in ending_balance_cols:
                            if search_start < col_idx < search_end:
                                ending_value = self.extract_numeric_value(row[col_idx])
                                if ending_value is not None:
                                    break

                        set_item_value(item_name, [beginning_value, ending_value])

                    else:
                        # 利润表/现金流量表提取 [上年/上期, 当前/最新]
                        previous_value = None
                        ending_value = None

                        if is_period_pair_statement:
                            for col_idx in beginning_balance_cols:
                                if search_start < col_idx < search_end:
                                    previous_value = self.extract_numeric_value(row[col_idx])
                                    if previous_value is not None:
                                        break

                        for col_idx in ending_balance_cols:
                            if search_start < col_idx < search_end:
                                ending_value = self.extract_numeric_value(row[col_idx])
                                if ending_value is not None:
                                    break

                        if is_period_pair_statement:
                            set_item_value(item_name, [previous_value, ending_value])
                        else:
                            set_item_value(item_name, ending_value)
            
            self.logger.info(f"成功解析 {len(data_dict)} 个科目数据")
            
        except Exception as e:
            self.logger.error(f"解析表格行失败: {e}")
            import traceback
            self.logger.error(traceback.format_exc())
        
        return data_dict, needs_rescue, rescue_reason
    
    def extract_numeric_value(self, cell_text: str):
        """
        从单元格文本中提取数值
        
        Args:
            cell_text: 单元格文本
            
        Returns:
            float 类型的数值；空值或无法解析时返回 None
        """
        try:
            # 清洗文本
            value_str = str(cell_text).strip()
            value_str = value_str.replace('**', '').replace('*', '')
            value_str = value_str.replace(',', '').replace('，', '')
            value_str = re.sub(r'\s+', '', value_str).strip()
            if len(value_str) >= 2 and value_str.startswith('$') and value_str.endswith('$'):
                value_str = value_str[1:-1].strip()
            value_str = value_str.replace('（', '(').replace('）', ')')
            
            # 保留空值语义，避免把缺失金额误记为 0
            if not value_str or value_str in {'-', '—', '－'}:
                return None

            if len(value_str) >= 2 and value_str.startswith('(') and value_str.endswith(')'):
                value_str = f"-{value_str[1:-1]}"
            
            # 转换为浮点数
            return float(value_str)
        except:
            return None
    
    # ==================== 文本清理 ====================
    
    def clean_item_text(self, text: str) -> str:
        """
        清理科目名称
        
        Args:
            text: 原始文本
            
        Returns:
            清理后的文本
        """
        text = html.unescape(replace_excel_escaped_control_chars(text).strip())
        text = text.replace('（', '(').replace('）', ')')
        text = re.sub(r'\s+', '', text)
        text = re.sub(r'^[一二三四五六七八九十]+、', '', text)
        text = re.sub(r'^\$?\^(?:\{\{[^{}]*\}\}|\{[^{}]*\})', '', text).strip('$')
        text = text.replace('*', '')
        text = text.lstrip('△☆')
        text = text.replace('帐', '账')
        return text


# 保持向后兼容的别名
TableParser = MarkdownTableExtractor


# ==================== 测试函数 ====================

def main():
    """
    测试主函数：读取 markdown 文件并解析为字典格式
    
    使用方法：
        python markdown_table_extractor.py [markdown_file_path] [table_type]
    
    示例：
        python markdown_table_extractor.py test_table.md 资产负债表
        python markdown_table_extractor.py test_table.md 利润表
    """
    import sys
    import json
    
    # 配置日志
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    # 获取命令行参数
    if len(sys.argv) < 2:
        print("使用方法: python markdown_table_extractor.py [markdown_file_path] [table_type]")
        print("\n示例:")
        print("  python markdown_table_extractor.py test_balance_sheet.md 资产负债表")
        print("  python markdown_table_extractor.py test_profit.md 利润表")
        print("  python markdown_table_extractor.py test_cashflow.md 现金流量表")
        sys.exit(1)
    
    markdown_file = sys.argv[1]
    table_type = sys.argv[2] if len(sys.argv) > 2 else None
    
    # 检查文件是否存在
    import os
    if not os.path.exists(markdown_file):
        print(f"错误: 文件 '{markdown_file}' 不存在！")
        sys.exit(1)
    
    # 读取 markdown 文件
    print(f"\n📖 正在读取文件: {markdown_file}")
    with open(markdown_file, 'r', encoding='utf-8') as f:
        markdown_content = f.read()
    
    print(f"✅ 文件读取成功，内容长度: {len(markdown_content)} 字符")
    print("-" * 80)
    
    # 创建提取器实例
    extractor = MarkdownTableExtractor()
    
    # 提取元数据
    print("\n📊 提取元数据...")
    metadata = extractor.extract_metadata_from_markdown(markdown_content)
    print(f"  日期: {metadata.get('日期', 'N/A')}")
    print(f"  单位: {metadata.get('单位', 'N/A')}")
    print("-" * 80)
    
    # 解析表格为字典
    print(f"\n🔄 解析表格 (类型: {table_type or '自动识别'})...")
    data_dict = extractor.parse_markdown_table_to_dict(markdown_content, table_type)
    
    # 输出结果
    print("\n📋 解析结果:")
    print(f"  共解析 {len(data_dict)} 个科目\n")
    
    if data_dict:
        # 美化输出
        print("=" * 80)
        for item_name, value in data_dict.items():
            if isinstance(value, list):
                # 资产负债表格式：[期初, 期末]
                beginning = value[0] if value[0] is not None else 0.0
                ending = value[1] if value[1] is not None else 0.0
                print(f"  {item_name:<40} | 期初: {beginning:<15} | 期末: {ending:<15}")
            else:
                # 其他报表格式：单个值
                display_value = value if value is not None else 0.0
                print(f"  {item_name:<40} | 金额: {display_value}")
        print("=" * 80)
        
        # 保存为 JSON 文件
        output_file = markdown_file.rsplit('.', 1)[0] + '_parsed.json'
        result = {
            'metadata': metadata,
            'data': data_dict
        }
        
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        
        print(f"\n💾 解析结果已保存到: {output_file}")
    else:
        print("  ⚠️  未解析到任何数据，请检查 markdown 文件格式")
    
    print("\n✨ 测试完成！\n")


if __name__ == "__main__":
    main()

