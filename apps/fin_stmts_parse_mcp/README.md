# fin_stmts_parse_mcp

这个目录是 `fin_stmts_parse` 的 MCP 适配层，用来把共享核心能力包装成 MCP tools，对外提供可组合调用的财报解析链路。

当前 MCP 服务提供 5 个 tool：

1. `parse_fin_stmts_markdown`
2. `fin_stmts_parse_map`
3. `fin_stmts_parse_inspect`
4. `fin_stmts_parse_markdown_to_excel`
5. `fin_stmts_parse_audit_firm`

典型调用链路如下：

```text
parse_fin_stmts_markdown
  -> fin_stmts_parse_map
  -> fin_stmts_parse_inspect

parse_fin_stmts_markdown
  -> fin_stmts_parse_markdown_to_excel

fin_stmts_parse_audit_firm
```

## 启动 MCP 服务

### 通过框架启动

在仓库根目录执行：

```bash
python start_all.py --runner mcp --mcp-app-path apps/fin_stmts_parse_mcp
```

### 本地联调启动

适合单机调试和 live test：

```bash
python apps/fin_stmts_parse_mcp/start_mcp_local.py
```

可选参数：

```bash
python apps/fin_stmts_parse_mcp/start_mcp_local.py \
  --host 127.0.0.1 \
  --port 8765 \
  --env local \
  --workspace-dir apps/fin_stmts_parse_mcp
```

## MCP 调用日志

MCP tool 调用会以 JSONL 形式写入 `log.root_path` 下的 `mcp_tools_YYYY-MM-DD.jsonl`。
每行是一条完整调用记录，包含 tool 名称、`session_id`、耗时、完整入参、完整出参或异常堆栈。

人工排查时可以用查看脚本把 JSONL 渲染成块状 pretty JSON：

```bash
python tools/view_mcp_tool_log.py logs/mcp_tools_2026-05-12.jsonl --latest
python tools/view_mcp_tool_log.py logs/mcp_tools_2026-05-12.jsonl --tool fin_stmts_parse_inspect
python tools/view_mcp_tool_log.py logs/mcp_tools_2026-05-12.jsonl --session-id frontend-xxx --limit 3
python tools/view_mcp_tool_log.py logs/mcp_tools_2026-05-12.jsonl --status error --all
```

## Tool 说明

### 1. `parse_fin_stmts_markdown`

作用：

- 输入 PDF 或图片文件
- 调用共享核心中的 PDF/图片解析器
- 输出按文件分组的 Markdown 财报内容

接口定义：

```python
parse_fin_stmts_markdown(
    files: List[Dict[str, Any]],
    session_id: str,
) -> List[Dict[str, Any]]
```

入参：

- 顶层参数：`files`
- 顶层参数：`session_id`
- 类型：数组
- 每个元素支持以下任一字段组合：
  - `{"fileUrl": "...", "fileName": "..."}`
  - `{"file_url": "...", "file_name": "..."}`
  - `{"url": "...", "name": "..."}`
  - `{"path": "/absolute/path/to/file.pdf"}`

入参说明：

- `fileUrl` / `file_url` / `url`：远程文件地址
- `fileName` / `file_name` / `name`：可选文件名
- `path`：本地文件绝对路径
- `session_id`：会话 ID，必填
- 单次请求中的多个文件会有界并发处理，默认并发数为 `2`；可通过环境变量 `MCP_PARSE_MAX_WORKERS` 调整
- 返回数组仍保持与 `files` 入参一致的顺序

文件保存：

- 原始输入文件会保存到 `/tmp/fin_stmts_parse/mcp/YYYYMMDD/download`
- 解析中间产物会保存到 `/tmp/fin_stmts_parse/mcp/YYYYMMDD/output`
- 下载目录不会在每次调用前清空；同名文件再次写入时按当前下载覆盖策略处理

返回：

- 顶层返回数组
- 每个元素对应一个输入文件

返回字段：

- `message`：本文件执行结果说明
- `file_name`：本次处理的文件名
- `company_name`：公司名称；优先由大模型识别正文/报表页提取，失败时再用规则兜底；若存在冲突则返回空字符串
- `markdown_files`：识别出的 Markdown 表数组

`markdown_files` 每项字段：

- `table_name`：表名，如 `资产负债表`、`合并利润表`
- `page`：可选，报表在 PDF 中所在页码
- `date`：识别到的报表日期
- `is_consolidated`：是否合并报表
- `content`：Markdown 表格内容
- `unit`：可选，识别到的单位

Markdown 入库：

- 解析成功后会把未经科目映射的表格内容保存到对应的资产负债表、利润表或现金流量表。
- 入库前会把 HTML `<table>` 原位转换为 Markdown 管道表格；MCP 返回的 `markdown_files` 仍保持解析器原始内容。
- 转换会保留普通文字和表格顺序，并将合并表头展平；数据库中的新写入数据不包含 HTML `<table>` 标签。
- 已存在的 `report_status="-1"` 历史行不会自动转换，需要重新解析文件或使用同一规范化器离线回填。
- `report_status="-1"` 表示该行保存的是 Markdown 文本，正文位于 `extension_field`。
- `report_type="1"` 表示单体，`report_type="2"` 表示合并。
- 同一文件、同一报表类型和同一 `report_type` 的多页 Markdown 按页拼接为一行。
- 重复解析同一 `session_id + file_name` 时，仅替换三张表中的 `report_status="-1"` 行，不影响标准科目数据。
- 未识别到 Markdown 或文件解析失败时保留数据库中的上一版 Markdown。
- HTML 表格无法安全转换或 Markdown 入库失败时，不替换数据库上一版，仍返回已解析的 `markdown_files`，并通过 `message` 返回失败原因。
- 查询标准科目时必须限定 `report_status IN ('0','1')`；查询 Markdown 时限定 `report_status='-1'`。

`message` 常见取值：

- `解析成功`
- `解析成功但 Markdown 入库失败: ...`
- `不支持的文件类型`
- `未识别到财报表格内容`
- `解析失败: ...`

调用示例：

```json
{
  "session_id": "session-1",
  "files": [
    {
      "path": "/absolute/path/to/report.pdf"
    },
    {
      "fileUrl": "https://example.com/demo.pdf",
      "fileName": "demo.pdf"
    }
  ]
}
```

返回示例：

```json
[
  {
    "message": "解析成功",
    "file_name": "report.pdf",
    "company_name": "公司名",
    "markdown_files": [
      {
        "table_name": "资产负债表",
        "page": 23,
        "date": "202412",
        "is_consolidated": false,
        "content": "# 资产负债表\n\n| 项目 | 期末余额 |\n| --- | --- |\n| 货币资金 | 100 |"
      }
    ]
  }
]
```

### 2. `fin_stmts_parse_map`

作用：

- 输入 `parse_fin_stmts_markdown` 的完整输出
- 先把 Markdown 表格解析成科目-数值字典
- 再按 YAML 规则映射为标准科目编码
- 返回前自动触发一次被动勾稽校验与入库

接口定义：

```python
fin_stmts_parse_map(
    parse_results: List[Any],
    session_id: str,
) -> List[Dict[str, Any]]
```

入参：

- 顶层参数：`parse_results`
- 顶层参数：`session_id`
- 类型：数组
- 必须直接传入 `parse_fin_stmts_markdown` 的完整返回结果
- `session_id`：会话 ID，必填

返回：

- 顶层返回数组
- 每个元素对应一个输入文件

返回字段：

- `message`
- `file_name`
- `company_name`
- `mapped_results`

`mapped_results` 每项字段：

- `table_name`
- `page`：可选，报表在 PDF 中所在页码
- `date`
- `is_consolidated`
- `view_data`

`view_data` 格式：

- 类型：数组
- 顶层元素为展示树根节点，顺序与 `view.yaml` 一致
- 分组节点格式：`{type: "group", key, name, level, parent?, children, code?, values?}`
- 行节点格式：`{type: "row", code, name, values}`
- `children` 是当前分组内的子分组或字段成员
- 当某个分组节点本身也对应展示科目时，会额外携带 `code` 和 `values`
- 这是 `fin_stmts_parse_map` 对外展示的主结果
- 仅返回前端展示字段，数值来自后端规范语义层的投影
- 字段值中的 `null`：表示原表未抽取到对应规范字段
- 字段值中的 `""`：表示原表抽取到了对应规范字段，但对应单元格为空

`fin_stmts_parse_inspect` 先基于 `view_data` 展示字段执行首层简单勾稽。
当 `map_results` 中未显式携带 `canonical_data` 时，服务仍会按同一个 `session_id` 读取 map 阶段缓存的规范语义结果，用于内部持久化和后续下钻能力。

额外行为：

- tool 返回前会自动调用一次 `fin_stmts_parse_inspect`
- 自动调用时固定使用 `report_status="0"`，表示被动触发保存
- 被动勾稽校验失败不会影响 `fin_stmts_parse_map` 的主返回

调用示例：

```json
{
  "session_id": "session-1",
  "parse_results": [
    {
      "message": "解析成功",
      "file_name": "report.pdf",
      "company_name": "公司名",
      "markdown_files": [
        {
          "table_name": "资产负债表",
          "page": 23,
          "date": "202412",
          "is_consolidated": false,
          "content": "# 资产负债表\n\n| 项目 | 期末余额 | 年初余额 |\n| --- | --- | --- |\n| 货币资金 | 100.50 | 90.25 |\n| 应收账款 | 200.00 | 180.00 |\n| 资产总计 | 300.50 | 270.25 |"
        }
      ]
    }
  ]
}
```

返回示例：

```json
[
  {
    "message": "全部 1 项 markdown 映射成功",
    "file_name": "report.pdf",
    "company_name": "公司名",
    "mapped_results": [
      {
        "table_name": "资产负债表",
        "page": 23,
        "date": "202412",
        "is_consolidated": false,
        "mapped_data": {
          "Z01010100": ["货币资金", "90.25", "100.5"],
          "Z01010611": ["预付款项", null, null],
          "Z01010610": ["应收账款", "180.0", "200.0"],
          "Z01030005": ["固定资产净额", "", ""],
          "Z01000001": ["资产总计", "270.25", "300.5"]
        }
      }
    ]
  }
]
```

### 3. `fin_stmts_parse_inspect`

作用：

- 输入 `fin_stmts_parse_map` 的完整输出
- 聚合三表映射结果
- 执行 `FinancialInspector` 勾稽校验
- 在需要时保存 PostgreSQL 财报事实表

接口定义：

```python
fin_stmts_parse_inspect(
    map_results: List[Any],
    session_id: str,
    report_status: str = "1",
) -> Dict[str, Any]
```

入参：

- `map_results`：必填，必须直接传入 `fin_stmts_parse_map` 的完整返回结果
- `session_id`：必填
- `report_status`：可选；`"0"` 表示被动触发保存，`"1"` 表示主动触发保存

返回：

- 顶层字段：
  - `message`
  - `inspection_passed`
  - `details`

`details` 结构：

- `details` 按 `statement_type` 分组，固定包含：
  - `balance`
  - `profit`
  - `cashflow`
- 每组内数组项字段：
  - `check_item`
  - `status`
  - `period`
  - `suspects`
  - `reason`

`period` 为校验期间：
- 资产负债表：`begin` 表示期初值校验，`end` 表示期末值校验
- 利润表、现金流量表：固定为 `end`

`suspects` 为嫌疑科目名称列表。
如果已缩小到更细粒度科目，则通常只返回 1 个科目；
如果尚未缩小到单一科目，则返回当前参与校验的嫌疑科目列表。

`status` 仅返回 `pass` / `fail` 两种状态。

`reason` 为前端可直接展示的短中文说明。
示例：
- `校验通过`
- `复核通过`
- `校验未通过`
- `字段缺失`
- `无法校验`
- `疑似字段错误`
- `字段缺失，推测值是398345.12`

调用示例：

```json
{
  "session_id": "session-1",
  "map_results": [
    {
      "message": "全部 1 项 markdown 映射成功",
      "file_name": "report.pdf",
      "company_name": "公司名",
      "mapped_results": [
        {
          "table_name": "资产负债表",
          "date": "202412",
          "is_consolidated": false,
          "mapped_data": {
            "Z01010100": ["货币资金", "90.25", "100.5"],
            "Z01010610": ["应收账款", "180.0", "200.0"],
            "Z01000001": ["资产总计", "270.25", "300.5"]
          }
        }
      ]
    }
  ]
}
```

返回示例：

```json
{
  "message": "勾稽校验完成，有1 张表参与了校验；总计 2 条，2 条通过，0 条失败",
  "inspection_passed": true,
  "details": {
    "balance": [
      {
        "check_item": "流动资产合计(年初)",
        "status": "pass",
        "period": "begin",
        "suspects": [],
        "reason": "校验通过"
      },
      {
        "check_item": "流动资产合计(期末)",
        "status": "pass",
        "period": "end",
        "suspects": [],
        "reason": "校验通过"
      }
    ],
    "profit": [],
    "cashflow": []
  }
}
```

### 4. `fin_stmts_parse_markdown_to_excel`

作用：

- 输入 `parse_fin_stmts_markdown` 返回的文件级结果
- 先将每个文件下的 `markdown_files` 导出为本地 Excel
- 再将 Excel 上传到 sdoss，并返回下载地址

接口定义：

```python
fin_stmts_parse_markdown_to_excel(
    parse_results: List[Any],
    session_id: str,
    output_dir: Optional[str] = None,
) -> List[Dict[str, Any]]
```

入参：

- 顶层参数：`parse_results`
- 顶层参数：`session_id`
- 类型：数组
- `session_id`：会话 ID，必填
- `output_dir`：可选；未传时默认保存到 `/tmp/fin_stmts_parse/mcp/YYYYMMDD/output`

每项字段：

- `file_name`：输入文件名
- `company_name`：公司名称，可选；为空时会优先从 `markdown_files` 内容中自动识别
- `markdown_files`：财报表数组
- `markdown_files[].table_name`：必填
- `markdown_files[].content`：必填
- `markdown_files[].page`：可选，报表在 PDF 中所在页码
- `markdown_files[].date`：可选
- `markdown_files[].is_consolidated`：可选
- `markdown_files[].unit`：可选

返回：

- 顶层返回数组
- 每个元素对应一个输入文件

返回字段：

- `message`：执行状态；成功时为空字符串
- `file_name`：输入文件名
- `company_name`：公司名称
- `excel_file_name`：导出的 Excel 文件名
- `excel_file_id`：Excel 上传到 sdoss 后对应的对象标识
- `excel_file_url`：上传到 sdoss 后返回的下载地址
- `sheets`：成功导出的源表元信息数组

`sheets` 每项字段：

- `table_name`：表名
- `page`：可选，报表在 PDF 中所在页码
- `date`：报表日期
- `is_consolidated`：字符串 `"true"` 或 `"false"`

`message` 常见取值：

- `""`
- `没有可导出的 markdown_files`
- `没有可导出的财报表格`
- `Excel 导出成功但上传失败`
- `Excel 导出失败: ...`

返回示例：

```json
[
  {
    "message": "",
    "file_name": "2024财报.pdf",
    "company_name": "公司名",
    "excel_file_name": "2024财报.xlsx",
    "excel_file_id": "llm/fin_parse_excel/20260414/uuid_2024财报.xlsx",
    "excel_file_url": "https://example.com/demo.xlsx",
    "sheets": [
      {
        "table_name": "资产负债表",
        "page": 23,
        "date": "202412",
        "is_consolidated": "false"
      },
      {
        "table_name": "利润表",
        "page": 24,
        "date": "202412",
        "is_consolidated": "true"
      }
    ]
  }
]
```

### 5. `fin_stmts_parse_audit_firm`

作用：

- 输入 PDF、图片或 Excel 财报文件
- 识别该文件是否经审计
- 返回唯一明确的会计师事务所名称；无法唯一确认时返回空字符串

接口定义：

```python
fin_stmts_parse_audit_firm(
    files: List[Dict[str, Any]],
    session_id: str,
) -> List[Dict[str, Any]]
```

入参复用 `parse_fin_stmts_markdown` 的 `files` 格式。

文件保存：

- 原始输入文件会保存到 `/tmp/fin_stmts_parse/mcp/YYYYMMDD/download`
- 下载目录不会在每次调用前清空；同名文件再次写入时按当前下载覆盖策略处理

返回字段：

- `message`：执行状态说明
- `file_name`：输入文件名
- `audit_status`：`audited`、`unaudited` 或 `unknown`
- `audit_firm_name`：会计师事务所名称
- `confidence`：`high`、`medium` 或 `low`
- `evidence`：命中的简短证据数组

调用示例：

```json
{
  "session_id": "session-1",
  "files": [
    {
      "path": "/absolute/path/to/report.pdf"
    }
  ]
}
```

返回示例：

```json
[
  {
    "message": "识别成功",
    "file_name": "report.pdf",
    "audit_status": "audited",
    "audit_firm_name": "中兴华会计师事务所（特殊普通合伙）",
    "confidence": "high",
    "evidence": [
      {
        "page": 3,
        "text": "中兴华会计师事务所（特殊普通合伙）"
      }
    ]
  }
]
```

## 单测与联调

### 单元测试

在仓库根目录执行：

```bash
python apps/fin_stmts_parse_mcp/tests/test_service.py
python apps/fin_stmts_parse_mcp/tests/test_audit_firm_service.py
python apps/fin_stmts_parse_mcp/tests/test_export_service.py
python apps/fin_stmts_parse_mcp/tests/test_map_service.py
python apps/fin_stmts_parse_mcp/tests/test_inspect_service.py
```

覆盖内容：

- `test_service.py`：`parse_fin_stmts_markdown` 的文件归一化和返回契约
- `test_audit_firm_service.py`：审计机构识别 tool 的文件归一化和返回契约
- `test_export_service.py`：Excel 导出上传和返回契约
- `test_map_service.py`：Markdown 到标准科目映射结果
- `test_inspect_service.py`：勾稽校验聚合和返回结构

### Live Test

1. 先启动本地 MCP 服务：

```bash
python apps/fin_stmts_parse_mcp/start_mcp_local.py
```

2. 再执行 live chain 测试：

```bash
python apps/fin_stmts_parse_mcp/tests/test_mcp_live.py --file files/2024财报.pdf --session-id session-1
```

如果测试远程文件：

```bash
python apps/fin_stmts_parse_mcp/tests/test_mcp_live.py \
  --file-url https://example.com/demo.pdf \
  --file-name demo.pdf \
  --session-id session-1
```

默认连接地址：

- `http://127.0.0.1:8765/`

### 批量评估

统一评测脚本位于仓库根目录 `evaluate/`，评测 MCP 服务可执行：

```bash
.venv/bin/python evaluate/run.py mcp --url http://127.0.0.1:8765/
```

其中评测链路只调用 `parse_fin_stmts_markdown -> fin_stmts_parse_map`。
`fin_stmts_parse_map` 会隐含触发被动勾稽校验，因此评测脚本不会再额外显式调用 `fin_stmts_parse_inspect`。
