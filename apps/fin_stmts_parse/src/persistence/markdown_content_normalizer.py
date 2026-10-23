from __future__ import annotations

import re
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Dict, List, Sequence, Tuple


_TABLE_TAG_RE = re.compile(r"<\s*(/?)\s*table\b[^>]*>", re.IGNORECASE)
_CELL_LINE_BREAK_TAGS = {"br", "div", "li", "p"}
_MAX_SPAN = 1000


class MarkdownStorageNormalizationError(ValueError):
    """Raised when HTML table content cannot be safely normalized for storage."""


@dataclass(frozen=True)
class _HtmlCell:
    value: str
    rowspan: int
    colspan: int
    is_header: bool


@dataclass(frozen=True)
class _HtmlRow:
    cells: Tuple[_HtmlCell, ...]
    is_header: bool


@dataclass(frozen=True)
class _ActiveSpan:
    value: str
    remaining_rows: int


class _SingleHtmlTableParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.table_depth = 0
        self.thead_depth = 0
        self.current_cells: List[_HtmlCell] | None = None
        self.current_row_is_header = False
        self.current_cell_tag = ""
        self.current_cell_attrs: Dict[str, str] = {}
        self.current_cell_parts: List[str] | None = None
        self.caption_parts: List[str] | None = None
        self.rows: List[_HtmlRow] = []
        self.caption = ""

    def handle_starttag(
        self,
        tag: str,
        attrs: List[Tuple[str, str | None]],
    ) -> None:
        normalized_tag = tag.lower()
        if normalized_tag == "table":
            self.table_depth += 1
            if self.table_depth > 1:
                raise MarkdownStorageNormalizationError("暂不支持嵌套 HTML 表格")
            return
        if self.table_depth != 1:
            return

        if normalized_tag == "thead":
            self.thead_depth += 1
            return
        if normalized_tag == "caption":
            if self.caption_parts is not None:
                raise MarkdownStorageNormalizationError("HTML 表格包含嵌套 caption")
            self.caption_parts = []
            return
        if normalized_tag == "tr":
            self._finish_current_row()
            self.current_cells = []
            self.current_row_is_header = self.thead_depth > 0
            return
        if normalized_tag in {"th", "td"}:
            if self.current_cells is None:
                self.current_cells = []
                self.current_row_is_header = self.thead_depth > 0
            self._finish_current_cell()
            self.current_cell_tag = normalized_tag
            self.current_cell_attrs = {
                str(name).lower(): str(value or "") for name, value in attrs
            }
            self.current_cell_parts = []
            return
        if (
            self.current_cell_parts is not None
            and normalized_tag in _CELL_LINE_BREAK_TAGS
            and self.current_cell_parts
        ):
            self.current_cell_parts.append("\n")
        if (
            self.caption_parts is not None
            and normalized_tag in _CELL_LINE_BREAK_TAGS
            and self.caption_parts
        ):
            self.caption_parts.append("\n")

    def handle_startendtag(
        self,
        tag: str,
        attrs: List[Tuple[str, str | None]],
    ) -> None:
        normalized_tag = tag.lower()
        if normalized_tag == "table":
            raise MarkdownStorageNormalizationError("HTML table 不能为空标签")
        if normalized_tag == "br" and self.table_depth == 1:
            if self.current_cell_parts is not None:
                self.current_cell_parts.append("\n")
            elif self.caption_parts is not None:
                self.caption_parts.append("\n")
            return
        self.handle_starttag(tag, attrs)

    def handle_endtag(self, tag: str) -> None:
        normalized_tag = tag.lower()
        if normalized_tag == "table":
            if self.table_depth != 1:
                raise MarkdownStorageNormalizationError("HTML table 标签不匹配")
            self._finish_current_row()
            self.table_depth = 0
            return
        if self.table_depth != 1:
            return

        if normalized_tag == "thead":
            if self.thead_depth <= 0:
                raise MarkdownStorageNormalizationError("HTML thead 标签不匹配")
            self.thead_depth -= 1
            return
        if normalized_tag == "caption":
            if self.caption_parts is None:
                raise MarkdownStorageNormalizationError("HTML caption 标签不匹配")
            self.caption = _normalize_cell_text("".join(self.caption_parts))
            self.caption_parts = None
            return
        if normalized_tag in {"th", "td"}:
            if self.current_cell_parts is None:
                raise MarkdownStorageNormalizationError("HTML 单元格标签不匹配")
            self._finish_current_cell()
            return
        if normalized_tag == "tr":
            if self.current_cells is None:
                raise MarkdownStorageNormalizationError("HTML tr 标签不匹配")
            self._finish_current_row()

    def handle_data(self, data: str) -> None:
        if self.table_depth != 1:
            return
        if self.current_cell_parts is not None:
            self.current_cell_parts.append(data)
        elif self.caption_parts is not None:
            self.caption_parts.append(data)

    def _finish_current_cell(self) -> None:
        if self.current_cell_parts is None:
            return
        if self.current_cells is None:
            raise MarkdownStorageNormalizationError("HTML 单元格不在 tr 内")
        self.current_cells.append(
            _HtmlCell(
                value=_normalize_cell_text("".join(self.current_cell_parts)),
                rowspan=_parse_span(self.current_cell_attrs.get("rowspan")),
                colspan=_parse_span(self.current_cell_attrs.get("colspan")),
                is_header=(
                    self.current_cell_tag == "th"
                    or self.current_row_is_header
                ),
            )
        )
        self.current_cell_tag = ""
        self.current_cell_attrs = {}
        self.current_cell_parts = None

    def _finish_current_row(self) -> None:
        if self.current_cells is None:
            return
        self._finish_current_cell()
        if self.current_cells:
            self.rows.append(
                _HtmlRow(
                    cells=tuple(self.current_cells),
                    is_header=(
                        self.current_row_is_header
                        or all(cell.is_header for cell in self.current_cells)
                    ),
                )
            )
        self.current_cells = None
        self.current_row_is_header = False

    def close(self) -> None:
        super().close()
        if self.table_depth != 0:
            raise MarkdownStorageNormalizationError("HTML table 标签未闭合")
        if self.thead_depth != 0:
            raise MarkdownStorageNormalizationError("HTML thead 标签未闭合")
        if self.current_cell_parts is not None or self.current_cells is not None:
            raise MarkdownStorageNormalizationError("HTML 表格存在未闭合的行或单元格")
        if self.caption_parts is not None:
            raise MarkdownStorageNormalizationError("HTML caption 标签未闭合")


class MarkdownStorageContentNormalizer:
    """Normalize HTML tables to Markdown pipe tables at the persistence boundary."""

    def normalize(self, content: str) -> str:
        if not isinstance(content, str):
            raise MarkdownStorageNormalizationError("Markdown 内容必须是字符串")

        table_spans = self._find_table_spans(content)
        if not table_spans:
            return content

        normalized = content
        for start, end in reversed(table_spans):
            markdown_table = self._html_table_to_markdown(content[start:end])
            normalized = normalized[:start] + markdown_table + normalized[end:]

        if _TABLE_TAG_RE.search(normalized):
            raise MarkdownStorageNormalizationError("HTML 表格未被完整转换")
        return normalized

    @staticmethod
    def _find_table_spans(content: str) -> List[Tuple[int, int]]:
        spans: List[Tuple[int, int]] = []
        depth = 0
        start = -1
        for match in _TABLE_TAG_RE.finditer(content):
            is_closing = bool(match.group(1))
            if match.group(0).rstrip().endswith("/>"):
                raise MarkdownStorageNormalizationError("HTML table 不能为空标签")
            if is_closing:
                if depth == 0:
                    raise MarkdownStorageNormalizationError("存在多余的 HTML table 结束标签")
                depth -= 1
                if depth == 0:
                    spans.append((start, match.end()))
                    start = -1
            else:
                if depth == 0:
                    start = match.start()
                depth += 1

        if depth != 0:
            raise MarkdownStorageNormalizationError("HTML table 标签未闭合")
        return spans

    @staticmethod
    def _html_table_to_markdown(html_table: str) -> str:
        parser = _SingleHtmlTableParser()
        try:
            parser.feed(html_table)
            parser.close()
        except MarkdownStorageNormalizationError:
            raise
        except Exception as exc:
            raise MarkdownStorageNormalizationError(
                f"HTML 表格解析失败: {exc}"
            ) from exc

        if not parser.rows:
            raise MarkdownStorageNormalizationError("HTML 表格中没有有效行")

        grid, header_flags = _expand_table_grid(parser.rows)
        markdown_table = _render_markdown_grid(grid, header_flags)
        if parser.caption:
            return f"**{_escape_markdown_cell(parser.caption)}**\n\n{markdown_table}"
        return markdown_table


def _parse_span(value: str | None) -> int:
    try:
        parsed = int(str(value or "1").strip())
    except (TypeError, ValueError):
        return 1
    if parsed < 1:
        return 1
    if parsed > _MAX_SPAN:
        raise MarkdownStorageNormalizationError(
            f"HTML 单元格跨度过大: {parsed}"
        )
    return parsed


def _normalize_cell_text(value: str) -> str:
    normalized = str(value or "").replace("\xa0", " ")
    lines = []
    for line in normalized.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        compact = re.sub(r"[\t\f\v ]+", " ", line).strip()
        if compact:
            lines.append(compact)
    return "<br>".join(lines)


def _expand_table_grid(
    rows: Sequence[_HtmlRow],
) -> Tuple[List[List[str]], List[bool]]:
    sparse_rows: List[Dict[int, str]] = []
    header_flags: List[bool] = []
    active_spans: Dict[int, _ActiveSpan] = {}
    max_column = -1

    for row in rows:
        sparse_row = {
            column: span.value for column, span in active_spans.items()
        }
        new_spans: Dict[int, _ActiveSpan] = {}
        cursor = 0

        for cell in row.cells:
            while any(
                cursor + offset in sparse_row
                for offset in range(cell.colspan)
            ):
                cursor += 1

            for offset in range(cell.colspan):
                column = cursor + offset
                value = cell.value if offset == 0 or cell.is_header else ""
                sparse_row[column] = value
                if cell.rowspan > 1:
                    new_spans[column] = _ActiveSpan(
                        value=value,
                        remaining_rows=cell.rowspan - 1,
                    )
            cursor += cell.colspan

        if sparse_row:
            max_column = max(max_column, max(sparse_row))
        sparse_rows.append(sparse_row)
        header_flags.append(row.is_header)

        next_spans = {
            column: _ActiveSpan(
                value=span.value,
                remaining_rows=span.remaining_rows - 1,
            )
            for column, span in active_spans.items()
            if span.remaining_rows > 1
        }
        next_spans.update(new_spans)
        active_spans = next_spans

    if max_column < 0:
        raise MarkdownStorageNormalizationError("HTML 表格中没有有效单元格")

    width = max_column + 1
    grid = [
        [sparse_row.get(column, "") for column in range(width)]
        for sparse_row in sparse_rows
    ]
    return grid, header_flags


def _render_markdown_grid(
    grid: Sequence[Sequence[str]],
    header_flags: Sequence[bool],
) -> str:
    if not grid:
        raise MarkdownStorageNormalizationError("HTML 表格中没有有效内容")

    header_start = next(
        (index for index, is_header in enumerate(header_flags) if is_header),
        0,
    )
    header_row_count = 0
    for is_header in header_flags[header_start:]:
        if not is_header:
            break
        header_row_count += 1
    if header_row_count == 0:
        header_row_count = 1

    width = len(grid[0])
    header: List[str] = []
    for column in range(width):
        values: List[str] = []
        for row in grid[header_start:header_start + header_row_count]:
            value = str(row[column] or "").strip()
            if value and value not in values:
                values.append(value)
        header.append("<br>".join(values))

    lines = [
        _render_markdown_row(header),
        _render_markdown_row(["---"] * width, escape=False),
    ]
    lines.extend(
        _render_markdown_row(row)
        for row in grid[header_start + header_row_count:]
    )
    table_markdown = "\n".join(lines)

    prefix_lines = []
    for row in grid[:header_start]:
        values = []
        for value in row:
            normalized_value = str(value or "").strip()
            if normalized_value and normalized_value not in values:
                values.append(normalized_value)
        if values:
            prefix_lines.append(
                " / ".join(_escape_markdown_cell(value) for value in values)
            )

    if prefix_lines:
        prefix_markdown = "\n".join(prefix_lines)
        return f"{prefix_markdown}\n\n{table_markdown}"
    return table_markdown


def _render_markdown_row(
    values: Sequence[str],
    *,
    escape: bool = True,
) -> str:
    rendered_values = [
        _escape_markdown_cell(value) if escape else str(value)
        for value in values
    ]
    return f"| {' | '.join(rendered_values)} |"


def _escape_markdown_cell(value: str) -> str:
    return str(value or "").replace("|", "&#124;")
