import os
import re
import traceback
import calendar
from datetime import datetime, timedelta

import pandas as pd
# 引入处理Excel文件的库，用于判断Hidden属性
import openpyxl 
import xlrd

# 保持原有的业务包引用
from fin_stmts_parse.utils.str_util import extract_data, is_match, extract_llm_json
from fin_stmts_parse.utils.logger import logger
from fin_stmts_parse.exceptions.base_exception import ServiceError
from fin_stmts_parse.clients.llm_client import LLMClient
from fin_stmts_parse.utils.read_yaml import load_env_config
from fin_stmts_parse.config.prompts import PROMPTS
from fin_stmts_parse.src.company_name_resolver import (
    CompanyNameResolver,
    extract_company_name_by_rule,
    resolve_unique_company_name,
)

class ExcelFinancialParser:
    """
    Excel财务报表解析器
    功能：
    1. 支持 xlsx/xls 格式读取
    2. 自动过滤隐藏 Sheet
    3. 识别三大表（资产负债、利润、现金流量）
    4. 相同类型的表只保留第一个（去重）
    5. 支持大模型辅助字段映射
    """

    def __init__(self, llm_client=None):
        self.logger = logger
        self.config = load_env_config(os.getenv("RUNNING_ENV", "local"))
        if llm_client is not None:
            self.llm = llm_client
        else:
            self.llm = LLMClient(self.config.get("llm", {}))
        self.company_name_resolver = CompanyNameResolver(
            llm_client=self.llm,
            logger=self.logger,
        )

    def _build_sheet_preview_rows_text(self, file_path, sheet_name, nrows=10):
        df_raw = pd.read_excel(file_path, header=None, sheet_name=sheet_name, nrows=nrows)
        rows_text = []
        for idx, row in df_raw.iterrows():
            cells = [str(self.cell_to_date_str(cell)) if pd.notna(cell) else "" for cell in row]
            non_empty_cells = [cell for cell in cells if cell.strip()]
            rows_text.append(f"第{idx}行: {non_empty_cells}")
        return rows_text

    def _get_visible_sheet_names(self, file_path):
        """
        获取Excel文件中非隐藏（可见）的Sheet名称列表
        :param file_path: 文件路径
        :return: 可见Sheet名称列表
        """
        visible_sheets = []
        ext = os.path.splitext(file_path)[1].lower()
        
        try:
            if ext in ['.xlsx', '.xlsm']:
                # 使用 openpyxl 处理 xlsx
                wb = openpyxl.load_workbook(file_path, read_only=True, data_only=True)
                for sheet in wb:
                    if sheet.sheet_state == 'visible':
                        visible_sheets.append(sheet.title)
                wb.close()
            elif ext in ['.xls']:
                # 使用 xlrd 处理 xls
                # formatting_info=True 是必须的，否则无法读取可见性，但仅支持 xls
                wb = xlrd.open_workbook(file_path, formatting_info=True, on_demand=True)
                for sheet in wb.sheets():
                    # xlrd visibility: 0=visible, 1=hidden, 2=very hidden
                    if sheet.visibility == 0:
                        visible_sheets.append(sheet.name)
                wb.release_resources()
            else:
                # 其他格式降级处理，默认全部读取
                self.logger.warning(f"不支持的文件后缀 {ext} 用于显隐判断，将读取所有Sheet")
                return pd.ExcelFile(file_path).sheet_names
        except Exception as e:
            self.logger.error(f"检测隐藏Sheet失败，降级为读取所有Sheet。错误信息: {str(e)}")
            # 发生异常时兜底：读取所有 sheet
            return pd.ExcelFile(file_path).sheet_names
            
        return visible_sheets

    def _is_excel_date(self, value):
        """判断是否为Excel日期序列号（Excel中日期常存储为浮点数）"""
        if isinstance(value, (int, float)) and 20000 < value < 60000:
            return True
        # 处理pandas自动添加的.1, .2等后缀
        if isinstance(value, str):
            try:
                num_val = float(value.split('.')[0])
                return 20000 < num_val < 60000
            except:
                return False
        return False
    
    def _excel_date_to_datetime(self, value):
        """将Excel日期序列号转换为datetime对象"""
        try:
            if isinstance(value, str):
                num_val = float(value.split('.')[0])
            else:
                num_val = float(value)
            base_date = datetime(1899, 12, 30)
            return base_date + timedelta(days=int(num_val))
        except:
            return None
    
    def _excel_date_to_string(self, value, date_format='%Y年%m月%d日'):
        """将Excel日期序列号转换为日期字符串"""
        if self._is_excel_date(value):
            date_obj = self._excel_date_to_datetime(value)
            if date_obj:
                return date_obj.strftime(date_format)
        return str(value) if not isinstance(value, str) else value
    
    def _clean_text(self, text):
        """通用文本清洗：处理空格、制表符、换行、中文括号等"""
        text = str(text).strip()
        text = text.replace('（', '(').replace('）', ')')
        text = re.sub(r'\s+', '', text)  # 处理空格、制表符、换行等
        return text

    def cell_to_date_str(self, cell, date_format='%Y-%m-%d'):
        """
        将单个单元格值转为指定格式的日期字符串。若无法识别为日期，则返回原值。
        """
        if isinstance(cell, (pd.Timestamp, datetime)):
            return cell.strftime(date_format)
        else:
            _fmt_date = self._excel_date_to_string(cell, date_format)
            return _fmt_date

    def _clean_item_text(self, text):
        """
        科目（项目）名称专用清洗 
        """
        text = str(text).strip()
        text = text.replace('（', '(').replace('）', ')')
        text = re.sub(r'\s+', '', text)  # 去除空白字符
        text = re.sub(r'^[一二三四五六七八九十0-9]+、', '', text)  # 去除开头的序号，如"一、"或"1、"
        return text

    @staticmethod
    def _normalize_cashflow_text(text):
        text = str(text or "").strip()
        text = re.sub(r'\s+', '', text)
        text = re.sub(r'^[一二三四五六七八九十\d]+[、,\.．]', '', text)
        return text.replace('：', ':').rstrip(':：。，、,')

    def _contextualize_cashflow_item_names(self, item_names):
        section = ""
        contextualized_names = []

        for item_name in item_names:
            normalized = self._normalize_cashflow_text(item_name)
            if "净额" not in normalized:
                if normalized in {"经营活动产生的现金流量", "经营活动现金流量"}:
                    section = "经营活动"
                elif normalized in {"投资活动产生的现金流量", "投资活动现金流量"}:
                    section = "投资活动"
                elif normalized in {"筹资活动产生的现金流量", "筹资活动现金流量"}:
                    section = "筹资活动"

            if normalized in {"现金流入小计", "现金流出小计"} and section:
                contextualized_names.append(f"{section}{normalized}")
            else:
                contextualized_names.append(item_name)

        return contextualized_names
    
    def _merge_multi_column_table(self, df, key_columns, sheet_name, table_type):
        """
        通用的多栏表格合并方法
        :param df: 已重命名列名的DataFrame
        :param key_columns: 需要识别的关键列名列表（如 ["项目", "期初余额", "期末余额"]）
        :param sheet_name: Sheet名称（用于日志）
        :param table_type: 表类型（用于错误提示）
        :return: 合并后的DataFrame
        """
        # 1. 构建列名到索引的映射（支持重复列名）
        col_name_to_indices = {}
        for idx, col_name in enumerate(df.columns):
            if col_name in key_columns:
                if col_name not in col_name_to_indices:
                    col_name_to_indices[col_name] = []
                col_name_to_indices[col_name].append(idx)
        
        # 2. 验证每个关键列都存在
        missing_cols = [col for col in key_columns if col not in col_name_to_indices]
        if missing_cols:
            raise ServiceError("3", 
                f"[{sheet_name}] {table_type}缺少必要的列: {missing_cols}")
        
        # 3. 计算栏数（以出现次数最多的列为准）
        max_occurrences = max(len(indices) for indices in col_name_to_indices.values())
        min_occurrences = min(len(indices) for indices in col_name_to_indices.values())
        
        if max_occurrences != min_occurrences:
            self.logger.warning(
                f"[{sheet_name}] 关键列出现次数不一致: "
                f"{[(col, len(indices)) for col, indices in col_name_to_indices.items()]}"
            )
            # 使用最小次数作为栏数，避免数据不完整
            group_count = min_occurrences
        else:
            group_count = max_occurrences
        
        self.logger.info(f"[{sheet_name}] 检测到{group_count}栏数据，开始合并...")
        self.logger.debug(f"[{sheet_name}] 列分布: {col_name_to_indices}")
        
        # 4. 按栏提取数据
        parts = []
        for i in range(group_count):
            # 提取每个关键列的第i次出现
            group_indices = []
            group_col_names = []
            
            for col_name in key_columns:
                if i < len(col_name_to_indices[col_name]):
                    idx = col_name_to_indices[col_name][i]
                    group_indices.append(idx)
                    group_col_names.append(col_name)
            
            # 确保提取到完整的一组
            if len(group_indices) != len(key_columns):
                self.logger.warning(f"[{sheet_name}] 第{i+1}栏数据不完整，跳过")
                continue
            
            # 按索引排序，保持原始列顺序
            sorted_pairs = sorted(zip(group_indices, group_col_names))
            group_indices_sorted = [idx for idx, _ in sorted_pairs]
            group_cols_sorted = [col for _, col in sorted_pairs]
            
            part = df.iloc[:, group_indices_sorted].copy()
            part.columns = group_cols_sorted  # 使用排序后的列名
            
            # 重新排列为标准顺序
            part = part[key_columns]
            parts.append(part)
            
            self.logger.debug(
                f"[{sheet_name}] 第{i+1}栏: 列索引{group_indices_sorted} -> "
                f"列名{group_cols_sorted} -> 标准顺序{key_columns}"
            )
        
        # 5. 合并所有栏
        if not parts:
            raise ServiceError("3", f"[{sheet_name}] {table_type}未能提取到有效的栏数据")
        
        merged_df = pd.concat(parts, ignore_index=True)
        self.logger.info(f"[{sheet_name}] 成功合并{len(parts)}栏数据，共{len(merged_df)}行")
        
        return merged_df

    def _extract_date(self, text):
        """从文本中提取日期并统一转换为 %Y%m 格式"""
        range_match = re.search(
            r"(\d{4})\s*年\s*\d{1,2}\s*[\-~至到－—–～]\s*(\d{1,2})\s*月",
            str(text or ""),
        )
        if range_match:
            year, end_month = map(int, range_match.groups())
            if 1 <= end_month <= 12:
                return f"{year:04d}{end_month:02d}"

        rules = [
            {"reg": "\\d{4}年\\d{1,2}月\\d{1,2}日", "in_fmt": "%Y年%m月%d日", "out_fmt": "%Y%m"},
            {"reg": "\\d{4}年\\d{1,2}月", "in_fmt": "%Y年%m月", "out_fmt": "%Y%m"},
            {"reg": "\\d{4}年", "in_fmt": "%Y年", "out_fmt": "%Y12"},
            {"reg": "\\d{4}-\\d{1,2}-\\d{1,2}", "in_fmt": "%Y-%m-%d", "out_fmt": "%Y%m"},
            {"reg": "\\d{4}-\\d{1,2}", "in_fmt": "%Y-%m", "out_fmt": "%Y%m"},
            {"reg": "\\d{4}\\d{1,2}\\d{1,2}", "in_fmt": "%Y%m%d", "out_fmt": "%Y%m"},
            {"reg": "\\d{4}\\d{1,2}", "in_fmt": "%Y%m", "out_fmt": "%Y%m"}
        ]
        str_date = None
        for rule in rules:
            str_date = extract_data(rule['reg'], text)
            if str_date is not None:
                try:
                    str_date = datetime.strptime(str_date, rule['in_fmt']).strftime(rule['out_fmt'])
                except Exception as e:
                    self.logger.debug(f"日期格式转换失败: {str_date}, Error: {e}")
                break
        return str_date

    def _standardize_header_value(self, col, date_format='%Y-%m-%d'):
        if isinstance(col, pd.Timestamp) or isinstance(col, datetime):
            return col.strftime(date_format)
        if isinstance(col, (int, float)):
            if not pd.isna(col) and float(col).is_integer() and 1900 <= int(col) <= 2100:
                return str(int(col))
            try:
                ts = pd.to_datetime(col, origin='1899-12-30', unit='D')
                return ts.strftime(date_format)
            except Exception:
                return str(col)
        return str(col) if pd.notna(col) else 'Unnamed'

    def standardize_header_dates(self, df, date_format='%Y-%m-%d'):
        """将 DataFrame 的列名中属于日期类型的项转换为标准格式的字符串"""
        new_columns = []
        for col in df.columns:
            new_columns.append(self._standardize_header_value(col, date_format))
        df.columns = new_columns
        return df

    def _column_header_match_candidates(self, value):
        """生成列名匹配候选，兼容 pandas 日期列名和重复列后缀。"""
        candidates = []

        def add_candidate(candidate):
            if candidate is None:
                return
            candidate = str(candidate).strip()
            if candidate and candidate not in candidates:
                candidates.append(candidate)

        add_candidate(value)

        if isinstance(value, (pd.Timestamp, datetime)):
            add_candidate(value.strftime('%Y-%m-%d'))
            add_candidate(value.strftime('%Y年%m月%d日'))
            add_candidate(f"{value.year}年{value.month}月{value.day}日")
        else:
            value_text = str(value).strip()
            duplicate_suffix_removed = re.sub(r'\.\d+$', '', value_text)
            if duplicate_suffix_removed != value_text:
                add_candidate(duplicate_suffix_removed)

            try:
                excel_serial = float(duplicate_suffix_removed)
            except (TypeError, ValueError):
                excel_serial = None

            if (
                excel_serial is not None
                and excel_serial.is_integer()
                and self._is_excel_date(excel_serial)
            ):
                excel_date = self._excel_date_to_datetime(excel_serial)
                if excel_date:
                    add_candidate(excel_date.strftime('%Y-%m-%d'))
                    add_candidate(excel_date.strftime('%Y年%m月%d日'))
                    add_candidate(f"{excel_date.year}年{excel_date.month}月{excel_date.day}日")

            parsed_date = pd.to_datetime(value_text, errors='coerce')
            if not pd.isna(parsed_date):
                add_candidate(parsed_date.strftime('%Y-%m-%d'))
                add_candidate(parsed_date.strftime('%Y年%m月%d日'))
                add_candidate(f"{parsed_date.year}年{parsed_date.month}月{parsed_date.day}日")

        return candidates

    def _build_column_mapping_lookup(self, column_mapping_raw):
        """把 LLM 返回的原始列名映射展开为可按多种列名格式命中的 lookup。"""
        lookup = {}
        for raw_col, mapped_value in column_mapping_raw.items():
            for candidate in self._column_header_match_candidates(raw_col):
                lookup.setdefault(candidate, mapped_value)
        return lookup

    def _parse_header_date_value(self, value):
        """识别表头中的日期/期间，用于兜底定位本期金额列。"""
        if isinstance(value, (pd.Timestamp, datetime)):
            return datetime(value.year, value.month, value.day)

        if isinstance(value, (int, float)) and not pd.isna(value):
            int_value = int(value)
            if 1900 <= int_value <= 2100:
                return datetime(int_value, 12, 31)
            if self._is_excel_date(value):
                return self._excel_date_to_datetime(value)

        text = str(value or "").strip()
        if not text:
            return None

        text = re.sub(r"\.\d+$", "", text)
        text = re.sub(r"\s+", "", text)

        match_special = re.search(
            r"(\d{4})年?(上半年|下半年|半年度|([一二三四1-4])季度|年度)",
            text,
        )
        if match_special:
            year = int(match_special.group(1))
            suffix = match_special.group(2)
            month, day = 12, 31
            if suffix in {"上半年", "半年度"}:
                month, day = 6, 30
            elif suffix == "下半年":
                month, day = 12, 31
            elif "季度" in suffix:
                quarter_key = match_special.group(3)
                quarter_map = {
                    "一": 3,
                    "1": 3,
                    "二": 6,
                    "2": 6,
                    "三": 9,
                    "3": 9,
                    "四": 12,
                    "4": 12,
                }
                month = quarter_map.get(quarter_key, 12)
                day = calendar.monthrange(year, month)[1]
            return datetime(year, month, day)

        match_range = re.search(r"(\d{4})年\d{1,2}[-~至](\d{1,2})月", text)
        if match_range:
            year = int(match_range.group(1))
            month = int(match_range.group(2))
            return datetime(year, month, calendar.monthrange(year, month)[1])

        match_cn = re.search(r"(\d{4})年(\d{1,2})月(?:(\d{1,2})日?)?", text)
        if match_cn:
            year = int(match_cn.group(1))
            month = int(match_cn.group(2))
            day = int(match_cn.group(3)) if match_cn.group(3) else calendar.monthrange(year, month)[1]
            return datetime(year, month, day)

        match_sep = re.search(r"(\d{4})[-/.](\d{1,2})(?:[-/.](\d{1,2}))?", text)
        if match_sep:
            year = int(match_sep.group(1))
            month = int(match_sep.group(2))
            day = int(match_sep.group(3)) if match_sep.group(3) else calendar.monthrange(year, month)[1]
            return datetime(year, month, day)

        match_year = re.search(r"^(\d{4})年?$", text)
        if match_year:
            return datetime(int(match_year.group(1)), 12, 31)

        return None

    def _augment_column_mapping_with_date_headers(self, tab_header, column_mapping, table_type):
        """当 LLM/正则没有识别金额列时，用日期表头补齐当前期金额列。"""
        augmented_mapping = dict(column_mapping or {})
        mapped_values = set(augmented_mapping.values())

        date_columns = []
        for title in tab_header:
            if augmented_mapping.get(title) in {"项目", "资产", "负债和所有者权益", "附注"}:
                continue
            parsed_date = self._parse_header_date_value(title)
            if parsed_date:
                date_columns.append((title, parsed_date))

        if not date_columns:
            return augmented_mapping

        if table_type == "资产负债表":
            date_columns.sort(key=lambda item: item[1])
            if "期初余额" not in mapped_values:
                augmented_mapping[date_columns[0][0]] = "期初余额"
            if "期末余额" not in mapped_values:
                augmented_mapping[date_columns[-1][0]] = "期末余额"
        elif table_type in {"利润表", "损益表"}:
            if "本年累计金额" not in mapped_values:
                latest_column = max(date_columns, key=lambda item: item[1])[0]
                augmented_mapping[latest_column] = "本年累计金额"
        elif table_type == "现金流量表":
            if "累计金额" not in mapped_values:
                latest_column = max(date_columns, key=lambda item: item[1])[0]
                augmented_mapping[latest_column] = "累计金额"

        return augmented_mapping

    def _parse_excel_numeric_value(self, value):
        """解析 Excel 金额单元格，保留空值语义，避免把缺失金额误记为 0。"""
        if value is None or pd.isna(value):
            return None

        value_str = str(value).strip()
        value_str = value_str.replace('**', '').replace('*', '')
        value_str = value_str.replace(',', '').replace('，', '')
        value_str = re.sub(r'\s+', '', value_str)

        if not value_str or value_str in {'-', '—', '－', 'nan', 'NaN', 'None', 'null', 'N/A', 'n/a'}:
            return None

        if value_str.startswith('(') and value_str.endswith(')'):
            value_str = '-' + value_str[1:-1]

        try:
            return round(float(value_str), 2)
        except (TypeError, ValueError):
            return None

    def _parse_excel_numeric_series(self, series):
        return pd.Series(
            [self._parse_excel_numeric_value(value) for value in series],
            index=series.index,
            dtype=object,
        )

    def _parse_balance_sheet(self, file_path, sheet_name, header_row, column_mapping=None):
        """
        解析资产负债表
        :param column_mapping: 可选，列映射字典。如果提供，则直接使用；否则使用正则+LLM fallback
        """
        self.logger.debug(f"[{sheet_name}] 开始解析资产负债表...")
        bs_df = pd.read_excel(file_path, header=header_row, sheet_name=sheet_name)
        bs_df = self.standardize_header_dates(bs_df)
        
        tab_header = bs_df.columns.tolist()
        
        # 如果已有 column_mapping，直接使用
        if column_mapping:
            self.logger.debug(f"[{sheet_name}] 使用LLM提供的列映射: {column_mapping}")
            cvt_std_cols = column_mapping
        else:
            # 否则使用原有的正则匹配逻辑
            std_header = {
                "资.*?产": "资产",
                "负债.*?所有者权益": "负债和所有者权益",
                "项.*?目": "项目", 
                "^(年末|期末).*?": "期末余额",
                "(年初|上年*.?末|期初)": "期初余额"
            }
            
            cvt_std_cols = {}
            for title in tab_header:
                _title_std = next((std_title for reg, std_title in std_header.items() if is_match(reg, title)), title)
                cvt_std_cols.update({title: _title_std})
                
            # 校验必要字段，不足则调用LLM
            required_columns1 = ["资产", "负债和所有者权益", "期末余额", "期初余额"]
            required_columns2 = ["项目", "期末余额", "期初余额"]

            self.logger.debug(f"[{sheet_name}] 原始表头: {tab_header}")
            self.logger.debug(f"[{sheet_name}] 正则识别结果: {cvt_std_cols}")
            
            if not set(required_columns1).issubset(set(cvt_std_cols.values())) and not set(required_columns2).issubset(set(cvt_std_cols.values())):
                self.logger.warning(f"[{sheet_name}] 正则未能识别资产负债表标准表头，将由后续列校验决定是否跳过")

        cvt_std_cols = self._augment_column_mapping_with_date_headers(
            tab_header,
            cvt_std_cols,
            "资产负债表",
        )

        _df = bs_df.copy().rename(columns=cvt_std_cols)

        # 资产负债表特殊处理：将"资产"和"负债和所有者权益"统一重命名为"项目"
        _df.rename(columns={"资产": "项目", "负债和所有者权益": "项目"}, inplace=True)
        
        # 使用通用多栏合并方法
        _df = self._merge_multi_column_table(
            df=_df,
            key_columns=["项目", "期初余额", "期末余额"],
            sheet_name=sheet_name,
            table_type="资产负债表"
        )
        
        # 数据清洗
        _df.dropna(subset=["项目"], inplace=True)
        _df['期初余额'] = self._parse_excel_numeric_series(_df['期初余额'])
        _df['期末余额'] = self._parse_excel_numeric_series(_df['期末余额'])
        
        bs_dict = _df.assign(项目=_df['项目'].apply(self._clean_item_text)).set_index('项目')[['期初余额', '期末余额']].T.to_dict('list')
        return bs_dict

    def _parse_cash_stmts(self, file_path, sheet_name, header_row, column_mapping=None):
        """
        解析现金流量表
        :param column_mapping: 可选，列映射字典。如果提供，则直接使用；否则使用正则+LLM fallback
        """
        self.logger.debug(f"[{sheet_name}] 开始解析现金流量表...")
        cs_df = pd.read_excel(file_path, header=header_row, sheet_name=sheet_name)
        cs_df = self.standardize_header_dates(cs_df)
        
        tab_header = cs_df.columns.tolist()
        required_columns = ["项目", "累计金额"]
        
        # 如果已有 column_mapping，直接使用
        if column_mapping:
            self.logger.debug(f"[{sheet_name}] 使用LLM提供的列映射: {column_mapping}")
            cvt_std_cols = column_mapping
        else:
            # 否则使用原有的正则匹配逻辑
            std_header = {
                "项.*?目": "项目",
                "(本年累计|本年)": "累计金额",
            }
            cvt_std_cols = {}
            for title in tab_header:
                _title_std = next((std_title for reg, std_title in std_header.items() if is_match(reg, title)), title)
                cvt_std_cols.update({title: _title_std})

            self.logger.debug(f"[{sheet_name}] 原始表头: {tab_header}")
            self.logger.debug(f"[{sheet_name}] 正则识别结果: {cvt_std_cols}")

            if not set(required_columns).issubset(set(cvt_std_cols.values())):
                self.logger.warning(f"[{sheet_name}] 正则未能识别现金流量表标准表头，将由后续列校验决定是否跳过")

        cvt_std_cols = self._augment_column_mapping_with_date_headers(
            tab_header,
            cvt_std_cols,
            "现金流量表",
        )

        _df = cs_df.copy().rename(columns=cvt_std_cols)
        self.logger.debug(f"[{sheet_name}] 原表头转标准表头: {cvt_std_cols}")

        # 使用通用多栏合并方法
        _df = self._merge_multi_column_table(
            df=_df,
            key_columns=["项目", "累计金额"],
            sheet_name=sheet_name,
            table_type="现金流量表"
        )
        
        # 数据清洗
        _df.dropna(subset=["项目"], inplace=True)
        _df['累计金额'] = self._parse_excel_numeric_series(_df['累计金额'])
        
        item_names = _df['项目'].apply(self._clean_item_text).tolist()
        item_names = self._contextualize_cashflow_item_names(item_names)
        cs_dict = dict(zip(item_names, _df['累计金额']))
        return cs_dict

    def _parse_income_stmts(self, file_path, sheet_name, header_row, column_mapping=None):
        """
        解析利润表
        :param column_mapping: 可选，列映射字典。如果提供，则直接使用；否则使用正则+LLM fallback
        """
        self.logger.debug(f"[{sheet_name}] 开始解析利润表...")
        is_df = pd.read_excel(file_path, header=header_row, sheet_name=sheet_name)
        is_df = self.standardize_header_dates(is_df)
        
        tab_header = is_df.columns.tolist()
        required_columns = ["项目", "本年累计金额"]
        
        # 如果已有 column_mapping，直接使用
        if column_mapping:
            self.logger.debug(f"[{sheet_name}] 使用LLM提供的列映射: {column_mapping}")
            cvt_std_cols = column_mapping
        else:
            # 否则使用原有的正则匹配逻辑
            std_header = {
                "项.*?目": "项目",
                "(本年累计|本年)": "本年累计金额",
            }
            cvt_std_cols = {}
            for title in tab_header:
                _title_std = next((std_title for reg, std_title in std_header.items() if is_match(reg, title)), title)
                cvt_std_cols.update({title: _title_std})

            self.logger.debug(f"[{sheet_name}] 原始表头: {tab_header}")
            self.logger.debug(f"[{sheet_name}] 正则识别结果: {cvt_std_cols}")

            if not set(required_columns).issubset(set(cvt_std_cols.values())):
                self.logger.warning(f"[{sheet_name}] 正则未能识别利润表标准表头，将由后续列校验决定是否跳过")

        cvt_std_cols = self._augment_column_mapping_with_date_headers(
            tab_header,
            cvt_std_cols,
            "利润表",
        )

        _df = is_df.copy().rename(columns=cvt_std_cols)
        self.logger.debug(f"[{sheet_name}] 原表头转标准表头: {cvt_std_cols}")

        # 使用通用多栏合并方法
        _df = self._merge_multi_column_table(
            df=_df,
            key_columns=["项目", "本年累计金额"],
            sheet_name=sheet_name,
            table_type="利润表"
        )
        
        # 数据清洗
        _df.dropna(subset=["项目"], inplace=True)
        _df['本年累计金额'] = self._parse_excel_numeric_series(_df['本年累计金额'])
        
        is_dict = dict(zip(_df['项目'].apply(self._clean_item_text), _df['本年累计金额']))
        return is_dict

    def _llm_detect_header_and_mapping(self, file_path, sheet_name, table_type):
        """
        通过 LLM 一次性识别表头行位置和列映射关系
        :param file_path: Excel文件路径
        :param sheet_name: Sheet名称
        :param table_type: 表类型（资产负债表/利润表/现金流量表）
        :return: (header_row: int, column_mapping: dict)
        """
        # 1. 读取前10行原始数据
        rows_text = self._build_sheet_preview_rows_text(file_path, sheet_name, nrows=10)
        
        # 3. 选择对应的 prompt
        prompt_map = {
            "资产负债表": "SP_BS_DETECT", 
            "利润表": "SP_IS_DETECT",
            "损益表": "SP_IS_DETECT", 
            "现金流量表": "SP_CS_DETECT"
        }
        prompt_key = prompt_map.get(table_type)
        
        if not prompt_key:
            self.logger.warning(f"[{sheet_name}] 未知的表类型: {table_type}，无法使用LLM检测")
            return -1, {}
        
        # 4. 调用 LLM 识别表头行
        user_message = "\n".join(rows_text)
        self.logger.debug(f"[{sheet_name}] 调用LLM检测表头行和列映射，输入数据:\n{user_message}")
        
        try:
            result = self.llm.chat(system_prompt=PROMPTS[prompt_key], user_message=user_message)
            parsed = extract_llm_json(result)
            
            header_row = parsed.get("header_row", -1)
            column_mapping_raw = parsed.get("column_mapping", {})
            
            if header_row < 0:
                self.logger.warning(f"[{sheet_name}] LLM未能识别表头行")
                return -1, {}
            
            # 5. 关键修复：用pandas读取表头，获取真实列名（包括重复列的后缀）
            df_with_header = pd.read_excel(file_path, header=header_row, sheet_name=sheet_name, nrows=0)
            actual_columns = df_with_header.columns.tolist()
            
            # 6. 将LLM返回的列映射适配到真实列名。
            # pandas 会把日期表头读成 datetime，也会给重复列名追加 .1/.2 后缀。
            column_mapping_lookup = self._build_column_mapping_lookup(column_mapping_raw)
            column_mapping = {}
            standardized_actual_columns = []
            
            for actual_col in actual_columns:
                standardized_col = self._standardize_header_value(actual_col)
                standardized_actual_columns.append(standardized_col)
                mapped_value = None
                for candidate in self._column_header_match_candidates(actual_col):
                    if candidate in column_mapping_lookup:
                        mapped_value = column_mapping_lookup[candidate]
                        break
                if mapped_value and str(mapped_value).strip():
                    column_mapping[standardized_col] = mapped_value

            column_mapping = self._augment_column_mapping_with_date_headers(
                standardized_actual_columns,
                column_mapping,
                table_type,
            )
            
            self.logger.debug(f"[{sheet_name}] LLM返回结果: header_row={header_row}")
            self.logger.debug(f"[{sheet_name}] 实际列名: {actual_columns}")
            self.logger.debug(f"[{sheet_name}] 适配后的列映射: {column_mapping}")
            
            return header_row, column_mapping
            
        except Exception as e:
            self.logger.error(f"[{sheet_name}] LLM检测表头行失败: {str(e)}")
            import traceback
            self.logger.error(traceback.format_exc())
            return -1, {}

    def _extract_company_name_from_cells(self, file_path, sheet_name, nrows=10):
        df_raw = pd.read_excel(file_path, header=None, sheet_name=sheet_name, nrows=nrows)
        candidates = []
        for cell in df_raw.to_numpy().flat:
            if pd.isna(cell):
                continue
            company_name = extract_company_name_by_rule(str(cell))
            if company_name:
                candidates.append(company_name)
        return resolve_unique_company_name(candidates)

    def _extract_company_name(self, file_path, sheet_name):
        company_name = self._extract_company_name_from_cells(file_path, sheet_name)
        if company_name:
            return company_name

        rows_text = self._build_sheet_preview_rows_text(file_path, sheet_name, nrows=10)
        preview_text = "\n".join(rows_text)
        company_name = self.company_name_resolver.extract_from_text(
            preview_text,
            source_type="excel_header_rows",
        )
        if company_name:
            return company_name
        return extract_company_name_by_rule(preview_text)

    def _detect_table_type_from_sheet_name(self, sheet_name):
        """仅从 Sheet 名识别财报类型，不推断合并属性。"""
        clean_sheet_name = self._clean_text(sheet_name)
        for scope_prefix in ("合并", "母公司", "单体", "个别", "本部"):
            if clean_sheet_name.startswith(scope_prefix):
                clean_sheet_name = clean_sheet_name[len(scope_prefix):]
                break
        table_types = {"资产负债表", "利润表", "现金流量表", "损益表"}
        return clean_sheet_name if clean_sheet_name in table_types else "N/A"

    def _detect_consolidation_from_sheet_name(self, sheet_name):
        """从 Sheet 名识别合并口径；未明确表达口径时返回 None。"""
        clean_sheet_name = self._clean_text(sheet_name)
        has_consolidated = "合并" in clean_sheet_name
        has_standalone = any(
            marker in clean_sheet_name
            for marker in ("母公司", "单体", "个别", "本部")
        )
        if has_consolidated == has_standalone:
            return None
        return "是" if has_consolidated else "否"

    def _detect_consolidation_from_title_text(self, text):
        """从报表标题文本识别合并口径；普通标题返回 None。"""
        clean_text = self._clean_text(text)
        title_markers = (
            "资产负债表",
            "利润表",
            "现金流量表",
            "损益表",
            "合并报表",
            "母公司报表",
            "单体报表",
            "个别报表",
        )
        if not any(marker in clean_text for marker in title_markers):
            return None

        has_consolidated = "合并" in clean_text
        has_standalone = any(
            marker in clean_text
            for marker in ("母公司", "单体", "个别", "本部")
        )
        if has_consolidated == has_standalone:
            return None
        return "是" if has_consolidated else "否"

    def _fuzzy_find_info(self, file_path, sheet_name, info_keywords):
        """
        在Sheet前10行中模糊查找表元数据（表名、日期、单位、合并属性等）
        注意：表头行识别已由 _llm_detect_header_and_mapping 负责
        """
        sheet_table_type = self._detect_table_type_from_sheet_name(sheet_name)
        sheet_consolidation = self._detect_consolidation_from_sheet_name(sheet_name)
        extracted = {
            "表名": sheet_table_type,
            "日期": "N/A",
            "单位": "N/A",
            "合并": sheet_consolidation or "否",
        }
        consolidation_conflict_warned = False

        if sheet_table_type != "N/A":
            self.logger.debug(f"[{sheet_name}] Sheet名严格匹配财报类型: {sheet_table_type}，跳过前10行表类型识别")
        else:
            self.logger.debug(f"[{sheet_name}] Sheet名未严格匹配财报类型，将回退前10行内容识别")

        # 读取前10行。Sheet 名命中时仍扫描内容，用于日期/单位/合并补齐和类型校验。
        df_info = pd.read_excel(file_path, header=None, sheet_name=sheet_name, nrows=10)
        
        for _idx, row in df_info.iterrows():
            # 将行转换为字符串用于正则匹配
            row_str = "".join([str(self.cell_to_date_str(cell)) for cell in row if pd.notna(cell) and str(cell).strip() != ''])
            clean_row_str = self._clean_text(row_str)
            
            # Sheet 名明确表达口径时优先；否则从报表标题识别。
            title_consolidation = self._detect_consolidation_from_title_text(row_str)
            if sheet_consolidation is None:
                if title_consolidation is not None:
                    extracted["合并"] = title_consolidation
            elif (
                title_consolidation is not None
                and title_consolidation != sheet_consolidation
                and not consolidation_conflict_warned
            ):
                self.logger.warning(
                    f"[{sheet_name}] Sheet 名与表内标题的合并口径冲突，"
                    f"优先采用 Sheet 名口径: {sheet_consolidation}"
                )
                consolidation_conflict_warned = True
            
            # 仅在Sheet名未命中时，才通过前10行判断表名。
            if extracted['表名'] == 'N/A':
                matched_kw = next((_item for _item in info_keywords['表名'] if is_match(_item, clean_row_str)), None)
                if matched_kw:
                    extracted['表名'] = matched_kw + "表"
            
            # 提取日期
            if extracted['日期'] == 'N/A':
                _date_str = self._extract_date(row_str)
                if _date_str is not None:
                    extracted['日期'] = _date_str
            
            # 提取单位
            if extracted['单位'] == 'N/A':
                matched_unit = next((_item for _item in info_keywords['单位'] if is_match(_item, clean_row_str)), None)
                if matched_unit:
                    extracted['单位'] = matched_unit

        return extracted

    def parse(self, file_url):
        """
        主解析入口
        :param file_url: Excel文件路径
        :return: 解析结果列表
        """
        result = []
        parsed_statement_keys = set()  # 按报表类型和合并口径去重
        company_name_candidates = []
        
        try:
            # 1. 获取可见的Sheet页（过滤隐藏页）
            sheet_names = self._get_visible_sheet_names(file_url)
            self.logger.info(f"[LIFECYCLE] 开始解析文件: {file_url}，检测到可见Sheet页: {sheet_names}")
            
            for sheet_name in sheet_names:
                self.logger.debug(f"---------------- 正在处理 Sheet: {sheet_name} ----------------")
                company_name_candidates.append(self._extract_company_name(file_url, sheet_name))
                
                # 2. 提取元数据（不包含表头行，表头行由LLM负责）
                meta_data = self._fuzzy_find_info(file_url, sheet_name,
                                            {
                                                "表名": ["资产负债", "利润", "现金流量", "损益"],
                                                "单位": ["亿元", "万元", "元"]
                                            })
                
                table_type = meta_data["表名"]

                if table_type == "损益表":
                    table_type = "利润表"
                
                # 3. 基础校验：表类型必须识别成功
                if table_type == 'N/A':
                    self.logger.warning(f"[{sheet_name}] 未识别到有效的财务表类型，跳过。识别结果: {meta_data}")
                    continue
                
                # 4. 同一报表类型分别保留一张合并表和一张单体表。
                statement_key = (table_type, meta_data["合并"] == "是")
                if statement_key in parsed_statement_keys:
                    self.logger.debug(
                        f"[{sheet_name}] 识别为 [{table_type}]，合并={meta_data['合并']}，"
                        "但同口径报表已解析，根据规则跳过（保留第一个）。"
                    )
                    continue
                
                self.logger.debug(f"[{sheet_name}] 识别元数据成功: {meta_data}")
                
                # 5. 通过LLM一次性识别表头行和列映射
                header_row, column_mapping = self._llm_detect_header_and_mapping(file_url, sheet_name, table_type)
                
                if header_row < 0:
                    self.logger.warning(f"[{sheet_name}] LLM未能识别表头行，跳过该Sheet")
                    continue
                
                self.logger.debug(f"[{sheet_name}] LLM识别到表头行: {header_row}, 列映射: {column_mapping}")

                # 6. 根据表类型分发解析
                try:
                    parsed_data = None
                    
                    if table_type == "资产负债表":
                        parsed_data = self._parse_balance_sheet(file_url, sheet_name, header_row, column_mapping)
                    elif table_type == "利润表" or table_type == "损益表":
                        parsed_data = self._parse_income_stmts(file_url, sheet_name, header_row, column_mapping)
                    elif table_type == "现金流量表":
                        parsed_data = self._parse_cash_stmts(file_url, sheet_name, header_row, column_mapping)

                    
                    # 7. 组装结果并标记该类型已解析
                    if parsed_data:
                        result.append({
                            "文件路径": file_url, 
                            "表名": "合并" + table_type if meta_data["合并"] == "是" else table_type, 
                            "日期": meta_data["日期"],
                            "单位": meta_data["单位"], 
                            "company_name": "",
                            "合并": meta_data["合并"], 
                            "数据": parsed_data
                        })
                        parsed_statement_keys.add(statement_key)
                        self.logger.debug(f"[{sheet_name}] -> [{table_type}] 解析成功并已收录。")
                        
                except ServiceError as e:
                    self.logger.warning(f"[{sheet_name}] 解析业务逻辑错误，跳过: {str(e)}")
                    continue
                except Exception as e:
                    self.logger.error(f"[{sheet_name}] 解析发生未预期异常: {traceback.format_exc()}")
                    continue
                    
        except ServiceError as ex:
            raise ex
        except Exception as e:
            self.logger.error(traceback.format_exc())
            raise Exception(f"文件解析流程发生致命错误（{file_url}）：{str(e)}")

        resolved_company_name = resolve_unique_company_name(company_name_candidates)
        for item in result:
            item["company_name"] = resolved_company_name

        self.logger.info(
            f"[LIFECYCLE] 文件解析结束，共提取 {len(result)} 张报表："
            f"{list(parsed_statement_keys)}"
        )
        return result

if __name__ == "__main__":
    excel_path = "files/example-report.xlsx"
    if os.path.exists(excel_path):
        parser = ExcelFinancialParser()
        parsed_results = parser.parse(excel_path)
        print(f"解析结果数量: {len(parsed_results)}")
        print(parsed_results)
    else:
        print("测试文件不存在")
