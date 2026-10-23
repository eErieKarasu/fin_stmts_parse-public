"""页面分类契约：只有明确否定才能跳过页面，失败和不确定必须显式处理。"""

from typing import Dict, Iterable


def classification(status: str, *, table_type=None, title="", source="vlm", reason="") -> Dict:
    return {
        "status": status,
        "has_target_table": True if status == "matched" else False if status == "not_matched" else None,
        "table_type": table_type,
        "extracted_title": title,
        "is_consolidated": bool(table_type and table_type.startswith("合并")),
        "source": source,
        "analysis": reason,
    }


def normalize_classification(result: Dict, target_tables: Iterable[str]) -> Dict:
    """兼容旧布尔返回值，同时拒绝缺失字段、字符串布尔值和矛盾响应。"""
    if not isinstance(result, dict):
        return classification("uncertain", reason="分类响应不是对象")
    status = result.get("status")
    if status in ("failed", "uncertain"):
        return {**result, "has_target_table": None, "table_type": None}
    matched = result.get("has_target_table")
    table_type = result.get("table_type")
    if matched is True and table_type in target_tables and status in (None, "matched"):
        return {**result, "status": "matched"}
    if matched is False and table_type in (None, "null", "") and status in (None, "not_matched"):
        return {**result, "status": "not_matched", "table_type": None}
    return classification("uncertain", reason="分类响应字段缺失、无效或互相矛盾")


class PageDiscoveryError(RuntimeError):
    """发现阶段未完成；pages 使用从 1 开始的页码并保留每页失败原因。"""

    def __init__(self, pages: Dict[int, Dict]):
        self.pages = pages
        details = "; ".join(f"第 {page} 页: {item.get('analysis', item['status'])}" for page, item in sorted(pages.items()))
        super().__init__(f"页面分类未完成，不能视为无财务报表: {details}")
