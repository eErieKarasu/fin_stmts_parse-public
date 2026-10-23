from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from types import MappingProxyType
from typing import Any, Dict, Iterable, List, Mapping, Optional


STATEMENT_TYPE_BY_TABLE_NAME = MappingProxyType({
    "资产负债表": "balance",
    "利润表": "profit",
    "现金流量表": "cashflow",
})

STATEMENT_TYPES = ("balance", "profit", "cashflow")


@dataclass(frozen=True)
class StatementMarkdownDocument:
    table_name: str
    table_type: str = ""
    page: Optional[int] = None
    date: str = "N/A"
    period: str = ""
    unit: str = "N/A"
    company_name: str = ""
    is_consolidated: bool = False
    content: str = ""
    source_file_name: str = ""
    source_file_path: str = ""

    def __post_init__(self) -> None:
        if not self.table_type and self.table_name:
            try:
                resolved_table_type, _ = resolve_statement_type(
                    self.table_name,
                    self.is_consolidated,
                )
            except ValueError:
                resolved_table_type = ""
            object.__setattr__(self, "table_type", resolved_table_type)
        if not self.period:
            object.__setattr__(self, "period", resolve_statement_period(self.date))

    def to_dict(self) -> Dict[str, Any]:
        item = {
            "table_name": self.table_name,
            "table_type": self.table_type,
            "date": self.date,
            "period": self.period,
            "is_consolidated": self.is_consolidated,
            "content": self.content,
        }
        if self.page is not None:
            item["page"] = self.page
        if self.unit and self.unit != "N/A":
            item["unit"] = self.unit
        if self.source_file_name:
            item["source_file_name"] = self.source_file_name
        if self.source_file_path:
            item["source_file_path"] = self.source_file_path
        return item


@dataclass(frozen=True)
class MappedStatementResult:
    statement_type: str
    table_name: str
    date: str = "N/A"
    unit: str = "N/A"
    is_consolidated: bool = False
    canonical_data_full: Dict[str, Any] = field(default_factory=dict)
    canonical_labels: Dict[str, str] = field(default_factory=dict)
    view_data_full: Dict[str, Any] = field(default_factory=dict)
    view_labels: Dict[str, str] = field(default_factory=dict)
    view_groups: List[Dict[str, Any]] = field(default_factory=list)
    semantic_config_path_used: str = ""
    view_config_path_used: str = ""
    source_file_name: str = ""
    source_file_path: str = ""

    def to_serialized_canonical_data(self, *, include_empty: bool = True) -> Dict[str, List[Any]]:
        return _serialize_labeled_mapping(
            self.canonical_data_full,
            self.canonical_labels,
            include_empty=include_empty,
        )

    def to_serialized_view_data(self, *, include_empty: bool = True) -> Dict[str, List[Any]]:
        return _serialize_labeled_mapping(
            self.view_data_full,
            self.view_labels,
            include_empty=include_empty,
        )

    def to_serialized_view_data_tree(self, *, include_empty: bool = True) -> List[Dict[str, Any]]:
        return _serialize_grouped_view_data(
            self.view_data_full,
            self.view_labels,
            self.view_groups,
            include_empty=include_empty,
        )


def _serialize_labeled_mapping(
    data: Mapping[str, Any],
    labels: Mapping[str, str],
    *,
    include_empty: bool,
) -> Dict[str, List[Any]]:
    serialized: Dict[str, List[Any]] = {}
    for code, value in data.items():
        label = labels.get(code)
        if not label:
            continue
        if not include_empty and _is_empty_mapping_value(value):
            continue
        serialized[code] = [label, *_serialize_mapping_value(value)]
    return serialized


def _serialize_grouped_view_data(
    data: Mapping[str, Any],
    labels: Mapping[str, str],
    groups: Iterable[Mapping[str, Any]],
    *,
    include_empty: bool,
) -> List[Dict[str, Any]]:
    rows_by_code: Dict[str, List[Any]] = {}
    for code, value in data.items():
        label = labels.get(code)
        if not label:
            continue
        if not include_empty and _is_empty_mapping_value(value):
            continue
        rows_by_code[code] = [label, *_serialize_mapping_value(value)]

    group_list = [
        group
        for group in groups
        if isinstance(group, Mapping) and str(group.get("key") or "").strip()
    ]
    if not group_list:
        return _build_ungrouped_view_tree(rows_by_code)

    children_by_parent: Dict[str, List[str]] = {}
    group_item_codes_by_key: Dict[str, List[str]] = {}
    groups_by_key: Dict[str, Dict[str, Any]] = {}
    roots: List[str] = []

    for group in group_list:
        key = str(group.get("key") or "").strip()
        parent = str(group.get("parent") or "").strip()
        item_codes = [
            str(code)
            for code in group.get("item_codes", [])
            if str(code or "").strip()
        ]
        group_item_codes_by_key[key] = item_codes
        groups_by_key[key] = {
            "name": str(group.get("name") or key),
            "level": group.get("level", 1),
            "items": [],
        }
        row_code = str(group.get("row_code") or "").strip()
        if row_code:
            groups_by_key[key]["row_code"] = row_code
        if parent:
            groups_by_key[key]["parent"] = parent
            children_by_parent.setdefault(parent, []).append(key)
        else:
            roots.append(key)

    def populate_items(group_key: str) -> None:
        child_keys = [
            child_key
            for child_key in children_by_parent.get(group_key, [])
            if child_key in groups_by_key
        ]
        for child_key in child_keys:
            populate_items(child_key)

        inserted_children = set()
        child_codes_by_key = {
            child_key: set(group_item_codes_by_key.get(child_key, []))
            for child_key in child_keys
        }
        first_code_by_child = {
            child_key: group_item_codes_by_key.get(child_key, [None])[0]
            for child_key in child_keys
            if group_item_codes_by_key.get(child_key)
        }

        items: List[Dict[str, Any]] = []
        group_row_code = str(groups_by_key[group_key].get("row_code") or "").strip()
        for code in group_item_codes_by_key.get(group_key, []):
            if group_row_code and code == group_row_code:
                continue

            child_at_code = next(
                (
                    child_key
                    for child_key, first_code in first_code_by_child.items()
                    if first_code == code and child_key not in inserted_children
                ),
                None,
            )
            if child_at_code is not None:
                items.append({"group": child_at_code})
                inserted_children.add(child_at_code)
                continue

            if any(code in codes for codes in child_codes_by_key.values()):
                continue

            if code in rows_by_code:
                items.append({"row": code})

        for child_key in child_keys:
            if child_key not in inserted_children:
                items.append({"group": child_key})

        groups_by_key[group_key]["items"] = items

    for key in roots:
        if key in groups_by_key:
            populate_items(key)

    return [
        _build_group_view_node(key, groups_by_key, rows_by_code)
        for key in roots
        if key in groups_by_key
    ]


def _build_ungrouped_view_tree(rows_by_code: Mapping[str, List[Any]]) -> List[Dict[str, Any]]:
    return [
        _build_row_view_node(code, row)
        for code, row in rows_by_code.items()
    ]


def _build_group_view_node(
    group_key: str,
    groups_by_key: Mapping[str, Mapping[str, Any]],
    rows_by_code: Mapping[str, List[Any]],
) -> Dict[str, Any]:
    group = groups_by_key[group_key]
    children: List[Dict[str, Any]] = []
    group_row_code = str(group.get("row_code") or "").strip()
    for item in group.get("items", []):
        if not isinstance(item, Mapping):
            continue
        child_group_key = item.get("group")
        if child_group_key and child_group_key in groups_by_key:
            children.append(_build_group_view_node(child_group_key, groups_by_key, rows_by_code))
            continue

        row_code = item.get("row")
        if row_code and row_code in rows_by_code:
            children.append(_build_row_view_node(row_code, rows_by_code[row_code]))

    parent = group.get("parent")

    if children:
        node = {
            "type": "group",
            "key": group_key,
            "name": group.get("name") or group_key,
            "level": group.get("level", 1),
            "children": children,
        }
        if group_row_code and group_row_code in rows_by_code:
            node["code"] = group_row_code
            node["values"] = rows_by_code[group_row_code][1:]
        if parent:
            node["parent"] = parent
        return node

    if group_row_code and group_row_code in rows_by_code:
        node = _build_row_view_node(group_row_code, rows_by_code[group_row_code])
        if parent:
            node["parent"] = parent
        return node

    node = {
        "type": "group",
        "key": group_key,
        "name": group.get("name") or group_key,
        "level": group.get("level", 1),
        "children": [],
    }
    if parent:
        node["parent"] = parent
    return node


def _build_row_view_node(code: str, row: List[Any]) -> Dict[str, Any]:
    return {
        "type": "row",
        "code": code,
        "name": row[0] if row else code,
        "values": row[1:] if row else [],
    }


@dataclass(frozen=True)
class InspectionResult:
    passed: bool
    remark: str = ""
    merged_data: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    details: List[Dict[str, Any]] = field(default_factory=list)
    summary: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class StatementExcelArtifact:
    source_file_name: str = ""
    source_file_path: str = ""
    excel_file_name: str = ""
    excel_file_path: str = ""
    sheet_names: List[str] = field(default_factory=list)
    exported_sheets: List[Dict[str, Any]] = field(default_factory=list)
    skipped_tables: List[Dict[str, Any]] = field(default_factory=list)
    summary: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        item = {
            "excel_file_name": self.excel_file_name,
            "excel_file_path": self.excel_file_path,
            "sheet_names": list(self.sheet_names),
            "skipped_tables": list(self.skipped_tables),
            "summary": dict(self.summary),
        }
        if self.source_file_name:
            item["source_file_name"] = self.source_file_name
        if self.source_file_path:
            item["source_file_path"] = self.source_file_path
        return item


def normalize_is_consolidated(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        return normalized in {"true", "1", "yes", "y", "是"}
    return bool(value)


def resolve_statement_period(value: Any) -> str:
    normalized = str(value or "").strip()
    if len(normalized) == 4 and normalized.isdigit():
        return "YEAR"
    if len(normalized) != 6 or not normalized.isdigit():
        return ""

    month = int(normalized[4:])
    if month < 1 or month > 12:
        return ""
    if month == 12:
        return "YEAR"
    if month == 6:
        return "INTERIM"
    if month in {3, 9}:
        return "QUATER"
    return "MONTH"


def resolve_statement_type(
    table_name: str,
    is_consolidated: Any = None,
) -> tuple[str, bool]:
    if not isinstance(table_name, str) or not table_name.strip():
        raise ValueError("table_name 不能为空")

    normalized_table_name = table_name.strip()
    normalized_name = normalized_table_name.removeprefix("合并")

    for candidate, statement_type in STATEMENT_TYPE_BY_TABLE_NAME.items():
        if candidate in normalized_name:
            resolved_consolidated = (
                normalize_is_consolidated(is_consolidated)
                or normalized_table_name.startswith("合并")
            )
            return statement_type, resolved_consolidated

    raise ValueError(f"无法识别的 table_name: {table_name}")


def statement_markdown_document_from_item(
    item: Mapping[str, Any],
    *,
    default_source_file_path: str = "",
    default_source_file_name: str = "",
) -> Optional[StatementMarkdownDocument]:
    if not isinstance(item, Mapping):
        return None

    table_name = _first_non_empty_string(item, "table_name", "表名")
    if not table_name:
        return None

    source_file_path = (
        _first_non_empty_string(item, "source_file_path", "文件路径")
        or default_source_file_path
    )
    source_file_name = (
        _first_non_empty_string(item, "source_file_name", "file_name", "fileName")
        or default_source_file_name
    )
    if not source_file_name and source_file_path:
        source_file_name = Path(source_file_path).name

    if "is_consolidated" in item:
        consolidated_value = item.get("is_consolidated")
    elif "合并" in item:
        consolidated_value = item.get("合并")
    else:
        consolidated_value = False

    return StatementMarkdownDocument(
        table_name=table_name,
        page=_first_valid_page(item, "page", "page_number", "page_num", "页码"),
        date=_first_non_empty_string(item, "date", "日期") or "N/A",
        unit=_first_non_empty_string(item, "unit", "单位") or "N/A",
        company_name=_first_non_empty_string(
            item,
            "company_name",
            "companyName",
            "公司名称",
            "编制单位",
            "企业名称",
            "单位名称",
        ),
        is_consolidated=normalize_is_consolidated(consolidated_value),
        content=_first_non_empty_string(item, "content", "Markdown"),
        source_file_name=source_file_name,
        source_file_path=source_file_path,
    )


def statement_markdown_documents_from_items(
    items: Iterable[Mapping[str, Any]],
    *,
    default_source_file_path: str = "",
    default_source_file_name: str = "",
) -> List[StatementMarkdownDocument]:
    documents: List[StatementMarkdownDocument] = []
    for item in items:
        document = statement_markdown_document_from_item(
            item,
            default_source_file_path=default_source_file_path,
            default_source_file_name=default_source_file_name,
        )
        if document is not None:
            documents.append(document)
    return documents


def mapped_statement_result_from_item(item: Mapping[str, Any]) -> Optional[MappedStatementResult]:
    if not isinstance(item, Mapping):
        return None

    canonical_payload = item.get("canonical_data_full")
    if not isinstance(canonical_payload, Mapping):
        canonical_payload = item.get("canonical_data")
    if not isinstance(canonical_payload, Mapping):
        return None

    view_payload = _flatten_serialized_view_payload(item.get("view_data_full"))
    if not view_payload:
        view_payload = _flatten_serialized_view_payload(item.get("view_data"))

    statement_type = item.get("statement_type")
    if not isinstance(statement_type, str) or not statement_type.strip():
        table_name = _first_non_empty_string(item, "table_name", "表名")
        if not table_name:
            return None
        try:
            statement_type, resolved_consolidated = resolve_statement_type(
                table_name,
                item.get("is_consolidated"),
            )
        except ValueError:
            return None
    else:
        statement_type = statement_type.strip()
        resolved_consolidated = normalize_is_consolidated(item.get("is_consolidated", False))

    normalized_canonical_data: Dict[str, Any] = {}
    canonical_labels: Dict[str, str] = {}
    for code, value in canonical_payload.items():
        label, normalized_value = _split_compact_mapping_value(value)
        if label:
            canonical_labels[str(code)] = label
        normalized_canonical_data[str(code)] = normalized_value

    normalized_view_data: Dict[str, Any] = {}
    view_labels: Dict[str, str] = {}
    for code, value in view_payload.items():
        label, normalized_value = _split_compact_mapping_value(value)
        if label:
            view_labels[str(code)] = label
        normalized_view_data[str(code)] = normalized_value

    return MappedStatementResult(
        statement_type=statement_type,
        table_name=_first_non_empty_string(item, "table_name", "表名") or statement_type,
        date=_first_non_empty_string(item, "date", "日期") or "N/A",
        unit=_first_non_empty_string(item, "unit", "单位") or "N/A",
        is_consolidated=resolved_consolidated,
        canonical_data_full=normalized_canonical_data,
        canonical_labels=canonical_labels,
        view_data_full=normalized_view_data,
        view_labels=view_labels,
        view_groups=[],
        semantic_config_path_used=_first_non_empty_string(item, "semantic_config_path_used"),
        view_config_path_used=_first_non_empty_string(item, "view_config_path_used"),
        source_file_name=_first_non_empty_string(item, "source_file_name", "file_name", "fileName"),
        source_file_path=_first_non_empty_string(item, "source_file_path", "文件路径"),
    )


def _flatten_serialized_view_payload(payload: Any) -> Dict[str, Any]:
    if not payload:
        return {}

    if isinstance(payload, Mapping) and _looks_like_compact_view_payload(payload):
        rows = payload.get("rows")
        return dict(rows) if isinstance(rows, Mapping) else {}

    if isinstance(payload, Mapping) and not (
        "groups" in payload or "rows" in payload or "children" in payload
    ):
        return dict(payload)

    flattened: Dict[str, Any] = {}

    def visit(node: Any) -> None:
        if isinstance(node, list):
            for item in node:
                visit(item)
            return
        if not isinstance(node, Mapping):
            return

        code = str(node.get("code") or "").strip()
        if code:
            values = node.get("values", [])
            if not isinstance(values, list):
                values = [values]
            name = str(node.get("name") or "").strip()
            flattened[code] = [name, *values] if name else values

        visit(node.get("rows", []))
        visit(node.get("groups", []))
        visit(node.get("children", []))

    visit(payload)
    return flattened


def _looks_like_compact_view_payload(payload: Mapping[str, Any]) -> bool:
    return (
        isinstance(payload.get("rows"), Mapping)
        and isinstance(payload.get("groups"), Mapping)
        and isinstance(payload.get("roots"), list)
    )


def _first_non_empty_string(item: Mapping[str, Any], *keys: str) -> str:
    for key in keys:
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _first_valid_page(item: Mapping[str, Any], *keys: str) -> Optional[int]:
    for key in keys:
        page = _normalize_page(item.get(key))
        if page is not None:
            return page
    return None


def _normalize_page(value: Any) -> Optional[int]:
    if value in ("", None):
        return None
    try:
        page = int(str(value).strip())
    except (TypeError, ValueError):
        return None
    return page if page > 0 else None


def _split_compact_mapping_value(value: Any) -> tuple[Optional[str], Any]:
    if not isinstance(value, list) or not value:
        return None, value

    first = value[0]
    if isinstance(first, str) and not _is_numeric_like(first):
        remaining = value[1:]
        if len(remaining) == 1:
            return first, remaining[0]
        return first, remaining

    return None, value


def _is_numeric_like(value: str) -> bool:
    try:
        Decimal(str(value).replace(",", ""))
        return True
    except Exception:
        return False


def _is_empty_mapping_value(value: Any) -> bool:
    if value in ("", None):
        return True
    if isinstance(value, list):
        return all(item in ("", None) for item in value)
    return False


def _serialize_mapping_value(value: Any) -> List[Any]:
    if isinstance(value, list):
        return [_serialize_scalar(item) for item in value]
    return [_serialize_scalar(value)]


def _serialize_scalar(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if value == "":
        return ""
    if value is None:
        return None
    return str(value)
