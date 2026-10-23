"""财报结果字典与 Markdown 诊断文件的公共输出格式。"""

import os
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List, Optional

from .statement_metadata_resolver import StatementPageMetadata
from fin_stmts_parse.utils.logger import logger


@dataclass
class StatementMarkdownSection:
    content: str
    extraction_method: str
    page: Optional[int] = None


def build_statement_result(
    source_file: str,
    table_type: str,
    data: Dict,
    metadata: StatementPageMetadata,
    markdown: str,
    *,
    company_name: str = "",
    is_consolidated: bool = False,
    page: Optional[int] = None,
) -> Dict:
    """保留现有对外字段，图片不添加页码，PDF 使用首个片段的页码。"""
    result = {
        "文件路径": source_file,
        "表名": table_type,
        "日期": metadata.date,
        "单位": metadata.unit,
        "company_name": company_name or metadata.company_name,
        "合并": "是" if is_consolidated else "否",
        "数据": data,
        "Markdown": markdown,
        "metadata": metadata.to_dict(),
    }
    if page is not None:
        result["page"] = page
    return result


def save_statement_markdown(
    output_file: str,
    table_type: str,
    source_file: str,
    sections: List[StatementMarkdownSection],
) -> None:
    """共用文件头与分节写入，保留独立图片和多页 PDF 的记录格式。"""
    with open(output_file, "w", encoding="utf-8") as file:
        file.write(f"# {table_type}提取结果\n\n")
        file.write(f"**提取时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        file.write(f"**来源文件**: {os.path.basename(source_file)}\n")
        if len(sections) == 1 and sections[0].page is None:
            section = sections[0]
            file.write(f"**提取方式**: {section.extraction_method}\n\n")
            file.write("---\n\n")
            file.write(section.content)
            file.write("\n")
        else:
            file.write("\n")
            for section in sections:
                file.write("---\n\n")
                file.write(f"### 第 {section.page} 页\n")
                file.write(f"**提取方式**: {section.extraction_method}\n\n")
                file.write(section.content)
                file.write("\n\n")


def save_raw_extraction_snapshot(
    output_dir: Optional[str],
    source_file: str,
    page: int,
    table_type: str,
    extraction_method: str,
    content: str,
) -> None:
    """在解析前保存每次原始提取，解析失败也保留诊断材料。"""
    if not output_dir:
        return
    try:
        os.makedirs(output_dir, exist_ok=True)
        source_name = os.path.splitext(os.path.basename(source_file))[0]
        safe_table_type = _safe_filename_token(table_type or "unknown")
        safe_method = _safe_filename_token(extraction_method or "unknown")
        output_file = os.path.join(
            output_dir,
            f"{source_name}_page_{int(page):03d}_{safe_table_type}_{safe_method}_raw.md",
        )
        with open(output_file, "w", encoding="utf-8") as file:
            file.write(f"# {table_type}原始提取结果\n\n")
            file.write(f"**提取时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            file.write(f"**来源文件**: {os.path.basename(source_file)}\n")
            file.write(f"**页码**: {page}\n")
            file.write(f"**提取方式**: {extraction_method}\n\n")
            file.write("---\n\n")
            file.write(content or "")
            file.write("\n")
    except Exception as exc:
        logger.warning(f"保存原始提取内容失败: {exc}")


def _safe_filename_token(value: str) -> str:
    safe_value = re.sub(r'[\\/:"*?<>|\s]+', "_", str(value or "").strip())
    return safe_value.strip("._") or "unknown"
