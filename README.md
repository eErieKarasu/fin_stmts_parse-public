# fin_stmts_parse in lwade

`fin_stmts_parse` 是基于 `lwade` 轻量化部署框架落地的一套财报解析项目，用来把 PDF、图片等财务报表资料解析成结构化结果，并通过不同协议对外提供服务。

## 公开版配置

本版本保留原有目录、解析核心、科目映射、勾稽校验、MCP、gRPC、前端和部署入口。
环境 YAML 使用 `${变量名:-默认值}` 读取配置；业务凭据、内部地址及业务评测数据不随源码提供。

建议使用 Python 3.12，在仓库根目录执行：

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m pip install -r apps/fin_stmts_parse_mcp/requirements.txt
cp .env.example .env
# 编辑 .env，填写自己的 VLM/LLM 地址、API Key 和模型名称。
set -a
source .env
set +a
export SKIP_RUNTIME_PIP_INSTALL=true
python apps/fin_stmts_parse_mcp/start_mcp_local.py
```

`.env` 需要按上面方式导出，不会被程序自动读取。gRPC 使用对应目录的 requirements。
对象存储、数据库、网关与跟踪服务继续使用原接口，按需配置自己的部署参数。
图像方向模型仍保留原文件与调用方式；模型/代码的再分发许可由发布者确认。

当前项目按“共享核心 + 协议适配层”的方式组织：

- 核心解析代码：`apps/fin_stmts_parse`
- gRPC 适配层：`apps/fin_stmts_parse_grpc`
- MCP 适配层：`apps/fin_stmts_parse_mcp`
- 统一评测脚本：`evaluate`

其中，核心目录负责财报识别、Markdown 抽取、科目映射、勾稽校验等通用能力；`grpc` 和 `mcp` 目录分别负责把这些能力包装成不同协议的服务入口。

## 目录关系

```text
apps/
├── fin_stmts_parse/         # 共享核心代码
├── fin_stmts_parse_grpc/    # gRPC 服务适配层
└── fin_stmts_parse_mcp/     # MCP 服务适配层

evaluate/
└── run.py                  # gRPC / MCP 评测入口；数据由使用者自行提供
```

推荐阅读顺序：

1. 先看 `apps/fin_stmts_parse`，了解核心解析能力和配置目录。
2. 再看 `apps/fin_stmts_parse_grpc`，了解传统 gRPC 服务如何对外暴露。
3. 最后看 `apps/fin_stmts_parse_mcp`，了解 MCP tool 的输入输出契约。

## 项目能力概览

`fin_stmts_parse` 当前覆盖的核心能力包括：

- 解析 PDF 财报和单张图片财报
- 自动识别资产负债表、利润表、现金流量表，以及合并/本部版本
- 产出 Markdown 表格结果，便于后续链路复用
- 基于 YAML 规则将报表项目映射为标准科目编码
- 对映射后的三表结果执行勾稽校验
- 通过独立 MCP tool 识别财报是否经审计及会计师事务所名称

## 启动服务

### 启动 gRPC 服务

在仓库根目录执行：

```bash
python start_all.py --runner grpc --grpc-app-path apps/fin_stmts_parse_grpc
```

说明：

- `service.py` 位于 `apps/fin_stmts_parse_grpc`
- 共享核心代码会直接复用 `apps/fin_stmts_parse`

### 启动 MCP 服务

在仓库根目录执行：

```bash
python start_all.py --runner mcp --mcp-app-path apps/fin_stmts_parse_mcp
```

如果只是本地联调 MCP，也可以直接启动本地 HTTP MCP 服务：

```bash
python apps/fin_stmts_parse_mcp/start_mcp_local.py
```

默认会监听：

- Host: `127.0.0.1`
- Port: `8765`

## 构建镜像

### 构建 gRPC 镜像

```bash
python build_image.py \
  --runner grpc \
  --grpc-app-path apps/fin_stmts_parse_grpc \
  --name fin-stmts-parse-grpc \
  --tag v1
```

### 构建 MCP 镜像

```bash
python build_image.py \
  --runner mcp \
  --mcp-app-path apps/fin_stmts_parse_mcp \
  --name fin-stmts-parse-mcp \
  --tag v1
```

镜像构建补充说明：

- 如果 `--grpc-app-path` 或 `--mcp-app-path` 指向 `lwade` 仓内目录，构建时会直接使用仓内路径。
- 如果 app 目录下存在 `my.dockerfile`，且未显式传入 `--sub-dockerfile`，构建脚本会自动注入该文件内容。
- `build_image.py` 会校验 app 目录的必要文件是否齐全后再构建。

## 文档索引

- 核心代码说明：[apps/fin_stmts_parse/README.md](apps/fin_stmts_parse/README.md)
- gRPC 适配层说明：[apps/fin_stmts_parse_grpc/README.md](apps/fin_stmts_parse_grpc/README.md)
- MCP 适配层说明：[apps/fin_stmts_parse_mcp/README.md](apps/fin_stmts_parse_mcp/README.md)
- 统一评测脚本说明：[evaluate/README.md](evaluate/README.md)
