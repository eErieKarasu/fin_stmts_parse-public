"""只通过原生文本和 OCR 定位报表；通用 VLM 不参与页面发现。"""

import os
import re
import time
import unicodedata
from math import isfinite

from .page_classification import classification


TITLES = {
    "资产负债表": ("资产负债表",),
    "利润表": ("利润表", "损益表", "利润及利润分配表"),
    "现金流量表": ("现金流量表",),
}
SUBJECTS = {
    "资产负债表": ("货币资金", "应收账款", "存货", "资产总计", "负债合计", "所有者权益", "实收资本", "未分配利润", "应付账款", "长期借款"),
    "利润表": ("营业收入", "营业成本", "营业利润", "利润总额", "净利润", "所得税费用", "销售费用", "管理费用", "财务费用"),
    "现金流量表": ("经营活动产生的现金流量", "投资活动产生的现金流量", "筹资活动产生的现金流量", "销售商品", "购买商品", "支付给职工", "现金及现金等价物", "收到的税费返还", "吸收投资", "偿还债务"),
}
HEADERS = ("项目", "行次", "期末", "期初", "年初", "本期", "上期", "本年", "上年", "金额", "余额")


def _matches_statement_title(line, aliases):
    return any(re.fullmatch(
        r"(?:[一二三四五六七八九十\d、.()]*)(?:合并|母公司)?" + re.escape(alias)
        + r"(?:[（(]?续[表页]?[）)]?)?", line,
    ) for alias in aliases)


def restore_statement_title_lines(texts, boxes):
    """只拼回页首同一视觉行的独立报表标题，保留其余 OCR 文字框顺序。"""
    original = "\n".join(texts)
    if boxes is None or len(boxes) != len(texts) or not texts:
        return original
    records = []
    try:
        for index, box in enumerate(boxes):
            if len(box) != 4:
                return original
            xs = [float(point[0]) for point in box]
            ys = [float(point[1]) for point in box]
            if not all(isfinite(value) for value in xs + ys):
                return original
            left, right, top, bottom = min(xs), max(xs), min(ys), max(ys)
            if right <= left or bottom <= top:
                return original
            records.append((index, left, top, bottom, (top + bottom) / 2))
    except (TypeError, ValueError, IndexError, OverflowError):
        return original

    # 用文字范围估算页首区域，避免在正文中拼接跨栏的标题引用。
    first_top = min(record[2] for record in records)
    last_bottom = max(record[3] for record in records)
    title_bottom = first_top + (last_bottom - first_top) * 0.25
    rows = []
    for record in sorted(records, key=lambda item: (item[4], item[1])):
        if record[3] > title_bottom:
            continue
        # 相对首个框判断，不让多个相邻行通过逐框串联被误合并。
        matching_rows = [row for row in rows if abs(record[4] - row[0][4]) <=
                         0.5 * min(record[3] - record[2], row[0][3] - row[0][2])]
        if matching_rows:
            min(matching_rows, key=lambda row: abs(record[4] - row[0][4])).append(record)
        else:
            rows.append([record])

    replacements = {}
    consumed = set()
    for row in rows:
        if len(row) < 2:
            continue
        ordered = sorted(row, key=lambda item: item[1])
        title = re.sub(r"\s+", "", unicodedata.normalize(
            "NFKC", "".join(texts[item[0]] for item in ordered),
        )).strip("#*|：:")
        if not any(_matches_statement_title(title, aliases) for aliases in TITLES.values()):
            continue
        indices = {item[0] for item in row}
        first_index = min(indices)
        replacements[first_index] = title
        consumed.update(indices - {first_index})
    return "\n".join(replacements.get(index, text) for index, text in enumerate(texts)
                     if index not in consumed)


def classify_statement_text(text: str, *, source="native_text") -> dict:
    """关键词只作为线索；标题、科目和金额共同成立才直接命中。"""
    if not isinstance(text, str):
        return classification("uncertain", source=source, reason="未取得有效文本")
    text = unicodedata.normalize("NFKC", text)
    text = re.sub(r"<[^>]+>", "\n", text)
    compact = re.sub(r"\s+", "", text)
    if len(compact) < 20 or compact.count("\ufffd") > len(compact) * 0.01:
        return classification("uncertain", source=source, reason="文本过少或乱码")

    lines = [re.sub(r"\s+", "", line).strip("#*|：:") for line in text.splitlines()]
    # 目录需要同时出现多个带页码的条目，不能仅凭正文中出现“目录”跳过。
    toc_rows = sum(bool(re.search(r"[.·…]{2,}\d+$", line)) for line in lines)
    toc_titles = sum(any(alias in line for aliases in TITLES.values() for alias in aliases) for line in lines)
    if any(line == "目录" for line in lines[:12]) and (toc_rows >= 2 or toc_titles >= 2):
        return classification("not_matched", source=source, reason="目录页")

    # 附注、权益变动表等有明确标题时，可排除，避免科目引用触发模型分类。
    excluded_titles = ("所有者权益变动表", "股东权益变动表", "审计报告", "财务报表附注")
    excluded = any(any(title in line for title in excluded_titles) and len(line) < 40 for line in lines[:8])
    candidates = {}
    subject_counts = {}
    for index, (table_type, aliases) in enumerate(TITLES.items(), 1):
        title = next((line for line in lines if _matches_statement_title(line, aliases)), "")
        form = re.search(r"会(?:小)?企0?" + str(index) + r"表", compact)
        subject_counts[table_type] = sum(subject in compact for subject in SUBJECTS[table_type])
        if title or form:
            candidates[table_type] = (title, subject_counts[table_type])

    numbers = len(re.findall(r"(?<![\w])[-(]?\d[\d,]*(?:\.\d+)?", text))
    has_headers = any(header in compact for header in HEADERS)
    if len(candidates) == 1 and not excluded:
        table_type, (title, subject_count) = next(iter(candidates.items()))
        if subject_count >= 2 and numbers >= 4 and has_headers and title:
            if "合并" in title:
                table_type = "合并" + table_type
            result = classification("matched", table_type=table_type, title=title, source=source, reason="标题、科目及金额共同命中")
            if re.search(r"合并\|母公司", compact):
                base_type = table_type.removeprefix("合并")
                result["table_types"] = [base_type, "合并" + base_type]
            return result
    if excluded and not candidates:
        result = classification("not_matched", source=source, reason="明确的非目标报表或附注标题")
        if any(re.fullmatch(r"(?:20\d{2}年?度?)?(?:合并)?财务报表附注(?:[（(]续[）)])?", line)
               for line in lines[:8]):
            result["document_section"] = "notes"
        return result
    equity_headers = ("其他权益工具", "资本公积", "其他综合收益", "专项储备", "未分配利润", "所有者权益合计")
    equity_rows = ("本期增减变动", "综合收益总额", "所有者投入", "利润分配", "所有者权益内部结转")
    if (not candidates and sum(word in compact for word in equity_headers) >= 4
            and sum(word in compact for word in equity_rows) >= 2):
        return classification("not_matched", source=source, reason="权益变动表列结构及变动项目共同命中")
    if candidates:
        return classification("uncertain", source=source, reason="目标标题或表号存在，但表型或内容尚不完整")
    if re.search(r"balance\s*sheet|income\s*statement|cash\s*flow", text, re.I):
        return classification("uncertain", source=source, reason="英文报表线索需要人工确认表型")
    continuation_types = [kind for kind, count in subject_counts.items()
                          if count >= 2 and numbers >= 4 and has_headers]
    if continuation_types or "续表" in compact:
        result = classification("uncertain", source=source, reason="无标题表格，需结合相邻报表定位续页")
        result["continuation_types"] = continuation_types
        return result
    readable = len(re.findall(r"[\u4e00-\u9fffA-Za-z0-9]", compact))
    if len(compact) < 80 or readable / len(compact) < 0.6:
        return classification("uncertain", source=source, reason="文本不足以可靠排除财报")
    return classification("not_matched", source=source, reason="未出现独立目标报表标题或续表结构")


class PDFPageDiscovery:
    def __init__(self, config, page_processor):
        self.config = config.get("pdf_parse", {}).get("discovery", {})
        self.page_processor = page_processor
        self.prepared_images = {}
        retries = self.config.get("ocr_retries", 1)
        try:
            self.ocr_retries = max(0, min(3, int(retries)))
        except (ValueError, TypeError):
            self.ocr_retries = 1

    def read_native(self, doc, page_num):
        """由调度线程读取 PyMuPDF，避免跨线程共享文档。"""
        try:
            page = doc[page_num]
            text = page.get_text("text", sort=True)
            result = classify_statement_text(text)
            # 带页眉文本的扫描页、图文混排页不能仅凭已有文本排除。
            image_area = sum((info["bbox"][2] - info["bbox"][0]) * (info["bbox"][3] - info["bbox"][1]) for info in page.get_image_info())
            if image_area > page.rect.get_area() * 0.2:
                return classification("uncertain", source="native_text", reason="页面含大幅图像，需要OCR")
            result["page_text"] = text
            return result
        except Exception as exc:
            return classification("uncertain", source="native_text", reason=f"读取原生文本失败: {exc}")

    def prepare_image(self, image_path):
        """一页只纠正一次方向；校正图片由本次 PDF 任务持有。"""
        if image_path not in self.prepared_images:
            self.prepared_images[image_path] = self.page_processor.correct_image_orientation(
                image_path, strict=True,
            )
        return self.prepared_images[image_path]

    def close(self):
        for original, prepared in self.prepared_images.items():
            if os.path.abspath(original) != os.path.abspath(prepared):
                try:
                    os.remove(prepared)
                except FileNotFoundError:
                    pass
        self.prepared_images.clear()

    def resolve(self, image_path, initial):
        if initial["status"] != "uncertain":
            return initial
        orientation_started = time.monotonic()
        try:
            prepared = self.prepare_image(image_path)
        except Exception as exc:
            return {**classification("failed", source="orientation", reason=f"方向纠正失败: {exc}"),
                    "ocr_calls": 0, "orientation_seconds": round(time.monotonic() - orientation_started, 3)}
        orientation_seconds = round(time.monotonic() - orientation_started, 3)
        start = time.monotonic()
        result = initial
        for attempt in range(self.ocr_retries + 1):
            try:
                content = self.page_processor.extract_discovery_text(prepared)
                result = classify_statement_text(content, source="rapidocr")
                result["page_text"] = content
                result["ocr_calls"] = attempt + 1
                break
            except Exception as exc:
                result = classification("failed", source="rapidocr", reason=f"OCR失败: {exc}")
                result["ocr_calls"] = attempt + 1
        result["ocr_seconds"] = round(time.monotonic() - start, 3)
        result["orientation_seconds"] = orientation_seconds
        return result


def resolve_continuations(detections):
    """只将紧邻已定位报表、且科目结构一致的无标题页归为续页。"""
    changed = True
    while changed:
        changed = False
        for page, item in sorted(detections.items()):
            candidates = item.get("continuation_types", [])
            if item["status"] != "uncertain" or not candidates:
                continue
            neighbors = [detections.get(page + offset, {}) for offset in (-1, 1)]
            types = {neighbor["table_type"] for neighbor in neighbors
                     if neighbor.get("status") == "matched"
                     and neighbor["table_type"].removeprefix("合并") in candidates}
            if len(types) == 1:
                table_type = types.pop()
                detections[page] = {**item, **classification(
                    "matched", table_type=table_type, title=table_type + "（续）",
                    source=item["source"], reason="相邻表型与续页科目结构一致",
                )}
                changed = True


def group_statement_pages(detections, target_tables):
    groups = []
    for page, item in sorted(detections.items()):
        if item["status"] != "matched" or not set(item.get("table_types", [item["table_type"]])) & target_tables:
            continue
        if groups and groups[-1]["table_type"] == item["table_type"] and groups[-1]["pages"][-1] == page - 1:
            groups[-1]["pages"].append(page)
        else:
            groups.append({"table_type": item["table_type"], "pages": [page]})
    return groups
