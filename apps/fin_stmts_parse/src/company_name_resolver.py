from __future__ import annotations

import html
import re
from typing import Any, Iterable, Mapping, Optional

from fin_stmts_parse.clients.llm_client import LLMClient
from fin_stmts_parse.config.prompts import PROMPTS
from fin_stmts_parse.utils.logger import logger as default_logger
from fin_stmts_parse.utils.str_util import extract_llm_json


COMPANY_NAME_KEYS = (
    "company_name",
    "companyName",
    "公司名称",
    "编制单位",
    "企业名称",
    "单位名称",
)

_LABEL_RE = re.compile(
    r"(?:编制单位|公司名称|企业名称|单位名称)\s*(?:\*{0,2})?\s*[：:]\s*",
    re.IGNORECASE,
)
_ROW_PREFIX_RE = re.compile(r"^第\d+行:\s*")
_TRAILING_SPLIT_RE = re.compile(
    r"(?:单位\s*[：:]|日期\s*[：:]|企业负责人\s*[：:]|财务负责人\s*[：:]|制表人\s*[：:]|电话\s*[：:]|地址\s*[：:])"
)
_DATE_RE = re.compile(
    r"\d{4}\s*年\s*\d{1,2}\s*月(?:\s*\d{1,2}\s*日)?|\d{4}-\d{1,2}(?:-\d{1,2})?|\d{6,8}"
)
_COMPANY_SUFFIX_RE = re.compile(
    r"(公司|集团|企业|中心|银行|医院|学校|委员会|管理局|事务所|研究院|合伙企业|合作社|基金会)"
)
_HTML_TAG_RE = re.compile(r"<[^>]+>")
_MARKDOWN_DECORATION_RE = re.compile(r"[*`#>]+")
_ONLY_PUNCT_RE = re.compile(r"^[\W_]+$")
_ONLY_NUMBER_RE = re.compile(r"^[\d\s./-]+$")
_INVALID_EXACT_VALUES = {
    "",
    "null",
    "none",
    "n/a",
    "na",
    "单位",
    "元",
    "万元",
    "亿元",
    "人民币元",
    "资产负债表",
    "利润表",
    "损益表",
    "现金流量表",
    "合并资产负债表",
    "合并利润表",
    "合并现金流量表",
}


def sanitize_company_name(value: Any) -> str:
    if value is None:
        return ""

    text = html.unescape(str(value))
    text = _HTML_TAG_RE.sub(" ", text)
    text = _MARKDOWN_DECORATION_RE.sub(" ", text)
    text = text.replace("\u3000", " ")
    text = _ROW_PREFIX_RE.sub("", text)
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        return ""

    text = _LABEL_RE.sub("", text)
    text = _TRAILING_SPLIT_RE.split(text, maxsplit=1)[0].strip()

    date_match = _DATE_RE.search(text)
    if date_match and date_match.start() > 0:
        text = text[:date_match.start()].strip()

    text = text.strip(" \t\r\n,，;；。:：()（）[]【】\"'“”‘’")
    text = text.strip("[]'\" ")
    if not is_valid_company_name(text):
        return ""
    return text


def is_valid_company_name(value: Any) -> bool:
    if value is None:
        return False

    text = str(value).strip()
    if not text:
        return False

    normalized = text.lower()
    if normalized in _INVALID_EXACT_VALUES:
        return False
    if len(text) < 2 or len(text) > 120:
        return False
    if _ONLY_PUNCT_RE.match(text) or _ONLY_NUMBER_RE.match(text):
        return False
    if "单位" in text and not _COMPANY_SUFFIX_RE.search(text):
        return False
    if "日期" in text:
        return False
    return True


def resolve_unique_company_name(candidates: Iterable[Any]) -> str:
    normalized = []
    seen = set()
    for candidate in candidates:
        company_name = sanitize_company_name(candidate)
        if not company_name or company_name in seen:
            continue
        seen.add(company_name)
        normalized.append(company_name)

    return normalized[0] if len(normalized) == 1 else ""


def pick_explicit_company_name(item: Mapping[str, Any]) -> str:
    if not isinstance(item, Mapping):
        return ""
    return resolve_unique_company_name(item.get(key) for key in COMPANY_NAME_KEYS)


def extract_company_name_by_rule(text: str) -> str:
    if not isinstance(text, str) or not text.strip():
        return ""

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if not _LABEL_RE.search(line):
            continue

        company_name = sanitize_company_name(line)
        if company_name:
            return company_name

    return ""


class CompanyNameResolver:
    def __init__(
        self,
        *,
        llm_client: Optional[LLMClient] = None,
        logger=None,
    ) -> None:
        self.llm_client = llm_client
        self.logger = logger or default_logger

    def extract_from_text(
        self,
        text: str,
        *,
        source_type: str = "text",
    ) -> str:
        if not isinstance(text, str) or not text.strip():
            return ""

        llm_result = self._extract_with_llm(text, source_type=source_type)
        rule_result = extract_company_name_by_rule(text)
        return resolve_unique_company_name([llm_result, rule_result])

    def extract_from_items(self, items: Iterable[Mapping[str, Any]]) -> str:
        explicit_candidates = []
        text_fragments = []
        rule_candidates = []

        for item in items:
            if not isinstance(item, Mapping):
                continue
            explicit_name = pick_explicit_company_name(item)
            if explicit_name:
                explicit_candidates.append(explicit_name)

            for key in ("content", "Markdown"):
                value = item.get(key)
                if isinstance(value, str) and value.strip():
                    text_fragments.append(value.strip())
                    rule_candidates.append(extract_company_name_by_rule(value))

        normalized_explicit_candidates = [
            company_name
            for company_name in (sanitize_company_name(candidate) for candidate in explicit_candidates)
            if company_name
        ]
        if len(set(normalized_explicit_candidates)) > 1:
            return ""
        explicit_company_name = resolve_unique_company_name(normalized_explicit_candidates)
        if explicit_company_name:
            return explicit_company_name

        if not text_fragments:
            return ""

        llm_company_name = self._extract_with_llm(
            "\n\n".join(text_fragments),
            source_type="markdown",
        )
        return resolve_unique_company_name([llm_company_name, *rule_candidates])

    def _extract_with_llm(self, text: str, *, source_type: str) -> str:
        if self.llm_client is None:
            return ""

        prompt = PROMPTS.get("SP_COMPANY_NAME_TEXT", "")
        if not prompt:
            return ""

        user_message = f"来源类型: {source_type}\n\n{text[:4000]}"
        try:
            response = self.llm_client.chat(
                user_message=user_message,
                system_prompt=prompt,
                temperature=0.1,
            )
        except Exception as exc:
            self.logger.warning(f"公司名文本识别失败，回退规则提取: {exc}")
            return ""

        parsed = extract_llm_json(response)
        if not isinstance(parsed, dict):
            return ""
        return sanitize_company_name(parsed.get("company_name", ""))
