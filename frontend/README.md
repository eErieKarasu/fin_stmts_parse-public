# 财报解析前端

一个零构建的本地页面，用于调用 `fin_stmts_parse_map` 和 `fin_stmts_parse_inspect`，并按“科目 / 期初 / 期初校验 / 期末 / 期末校验”五栏渲染财报结果。

## 启动

先启动 MCP 服务：

```bash
python apps/fin_stmts_parse_mcp/start_mcp_local.py
```

再启动前端代理：

```bash
python frontend/server.py
```

打开：

```text
http://127.0.0.1:5173
```

使用仓库根目录的 Docker 镜像时，前端会随 gRPC 和 MCP 服务一起启动，默认监听
`0.0.0.0:5173`，并连接同一容器内的 `http://127.0.0.1:8001/mcp`。可通过
`ENABLE_FRONTEND`、`FRONTEND_HOST`、`FRONTEND_PORT` 和 `FIN_STMTS_MCP_URL`
环境变量覆盖这些默认值。

页面默认连接 `http://127.0.0.1:8765/mcp`。可一次选择多个 PDF、图片或 Excel 财报文件，在文件队列中确认或移除单个文件后，点击“上传并解析”。所有文件会在同一次 `parse_fin_stmts_markdown` 请求中提交，并按文件展示解析状态。

前端代理会按顺序调用：

```text
parse_fin_stmts_markdown -> fin_stmts_parse_map -> fin_stmts_parse_inspect(report_status="0")
```

结果页支持在资产负债表、利润表、现金流量表之间切换；上传解析完成后会展示一次被动校验结果。期初、期末单元格可直接编辑。编辑完成后点击“MCP 校验”会单独调用 `fin_stmts_parse_inspect(report_status="1")`，并使用当前页面里的修改值作为校验输入。参与校验的期初、期末会分别标色，通过标绿，未通过标红。
