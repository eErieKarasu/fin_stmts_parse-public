#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

from typing import Any, Dict, List, Mapping

import yaml

from fin_stmts_parse.utils.logger import logger


class ViewDataProjector:
    """将规范语义结果投影为前端稳定展示字段。"""

    def __init__(self, view_config_path: str):
        self.logger = logger
        self.config_path = view_config_path
        self.config = self._load_yaml_config()
        self.view_groups, self.view_rules = self._extract_view_definitions(self.config)
        self.logger.info(
            f"成功加载 view 配置文件: {self.config_path}, 共 {len(self.view_rules)} 个展示字段"
        )

    def _load_yaml_config(self) -> Dict[str, Any]:
        try:
            with open(self.config_path, "r", encoding="utf-8") as f:
                config = yaml.safe_load(f)
            if isinstance(config, dict):
                return config
            self.logger.warning(f"view 配置文件格式异常: {self.config_path}")
            return {}
        except Exception as exc:
            self.logger.error(f"加载 view 配置文件失败 {self.config_path}: {exc}")
            return {}

    def _extract_view_definitions(
        self,
        config: Mapping[str, Any],
    ) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        view_data = config.get("view_data")
        if isinstance(view_data, list):
            return self._extract_from_view_data(view_data)

        view_items = config.get("view_items")
        if isinstance(view_items, list):
            view_groups = config.get("view_groups")
            view_rules = [
                rule
                for item in view_items
                if isinstance(item, Mapping)
                if (rule := self._build_view_rule(item)) is not None
            ]
            return (
                list(view_groups) if isinstance(view_groups, list) else [],
                view_rules,
            )

        self.logger.warning(f"view 配置文件缺少 view_data/view_items: {self.config_path}")
        return [], []

    def _extract_from_view_data(
        self,
        view_data: List[Any],
    ) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        view_groups: List[Dict[str, Any]] = []
        view_rules: List[Dict[str, Any]] = []

        def walk_nodes(nodes: List[Any], *, parent: str = "", level: int = 1) -> List[str]:
            item_codes: List[str] = []
            for node in nodes:
                if not isinstance(node, Mapping):
                    continue

                code = str(node.get("code") or "").strip()
                name = str(node.get("name") or code).strip()
                children = node.get("items")
                if isinstance(children, list):
                    key = str(node.get("key") or "").strip()
                    if key:
                        group: Dict[str, Any] = {
                            "key": key,
                            "name": str(node.get("name") or key),
                            "level": node.get("level", level),
                            "item_codes": [],
                        }
                        if parent:
                            group["parent"] = parent
                        view_groups.append(group)

                        child_codes = walk_nodes(children, parent=key, level=level + 1)
                        group["item_codes"] = child_codes
                        item_codes.extend(child_codes)
                        continue

                    if not code:
                        self.logger.warning(
                            f"view_data 分组缺少 key，已跳过: {self.config_path}"
                        )
                        continue

                    group: Dict[str, Any] = {
                        "key": code,
                        "name": name,
                        "level": node.get("level", level),
                        "item_codes": [],
                        "row_code": code,
                    }
                    if parent:
                        group["parent"] = parent
                    view_groups.append(group)

                    view_rule = self._build_view_rule(node, fallback_code=code)
                    if view_rule is not None:
                        view_rules.append(view_rule)

                    child_codes = walk_nodes(children, parent=code, level=level + 1)
                    group["item_codes"] = [code, *child_codes]
                    item_codes.extend(group["item_codes"])
                    continue

                if not code:
                    continue
                view_rule = self._build_view_rule(node, fallback_code=code)
                if view_rule is not None:
                    view_rules.append(view_rule)
                item_codes.append(code)
            return item_codes

        walk_nodes(view_data)
        return view_groups, view_rules

    def project(self, canonical_data_full: Dict[str, Any]) -> Dict[str, Any]:
        view_data_full: Dict[str, Any] = {}
        for rule in self.view_rules:
            code = str(rule.get("code") or "").strip()
            source_codes = self._normalize_source_codes(
                rule.get("source_codes"),
                source_code=rule.get("source_code"),
                fallback_code=code,
            )
            if not code or not source_codes:
                continue
            view_data_full[code] = self._pick_source_value(
                canonical_data_full,
                source_codes,
            )
        return view_data_full

    def _build_view_rule(
        self,
        node: Mapping[str, Any],
        *,
        fallback_code: str = "",
    ) -> Dict[str, Any] | None:
        code = str(node.get("code") or fallback_code).strip()
        if not code:
            return None

        source_codes = self._normalize_source_codes(
            node.get("source_codes"),
            source_code=node.get("source_code"),
            fallback_code=code,
        )
        return {
            "code": code,
            "name": str(node.get("name") or code).strip(),
            "source_code": source_codes[0] if source_codes else "",
            "source_codes": source_codes,
        }

    def _normalize_source_codes(
        self,
        raw_source_codes: Any,
        *,
        source_code: Any = None,
        fallback_code: str = "",
    ) -> List[str]:
        normalized_codes: List[str] = []
        if isinstance(raw_source_codes, list):
            normalized_codes.extend(
                str(code).strip()
                for code in raw_source_codes
                if str(code or "").strip()
            )
        elif isinstance(source_code, str) and source_code.strip():
            normalized_codes.append(source_code.strip())
        elif fallback_code:
            normalized_codes.append(fallback_code)
        return normalized_codes

    def _pick_source_value(
        self,
        canonical_data_full: Mapping[str, Any],
        source_codes: List[str],
    ) -> Any:
        for source_code in source_codes:
            value = canonical_data_full.get(source_code)
            if not self._is_empty_value(value):
                return value
        return canonical_data_full.get(source_codes[0]) if source_codes else None

    @staticmethod
    def _is_empty_value(value: Any) -> bool:
        if value in ("", None):
            return True
        if isinstance(value, list):
            return all(item in ("", None) for item in value)
        return False

    @property
    def view_labels(self) -> Dict[str, str]:
        return {
            str(rule["code"]): str(rule["name"])
            for rule in self.view_rules
            if rule.get("code") and rule.get("name")
        }
