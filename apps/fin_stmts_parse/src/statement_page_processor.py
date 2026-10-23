"""PDF 页面和独立图片共用的财报处理流程。"""

import os
import re
import copy
import json
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional

from .base_financial_processor import BaseFinancialProcessor
from .markdown_table_extractor import MarkdownTableExtractor
from .page_classification import PageDiscoveryError, normalize_classification
from .company_name_resolver import resolve_unique_company_name
from .statement_metadata_resolver import StatementPageMetadata


@dataclass
class StatementPageVariant:
    """同一物理页拆分出的逻辑报表，正文保留用于后续跨页聚合。"""

    table_type: str
    is_consolidated: bool
    data: Dict
    table_content: str


@dataclass
class PageExtractionResult:
    """单页结果；文件级日期投票和跨页归并由文件处理器完成。"""

    source_file_path: str
    page_number: Optional[int]
    table_type: str
    markdown: str
    extraction_method: str
    company_name: str
    metadata: StatementPageMetadata
    variants: List[StatementPageVariant]
    is_valid: bool


class StatementPageProcessor(BaseFinancialProcessor):
    """复用底层识别能力，统一分类、预处理、提取回退和页级元数据决策。"""

    def extract_discovery_text(self, image_path: str) -> str:
        from .lightweight_ocr import extract_page_text

        return extract_page_text(image_path)

    def process_statement(
        self,
        image_paths: List[str],
        *,
        table_type: str,
        source_file_path: str,
        page_numbers: List[int],
        orientation_corrected: bool = False,
        on_extraction: Optional[Callable[[str, str], None]] = None,
    ) -> PageExtractionResult:
        """PDF 逻辑表：一次模型请求，随后仅进行本地解析、校验和元数据合并。"""
        if not image_paths or len(image_paths) != len(page_numbers):
            raise ValueError("报表图片和页码不能为空且须一一对应")
        temporary_paths = set()
        originals = {os.path.abspath(path) for path in image_paths}
        try:
            prepared = []
            for image_path in image_paths:
                cleaned = self.remove_watermark_from_file(image_path, keep_file=False)
                temporary_paths.add(cleaned)
                rotated = cleaned if orientation_corrected else self.correct_image_orientation(cleaned)
                temporary_paths.add(rotated)
                prepared.append(rotated)
            payload = self.extract_statement_group_with_vl(prepared, table_type)
            method = "VL大模型(按表合并页面)"
            if on_extraction:
                on_extraction(method, json.dumps(payload, ensure_ascii=False, indent=2))
            markdown = self.normalize_extracted_markdown(payload["markdown"])
            # 每个任务独立持有无 LLM 的表格解析器，禁止内部表头回退再产生模型调用。
            local_processor = copy.copy(self)
            local_processor.table_extractor = MarkdownTableExtractor(logger=self.logger, llm_client=None)
            variants = local_processor._parse_extracted_statement_variants(markdown, table_type=table_type)
            if not local_processor._are_statement_variants_valid(variants):
                raise ValueError(f"{table_type} 提取结果未通过数据校验，请检查原始响应")
            resolver = self.metadata_resolver
            file_metadata = resolver.extract_statement_metadata_from_filename(
                os.path.basename(source_file_path), table_type
            )
            metadata = resolver.merge_statement_metadata(
                resolver.normalize_vl_response({**payload, "confidence": "high"}, table_type),
                resolver.extract_statement_metadata_from_text(markdown, table_type),
                file_metadata,
            )
            metadata = resolver.resolve_statement_metadata_date(metadata, file_metadata)
            page_variants = [StatementPageVariant(
                table_type=variant["table_type"],
                is_consolidated=bool(variant.get("is_consolidated")),
                data=variant["data"],
                table_content=(
                    local_processor._render_statement_variant_table(variant["table_type"], variant["data"])
                    if variant.get("is_split_variant") else self._strip_leading_metadata_header(markdown)
                ),
            ) for variant in variants]
            return PageExtractionResult(
                source_file_path=source_file_path, page_number=page_numbers[0], table_type=table_type,
                markdown=markdown, extraction_method=method, company_name=metadata.company_name,
                metadata=metadata, variants=page_variants, is_valid=True,
            )
        finally:
            for path in temporary_paths:
                if path and os.path.abspath(path) not in originals:
                    try:
                        os.remove(path)
                    except FileNotFoundError:
                        pass

    def classify_page(self, image_path: str) -> Dict:
        # 合并/母公司列可能共存，分类阶段始终检测所有报表类型。
        return self.analyze_page_content(image_path, target_tables=self.get_target_tables(None))

    def process_page(
        self,
        image_path: str,
        *,
        source_file_path: Optional[str] = None,
        page_number: Optional[int] = None,
        analysis_result: Optional[Dict] = None,
        on_extraction: Optional[Callable[[str, str], None]] = None,
    ) -> Optional[PageExtractionResult]:
        """处理单页；可复用 PDF 扫描阶段的分类结果，回调保留每次原始提取。"""
        source_file_path = source_file_path or image_path
        if analysis_result is None:
            analysis_result = self.classify_page(image_path)
        analysis_result = normalize_classification(analysis_result, self.get_target_tables(None))
        if analysis_result["status"] in ("failed", "uncertain"):
            raise PageDiscoveryError({page_number or 1: analysis_result})
        table_type = analysis_result.get("table_type")
        if not analysis_result.get("has_target_table") or table_type not in self.get_target_tables(None):
            return None

        processing_image_path = None
        rotated_image_path = None
        try:
            processing_image_path = self.remove_watermark_from_file(image_path, keep_file=False)
            rotated_image_path = self.correct_image_orientation(processing_image_path)
            cached_ocr = analysis_result.get("ocr_markdown")
            if isinstance(cached_ocr, str) and cached_ocr.strip():
                markdown, method = cached_ocr, "PaddleOCRVL"
            else:
                markdown, method = self._extract_table_content(rotated_image_path, table_type)
            if on_extraction is not None:
                on_extraction(method, markdown)
            variants = self._parse_extracted_statement_variants(markdown, table_type=table_type)
            is_valid = self._are_statement_variants_valid(variants)

            if not is_valid and method == "PaddleOCRVL":
                self.logger.warning(f"{table_type} PaddleOCR 解析无效，使用 VLM 回退重试")
                try:
                    retry_markdown = self.extract_table_with_vl(rotated_image_path, table_type)
                    if on_extraction is not None:
                        on_extraction("VL大模型(回退)", retry_markdown)
                    retry_variants = self._parse_extracted_statement_variants(
                        retry_markdown, table_type=table_type
                    )
                    retry_valid = self._are_statement_variants_valid(retry_variants)
                    # 保留最后一次成功返回的内容，即使校验仍未通过。
                    markdown, variants, is_valid = retry_markdown, retry_variants, retry_valid
                    method = "VL大模型(回退)" if retry_valid else "VL大模型(回退-仍无效)"
                    if not retry_valid:
                        self.logger.warning(f"[ALARM] {table_type} 回退后仍无效，保留最后一次结果")
                except Exception as exc:
                    self.logger.error(f"[ALARM] {table_type} VLM 回退失败，保留首次结果: {exc}")

            # 所有来源统一使用最终提取内容，避免回退后公司名仍来自旧内容。
            company_name = resolve_unique_company_name([
                self.extract_company_name_from_image(rotated_image_path),
                self.company_name_resolver.extract_from_text(markdown, source_type="markdown"),
            ])
            metadata = self._resolve_page_metadata(
                rotated_image_path, source_file_path, table_type, analysis_result, markdown, company_name
            )
            page_variants = [
                StatementPageVariant(
                    table_type=variant["table_type"],
                    is_consolidated=bool(variant.get("is_consolidated")),
                    data=variant["data"],
                    table_content=(
                        self._render_statement_variant_table(variant["table_type"], variant["data"])
                        if variant.get("is_split_variant")
                        else self._strip_leading_metadata_header(markdown)
                    ),
                )
                for variant in variants
            ]
            return PageExtractionResult(
                source_file_path=source_file_path,
                page_number=page_number,
                table_type=table_type,
                markdown=markdown,
                extraction_method=method,
                company_name=company_name,
                metadata=metadata,
                variants=page_variants,
                is_valid=is_valid,
            )
        finally:
            # 只清理由本次预处理生成的文件；输入图片和 PDF 渲染图归调用方所有。
            retained = {os.path.abspath(image_path)}
            for temp_path in (rotated_image_path, processing_image_path):
                if not temp_path:
                    continue
                normalized_path = os.path.abspath(temp_path)
                if normalized_path in retained:
                    continue
                retained.add(normalized_path)
                try:
                    os.remove(temp_path)
                except FileNotFoundError:
                    pass
                except OSError as exc:
                    self.logger.warning(f"清理临时图片失败: {temp_path}: {exc}")

    def _resolve_page_metadata(
        self,
        image_path: str,
        source_file_path: str,
        table_type: str,
        analysis_result: Dict,
        markdown: str,
        company_name: str,
    ) -> StatementPageMetadata:
        resolver = self.metadata_resolver
        file_metadata = resolver.extract_statement_metadata_from_filename(
            os.path.basename(source_file_path), table_type
        )
        metadata = resolver.merge_statement_metadata(
            resolver.extract_statement_metadata_from_analysis(analysis_result, table_type),
            resolver.extract_statement_metadata_from_text(
                markdown, table_type, source="markdown", confidence="high"
            ),
            {"company_name": company_name, "source": "company_name", "confidence": "medium"},
        )
        vl_metadata = None
        if resolver.needs_vl_recheck(metadata, file_metadata):
            vl_metadata = self.extract_statement_metadata_with_vl(image_path, table_type)
        metadata = resolver.merge_statement_metadata(metadata, vl_metadata, file_metadata)
        return resolver.resolve_statement_metadata_date(metadata, file_metadata, vl_metadata)

    def get_target_tables(self, is_consolidated: Optional[bool]) -> List[str]:
        """根据is_consolidated参数获取目标表格列表"""
        if is_consolidated is True:
            return ["合并资产负债表", "合并利润表", "合并现金流量表"]
        elif is_consolidated is False:
            return ["资产负债表", "利润表", "现金流量表"]
        else:
            return [
                "资产负债表", "合并资产负债表",
                "利润表", "合并利润表",
                "现金流量表", "合并现金流量表"
            ]

    def is_parsing_result_valid(self, data_dict: dict, table_type: str) -> bool:
        """
        检查解析结果是否有效

        校验逻辑：
        1. 字典非空。
        2. 键名纯净度校验：统计“不含中文”的键。
        3. 数值检查：
           - 列表结构（资产负债表）：分别检查 [期初] 和 [期末] 列，任一列全为None视为无效。
           - 单值结构（利润/现金表）：检查是否全为None。

        Args:
            data_dict: 解析得到的字典数据
            table_type: 表格类型

        Returns:
            如果解析结果有效返回True，否则返回False
        """
        # 1. 空字典检查
        if not data_dict:
            self.logger.warning(f"[ALARM] ❌ {table_type} 解析结果为空字典")
            return False

        # 2. 键名(科目)纯净度校验
        total_keys = len(data_dict)
        chinese_pattern = re.compile(r'[\u4e00-\u9fa5]')

        # 收集"坏键"（即不包含任何中文字符的键，如 "Asset", "123", "Note 1"）
        invalid_keys = []
        for key in data_dict.keys():
            # 转字符串判断，如果搜索不到中文，则记为无效键
            if not chinese_pattern.search(str(key)):
                invalid_keys.append(str(key))

        invalid_count = len(invalid_keys)

        if invalid_count > 0:
            self.logger.warning(
                f"[ALARM] ❌ {table_type} 键名校验失败：发现项目名中不含中文，可能提取到了错误的表头。"
            )
            return False

        # 3. 数值完整性校验

        # 取第一个值判断结构
        first_value = next(iter(data_dict.values()))
        is_list_structure = isinstance(first_value, list)

        if is_list_structure and self._is_balance_sheet_table(table_type):
            # === 针对资产负债表 (List结构: [数值1, 数值2]) ===
            # 分别校验两列，任何一列全为None都算失败

            all_col1_none = True # 第一列 (通常是期初)
            all_col2_none = True # 第二列 (通常是期末)

            for value in data_dict.values():
                if not isinstance(value, list): continue

                # 检查第一列 (Index 0)
                if len(value) > 0 and value[0] is not None:
                    all_col1_none = False

                # 检查第二列 (Index 1)
                if len(value) > 1 and value[1] is not None:
                    all_col2_none = False

            # 如果第一列全空
            if all_col1_none:
                self.logger.warning(f"[ALARM] ❌ {table_type} 校验失败：期初列数据全部为None")
                return False

            # 如果第二列全空
            if all_col2_none:
                self.logger.warning(f"[ALARM] ❌ {table_type} 校验失败：期末列数据全部为None")
                return False


        else:
            # === 针对利润表/现金流量表 ===
            # 即使解析成双列 list，也只要求至少有一个期间有有效值，不做期初列校验。
            if not self._has_any_statement_value(data_dict):
                self.logger.warning(f"[ALARM] ❌ {table_type} 校验失败：所有科目数值均为None")
                return False

            self.logger.debug(f"✅ {table_type} 校验通过")

        return True

    def _extract_table_content(self, image_path: str, table_type: str) -> tuple:
        """
        提取表格内容

        Returns:
            (markdown内容, 提取方法)元组
        """
        if self.use_paddle and self.paddle_api_url:
            return self.normalize_extracted_markdown(self._extract_with_paddle(image_path)), 'PaddleOCRVL'
        else:
            return self.extract_table_with_vl(image_path, table_type), 'VL大模型'

    def _extract_with_paddle(self, image_path: str) -> str:
        """使用PaddleOCRVL API服务提取表格"""
        try:
            import base64
            import requests

            self.logger.debug(f"正在使用 PaddleOCRVL API 提取内容: {image_path}")

            # 读取图像并进行Base64编码
            with open(image_path, "rb") as file:
                image_bytes = file.read()
                image_data = base64.b64encode(image_bytes).decode("ascii")

            # 构造请求payload
            payload = {
                "file": image_data,  # Base64编码的文件内容
                "fileType": 1,  # 1表示图像文件
            }

            # 调用API
            self.logger.debug(f"调用 PaddleOCRVL API: {self.paddle_api_url}")
            response = requests.post(self.paddle_api_url, json=payload, timeout=300)

            # 检查响应状态
            if response.status_code != 200:
                error_msg = f"API 调用失败，状态码: {response.status_code}"
                self.logger.error(error_msg)
                return f"提取失败: {error_msg}"

            # 解析响应
            result = response.json().get("result", {})
            layout_results = result.get("layoutParsingResults", [])

            if not layout_results:
                self.logger.warning("PaddleOCRVL API 未返回任何结果")
                return "未提取到表格内容"

            # 合并所有结果的markdown内容
            markdown_content = ""
            for i, res in enumerate(layout_results):
                markdown_text = res.get("markdown", {}).get("text", "")
                if markdown_text:
                    markdown_content += markdown_text + "\n\n"
                    self.logger.debug(f"成功提取第 {i+1} 个布局结果")

            if not markdown_content:
                self.logger.warning("未从 PaddleOCRVL API 结果中提取到有效内容")
                return "未提取到表格内容"

            self.logger.debug(f"提取完成，共 {len(layout_results)} 个布局结果")
            return markdown_content

        except requests.exceptions.Timeout:
            error_msg = "PaddleOCRVL API 调用超时"
            self.logger.error(error_msg)
            return f"提取失败: {error_msg}"
        except requests.exceptions.RequestException as e:
            error_msg = f"PaddleOCRVL API 请求异常: {e}"
            self.logger.error(error_msg)
            return f"提取失败: {error_msg}"
        except Exception as e:
            self.logger.error(f"PaddleOCRVL API 提取出错: {e}")
            return f"提取失败: {e}"

    def _are_statement_variants_valid(self, variants: List[Dict]) -> bool:
        if not variants:
            return False
        for variant in variants:
            data_dict = variant.get("data")
            table_type = variant.get("table_type")
            if not self.is_parsing_result_valid(data_dict, table_type):
                return False
        return True

    @staticmethod
    def _is_balance_sheet_table(table_type: str = None) -> bool:
        return "资产负债表" in str(table_type or "")

    @staticmethod
    def _has_any_statement_value(data_dict: Dict) -> bool:
        for value in data_dict.values():
            if isinstance(value, list):
                if any(item is not None for item in value):
                    return True
            elif value is not None:
                return True
        return False
