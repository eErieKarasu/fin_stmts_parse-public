from __future__ import annotations

import base64
import html
import os
import re
import shutil
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional

try:
    import fitz
except Exception:  # pragma: no cover - import guard for minimal test envs
    fitz = None

try:
    import pandas as pd
except Exception:  # pragma: no cover - import guard for minimal test envs
    pd = None

from fin_stmts_parse.clients.llm_client import LLMClient
from fin_stmts_parse.config.prompts import PROMPTS
from fin_stmts_parse.utils.logger import logger as default_logger
from fin_stmts_parse.utils.str_util import extract_llm_json


SUPPORTED_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".bmp", ".tiff", ".tif", ".webp"}
SUPPORTED_PDF_EXTENSIONS = {".pdf"}
SUPPORTED_EXCEL_EXTENSIONS = {".xlsx", ".xls"}

AUDIT_STATUSES = {"audited", "unaudited", "unknown"}
CONFIDENCE_LEVELS = {"high", "medium", "low"}

_HTML_TAG_RE = re.compile(r"<[^>]+>")
_MARKDOWN_DECORATION_RE = re.compile(r"[*`#>]+")
_AUDIT_FIRM_SUFFIX_RE = (
    r"(?:（特殊普通合伙）|\(特殊普通合伙\)|（普通合伙）|\(普通合伙\)|"
    r"（有限合伙）|\(有限合伙\)|有限责任公司|有限公司)"
)
_AUDIT_FIRM_RE = re.compile(
    r"[\u4e00-\u9fa5A-Za-z0-9·（）()]{2,80}?会计师事务所"
    rf"{_AUDIT_FIRM_SUFFIX_RE}"
    r"|[\u4e00-\u9fa5A-Za-z0-9·（）()]{2,80}?会计师事务所"
)
_UNAUDITED_RE = re.compile(
    r"未经审计|未审计|未经会计师事务所审计|未经注册会计师审计|未经过审计|未予审计"
)
_LEADING_CONTEXT_RE = re.compile(
    r"^(?:审计机构|审计单位|审计师|会计师事务所|事务所名称|"
    r"由|经|聘请|委托|本公司聘请|本公司委托)[：:、，\s]*"
)


@dataclass(frozen=True)
class AuditFirmEvidence:
    text: str
    page: Optional[int] = None

    def to_dict(self) -> Dict[str, Any]:
        item: Dict[str, Any] = {"text": self.text}
        if self.page is not None:
            item["page"] = self.page
        return item


@dataclass(frozen=True)
class AuditFirmResult:
    audit_status: str = "unknown"
    audit_firm_name: str = ""
    confidence: str = "low"
    evidence: List[AuditFirmEvidence] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "audit_status": normalize_audit_status(self.audit_status),
            "audit_firm_name": self.audit_firm_name,
            "confidence": normalize_confidence(self.confidence),
            "evidence": [item.to_dict() for item in self.evidence],
        }


@dataclass(frozen=True)
class _AuditFirmCandidate:
    firm_name: str
    evidence: AuditFirmEvidence


def normalize_audit_status(value: Any) -> str:
    normalized = str(value or "").strip().lower()
    return normalized if normalized in AUDIT_STATUSES else "unknown"


def normalize_confidence(value: Any) -> str:
    normalized = str(value or "").strip().lower()
    return normalized if normalized in CONFIDENCE_LEVELS else "low"


def sanitize_audit_firm_name(value: Any) -> str:
    if value is None:
        return ""

    text = html.unescape(str(value))
    text = _HTML_TAG_RE.sub(" ", text)
    text = _MARKDOWN_DECORATION_RE.sub(" ", text)
    text = text.replace("\u3000", " ")
    text = re.sub(r"\s+", "", text).strip()
    if not text:
        return ""

    text = _LEADING_CONTEXT_RE.sub("", text)
    text = text.strip(" \t\r\n,，;；。:：[]【】\"'“”‘’")
    if "会计师事务所" not in text:
        return ""

    match = _AUDIT_FIRM_RE.search(text)
    if not match:
        return ""

    firm_name = match.group(0).strip(" \t\r\n,，;；。:：[]【】\"'“”‘’")
    prefix = firm_name.split("会计师事务所", 1)[0]
    if len(prefix) < 2:
        return ""
    if prefix.endswith(("未经", "未由", "未聘请", "无须", "无需", "没有")):
        return ""
    if firm_name in {"会计师事务所", "审计机构会计师事务所"}:
        return ""
    return firm_name


class FinancialStatementAuditFirmCore:
    def __init__(
        self,
        config: Optional[Dict[str, Any]] = None,
        *,
        llm_client: Optional[LLMClient] = None,
        logger: Any = None,
    ) -> None:
        self.config = config or {}
        self.logger = logger or default_logger
        if llm_client is not None:
            self.llm_client = llm_client
        else:
            llm_config = self.config.get("llm", {})
            self.llm_client = LLMClient(llm_config) if llm_config.get("base_url") else None

    def extract_local_file(self, file_path: str) -> AuditFirmResult:
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"文件不存在: {file_path}")

        file_ext = Path(file_path).suffix.lower()
        if file_ext in SUPPORTED_PDF_EXTENSIONS:
            return self.extract_from_pdf(file_path)
        if file_ext in SUPPORTED_EXCEL_EXTENSIONS:
            return self.extract_from_excel(file_path)
        if file_ext in SUPPORTED_IMAGE_EXTENSIONS:
            return self.extract_from_image(file_path)
        raise ValueError(f"不支持的文件格式: {file_ext}")

    def extract_from_text(
        self,
        text: str,
        *,
        source_type: str = "text",
        page: Optional[int] = None,
    ) -> AuditFirmResult:
        if not isinstance(text, str) or not text.strip():
            return AuditFirmResult()

        rule_result = self._extract_from_text_pages([(page, text)])
        if rule_result.audit_status != "unknown":
            return rule_result

        llm_result = self._extract_with_llm(text, source_type=source_type)
        return llm_result or rule_result

    def extract_from_pdf(self, file_path: str) -> AuditFirmResult:
        if fitz is None:
            raise RuntimeError("PyMuPDF 未安装，无法读取 PDF")

        doc = None
        try:
            doc = fitz.open(file_path)
            page_texts = [
                (page_index + 1, page.get_text("text") or "")
                for page_index, page in enumerate(doc)
            ]

            text_result = self._extract_from_text_pages(page_texts)
            if text_result.audit_status != "unknown":
                return text_result

            if not self._can_use_vlm():
                return text_result

            image_result = self._extract_from_selected_pdf_pages(doc)
            if image_result.audit_status != "unknown":
                return image_result
            return text_result
        finally:
            if doc is not None and not doc.is_closed:
                doc.close()

    def extract_from_excel(self, file_path: str) -> AuditFirmResult:
        if pd is None:
            raise RuntimeError("pandas 未安装，无法读取 Excel")

        sheet_names = self._get_visible_excel_sheet_names(file_path)
        fragments: List[str] = []
        for sheet_name in sheet_names[:8]:
            try:
                df = pd.read_excel(file_path, header=None, sheet_name=sheet_name, nrows=12)
            except Exception as exc:
                self.logger.warning(f"读取 Excel sheet 失败: {sheet_name}, error={exc}")
                continue

            fragments.append(f"Sheet: {sheet_name}")
            for row_index, row in df.iterrows():
                cells = [cell for cell in (self._stringify_excel_cell(cell) for cell in row.tolist()) if cell]
                if cells:
                    fragments.append(f"第{row_index}行: {' '.join(cells)}")

        return self.extract_from_text(
            "\n".join(fragments),
            source_type="excel_header_rows",
        )

    def extract_from_image(self, image_path: str) -> AuditFirmResult:
        if not self._can_use_vlm():
            return AuditFirmResult()
        return self._extract_image_with_vlm(image_path)

    def _extract_from_text_pages(
        self,
        page_texts: Iterable[tuple[Optional[int], str]],
    ) -> AuditFirmResult:
        candidates: List[_AuditFirmCandidate] = []
        unaudited_evidence: List[AuditFirmEvidence] = []

        for page, text in page_texts:
            if not isinstance(text, str) or not text.strip():
                continue

            unaudited_evidence.extend(self._find_unaudited_evidence(text, page=page))
            candidates.extend(self._find_audit_firm_candidates(text, page=page))

        unique_candidates: Dict[str, AuditFirmEvidence] = {}
        for candidate in candidates:
            unique_candidates.setdefault(candidate.firm_name, candidate.evidence)

        if len(unique_candidates) == 1:
            firm_name, evidence = next(iter(unique_candidates.items()))
            return AuditFirmResult(
                audit_status="audited",
                audit_firm_name=firm_name,
                confidence="high",
                evidence=[evidence],
            )

        if len(unique_candidates) > 1:
            return AuditFirmResult(
                audit_status="unknown",
                audit_firm_name="",
                confidence="low",
                evidence=[
                    AuditFirmEvidence(text=evidence.text, page=evidence.page)
                    for evidence in list(unique_candidates.values())[:5]
                ],
            )

        if unaudited_evidence:
            return AuditFirmResult(
                audit_status="unaudited",
                audit_firm_name="",
                confidence="high",
                evidence=unaudited_evidence[:3],
            )

        return AuditFirmResult()

    def _find_audit_firm_candidates(
        self,
        text: str,
        *,
        page: Optional[int],
    ) -> List[_AuditFirmCandidate]:
        candidates: List[_AuditFirmCandidate] = []
        for line in self._iter_candidate_lines(text, keyword="会计师事务所"):
            compact_line = re.sub(r"\s+", "", line)
            for match in _AUDIT_FIRM_RE.finditer(compact_line):
                firm_name = sanitize_audit_firm_name(match.group(0))
                if not firm_name:
                    continue
                candidates.append(
                    _AuditFirmCandidate(
                        firm_name=firm_name,
                        evidence=AuditFirmEvidence(
                            text=self._truncate_evidence(line),
                            page=page,
                        ),
                    )
                )
        return candidates

    def _find_unaudited_evidence(
        self,
        text: str,
        *,
        page: Optional[int],
    ) -> List[AuditFirmEvidence]:
        evidence: List[AuditFirmEvidence] = []
        for line in self._iter_candidate_lines(text, keyword="审计"):
            if _UNAUDITED_RE.search(line):
                evidence.append(
                    AuditFirmEvidence(
                        text=self._truncate_evidence(line),
                        page=page,
                    )
                )
        return evidence

    @staticmethod
    def _iter_candidate_lines(text: str, *, keyword: str) -> Iterable[str]:
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        yielded = False
        for line in lines:
            if keyword in line:
                yielded = True
                yield line

        if yielded:
            return

        compact_text = re.sub(r"\s+", "", text)
        keyword_index = compact_text.find(keyword)
        while keyword_index >= 0:
            start = max(0, keyword_index - 80)
            end = min(len(compact_text), keyword_index + 120)
            yield compact_text[start:end]
            keyword_index = compact_text.find(keyword, keyword_index + len(keyword))

    @staticmethod
    def _truncate_evidence(text: str, limit: int = 180) -> str:
        normalized = re.sub(r"\s+", " ", str(text or "")).strip()
        return normalized if len(normalized) <= limit else f"{normalized[:limit]}..."

    def _extract_with_llm(self, text: str, *, source_type: str) -> Optional[AuditFirmResult]:
        if self.llm_client is None:
            return None

        prompt = PROMPTS.get("SP_AUDIT_FIRM_TEXT", "")
        if not prompt:
            return None

        user_message = f"来源类型: {source_type}\n\n{text[:6000]}"
        try:
            response = self.llm_client.chat(
                user_message=user_message,
                system_prompt=prompt,
                temperature=0.1,
            )
        except Exception as exc:
            self.logger.warning(f"审计机构文本识别失败，回退规则结果: {exc}")
            return None

        parsed = extract_llm_json(response)
        if not isinstance(parsed, Mapping):
            return None
        return self._audit_result_from_llm_payload(parsed)

    def _audit_result_from_llm_payload(
        self,
        payload: Mapping[str, Any],
        *,
        default_page: Optional[int] = None,
    ) -> AuditFirmResult:
        status = normalize_audit_status(payload.get("audit_status"))
        confidence = normalize_confidence(payload.get("confidence"))
        firm_name = sanitize_audit_firm_name(payload.get("audit_firm_name"))

        if status == "audited" and not firm_name:
            status = "unknown"
        if status != "audited":
            firm_name = ""

        evidence_text = str(payload.get("evidence") or "").strip()
        evidence = (
            [AuditFirmEvidence(text=self._truncate_evidence(evidence_text), page=default_page)]
            if evidence_text
            else []
        )
        return AuditFirmResult(
            audit_status=status,
            audit_firm_name=firm_name,
            confidence=confidence,
            evidence=evidence,
        )

    def _can_use_vlm(self) -> bool:
        vlm_config = self.config.get("vlm", {})
        return bool(vlm_config.get("base_url") and vlm_config.get("model"))

    def _extract_from_selected_pdf_pages(self, doc: Any) -> AuditFirmResult:
        page_indexes = self._select_pdf_page_indexes(doc.page_count)
        temp_dir = tempfile.mkdtemp(prefix="audit_firm_pdf_pages_")
        try:
            for page_index in page_indexes:
                image_path = self._render_pdf_page(doc, page_index, temp_dir)
                image_result = self._extract_image_with_vlm(
                    image_path,
                    default_page=page_index + 1,
                )
                if image_result.audit_status != "unknown":
                    return image_result
        finally:
            if os.path.exists(temp_dir):
                shutil.rmtree(temp_dir)
        return AuditFirmResult()

    @staticmethod
    def _select_pdf_page_indexes(page_count: int) -> List[int]:
        if page_count <= 0:
            return []
        candidates = [0, 1, page_count - 2, page_count - 1]
        seen = set()
        page_indexes = []
        for page_index in candidates:
            if page_index < 0 or page_index >= page_count or page_index in seen:
                continue
            seen.add(page_index)
            page_indexes.append(page_index)
        return page_indexes

    @staticmethod
    def _stringify_excel_cell(value: Any) -> str:
        if value is None:
            return ""
        text = str(value).strip()
        if not text or text.lower() == "nan":
            return ""
        return text

    @staticmethod
    def _render_pdf_page(doc: Any, page_index: int, output_dir: str) -> str:
        page = doc[page_index]
        pix = page.get_pixmap(matrix=fitz.Matrix(2.0, 2.0))
        image_path = os.path.join(output_dir, f"page_{page_index + 1:03d}.png")
        pix.save(image_path)
        pix = None
        return image_path

    def _extract_image_with_vlm(
        self,
        image_path: str,
        *,
        default_page: Optional[int] = None,
    ) -> AuditFirmResult:
        prompt = PROMPTS.get("SP_AUDIT_FIRM_IMAGE", "")
        if not prompt:
            return AuditFirmResult()

        try:
            from openai import OpenAI

            vlm_config = self.config.get("vlm", {})
            client = OpenAI(
                api_key=vlm_config.get("api_key"),
                base_url=vlm_config.get("base_url"),
            )
            with open(image_path, "rb") as image_file:
                b64_img = base64.b64encode(image_file.read()).decode("utf-8")

            response = client.chat.completions.create(
                model=vlm_config.get("model"),
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": prompt},
                            {
                                "type": "image_url",
                                "image_url": {"url": f"data:image/jpeg;base64,{b64_img}"},
                            },
                        ],
                    }
                ],
                temperature=0.1,
                max_tokens=200,
                stream=False,
            )
            parsed = extract_llm_json(response.choices[0].message.content)
            if not isinstance(parsed, Mapping):
                return AuditFirmResult()
            return self._audit_result_from_llm_payload(
                parsed,
                default_page=default_page,
            )
        except Exception as exc:
            self.logger.warning(f"图片审计机构识别失败: {exc}")
            return AuditFirmResult()

    @staticmethod
    def _get_visible_excel_sheet_names(file_path: str) -> List[str]:
        suffix = Path(file_path).suffix.lower()
        try:
            if suffix == ".xlsx":
                import openpyxl

                wb = openpyxl.load_workbook(file_path, read_only=True, data_only=True)
                try:
                    return [
                        sheet.title
                        for sheet in wb
                        if sheet.sheet_state == "visible"
                    ]
                finally:
                    wb.close()
            if suffix == ".xls":
                import xlrd

                wb = xlrd.open_workbook(file_path, formatting_info=True, on_demand=True)
                try:
                    return [
                        sheet.name
                        for sheet in wb.sheets()
                        if sheet.visibility == 0
                    ]
                finally:
                    wb.release_resources()
        except Exception:
            pass

        excel_file = pd.ExcelFile(file_path)
        return list(excel_file.sheet_names)
