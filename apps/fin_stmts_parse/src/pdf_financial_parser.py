#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PDF财务报表处理模块
专门处理PDF文件的财务报表识别和提取
"""

import os
import json
import fitz  # pymupdf
import shutil
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, List, Optional
from .statement_page_processor import StatementPageProcessor
from .pdf_page_renderer import PDFPageRenderer
from .pdf_page_discovery import PDFPageDiscovery, resolve_continuations, group_statement_pages
from .page_classification import PageDiscoveryError, classification
from .statement_output import (
    StatementMarkdownSection, build_statement_result,
    save_statement_markdown, save_raw_extraction_snapshot,
)
from fin_stmts_parse.src.company_name_resolver import resolve_unique_company_name
from fin_stmts_parse.utils.logger import logger, context_aware_submit

class PDFFinancialProcessor:
    """PDF财务报表处理器"""

    def __init__(
        self,
        config: Dict,
        use_paddle: bool = False,
        llm_client=None,
        *,
        page_processor: Optional[StatementPageProcessor] = None,
        page_renderer: Optional[PDFPageRenderer] = None,
    ):
        self.config = config
        self.logger = logger
        self.page_processor = page_processor if page_processor is not None else StatementPageProcessor(
            config, use_paddle, llm_client=llm_client
        )
        self.page_renderer = page_renderer if page_renderer is not None else PDFPageRenderer()

    def process_pdf(
        self,
        pdf_path: str,
        output_dir: str = None,
        is_consolidated: Optional[bool] = None,
        report_period: Optional[str] = None
    ) -> List[Dict]:
        """
        处理PDF文件，自动识别并提取财务报表
        OCR 定位实际存在的目标报表并确认续页；每张逻辑表调用一次模型
        返回与Excel解析器一致的格式

        Args:
            pdf_path: PDF文件路径
            output_dir: 输出目录（可选，用于保存中间文件）
            is_consolidated: 是否为合并报表（None=检测所有, True=只检测合并报表, False=只检测非合并报表）
            report_period: 报告周期 (MON=月报/QTR=季报/HYR=半年报/ANN=年报)

        Returns:
            结果列表，格式与Excel解析器一致:
            [{'文件路径': str, '表名': str, '日期': str, '单位': str, '合并': str, '数据': dict}]
        """
        result = []
        temp_images_dir = None
        doc = None
        discovery = None

        try:
            # 检测阶段不按合并属性过滤；同表内合并/母公司列需要在解析后拆分。
            metadata_resolver = self.page_processor.metadata_resolver
            source_file_name = os.path.basename(pdf_path)

            import tempfile
            temp_images_dir = tempfile.mkdtemp(prefix='pdf_extract_')

            self.logger.debug(f"开始解析PDF文件: {pdf_path}")
            doc = fitz.open(pdf_path)
            total_pages = doc.page_count

            extracted_contents = {
                "资产负债表": [], "合并资产负债表": [],
                "利润表": [], "合并利润表": [],
                "现金流量表": [], "合并现金流量表": []
            }

            discovery = PDFPageDiscovery(self.config, self.page_processor)
            self.logger.debug("PDF定位: 原生文本优先；扫描页先纠正方向，再使用本地 RapidOCR (PP-OCRv4 mobile)")
            detections = {}
            rendered_images = {}
            scan_config = self.config.get("pdf_parse", {}).get("page_scan", {})
            target_tables = set(self.page_processor.get_target_tables(is_consolidated))
            try:
                batch_size = max(1, min(8, int(scan_config.get("batch_size", 3))))
                initial_window = int(scan_config.get("initial_window_pages", 30))
            except (TypeError, ValueError):
                batch_size, initial_window = 3, 30
            scan_limit = total_pages
            if scan_config.get("enabled", True) and not scan_config.get("fallback_full_scan", True) and initial_window > 0:
                scan_limit = min(total_pages, initial_window)
            discovery_started = time.monotonic()
            stop_reason = "scan_limit"

            def render_page(page_num):
                # PyMuPDF 文档仅由调度线程读取和渲染。
                if page_num not in rendered_images:
                    rendered_images[page_num] = self.page_renderer.render(
                        doc, page_num, temp_images_dir, page_num + 1
                    )
                return rendered_images[page_num]

            with ThreadPoolExecutor(max_workers=batch_size) as executor:
                cursor = 0
                while cursor < scan_limit:
                    futures = {}
                    batch_end = min(scan_limit, cursor + batch_size)
                    for page_num in range(cursor, batch_end):
                        initial = discovery.read_native(doc, page_num)
                        if initial["status"] != "uncertain":
                            detections[page_num] = initial
                            continue
                        try:
                            futures[context_aware_submit(
                                executor, discovery.resolve, render_page(page_num), initial
                            )] = page_num
                        except Exception as exc:
                            detections[page_num] = classification("failed", source="render", reason=str(exc))
                    for future in as_completed(futures):
                        page_num = futures[future]
                        try:
                            detections[page_num] = future.result()
                        except Exception as exc:
                            detections[page_num] = classification("failed", source="ocr", reason=str(exc))
                    resolve_continuations(detections)
                    cursor = batch_end
                    found = {kind for item in detections.values() if item["status"] == "matched"
                             for kind in item.get("table_types", [item["table_type"]])}
                    self.logger.debug(
                        f"已扫描 {cursor}/{total_pages} 页 | "
                        f"发现：{'、'.join(sorted(found & target_tables)) or '暂无'} | "
                        f"耗时 {time.monotonic() - discovery_started:.1f} 秒"
                    )
                    matched_pages = [page for page, item in detections.items()
                                     if item["status"] == "matched" and set(item.get("table_types", [item["table_type"]])) & target_tables]
                    # 明确进入附注即可结束当前报表区段，不要求存在全部六类表。
                    if matched_pages and any(
                        page > max(matched_pages) and item.get("document_section") == "notes"
                        for page, item in detections.items()
                    ):
                        stop_reason = "notes_section"
                        break
                    # 覆盖所有支持类型只是提前结束的优化，不是进入解析的前提。
                    if target_tables.issubset(found) and matched_pages:
                        last = max(matched_pages)
                        boundary = detections.get(last + 1, {})
                        if last == total_pages - 1 or boundary.get("status") in ("matched", "not_matched"):
                            stop_reason = "all_supported_types"
                            break
                    # 窗口边界上的报表需要继续查完续页，即使禁止全文件回退。
                    if cursor == scan_limit < total_pages and detections.get(cursor - 1, {}).get("status") == "matched":
                        scan_limit = min(total_pages, scan_limit + 1)

            groups = group_statement_pages(detections, target_tables)
            unresolved = {page + 1: item for page, item in detections.items()
                          if item["status"] in ("failed", "uncertain")}
            summary = {
                "total_pages": total_pages,
                "scanned_pages": len(detections),
                "rendered_pages": len(rendered_images),
                "vlm_calls": 0,
                "ocr_engine": "rapidocr",
                "ocr_calls": sum(item.get("ocr_calls", 0) for item in detections.values()),
                "discovery_seconds": round(time.monotonic() - discovery_started, 3),
                "stop_reason": stop_reason,
                "discovery_status": "partial" if unresolved else "complete",
                "unresolved_pages": sorted(unresolved),
                "extraction_calls": 0,
                "groups": [{"table_type": group["table_type"], "pages": [page + 1 for page in group["pages"]]}
                           for group in groups],
                "pages": {str(page + 1): {key: value for key, value in item.items() if key != "page_text"}
                          for page, item in sorted(detections.items())},
            }

            def save_discovery():
                if output_dir:
                    os.makedirs(output_dir, exist_ok=True)
                    path = os.path.join(output_dir, f"{os.path.splitext(source_file_name)[0]}_discovery.json")
                    with open(path, "w", encoding="utf-8") as output:
                        json.dump(summary, output, ensure_ascii=False, indent=2)

            save_discovery()
            if unresolved and not groups:
                raise PageDiscoveryError(unresolved)
            scan_summary = (
                f"[LIFECYCLE] 扫描完成 {len(detections)}/{total_pages} 页 | "
                f"发现：{'、'.join(dict.fromkeys(group['table_type'] for group in groups)) or '暂无'} | "
                f"耗时 {summary['discovery_seconds']:.1f} 秒"
            )
            if unresolved:
                self.logger.warning(scan_summary + f" | 另有 {len(unresolved)} 页未确定，详见逐页诊断")
            else:
                self.logger.info(scan_summary)

            def extract_group(group, images):
                started = time.monotonic()
                pages = [page + 1 for page in group["pages"]]
                self.logger.info(f"[LIFECYCLE] 开始按表解析: {group['table_type']}，页码={pages}")
                prepared = [discovery.prepare_image(path) for path in images]
                page_result = self.page_processor.process_statement(
                    prepared, table_type=group["table_type"], source_file_path=pdf_path, page_numbers=pages,
                    orientation_corrected=True,
                    on_extraction=lambda method, content: save_raw_extraction_snapshot(
                        output_dir, pdf_path, pages[0], group["table_type"], method, content
                    ),
                )
                seconds = round(time.monotonic() - started, 3)
                self.logger.info(f"[LIFECYCLE] 按表解析完成: {group['table_type']}，页码={pages}，耗时={seconds}秒")
                return page_result, seconds

            failures = {}
            with ThreadPoolExecutor(max_workers=3) as executor:
                futures = {}
                for index, group in enumerate(groups):
                    try:
                        images = [render_page(page) for page in group["pages"]]
                        futures[context_aware_submit(executor, extract_group, group, images)] = index
                        summary["extraction_calls"] += 1
                    except Exception as exc:
                        failures[group["pages"][0] + 1] = classification("failed", source="render", reason=str(exc))
                for future in as_completed(futures):
                    index = futures[future]
                    group = groups[index]
                    try:
                        page_result, seconds = future.result()
                        summary["groups"][index].update(status="matched", extraction_seconds=seconds)
                        for variant in page_result.variants:
                            extracted_contents.setdefault(variant.table_type, []).append({
                                "page": group["pages"][0] + 1,
                                "pages": [page + 1 for page in group["pages"]],
                                "table_content": variant.table_content,
                                "method": page_result.extraction_method,
                                "company_name": page_result.company_name,
                                "parsed_data": variant.data,
                                "metadata": page_result.metadata.to_dict(),
                            })
                    except Exception as exc:
                        failures[group["pages"][0] + 1] = classification("failed", source="extraction", reason=str(exc))
                        summary["groups"][index].update(status="failed", error=str(exc))
            summary["rendered_pages"] = len(rendered_images)
            save_discovery()
            if failures:
                raise RuntimeError("报表解析失败: " + "; ".join(
                    f"第 {page} 页起: {item['analysis']}" for page, item in sorted(failures.items())
                ))

            # ====== 5. 最终组装数据 (复用 extraction_worker 中已解析的数据，避免重复解析) ======
            resolved_company_name = resolve_unique_company_name(
                item.get("company_name", "")
                for items in extracted_contents.values()
                for item in items
            )
            file_metadata = metadata_resolver.extract_statement_metadata_from_filename(source_file_name)
            file_level_metadata = metadata_resolver.resolve_file_level_statement_date_metadata(
                [
                    item.get("metadata")
                    for items in extracted_contents.values()
                    for item in items
                    if item.get("metadata")
                ],
                file_metadata,
            )
            for table_type, items in extracted_contents.items():
                if items:
                    if is_consolidated is not None and ("合并" in table_type) != is_consolidated:
                        continue

                    sorted_items = sorted(
                        items,
                        key=lambda item: int(item.get("page") or 0),
                    )
                    combined_markdown = "\n\n".join(
                        [item["table_content"] for item in sorted_items]
                    )
                    item_metadata = [
                        item.get("metadata")
                        for item in sorted_items
                        if item.get("metadata")
                    ]
                    table_file_metadata = metadata_resolver.extract_statement_metadata_from_filename(
                        source_file_name,
                        table_type,
                    )
                    metadata = metadata_resolver.merge_statement_metadata(
                        *item_metadata,
                        metadata_resolver.extract_statement_metadata_from_text(
                            combined_markdown,
                            table_type,
                            source="combined_markdown",
                            confidence="medium",
                        ),
                        table_file_metadata,
                        file_level_metadata,
                    )
                    metadata = metadata_resolver.resolve_statement_metadata_date(
                        metadata,
                        table_file_metadata,
                        file_level_metadata,
                    )

                    cached_dicts = [
                        item["parsed_data"]
                        for item in sorted_items
                        if item.get("parsed_data")
                    ]
                    if cached_dicts:
                        data_dict = self.page_processor.table_extractor.merge_table_dicts(cached_dicts) if len(cached_dicts) > 1 else cached_dicts[0]
                    else:
                        data_dict = self.page_processor.table_extractor.parse_markdown_table_to_dict(combined_markdown, table_type=table_type)

                    # 这里只需要做最后的空值检查警告即可，不需要再做处理逻辑

                    if not self.page_processor.is_parsing_result_valid(data_dict, table_type):
                        self.logger.warning(f"⚠️ {table_type} 最终数据有效性较低，请人工核查")

                    result_item = build_statement_result(
                        pdf_path, table_type, data_dict, metadata,
                        self.page_processor.render_statement_markdown_with_metadata(
                            combined_markdown, table_type, metadata,
                        ),
                        company_name=resolved_company_name,
                        is_consolidated='合并' in table_type,
                        page=int(sorted_items[0].get("page") or 0) or None,
                    )
                    result.append(result_item)

                    self.logger.info(f"[LIFECYCLE] ✅ {table_type} 解析完成")

                    # 保存 Markdown (可选)
                    if output_dir:
                        os.makedirs(output_dir, exist_ok=True)
                        f_name = f"{os.path.splitext(os.path.basename(pdf_path))[0]}_{table_type}.md"
                        save_items = []
                        for item in items:
                            item_metadata_obj = metadata_resolver.merge_statement_metadata(
                                item.get("metadata"),
                                table_file_metadata,
                                file_level_metadata,
                            )
                            item_metadata_obj = metadata_resolver.resolve_statement_metadata_date(
                                item_metadata_obj,
                                table_file_metadata,
                                file_level_metadata,
                            )
                            save_items.append(StatementMarkdownSection(
                                content=self.page_processor.render_statement_markdown_with_metadata(
                                    item["table_content"], table_type, item_metadata_obj,
                                ),
                                extraction_method=item["method"],
                                page=item["page"],
                            ))
                        save_statement_markdown(
                            os.path.join(output_dir, f_name), table_type, pdf_path, save_items
                        )

        except Exception as e:
            self.logger.error(f"PDF解析异常: {e}")
            raise e
        finally:
            if discovery is not None:
                discovery.close()
            if doc is not None and not doc.is_closed:
                doc.close()
                self.logger.info("fitz.Document 已在 finally 中关闭")
            if temp_images_dir and os.path.exists(temp_images_dir):
                shutil.rmtree(temp_images_dir)

        return result

    def _has_complete_financial_statements(
        self,
        found_tables: set,
        is_consolidated: Optional[bool] = None,
    ) -> bool:
        """
        检查是否已找到全部目标表型（默认六类，指定合并属性时三类）

        Args:
            found_tables: 已找到的表格集合

        Returns:
            全部目标表型均已找到时返回 True，否则返回 False
        """
        return set(self.page_processor.get_target_tables(is_consolidated)).issubset(found_tables)

    def _initialize_summary(self) -> Dict:
        """初始化结果摘要"""
        return {
            "资产负债表": {"found": False, "pages": 0},
            "合并资产负债表": {"found": False, "pages": 0},
            "利润表": {"found": False, "pages": 0},
            "合并利润表": {"found": False, "pages": 0},
            "现金流量表": {"found": False, "pages": 0},
            "合并现金流量表": {"found": False, "pages": 0}
        }


def process_pdf_pipeline(
    pdf_path: str,
    output_dir: str,
    config: Dict,
    use_paddle: bool = False,
    is_consolidated: Optional[bool] = None,
    report_period: Optional[str] = None,
    return_legacy_format: bool = False
) -> Dict:
    """
    PDF处理管道函数（兼容旧接口）

    Args:
        pdf_path: PDF路径
        output_dir: 输出目录
        config: 配置字典
        use_paddle: 是否使用PaddleOCRVL
        is_consolidated: 是否为合并报表
        report_period: 报告周期
        return_legacy_format: 是否返回旧格式（包含success等字段）

    Returns:
        处理结果 - 如果return_legacy_format=True返回旧格式字典，否则返回列表
    """
    processor = PDFFinancialProcessor(config, use_paddle)
    result = processor.process_pdf(pdf_path, output_dir, is_consolidated, report_period)

    # 如果需要返回旧格式（用于向后兼容）
    if return_legacy_format:
        if result:
            summary = processor._initialize_summary()
            for item in result:
                table_type = item['表名']
                if table_type in summary:
                    summary[table_type]["found"] = True
                    summary[table_type]["pages"] = 1

            return {
                "success": True,
                "data": result,
                "summary": summary
            }
        else:
            return {
                "success": False,
                "message": "未找到任何财务报表",
                "data": [],
                "summary": processor._initialize_summary()
            }

    return result


