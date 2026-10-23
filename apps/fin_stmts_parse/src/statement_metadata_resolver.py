"""财务报表页眉元数据的解析、候选合并与日期决策规则。

通过函数依赖复用现有日期和 Markdown 元数据解析，不依赖财务处理器，
也不创建模型客户端或执行图像处理。模型补识别与 Markdown 渲染由调用方负责。
"""

import os
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional, Tuple

from fin_stmts_parse.src.company_name_resolver import sanitize_company_name
from fin_stmts_parse.utils.logger import logger as default_logger


@dataclass(frozen=True)
class StatementPageMetadata:
    title: str = ""
    accounting_form: str = ""
    company_name: str = ""
    date_raw: str = ""
    date: str = "N/A"
    unit: str = "N/A"
    source: str = ""
    confidence: str = "low"
    date_source: str = ""
    date_candidates: Tuple[Dict[str, Any], ...] = ()
    date_warnings: Tuple[str, ...] = ()

    def to_dict(self) -> Dict[str, Any]:
        item: Dict[str, Any] = {
            "title": self.title,
            "accounting_form": self.accounting_form,
            "company_name": self.company_name,
            "date_raw": self.date_raw,
            "date": self.date,
            "unit": self.unit,
            "source": self.source,
            "confidence": self.confidence,
        }
        if self.date_source:
            item["date_source"] = self.date_source
        if self.date_candidates:
            item["date_candidates"] = list(self.date_candidates)
        if self.date_warnings:
            item["date_warnings"] = list(self.date_warnings)
        return item


class StatementMetadataResolver:
    """基于页面、文件名和模型已返回的候选信息决策报表元数据。"""

    def __init__(
        self,
        *,
        date_parser: Callable[[str], Optional[datetime]],
        markdown_metadata_extractor: Callable[[str], Dict[str, Any]],
        logger=None,
    ):
        """注入已有的纯解析函数，保留日期和单位的兼容规则。"""
        self._parse_date_from_header = date_parser
        self._extract_metadata_from_markdown = markdown_metadata_extractor
        self.logger = logger if logger is not None else default_logger

    @staticmethod
    def _normalize_metadata_value(value: Any) -> str:
        if value in (None, ""):
            return ""
        return str(value).strip().strip("#").strip()

    @staticmethod
    def _normalize_metadata_confidence(confidence: Any) -> str:
        normalized = str(confidence or "").strip().lower()
        if normalized in {"high", "medium", "low"}:
            return normalized
        if normalized in {"高", "高置信", "high_confidence"}:
            return "high"
        if normalized in {"中", "中等", "中置信", "medium_confidence"}:
            return "medium"
        return "low"

    @staticmethod
    def _metadata_confidence_score(confidence: Any) -> int:
        return {"low": 1, "medium": 2, "high": 3}.get(
            StatementMetadataResolver._normalize_metadata_confidence(confidence),
            0,
        )

    @classmethod
    def _normalize_date_candidate_dict(cls, candidate: Any) -> Optional[Dict[str, Any]]:
        if not isinstance(candidate, dict):
            return None
        date = cls._normalize_metadata_value(candidate.get("date"))
        if not date or date == "N/A":
            return None
        normalized = {
            "date": date,
            "raw": cls._normalize_metadata_value(candidate.get("raw") or candidate.get("date_raw")),
            "source": cls._normalize_metadata_value(candidate.get("source")),
            "confidence": cls._normalize_metadata_confidence(candidate.get("confidence")),
        }
        table_type = cls._normalize_metadata_value(candidate.get("table_type"))
        if table_type:
            normalized["table_type"] = table_type
        page = candidate.get("page")
        if page not in (None, ""):
            normalized["page"] = page
        weight = candidate.get("weight")
        if weight not in (None, ""):
            try:
                normalized["weight"] = float(weight)
            except (TypeError, ValueError):
                pass
        return normalized

    @classmethod
    def _normalize_date_candidates(cls, value: Any) -> Tuple[Dict[str, Any], ...]:
        if not value:
            return ()
        if isinstance(value, dict):
            value = [value]
        if not isinstance(value, (list, tuple)):
            return ()
        candidates: List[Dict[str, Any]] = []
        for candidate in value:
            normalized = cls._normalize_date_candidate_dict(candidate)
            if normalized is not None:
                candidates.append(normalized)
        return tuple(candidates)

    @classmethod
    def _normalize_metadata_warnings(cls, value: Any) -> Tuple[str, ...]:
        if not value:
            return ()
        if isinstance(value, str):
            value = [value]
        if not isinstance(value, (list, tuple)):
            return ()
        warnings: List[str] = []
        for warning in value:
            normalized = cls._normalize_metadata_value(warning)
            if normalized and normalized not in warnings:
                warnings.append(normalized)
        return tuple(warnings)

    @classmethod
    def normalize_metadata(cls, metadata: Any) -> StatementPageMetadata:
        """归一化字典字段及候选证据；已有页面元数据对象直接复用。"""
        if isinstance(metadata, StatementPageMetadata):
            return metadata
        if not isinstance(metadata, dict):
            return StatementPageMetadata()
        return StatementPageMetadata(
            title=cls._normalize_metadata_value(metadata.get("title") or metadata.get("表名")),
            accounting_form=cls._normalize_metadata_value(
                metadata.get("accounting_form")
                or metadata.get("accountingForm")
                or metadata.get("会计表号")
            ),
            company_name=cls._normalize_metadata_value(
                metadata.get("company_name")
                or metadata.get("companyName")
                or metadata.get("公司名称")
                or metadata.get("编制单位")
            ),
            date_raw=cls._normalize_metadata_value(
                metadata.get("date_raw") or metadata.get("dateRaw") or metadata.get("日期原文")
            ),
            date=cls._normalize_metadata_value(metadata.get("date") or metadata.get("日期")) or "N/A",
            unit=cls._normalize_metadata_value(metadata.get("unit") or metadata.get("单位")) or "N/A",
            source=cls._normalize_metadata_value(metadata.get("source")),
            confidence=cls._normalize_metadata_confidence(metadata.get("confidence")),
            date_source=cls._normalize_metadata_value(
                metadata.get("date_source")
                or metadata.get("dateSource")
                or metadata.get("日期来源")
            ),
            date_candidates=cls._normalize_date_candidates(
                metadata.get("date_candidates")
                or metadata.get("dateCandidates")
                or metadata.get("日期候选")
            ),
            date_warnings=cls._normalize_metadata_warnings(
                metadata.get("date_warnings")
                or metadata.get("dateWarnings")
                or metadata.get("日期警告")
            ),
        )

    @staticmethod
    def _metadata_field_empty(field_name: str, value: Any) -> bool:
        if value in (None, ""):
            return True
        if field_name in {"date", "unit"} and str(value).strip() == "N/A":
            return True
        return False

    def merge_statement_metadata(self, *candidates: Any) -> StatementPageMetadata:
        fields = ["title", "accounting_form", "company_name", "date_raw", "date", "unit"]
        values = {
            "title": "",
            "accounting_form": "",
            "company_name": "",
            "date_raw": "",
            "date": "N/A",
            "unit": "N/A",
        }
        field_scores = {field: 0 for field in fields}
        field_sources = {field: "" for field in fields}
        sources: List[str] = []
        date_candidates: List[Dict[str, Any]] = []
        date_warnings: List[str] = []
        max_confidence_score = 0

        for raw_candidate in candidates:
            candidate = self.normalize_metadata(raw_candidate)
            score = self._metadata_confidence_score(candidate.confidence)
            if score > max_confidence_score:
                max_confidence_score = score
            if candidate.source and candidate.source not in sources:
                sources.append(candidate.source)
            for date_candidate in candidate.date_candidates:
                if date_candidate not in date_candidates:
                    date_candidates.append(date_candidate)
            if (
                candidate.date not in ("", "N/A", None)
                and not candidate.date_candidates
            ):
                generated_candidate = self._build_statement_date_candidate(
                    candidate.date,
                    raw=candidate.date_raw,
                    source=candidate.date_source or candidate.source,
                    confidence=candidate.confidence,
                )
                if generated_candidate and generated_candidate not in date_candidates:
                    date_candidates.append(generated_candidate)
            for warning in candidate.date_warnings:
                if warning and warning not in date_warnings:
                    date_warnings.append(warning)

            for field in fields:
                value = getattr(candidate, field)
                if self._metadata_field_empty(field, value):
                    continue

                current_value = values[field]
                if self._metadata_field_empty(field, current_value):
                    values[field] = value
                    field_scores[field] = score
                    field_sources[field] = candidate.date_source or candidate.source
                    continue

                if score > field_scores[field]:
                    values[field] = value
                    field_scores[field] = score
                    field_sources[field] = candidate.date_source or candidate.source
                elif value != current_value and score == field_scores[field] and field in {"date", "unit"}:
                    warning = f"页眉元数据冲突，保留先识别值: {field}={current_value}, candidate={value}"
                    self.logger.warning(warning)
                    if warning not in date_warnings:
                        date_warnings.append(warning)

        confidence = {3: "high", 2: "medium", 1: "low"}.get(max_confidence_score, "low")
        return StatementPageMetadata(
            title=values["title"],
            accounting_form=values["accounting_form"],
            company_name=values["company_name"],
            date_raw=values["date_raw"],
            date=values["date"] or "N/A",
            unit=values["unit"] or "N/A",
            source="+".join(sources),
            confidence=confidence,
            date_source=field_sources.get("date", ""),
            date_candidates=tuple(date_candidates),
            date_warnings=tuple(date_warnings),
        )

    @staticmethod
    def _leading_metadata_text(text: str) -> str:
        lines = str(text or "").splitlines()
        leading_lines: List[str] = []
        for line in lines:
            stripped = line.strip()
            if stripped.startswith("|") and stripped.count("|") >= 2:
                break
            if stripped:
                leading_lines.append(stripped)

        if leading_lines:
            return "\n".join(leading_lines[:20])
        return "\n".join(line.strip() for line in lines[:20] if line.strip())

    @staticmethod
    def _clean_metadata_line(line: str) -> str:
        cleaned = str(line or "").strip()
        cleaned = cleaned.strip("#").strip()
        cleaned = cleaned.replace("**", "").replace("*", "")
        return cleaned.strip()

    def _extract_statement_title_from_text(self, text: str, table_type: Optional[str]) -> str:
        search_text = self._leading_metadata_text(text)
        candidates = search_text.splitlines() or str(text or "").splitlines()[:20]
        for line in candidates:
            cleaned = self._clean_metadata_line(line)
            compact = re.sub(r"\s+", "", cleaned)
            if not compact:
                continue
            if any(
                keyword in compact
                for keyword in (
                    "合并资产负债表",
                    "资产负债表",
                    "合并利润表",
                    "利润表",
                    "损益表",
                    "利润及利润分配表",
                    "合并现金流量表",
                    "现金流量表",
                )
            ):
                return cleaned
        return ""

    @staticmethod
    def _extract_accounting_form_from_text(text: str) -> str:
        match = re.search(r"会\s*(?:计|企)\s*\d{1,3}\s*表", str(text or ""))
        if not match:
            return ""
        return re.sub(r"\s+", "", match.group(0))

    @staticmethod
    def _extract_date_raw_from_text(text: str) -> str:
        patterns = [
            r"\d{4}\s*年\s*\d{1,2}\s*月\s*\d{1,2}\s*日",
            r"\d{4}\s*年度",
            r"\d{4}\s*年\s*\d{1,2}\s*[\-~至到－—–～]\s*\d{1,2}\s*月",
            r"\d{4}\s*年\s*\d{1,2}\s*月",
            r"\d{4}\s*年\s*第?\s*\d{1,2}\s*期",
            r"\d{4}[-/.]\s*\d{1,2}(?:[-/.]\s*\d{1,2})?",
            r"(?<!\d)\d{8}(?!\d)",
            r"(?<!\d)\d{6}(?!\d)",
            r"\d{4}\s*年",
        ]
        for pattern in patterns:
            match = re.search(pattern, str(text or ""))
            if match:
                return re.sub(r"\s+", "", match.group(0))
        return ""

    def _normalize_statement_date_from_raw(self, date_raw: str) -> str:
        if not date_raw:
            return "N/A"
        try:
            parsed_date = self._parse_date_from_header(date_raw)
            if parsed_date:
                return parsed_date.strftime("%Y%m")
        except Exception:
            return "N/A"
        return "N/A"

    @staticmethod
    def _extract_unit_from_text(text: str) -> str:
        unit_match = re.search(
            r"(?:金额单位|单位)\s*[：:]\s*(?:人民币)?\s*([亿万]?\s*元)",
            str(text or ""),
        )
        if unit_match:
            return re.sub(r"\s+", "", unit_match.group(1))
        loose_match = re.search(r"(?<![\u4e00-\u9fa5])([亿万]?元)(?![\u4e00-\u9fa5])", str(text or ""))
        return loose_match.group(1) if loose_match else ""

    @staticmethod
    def _extract_company_name_from_text_rule(text: str) -> str:
        match = re.search(
            r"(?:编制单位|公司名称|企业名称|单位名称)\s*[：:]\s*(.+)",
            str(text or ""),
        )
        if not match:
            return ""
        candidate = match.group(1).strip()
        candidate = re.split(
            r"\s*(?=\d{4}\s*(?:年度|年|[-/.]|\d{2}))|(?:金额)?单位\s*[：:]|会\s*(?:计|企)\s*\d{1,3}\s*表",
            candidate,
            maxsplit=1,
        )[0]
        return sanitize_company_name(candidate)

    @staticmethod
    def _normalize_filename_year(year_text: str) -> Optional[int]:
        year_text = str(year_text or "").strip()
        if re.fullmatch(r"\d{4}", year_text):
            year = int(year_text)
            return year if 1900 <= year <= 2099 else None
        if re.fullmatch(r"\d{2}", year_text):
            year = int(year_text)
            if 0 <= year <= 79:
                return 2000 + year
            return 1900 + year
        return None

    @staticmethod
    def _normalize_year_month(year: int, month: int) -> str:
        if not 1 <= month <= 12:
            return ""
        return f"{year:04d}{month:02d}"

    @staticmethod
    def _is_valid_statement_date_value(date_value: Any) -> bool:
        text = str(date_value or "").strip()
        if not re.fullmatch(r"\d{6}", text):
            return False
        month = int(text[-2:])
        return 1 <= month <= 12

    def _build_statement_date_candidate(
        self,
        date: Any,
        *,
        raw: Any = "",
        source: Any = "",
        confidence: Any = "low",
        table_type: Any = "",
        page: Any = None,
    ) -> Optional[Dict[str, Any]]:
        date_value = self._normalize_metadata_value(date)
        if not self._is_valid_statement_date_value(date_value):
            return None

        source_value = self._normalize_metadata_value(source)
        confidence_value = self._normalize_metadata_confidence(confidence)
        candidate: Dict[str, Any] = {
            "date": date_value,
            "raw": self._normalize_metadata_value(raw),
            "source": source_value,
            "confidence": confidence_value,
            "weight": self._date_candidate_weight(source_value, confidence_value),
        }
        table_value = self._normalize_metadata_value(table_type)
        if table_value:
            candidate["table_type"] = table_value
        if page not in (None, ""):
            candidate["page"] = page
        return candidate

    @classmethod
    def _date_candidate_weight(cls, source: Any, confidence: Any) -> float:
        source_value = cls._normalize_metadata_value(source)
        confidence_value = cls._normalize_metadata_confidence(confidence)
        if "vl_metadata" in source_value:
            base_weight = 100
        elif "file_name" in source_value:
            base_weight = 85
        elif "file_vote" in source_value:
            base_weight = 90
        elif "combined_markdown" in source_value:
            base_weight = 45
        elif "markdown" in source_value:
            base_weight = 50
        elif "request" in source_value:
            base_weight = 10
        else:
            base_weight = 30
        return base_weight + {"high": 10, "medium": 5, "low": 0}.get(confidence_value, 0)

    def extract_statement_metadata_from_filename(
        self,
        file_name: str,
        table_type: Optional[str] = None,
    ) -> StatementPageMetadata:
        basename = os.path.basename(str(file_name or "")).strip()
        if not basename:
            return StatementPageMetadata()

        stem = os.path.splitext(basename)[0]
        compact = re.sub(r"\s+", "", stem)
        patterns = [
            (
                r"(?<!\d)(\d{2,4})年\d{1,2}[\-~至到－—–～](\d{1,2})月",
                lambda match: (match.group(1), match.group(2), match.group(0), "high"),
            ),
            (
                r"(?<!\d)(\d{2,4})年第?(\d{1,2})期",
                lambda match: (match.group(1), match.group(2), match.group(0), "high"),
            ),
            (
                r"(?<!\d)(\d{2,4})年(\d{1,2})月(?:\d{1,2}日)?",
                lambda match: (match.group(1), match.group(2), match.group(0), "high"),
            ),
            (
                r"(?<!\d)(20\d{2})[-._/](\d{1,2})(?:[-._/]\d{1,2})?(?!\d)",
                lambda match: (match.group(1), match.group(2), match.group(0), "high"),
            ),
            (
                r"(?<!\d)(20\d{2})(0[1-9]|1[0-2])(?:[0-3]\d)?(?!\d)",
                lambda match: (match.group(1), match.group(2), match.group(0), "high"),
            ),
            (
                r"(?<!\d)(20\d{2})年(?:度|年报|审计报告|财报|报表)?(?!\d)",
                lambda match: (match.group(1), "12", match.group(0), "medium"),
            ),
        ]

        for pattern, extractor in patterns:
            match = re.search(pattern, compact)
            if not match:
                continue
            year_text, month_text, raw, confidence = extractor(match)
            year = self._normalize_filename_year(year_text)
            if year is None:
                continue
            try:
                month = int(month_text)
            except (TypeError, ValueError):
                continue
            date_value = self._normalize_year_month(year, month)
            if not date_value:
                if confidence == "high":
                    return StatementPageMetadata()
                continue
            candidate = self._build_statement_date_candidate(
                date_value,
                raw=raw,
                source="file_name",
                confidence=confidence,
                table_type=table_type or "",
            )
            return StatementPageMetadata(
                date_raw=raw,
                date=date_value,
                source="file_name",
                confidence=confidence,
                date_source="file_name",
                date_candidates=(candidate,) if candidate else (),
            )

        return StatementPageMetadata()

    @staticmethod
    def _metadata_has_valid_date(metadata: StatementPageMetadata) -> bool:
        return StatementMetadataResolver._is_valid_statement_date_value(metadata.date)

    def _metadata_date_conflicts(
        self,
        left: Any,
        right: Any,
    ) -> bool:
        left_metadata = self.normalize_metadata(left)
        right_metadata = self.normalize_metadata(right)
        return (
            self._metadata_has_valid_date(left_metadata)
            and self._metadata_has_valid_date(right_metadata)
            and left_metadata.date != right_metadata.date
        )

    def needs_vl_recheck(
        self,
        metadata: Any,
        file_metadata: Any = None,
    ) -> bool:
        """判断日期、单位缺失或页眉与文件名日期冲突时是否需要补识别。"""
        metadata_obj = self.normalize_metadata(metadata)
        file_metadata_obj = self.normalize_metadata(file_metadata)
        return (
            self._metadata_needs_vl_fallback(metadata_obj)
            or self._metadata_date_conflicts(metadata_obj, file_metadata_obj)
        )

    def _date_candidates_from_metadata(self, metadata: Any) -> List[Dict[str, Any]]:
        metadata_obj = self.normalize_metadata(metadata)
        candidates = list(metadata_obj.date_candidates)
        if self._metadata_has_valid_date(metadata_obj):
            generated_candidate = self._build_statement_date_candidate(
                metadata_obj.date,
                raw=metadata_obj.date_raw,
                source=metadata_obj.date_source or metadata_obj.source,
                confidence=metadata_obj.confidence,
            )
            if generated_candidate and generated_candidate not in candidates:
                candidates.append(generated_candidate)
        return candidates

    @classmethod
    def _dedupe_date_candidates(
        cls,
        candidates: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        deduped: List[Dict[str, Any]] = []
        seen = set()
        for candidate in candidates:
            normalized = cls._normalize_date_candidate_dict(candidate)
            if normalized is None:
                continue
            key = (
                normalized.get("date"),
                normalized.get("raw"),
                normalized.get("source"),
                normalized.get("table_type"),
                normalized.get("page"),
            )
            if key in seen:
                continue
            seen.add(key)
            deduped.append(normalized)
        return deduped

    def _select_statement_date_candidate(
        self,
        candidates: List[Dict[str, Any]],
    ) -> Optional[Dict[str, Any]]:
        valid_candidates = self._dedupe_date_candidates(candidates)
        if not valid_candidates:
            return None

        vl_candidates = [
            candidate for candidate in valid_candidates
            if "vl_metadata" in str(candidate.get("source") or "")
        ]
        if vl_candidates:
            return max(
                vl_candidates,
                key=lambda candidate: float(candidate.get("weight") or 0),
            )

        file_candidates = [
            candidate for candidate in valid_candidates
            if "file_name" in str(candidate.get("source") or "")
            and candidate.get("confidence") == "high"
        ]
        non_file_dates = {
            candidate.get("date")
            for candidate in valid_candidates
            if "file_name" not in str(candidate.get("source") or "")
        }
        if file_candidates and non_file_dates and any(
            file_candidate.get("date") not in non_file_dates
            for file_candidate in file_candidates
        ):
            return max(
                file_candidates,
                key=lambda candidate: float(candidate.get("weight") or 0),
            )

        score_by_date: Dict[str, float] = {}
        first_candidate_by_date: Dict[str, Dict[str, Any]] = {}
        for candidate in valid_candidates:
            date_value = str(candidate.get("date") or "")
            score_by_date[date_value] = score_by_date.get(date_value, 0.0) + float(
                candidate.get("weight") or self._date_candidate_weight(
                    candidate.get("source"),
                    candidate.get("confidence"),
                )
            )
            first_candidate_by_date.setdefault(date_value, candidate)

        selected_date = max(score_by_date, key=lambda date_value: score_by_date[date_value])
        return first_candidate_by_date[selected_date]

    def resolve_statement_metadata_date(
        self,
        metadata: Any,
        *candidate_sources: Any,
    ) -> StatementPageMetadata:
        metadata_obj = self.normalize_metadata(metadata)
        candidates = self._date_candidates_from_metadata(metadata_obj)
        warnings = list(metadata_obj.date_warnings)

        for source_metadata in candidate_sources:
            candidates.extend(self._date_candidates_from_metadata(source_metadata))
            source_metadata_obj = self.normalize_metadata(source_metadata)
            for warning in source_metadata_obj.date_warnings:
                if warning and warning not in warnings:
                    warnings.append(warning)

        candidates = self._dedupe_date_candidates(candidates)
        selected = self._select_statement_date_candidate(candidates)
        if not selected:
            return StatementPageMetadata(
                title=metadata_obj.title,
                accounting_form=metadata_obj.accounting_form,
                company_name=metadata_obj.company_name,
                date_raw=metadata_obj.date_raw,
                date=metadata_obj.date,
                unit=metadata_obj.unit,
                source=metadata_obj.source,
                confidence=metadata_obj.confidence,
                date_source=metadata_obj.date_source,
                date_candidates=tuple(candidates),
                date_warnings=tuple(warnings),
            )

        selected_date = str(selected.get("date") or "")
        selected_source = str(selected.get("source") or "")
        selected_raw = str(selected.get("raw") or "")
        if (
            self._metadata_has_valid_date(metadata_obj)
            and selected_date != metadata_obj.date
        ):
            warning = (
                f"报表日期已根据多源证据修正: original={metadata_obj.date}, "
                f"selected={selected_date}, source={selected_source}"
            )
            self.logger.warning(warning)
            if warning not in warnings:
                warnings.append(warning)

        return StatementPageMetadata(
            title=metadata_obj.title,
            accounting_form=metadata_obj.accounting_form,
            company_name=metadata_obj.company_name,
            date_raw=selected_raw or metadata_obj.date_raw,
            date=selected_date or metadata_obj.date,
            unit=metadata_obj.unit,
            source=metadata_obj.source,
            confidence=metadata_obj.confidence,
            date_source=selected_source or metadata_obj.date_source,
            date_candidates=tuple(candidates),
            date_warnings=tuple(warnings),
        )

    def resolve_file_level_statement_date_metadata(
        self,
        metadata_items: List[Any],
        file_metadata: Any = None,
    ) -> StatementPageMetadata:
        candidates: List[Dict[str, Any]] = []
        warnings: List[str] = []
        for metadata in metadata_items:
            metadata_obj = self.normalize_metadata(metadata)
            candidates.extend(self._date_candidates_from_metadata(metadata_obj))
            for warning in metadata_obj.date_warnings:
                if warning and warning not in warnings:
                    warnings.append(warning)
        file_metadata_obj = self.normalize_metadata(file_metadata)
        candidates.extend(self._date_candidates_from_metadata(file_metadata_obj))
        for warning in file_metadata_obj.date_warnings:
            if warning and warning not in warnings:
                warnings.append(warning)

        candidates = self._dedupe_date_candidates(candidates)
        selected = self._select_statement_date_candidate(candidates)
        if not selected:
            return StatementPageMetadata(
                source="file_vote" if candidates else "",
                date_candidates=tuple(candidates),
                date_warnings=tuple(warnings),
            )

        selected_source = self._normalize_metadata_value(selected.get("source"))
        vote_candidate = self._build_statement_date_candidate(
            selected.get("date"),
            raw=selected.get("raw"),
            source="file_vote",
            confidence="high",
        )
        all_candidates = list(candidates)
        if vote_candidate and vote_candidate not in all_candidates:
            all_candidates.append(vote_candidate)

        distinct_dates = sorted({candidate["date"] for candidate in candidates})
        if len(distinct_dates) > 1:
            warning = (
                f"同一文件存在多个报表日期候选，选择 {selected.get('date')} "
                f"(source={selected_source or 'unknown'}), candidates={','.join(distinct_dates)}"
            )
            self.logger.warning(warning)
            if warning not in warnings:
                warnings.append(warning)

        return StatementPageMetadata(
            date_raw=self._normalize_metadata_value(selected.get("raw")),
            date=self._normalize_metadata_value(selected.get("date")) or "N/A",
            source="file_vote",
            confidence="high",
            date_source=selected_source or "file_vote",
            date_candidates=tuple(all_candidates),
            date_warnings=tuple(warnings),
        )

    def extract_statement_metadata_from_text(
        self,
        text: str,
        table_type: Optional[str] = None,
        *,
        source: str = "markdown",
        confidence: str = "high",
    ) -> StatementPageMetadata:
        text = str(text or "")
        basic_metadata = self._extract_metadata_from_markdown(text)
        leading_text = self._leading_metadata_text(text)
        date_raw = self._extract_date_raw_from_text(text)
        unit = self._extract_unit_from_text(text) or basic_metadata.get("单位") or "N/A"
        date_value = self._normalize_statement_date_from_raw(date_raw)
        if date_value == "N/A" and not date_raw:
            date_value = basic_metadata.get("日期") or "N/A"
        title = self._extract_statement_title_from_text(text, table_type)
        accounting_form = self._extract_accounting_form_from_text(leading_text or text)
        company_name = self._extract_company_name_from_text_rule(leading_text or text)

        has_metadata = any(
            value not in ("", "N/A", None)
            for value in (title, accounting_form, company_name, date_raw, date_value, unit)
        )
        date_candidate = self._build_statement_date_candidate(
            date_value,
            raw=date_raw,
            source=source,
            confidence=confidence,
            table_type=table_type or "",
        )
        return StatementPageMetadata(
            title=title,
            accounting_form=accounting_form,
            company_name=company_name,
            date_raw=date_raw,
            date=date_value if date_value else "N/A",
            unit=unit if unit else "N/A",
            source=source if has_metadata else "",
            confidence=self._normalize_metadata_confidence(confidence if has_metadata else "low"),
            date_source=source if date_candidate else "",
            date_candidates=(date_candidate,) if date_candidate else (),
        )

    def normalize_vl_response(
        self,
        parsed: Any,
        table_type: Optional[str] = None,
    ) -> StatementPageMetadata:
        """将已解码的 VLM 元数据响应清洗并合并为页面元数据，不调用模型。"""
        if not isinstance(parsed, dict):
            return StatementPageMetadata()

        text_parts = [
            str(parsed.get("title") or ""),
            str(parsed.get("accounting_form") or parsed.get("accountingForm") or ""),
            str(parsed.get("company_name") or parsed.get("companyName") or ""),
            str(parsed.get("date_raw") or parsed.get("dateRaw") or parsed.get("date") or ""),
            str(parsed.get("unit") or ""),
        ]
        rule_metadata = self.extract_statement_metadata_from_text(
            "\n".join(part for part in text_parts if part),
            table_type,
            source="vl_metadata",
            confidence=parsed.get("confidence", "medium"),
        )
        return self.merge_statement_metadata(
            rule_metadata,
            StatementPageMetadata(
                title=self._normalize_metadata_value(parsed.get("title")),
                accounting_form=self._normalize_metadata_value(
                    parsed.get("accounting_form") or parsed.get("accountingForm")
                ),
                company_name=sanitize_company_name(
                    parsed.get("company_name") or parsed.get("companyName") or ""
                ),
                date_raw=self._normalize_metadata_value(
                    parsed.get("date_raw") or parsed.get("dateRaw")
                ),
                date=self._normalize_metadata_value(parsed.get("date")) or "N/A",
                unit=self._normalize_metadata_value(parsed.get("unit")) or "N/A",
                source="vl_metadata",
                confidence=self._normalize_metadata_confidence(
                    parsed.get("confidence", "medium")
                ),
            ),
        )

    def extract_statement_metadata_from_analysis(
        self,
        analysis_result: Optional[Dict[str, Any]],
        table_type: Optional[str] = None,
    ) -> StatementPageMetadata:
        if not isinstance(analysis_result, dict):
            return StatementPageMetadata()
        title = self._normalize_metadata_value(analysis_result.get("extracted_title"))
        return StatementPageMetadata(
            title=title,
            source="page_analysis" if title else "",
            confidence="medium" if title else "low",
        )

    @staticmethod
    def _metadata_needs_vl_fallback(metadata: StatementPageMetadata) -> bool:
        return metadata.date in ("", "N/A") or metadata.unit in ("", "N/A")
