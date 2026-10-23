"""独立图片的财报入口，单页识别交给 StatementPageProcessor。"""

import os
from typing import Dict, List, Optional

from .statement_page_processor import StatementPageProcessor
from .statement_output import StatementMarkdownSection, build_statement_result, save_statement_markdown
from fin_stmts_parse.utils.logger import logger


class ImageFinancialProcessor:
    def __init__(
        self,
        config: Dict,
        use_paddle: bool = False,
        llm_client=None,
        *,
        page_processor: Optional[StatementPageProcessor] = None,
    ):
        self.page_processor = page_processor if page_processor is not None else StatementPageProcessor(
            config, use_paddle, llm_client=llm_client
        )
        self.logger = logger

    def process_image(
        self,
        image_path: str,
        output_dir: str = None,
        is_consolidated: Optional[bool] = None,
        report_period: Optional[str] = None,
    ) -> List[Dict]:
        """处理独立图片，完成文件级日期决策并输出现有结果格式。"""
        try:
            if not os.path.exists(image_path):
                raise FileNotFoundError(f"找不到图片文件: {image_path}")
            self.logger.info(f"[LIFECYCLE] 开始处理图片: {image_path}")
            page_result = self.page_processor.process_page(image_path)
            if page_result is None:
                return []

            resolver = self.page_processor.metadata_resolver
            file_metadata = resolver.extract_statement_metadata_from_filename(
                os.path.basename(image_path), page_result.table_type
            )
            file_level_metadata = resolver.resolve_file_level_statement_date_metadata(
                [page_result.metadata], file_metadata
            )
            metadata = resolver.resolve_statement_metadata_date(
                page_result.metadata, file_metadata, file_level_metadata
            )
            results = []
            for variant in page_result.variants:
                if is_consolidated is not None and variant.is_consolidated != is_consolidated:
                    continue
                markdown = self.page_processor.render_statement_markdown_with_metadata(
                    variant.table_content, variant.table_type, metadata
                )
                results.append(build_statement_result(
                    image_path, variant.table_type, variant.data, metadata, markdown,
                    company_name=page_result.company_name,
                    is_consolidated=variant.is_consolidated,
                ))
                if output_dir:
                    os.makedirs(output_dir, exist_ok=True)
                    filename = f"{os.path.splitext(os.path.basename(image_path))[0]}_{variant.table_type}.md"
                    save_statement_markdown(
                        os.path.join(output_dir, filename), variant.table_type, image_path,
                        [StatementMarkdownSection(markdown, page_result.extraction_method)],
                    )
                self.logger.info(f"[LIFECYCLE] ✅ {variant.table_type} 解析完成")
            return results
        except Exception as exc:
            self.logger.error(f"图片解析异常（{image_path}）：{exc}")
            raise Exception(f"图片解析异常（{image_path}）：{exc}") from exc

    def _build_summary(self, table_type: str) -> Dict:
        """构建结果摘要"""
        summary = {
            "资产负债表": {"found": False, "pages": 0},
            "合并资产负债表": {"found": False, "pages": 0},
            "利润表": {"found": False, "pages": 0},
            "合并利润表": {"found": False, "pages": 0},
            "现金流量表": {"found": False, "pages": 0},
            "合并现金流量表": {"found": False, "pages": 0}
        }

        if table_type in summary:
            summary[table_type]["found"] = True
            summary[table_type]["pages"] = 1

        return summary



def process_image_pipeline(
    image_path: str,
    output_dir: str,
    config: Dict,
    use_paddle: bool = False,
    is_consolidated: Optional[bool] = None,
    report_period: Optional[str] = None,
    return_legacy_format: bool = False
) -> Dict:
    """
    图片处理管道函数（兼容旧接口）

    Args:
        image_path: 图片路径
        output_dir: 输出目录
        config: 配置字典
        use_paddle: 是否使用PaddleOCRVL
        is_consolidated: 是否为合并报表
        report_period: 报告周期
        return_legacy_format: 是否返回旧格式（包含success等字段）

    Returns:
        处理结果 - 如果return_legacy_format=True返回旧格式字典，否则返回列表
    """
    processor = ImageFinancialProcessor(config, use_paddle)
    result = processor.process_image(image_path, output_dir, is_consolidated, report_period)

    # 如果需要返回旧格式（用于向后兼容）
    if return_legacy_format:
        if result:
            return {
                "success": True,
                "data": result,
                "summary": processor._build_summary(result[0]['表名']) if result else {}
            }
        else:
            return {
                "success": False,
                "message": "未识别到财务报表",
                "data": []
            }

    return result


