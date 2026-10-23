from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from fin_stmts_parse.clients.llm_client import LLMClient
from fin_stmts_parse.src.account_code_mapper import AccountCodeMapper
from fin_stmts_parse.src.core.contracts import (
    MappedStatementResult,
    StatementMarkdownDocument,
    resolve_statement_type,
)
from fin_stmts_parse.src.markdown_table_extractor import MarkdownTableExtractor
from fin_stmts_parse.src.view_data_projector import ViewDataProjector
from fin_stmts_parse.utils.read_yaml import get_mapping_config_paths


DEFAULT_REPO_ROOT = Path(__file__).resolve().parents[4]


class FinancialStatementMapCore:
    def __init__(
        self,
        config: Optional[Dict[str, Any]] = None,
        *,
        repo_root: Optional[Path] = None,
    ):
        config = config or {}
        llm_config = config.get("llm", {})
        shared_llm_client = LLMClient(llm_config) if llm_config.get("base_url") else None
        self.table_extractor = MarkdownTableExtractor(llm_client=shared_llm_client)
        self.repo_root = repo_root or DEFAULT_REPO_ROOT

    def map_markdown_document(
        self,
        document: StatementMarkdownDocument,
        *,
        mapping_config_dir: Optional[str] = None,
    ) -> MappedStatementResult:
        if not document.content.strip():
            raise ValueError("markdown 文档 content 不能为空")

        parsed_data = self.table_extractor.parse_markdown_table_to_dict(
            document.content,
            table_type=document.table_name,
        )
        if not parsed_data:
            raise ValueError("未能从 markdown 文档中解析到结构化数据")

        statement_type, is_consolidated = resolve_statement_type(
            document.table_name,
            document.is_consolidated,
        )
        semantic_config_path, view_config_path = resolve_mapping_config_paths(
            statement_type,
            is_consolidated,
            mapping_config_dir_override=mapping_config_dir,
            repo_root=self.repo_root,
        )

        mapper = AccountCodeMapper(semantic_config_path)
        canonical_data_full = mapper.map_data(parsed_data)
        if statement_type in {"profit", "cashflow"}:
            canonical_data_full = _normalize_period_pair_values(canonical_data_full)
        canonical_labels = {
            str(rule["code"]): str(rule["name"])
            for rule in mapper.mapping_rules
            if rule.get("code") and rule.get("name")
        }
        projector = ViewDataProjector(view_config_path)
        view_data_full = projector.project(canonical_data_full)

        return MappedStatementResult(
            statement_type=statement_type,
            table_name=document.table_name,
            date=document.date,
            unit=document.unit,
            is_consolidated=is_consolidated,
            canonical_data_full=canonical_data_full,
            canonical_labels=canonical_labels,
            view_data_full=view_data_full,
            view_labels=projector.view_labels,
            view_groups=projector.view_groups,
            semantic_config_path_used=str(semantic_config_path),
            view_config_path_used=str(view_config_path),
            source_file_name=document.source_file_name,
            source_file_path=document.source_file_path,
        )

    def map_markdown_documents(
        self,
        documents: Iterable[StatementMarkdownDocument],
        *,
        mapping_config_dirs: Optional[Iterable[Optional[str]]] = None,
    ) -> List[MappedStatementResult]:
        mapping_config_dir_list = list(mapping_config_dirs) if mapping_config_dirs is not None else None
        results: List[MappedStatementResult] = []
        for index, document in enumerate(documents):
            mapping_config_dir = None
            if mapping_config_dir_list is not None and index < len(mapping_config_dir_list):
                mapping_config_dir = mapping_config_dir_list[index]
            results.append(
                self.map_markdown_document(document, mapping_config_dir=mapping_config_dir)
            )
        return results


def resolve_mapping_config_paths(
    statement_type: str,
    is_consolidated: bool,
    mapping_config_dir_override: Optional[str] = None,
    *,
    repo_root: Optional[Path] = None,
) -> Tuple[str, str]:
    if isinstance(mapping_config_dir_override, str) and mapping_config_dir_override.strip():
        candidate = Path(mapping_config_dir_override.strip()).expanduser()
        if not candidate.is_absolute():
            base_dir = repo_root if repo_root is not None else DEFAULT_REPO_ROOT
            candidate = (base_dir / candidate).resolve()
        if not candidate.exists():
            raise FileNotFoundError(f"mapping_config_dir 不存在: {candidate}")
        if not candidate.is_dir():
            raise ValueError(f"mapping_config_dir 不是目录: {candidate}")
        semantic_config_path = candidate / "semantic.yaml"
        view_config_path = candidate / "view.yaml"
        if not semantic_config_path.is_file():
            raise FileNotFoundError(f"semantic.yaml 不存在: {semantic_config_path}")
        if not view_config_path.is_file():
            raise FileNotFoundError(f"view.yaml 不存在: {view_config_path}")
        return str(semantic_config_path), str(view_config_path)

    return get_mapping_config_paths(statement_type, consolidated=is_consolidated)


def _normalize_period_pair_values(data: Dict[str, Any]) -> Dict[str, Any]:
    normalized: Dict[str, Any] = {}
    for code, value in data.items():
        if isinstance(value, list):
            if len(value) >= 2:
                normalized[code] = [value[0], value[1]]
            elif len(value) == 1:
                normalized[code] = [None, value[0]]
            else:
                normalized[code] = [None, None]
            continue

        if value is None:
            normalized[code] = [None, None]
        else:
            normalized[code] = [None, value]
    return normalized


def map_markdown_document(
    document: StatementMarkdownDocument,
    *,
    config: Optional[Dict[str, Any]] = None,
    mapping_config_dir: Optional[str] = None,
    repo_root: Optional[Path] = None,
) -> MappedStatementResult:
    return FinancialStatementMapCore(config, repo_root=repo_root).map_markdown_document(
        document,
        mapping_config_dir=mapping_config_dir,
    )


def map_markdown_documents(
    documents: Iterable[StatementMarkdownDocument],
    *,
    config: Optional[Dict[str, Any]] = None,
    mapping_config_dirs: Optional[Iterable[Optional[str]]] = None,
    repo_root: Optional[Path] = None,
) -> List[MappedStatementResult]:
    return FinancialStatementMapCore(config, repo_root=repo_root).map_markdown_documents(
        documents,
        mapping_config_dirs=mapping_config_dirs,
    )
