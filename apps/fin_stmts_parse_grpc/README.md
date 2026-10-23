# fin_stmts_parse_grpc

这个目录是 `fin_stmts_parse` 的 gRPC 适配层。它本身不承载核心解析逻辑，主要职责是：

- 暴露 gRPC 协议入口
- 做请求参数校验与协议字段适配
- 调用 `apps/fin_stmts_parse` 中的共享解析流水线
- 将共享结果转换为历史兼容的 gRPC 返回结构

真正的业务核心代码位于同级目录：

- `../fin_stmts_parse`

## 目录职责

### `service.py`

gRPC 服务入口，负责：

- 接收 `parseFinStmts` 请求
- 校验必填字段和报表类型
- 初始化 `FinancialReportService`
- 调用共享解析服务并组装 `ParseReply`

`ParseReply.dealSts` 取值：

- `1`：资产负债表期初、资产负债表期末、利润表和现金流量表均解析成功
- `2`：解析中，当前仅作占位，服务不会返回
- `3`：所有部分均解析失败，或处理过程发生异常
- `4`：部分解析成功

`dealRemark` 在部分成功或失败时会逐项列出解析失败的部分。

返回的报表存在性标志为字符串 `0` 或 `1`，依据报表是否成功识别并进入映射结果设置，不依据金额是否为零：

- `fnsItemBsFlag`：资产负债表
- `fnsItemIsFlag`：利润表
- `fnsItemCsFlag`：现金流量表

### `protos/`

存放 gRPC 协议文件和生成代码：

- `fin_stmts_parse.proto`
- `ALL_IN_ONE.proto`
- `fin_stmts_parse_pb2.py`
- `fin_stmts_parse_pb2_grpc.py`

### `tests/`

测试脚本目录：

- `test_financial_inspector.py`：勾稽校验规则相关单元测试
- `test_service.py`：gRPC 状态码和返回说明相关单元测试
- `test_grpc_smoke.py`：连通本地 gRPC 服务的 smoke test

### `tools/`

联调和评估脚本目录：

- `testparse.py`：对 gRPC 服务发起真实解析请求

### `testdata/`

放轻量示例数据或确认结果文件。

## 启动 gRPC 服务

在仓库根目录执行：

```bash
python start_all.py --runner grpc --grpc-app-path apps/fin_stmts_parse_grpc
```

说明：

- 协议入口来自当前目录的 `service.py`
- 共享解析逻辑复用 `apps/fin_stmts_parse`

## 构建镜像

在仓库根目录执行：

```bash
python build_image.py \
  --runner grpc \
  --grpc-app-path apps/fin_stmts_parse_grpc \
  --name fin-stmts-parse-grpc \
  --tag v1
```

补充说明：

- `protos/ALL_IN_ONE.proto`、`requirements.txt`、`service.py` 是 gRPC app 的必要文件
- 如果当前目录下存在 `my.dockerfile`，构建时会自动注入到主 `Dockerfile`

## 单测与联调

### 单元测试

在仓库根目录执行：

```bash
python apps/fin_stmts_parse_grpc/tests/test_financial_inspector.py
```

这个测试主要验证共享 `FinancialInspector` 的关键校验逻辑。

### Smoke Test

1. 先启动本地 gRPC 服务：

```bash
python start_all.py --runner grpc --grpc-app-path apps/fin_stmts_parse_grpc
```

2. 再执行 smoke test：

```bash
python apps/fin_stmts_parse_grpc/tests/test_grpc_smoke.py \
  --host localhost \
  --file-name sample.pdf \
  --file-url https://example.com/sample.pdf
```

可选参数：

- `--port`：默认读取 `lwade_config.GRPC_PORT`
- `--fns-no`：默认 `FN191`，可改为 `FN192`

### 工具脚本

联调单文件：

```bash
python apps/fin_stmts_parse_grpc/tools/testparse.py \
  --host localhost \
  --file-name sample.pdf \
  --file-url https://example.com/sample.pdf
```

批量评估：

```bash
.venv/bin/python evaluate/run.py grpc
```
