#!/usr/bin/env python3
"""Run the financial-statement evaluation from one gold JSON file."""
from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_GOLD = Path(__file__).with_name("gold.json")
EMPTY = {None, "", "-", "--", "—", "－"}
MISSING = object()
TABLE_NAMES = {
    "资产负债表": "balance",
    "合并资产负债表": "balance",
    "利润表": "profit",
    "合并利润表": "profit",
    "现金流量表": "cashflow",
    "合并现金流量表": "cashflow",
}


def add_project_imports() -> None:
    for path in (
        ROOT,
        ROOT / "apps",
        ROOT / "apps/fin_stmts_parse_grpc",
        ROOT / "apps/fin_stmts_parse",
        ROOT / "packages/mcp",
    ):
        value = str(path)
        if value not in sys.path:
            sys.path.insert(0, value)


def safe_source(root: Path, relative: str) -> Path:
    if Path(relative).is_absolute():
        raise ValueError(f"原文件路径必须相对仓库根目录: {relative}")
    root = root.resolve()
    path = (root / relative).resolve()
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"原文件路径越界: {relative}") from exc
    if not path.is_file():
        raise FileNotFoundError(f"原文件不存在: {path}")
    return path


def load_gold(path: Path) -> list[dict]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("version") != 2 or data.get("empty_values_equal_zero") is not True:
        raise ValueError("不支持的 gold.json 版本或空值规则")
    cases = data.get("cases")
    if not isinstance(cases, list) or not cases:
        raise ValueError("gold.json 没有评测用例")
    seen_cases = set()
    for case in cases:
        required = {"file", "company", "fns_no", "end_date", "report_type", "expected"}
        if not required <= set(case):
            raise ValueError(f"用例缺少字段: {required - set(case)}")
        identity = (case["file"], case["fns_no"])
        if identity in seen_cases:
            raise ValueError(f"重复用例: {identity}")
        seen_cases.add(identity)
        label = case_label(case)
        if case["fns_no"] not in {"FN191", "FN192"}:
            raise ValueError(f"{label}: fns_no 错误")
        if not re.fullmatch(r"\d{6}", str(case["end_date"])):
            raise ValueError(f"{label}: end_date 错误")
        if case["report_type"] not in {"ANN", "QTR", "MON", "SEMI"}:
            raise ValueError(f"{label}: report_type 错误")
        expected = case["expected"]
        if not isinstance(expected, dict) or set(expected) != {"balance", "profit", "cashflow"}:
            raise ValueError(f"{label}: expected 必须包含三种报表")
        for table, rows in expected.items():
            if not isinstance(rows, dict):
                raise ValueError(f"{label}: {table} 必须是对象")
            slots = {"begin", "end"} if table == "balance" else {"current"}
            for code, item in rows.items():
                if not code or not isinstance(item, dict) or not isinstance(item.get("name"), str):
                    raise ValueError(f"{label}: {table}/{code} 格式错误")
                if not slots <= set(item):
                    raise ValueError(f"{label}: {table}/{code} 缺少金额")
                for slot in slots:
                    if parse_amount(item[slot])[0] != "number":
                        raise ValueError(f"{label}: {table}/{code}/{slot} 标准金额无效")
    return cases


def case_label(case: dict) -> str:
    return f"{case['file']} [{case['fns_no']}]"


def answers(case: dict):
    for table, rows in case["expected"].items():
        slots = ("begin", "end") if table == "balance" else ("current",)
        for code, item in rows.items():
            for slot in slots:
                yield {
                    "table_id": table,
                    "table": table,
                    "code": code,
                    "slot": slot,
                    "name": item["name"],
                    "value": item[slot],
                }


def parse_amount(value):
    if value is MISSING:
        return "missing", None
    if value is None or isinstance(value, str) and value.strip() in EMPTY:
        # gRPC 把原表空白和横线返回为 0.0，因此接口评测统一视作零。
        return "number", Decimal(0)
    if isinstance(value, bool):
        return "invalid", None
    text = re.sub(r"[,，\s]", "", str(value))
    if text.startswith(("(", "（")) and text.endswith((")", "）")):
        text = "-" + text[1:-1]
    try:
        number = Decimal(text)
        return ("number", number) if number.is_finite() else ("invalid", None)
    except InvalidOperation:
        return "invalid", None


def answer_key(answer: dict) -> tuple[str, str, str]:
    return answer["table"], answer["code"], answer["slot"]


def compare(case: dict, prediction: dict, failure: str | None = None) -> dict:
    fields = []
    expected_answers = list(answers(case))
    for answer in expected_answers:
        actual = prediction.get(answer_key(answer), MISSING)
        match = not failure and parse_amount(actual)[0] == "number" and parse_amount(actual) == parse_amount(answer["value"])
        reason = (
            "service_failure" if failure else
            "missing_field" if actual is MISSING else
            "invalid_amount" if parse_amount(actual)[0] == "invalid" else
            "amount_mismatch"
        )
        fields.append({
            **answer,
            "actual": None if actual is MISSING else actual,
            "present": actual is not MISSING,
            "exact_match": bool(match),
            "reason": None if match else reason,
        })
    table_ids = {field["table_id"] for field in fields}
    table_matches = sum(
        all(field["exact_match"] for field in fields if field["table_id"] == table_id)
        for table_id in table_ids
    )
    expected = {answer_key(answer) for answer in expected_answers}
    extras = [
        {"table": key[0], "code": key[1], "slot": key[2], "actual": value}
        for key, value in prediction.items()
        if key not in expected and parse_amount(value) != ("number", Decimal(0))
    ]
    return {
        "case": case_label(case),
        "file": case["file"],
        "fns_no": case["fns_no"],
        "end_date": case["end_date"],
        "error": failure,
        "field_total": len(fields),
        "field_matched": sum(field["exact_match"] for field in fields),
        "table_total": len(table_ids),
        "table_exact_match_count": table_matches,
        "case_exact_match": not failure and table_matches == len(table_ids),
        "differences": [field for field in fields if not field["exact_match"]],
        "unscored_predictions": extras,
    }


def summary(results: list[dict]) -> dict:
    totals = {
        key: sum(result[key] for result in results)
        for key in (
            "field_total", "field_matched", "table_total", "table_exact_match_count",
        )
    }
    count = len(results)
    failed = sum(bool(result["error"]) for result in results)
    return {
        **totals,
        "total_cases": count,
        "evaluated_cases": count - failed,
        "failed_cases": failed,
        "field_exact_match_rate": totals["field_matched"] / totals["field_total"] if totals["field_total"] else None,
        "table_exact_match_rate": totals["table_exact_match_count"] / totals["table_total"] if totals["table_total"] else None,
        "case_exact_match_rate": sum(result["case_exact_match"] for result in results) / count if count else None,
    }


def build_grpc_request(index, case, file_path, proto):
    return proto.ParseRequest(
        pubGloblJnno=f"evaluate-{uuid.uuid4()}",
        seriNo=f"evaluate-{uuid.uuid4()}",
        requestId=f"EVAL-{index}-{uuid.uuid4().hex[:8]}",
        fnsId=f"evaluate-{uuid.uuid4()}",
        fnsNo=case["fns_no"],
        companyName=case["company"],
        reportType=case["report_type"],
        endDate=case["end_date"],
        finFiles=[{"fileName": Path(case["file"]).name, "fileUrl": file_path}],
    )


def grpc_prediction(response) -> dict:
    if response.dealSts not in {"1", "4"}:
        raise RuntimeError(f"gRPC 业务失败 ({response.dealSts}): {response.dealRemark}")
    prediction = {}
    for attribute, table, slot in (
        ("fnsItemBsBegin", "balance", "begin"),
        ("fnsItemBsEnd", "balance", "end"),
        ("fnsItemIs", "profit", "current"),
        ("fnsItemCs", "cashflow", "current"),
    ):
        for code, value in getattr(response, attribute).items():
            prediction[(table, code, slot)] = value
    return prediction


def tool_payload(name, result):
    if getattr(result, "isError", False):
        raise RuntimeError(f"{name} 调用失败: {result}")
    payload = getattr(result, "structuredContent", None)
    if payload is None:
        texts = [item.text for item in getattr(result, "content", []) if getattr(item, "type", None) == "text"]
        if len(texts) != 1:
            raise RuntimeError(f"{name} 未返回 JSON")
        payload = json.loads(texts[0])
    if isinstance(payload, dict) and set(payload) == {"result"}:
        return payload["result"]
    return payload


def view_rows(nodes):
    if not isinstance(nodes, list):
        raise ValueError("MCP view_data 必须是数组")
    for node in nodes:
        if not isinstance(node, dict):
            raise ValueError("MCP view_data 节点必须是对象")
        if node.get("code"):
            values = node.get("values", [])
            if not isinstance(values, list):
                raise ValueError("MCP values 必须是数组")
            yield str(node["code"]), values
        yield from view_rows(node.get("children", []))


def normalized_month(value) -> str | None:
    match = re.fullmatch(r"(\d{4})[-/年]?(\d{2})(?:[-/月]?\d{2}日?)?", str(value or "").strip())
    return "".join(match.groups()) if match else None


def boolean_scope(value) -> bool:
    if value in (True, "true", "True", "1", 1):
        return True
    if value in (False, "false", "False", "0", 0):
        return False
    raise ValueError(f"MCP 缺少或无效的 is_consolidated: {value!r}")


def mcp_prediction(payload, case) -> dict:
    if not isinstance(payload, list):
        raise ValueError("MCP 映射结果必须是数组")
    prediction, seen_tables = {}, set()
    consolidated = case["fns_no"] == "FN192"
    for file_result in payload:
        for statement in file_result.get("mapped_results", []):
            table = statement.get("table_type") or TABLE_NAMES.get(statement.get("table_name"))
            if table not in {"balance", "profit", "cashflow"}:
                continue
            if boolean_scope(statement.get("is_consolidated")) != consolidated:
                continue
            month = normalized_month(statement.get("date"))
            if month is None:
                raise ValueError(f"MCP 报表日期无法识别: {statement.get('date')!r}")
            if month != case["end_date"]:
                continue
            if table in seen_tables:
                raise ValueError(f"MCP 同一期间和口径返回多张 {table}")
            seen_tables.add(table)
            codes = set()
            for code, values in view_rows(statement.get("view_data", [])):
                if code in codes:
                    raise ValueError(f"MCP 同一张表出现重复编码: {code}")
                codes.add(code)
                if table == "balance" and len(values) >= 2:
                    prediction[(table, code, "begin")] = values[0]
                    prediction[(table, code, "end")] = values[1]
                elif table == "balance" and values == [None]:
                    prediction[(table, code, "begin")] = None
                    prediction[(table, code, "end")] = None
                elif values:
                    prediction[(table, code, "current")] = values[-1]
    return prediction


class GrpcClient:
    def __init__(self, args):
        self.args = args
        self.channel = None

    async def __aenter__(self):
        add_project_imports()
        import grpc
        from lwade_config import config
        from protos import fin_stmts_parse_pb2, fin_stmts_parse_pb2_grpc
        self.grpc = grpc
        self.proto = fin_stmts_parse_pb2
        port = self.args.grpc_port if self.args.grpc_port is not None else config.GRPC_PORT
        self.channel = grpc.insecure_channel(f"{self.args.host}:{port}")
        self.stub = fin_stmts_parse_pb2_grpc.FinStmtsParseStub(self.channel)
        try:
            await asyncio.to_thread(grpc.channel_ready_future(self.channel).result, timeout=self.args.connect_timeout)
        except BaseException:
            self.channel.close()
            raise
        return self

    async def parse(self, case, file_path, index):
        request = build_grpc_request(index, case, file_path, self.proto)
        response = await asyncio.to_thread(self.stub.parseFinStmts, request, timeout=self.args.timeout)
        raw = {
            "dealSts": response.dealSts,
            "dealRemark": response.dealRemark,
            **{
                name: dict(getattr(response, name))
                for name in ("fnsItemBsBegin", "fnsItemBsEnd", "fnsItemIs", "fnsItemCs")
            },
        }
        return raw, grpc_prediction(response)

    async def __aexit__(self, *_):
        if self.channel:
            self.channel.close()


class McpClient:
    def __init__(self, args):
        self.args = args

    async def __aenter__(self):
        from contextlib import AsyncExitStack
        add_project_imports()
        import httpx
        from mcp import ClientSession
        from mcp.client.streamable_http import streamable_http_client
        self.stack = AsyncExitStack()
        await self.stack.__aenter__()
        try:
            http_client = await self.stack.enter_async_context(httpx.AsyncClient(
                follow_redirects=True,
                timeout=httpx.Timeout(self.args.timeout, connect=self.args.connect_timeout),
            ))
            streams = await self.stack.enter_async_context(
                streamable_http_client(self.args.url, http_client=http_client)
            )
            self.session = await self.stack.enter_async_context(ClientSession(
                streams[0], streams[1], read_timeout_seconds=timedelta(seconds=self.args.timeout)
            ))
            await asyncio.wait_for(self.session.initialize(), self.args.connect_timeout)
            tools = await asyncio.wait_for(self.session.list_tools(), self.args.connect_timeout)
            missing = {"parse_fin_stmts_markdown", "fin_stmts_parse_map"} - {tool.name for tool in tools.tools}
            if missing:
                raise RuntimeError(f"MCP 缺少工具: {sorted(missing)}")
        except BaseException:
            await self.stack.aclose()
            raise
        return self

    async def parse(self, case, file_path, index):
        session_id = f"evaluate-{index}-{uuid.uuid4().hex}"

        async def call(name, arguments):
            result = await asyncio.wait_for(self.session.call_tool(name, arguments), self.args.timeout)
            payload = tool_payload(name, result)
            if not isinstance(payload, list):
                raise RuntimeError(f"{name} 必须返回数组")
            return payload

        parsed = await call("parse_fin_stmts_markdown", {
            "session_id": session_id,
            "files": [{"path": file_path}],
        })
        mapped = await call("fin_stmts_parse_map", {
            "session_id": session_id,
            "parse_results": parsed,
        })
        return {"parse_results": parsed, "map_results": mapped}, mcp_prediction(mapped, case)

    async def __aexit__(self, *exc):
        return await self.stack.__aexit__(*exc)


def positive_int(value):
    result = int(value)
    if result <= 0:
        raise argparse.ArgumentTypeError("必须大于 0")
    return result


def rate(value):
    result = float(value)
    if not 0 <= result <= 1:
        raise argparse.ArgumentTypeError("必须在 0 到 1 之间")
    return result


def arguments(argv=None):
    parser = argparse.ArgumentParser(description="使用 gold.json 评测本地财报解析服务")
    parser.add_argument("protocol", choices=("grpc", "mcp"), help="选择 gRPC 或 MCP")
    parser.add_argument("--gold", type=Path, default=DEFAULT_GOLD, help="标准答案文件")
    parser.add_argument("--root", type=Path, default=ROOT, help="原文件所在的仓库根目录")
    parser.add_argument("--limit", type=positive_int, help="只运行前 N 个用例")
    parser.add_argument("--file", action="append", default=[], help="只运行指定文件，可重复")
    parser.add_argument("--output", type=Path, help="报告路径")
    parser.add_argument("--service-root", type=Path, help="容器等环境中的服务端仓库根目录")
    parser.add_argument("--host", default="localhost", help="gRPC 地址")
    parser.add_argument("--grpc-port", type=positive_int, help="gRPC 端口")
    parser.add_argument("--url", default="http://127.0.0.1:8765/", help="MCP 地址")
    parser.add_argument("--timeout", type=positive_int, default=600, help="单次解析超时秒数")
    parser.add_argument("--connect-timeout", type=positive_int, default=10, help="连接超时秒数")
    parser.add_argument("--check", action="store_true", help="只检查 gold.json 和原文件")
    parser.add_argument("--fail-under", type=rate, help="字段准确率低于阈值时返回 2")
    args = parser.parse_args(argv)
    if args.service_root is not None and not args.service_root.is_absolute():
        parser.error("--service-root 必须是绝对路径")
    return args


def service_file(args, case, local_path: Path) -> str:
    if args.service_root is None:
        return str(local_path)
    return str(args.service_root / case["file"])


def error_text(exc) -> str:
    if isinstance(exc, BaseExceptionGroup):
        return "; ".join(error_text(item) for item in exc.exceptions)
    return f"{type(exc).__name__}: {exc}"


def write_report(report: dict, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


async def evaluate(args, cases, client_factory=None) -> tuple[int, Path]:
    output = (args.output or ROOT / "evaluate/reports" / (
        datetime.now().strftime("%Y%m%d-%H%M%S-%f") + f"-{args.protocol}.json"
    )).resolve()
    results, failures = [], []
    report = {
        "version": 2,
        "protocol": args.protocol,
        "gold": str(args.gold.resolve()),
        "started_at": datetime.now(timezone.utc).isoformat(),
        "results": results,
        "failures": failures,
    }

    def save():
        report["summary"] = summary(results)
        write_report(report, output)

    def fail(case, stage, exc):
        message = error_text(exc)
        failures.append({"case": case_label(case), "stage": stage, "error": message})
        results.append(compare(case, {}, failure=message))
        print(f"[{len(results)}/{len(cases)}] {case_label(case)}: {stage} 失败: {message}", flush=True)
        save()

    ready = []
    for case in cases:
        try:
            ready.append((case, safe_source(args.root, case["file"])))
        except (OSError, ValueError) as exc:
            fail(case, "source", exc)

    factory = client_factory or (GrpcClient if args.protocol == "grpc" else McpClient)
    if ready:
        try:
            async with factory(args) as client:
                for index, (case, local_path) in enumerate(ready, 1):
                    try:
                        remote_path = service_file(args, case, local_path)
                        print(f"[{len(results) + 1}/{len(cases)}] {case_label(case)}", flush=True)
                        raw, prediction = await client.parse(case, remote_path, index)
                        result = compare(case, prediction)
                        result["service_file"] = remote_path
                        result["raw_response"] = raw
                        results.append(result)
                        print(f"  字段匹配 {result['field_matched']}/{result['field_total']}", flush=True)
                    except Exception as exc:
                        fail(case, "parse", exc)
                    finally:
                        save()
        except Exception as exc:
            completed = {result["case"] for result in results}
            for case, _ in ready:
                if case_label(case) not in completed:
                    fail(case, "connection", exc)

    report["finished_at"] = datetime.now(timezone.utc).isoformat()
    save()
    stats = report["summary"]
    print(f"用例: {stats['evaluated_cases']}/{stats['total_cases']}")
    print(f"字段准确率: {stats['field_exact_match_rate']:.2%}" if stats["field_exact_match_rate"] is not None else "字段准确率: N/A")
    print(f"报告: {output}")
    if stats["failed_cases"]:
        return 1, output
    if args.fail_under is not None and (
        stats["field_exact_match_rate"] is None
        or stats["field_exact_match_rate"] < args.fail_under
    ):
        return 2, output
    return 0, output


def main(argv=None) -> int:
    args = arguments(argv)
    try:
        cases = load_gold(args.gold.resolve())
        if args.file:
            selected = set(args.file)
            missing = selected - {case["file"] for case in cases}
            if missing:
                raise ValueError(f"未知文件: {sorted(missing)}")
            cases = [case for case in cases if case["file"] in selected]
        if args.limit:
            cases = cases[:args.limit]
        paths = {case_label(case): safe_source(args.root, case["file"]) for case in cases}
        if args.check:
            print(json.dumps({
                "valid": True,
                "cases": len(cases),
                "files": len({case["file"] for case in cases}),
                "answers": sum(1 for case in cases for _ in answers(case)),
                "service_files": {
                    case_label(case): service_file(args, case, paths[case_label(case)]) for case in cases
                },
            }, ensure_ascii=False, indent=2))
            return 0
        return asyncio.run(evaluate(args, cases))[0]
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        print(f"评测配置错误: {error_text(exc)}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
