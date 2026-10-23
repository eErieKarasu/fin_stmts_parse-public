# fin_stmts_parse 核心说明

`apps/fin_stmts_parse` 是财报解析项目的共享核心目录，`grpc` 和 `mcp` 两个适配层都直接复用这里的能力。

它负责的不是协议封装，而是实际的财报处理流程，包括：

- PDF 财报解析
- 图片财报解析
- Markdown 表格提取
- 标准科目映射
- 三表勾稽校验
- 环境配置与提示词管理

## 目录结构

```text
apps/fin_stmts_parse/
├── clients/
├── config/
│   ├── env/
│   ├── mappings/
│   └── prompts/
├── consts/
├── exceptions/
├── src/
├── tests/
└── utils/
```

## 核心目录说明

### `src/`

核心业务实现目录，主要放解析主流程和处理器实现。

关键模块包括：

- `financial_report_service.py`
  - 共享解析主入口
  - 负责下载文件、分发文件处理、合并三表结果、执行勾稽校验
- `pdf_financial_parser.py`
  - PDF 财报解析器
  - 支持分页识别、表格检测、Markdown 提取、异常回退
- `image_financial_parser.py`
  - 图片财报解析器
  - 调用公共单页流程，完成文件级日期决策和结果输出
- `statement_page_processor.py`
  - PDF 按逻辑表解析，图片沿用单页分类、提取回退；复用预处理、校验和逻辑报表拆分
  - 返回 `PageExtractionResult`，保留逻辑报表正文、数据和页面元数据供跨页聚合
  - PDF 调用 `process_statement()`，将同表全部页面与元数据合为一次模型请求
- `pdf_page_renderer.py`
  - PDF 页面渲染；扫描窗口、并发、提前停止和跨页聚合仍由 PDF 解析器负责
- `pdf_page_discovery.py`
  - 仅通过原生文本/OCR 定位目标报表、识别续页并分组
- `page_classification.py`
  - 分类状态校验及携带失败页码的 `PageDiscoveryError`
- `statement_output.py`
  - 共用结果字典格式、Markdown 文件写入和原始提取快照
- `markdown_table_extractor.py`
  - 把 Markdown 表格解析为结构化字典
- `account_code_mapper.py`
  - 按 YAML 规则把报表字段映射到标准科目编码
- `financial_inspector.py`
  - 对资产负债表、利润表、现金流量表做勾稽校验
- `excel_financial_parser.py`
  - Excel 财务数据解析支持
- `orientation_inference.py` / `orientation_model/`
  - 图像方向识别与推理相关代码
- `watermark_remover.py`
  - 图片/页面去水印处理

PDF 和图片解析器通过 `page_processor` 构造参数组合 `StatementPageProcessor`，
PDF 还可通过 `page_renderer` 替换页面渲染。底层识别能力暂由单页处理器继承
`BaseFinancialProcessor` 复用。单页处理器只清理预处理生成的临时图片，
原始图片由调用方保留，PDF 渲染目录由 PDF 解析器统一释放。

#### PDF：OCR 定位后按表解析

1. 原生文本可用时直接筛选；扫描页先复用现有 ONNX 四方向分类器纠正方向，
   再用本地 RapidOCR 提取中文文字，**不调用远程 OCR 服务或通用 VLM 分类**。
   根据独立标题、表号、典型科目和金额定位目标表型；识别目录、附注及权益变动表，
   用相邻报表与科目结构归属无标题续页。
2. 支持资产负债表、利润表、现金流量表及对应合并报表，共六种类型，
   **不要求文件包含全部六类或至少三类：按实际定位的表组进入解析**。
   指定 `is_consolidated=True/False` 时仅选择对应范围。
   每批默认扫描 3 页；已定位报表之后出现明确的财务报表附注标题时结束扫描。
   已覆盖全部支持类型并确认续页边界时也可提前停止，否则扫描至配置窗口或文件末尾。
   未确定/失败页面保留诊断，不阻断已定位表组；仅当没有可解析表组且存在未确定页时抛出发现错误。
3. 连续的同表页面合为一个请求，**每组仅调用一次 VLM**，同时返回完整表格正文、
   公司名、日期、单位和标题。随后本地解析、拆分合并/母公司列、校验和组装结果；
   不再调用公司名、元数据或表头识别模型。最多并行解析 3 组。
   OCR 与 VLM 复用纠正后的图片，避免重复方向检测；任务结束（包括失败）后清理临时图片。

例如六张逻辑表位于第 6–13 页，两张资产负债表各占两页时，请求分组为
`[6,7]、[8,9]、[10]、[11]、[12]、[13]`，共六次模型解析。
分组基于连续页面，不把文件中不同位置的同名报表直接拼接。

```yaml
pdf_parse:
  discovery:
    ocr_retries: 1      # OCR 调用失败时的额外重试次数，0–3
  page_scan:
    enabled: true
    initial_window_pages: 30
    fallback_full_scan: true
    batch_size: 3       # 每批页数及预处理并发，1–8；并非先扫描满 30 页
```

PDF 定位使用 `rapidocr==3.8.4` 和 ONNX Runtime，固定加载 wheel 随附的中文
PP-OCRv4 mobile 检测/识别模型。无需设置 `paddle_ocr` 或 `use_paddle=True`；
原有 Paddle 配置仍用于图片入口。两个服务的 requirements 均包含 RapidOCR，
Docker 构建会校验本地模型可加载；运行时不自动下载模型。
RapidOCR 实例在进程内懒加载复用，并用锁保护其内部可变状态；ONNX 推理使用 2 个计算线程。
定位用的 OCR 不执行表格结构还原或文本行方向分类；整页方向由现有分类器负责。
方向纠正失败、OCR 失败或文本不能确定表型时，保留失败/不确定状态并报告页码，
不会悄悄改用 VLM 分类或把调用失败当作无报表。
存在已定位表组时继续解析，并输出可能不完整的警告；目标表自身的 VLM 提取失败仍明确报错。
旧的 `discovery.enabled` 和 `vlm_retries` 不再控制 PDF 发现流程。

分类状态为 `matched`、`not_matched`、`uncertain`、`failed`；
兼容字段 `has_target_table` 分别为 `true`、`false`、`null`、`null`。
设置 `output_dir` 后写入 `<文件名>_discovery.json`，记录 OCR 引擎、每页结论、方向纠正耗时、OCR 次数/耗时、
定位总耗时、逻辑表页码分组和各组解析耗时。
`discovery_status=partial` 和 `unresolved_pages` 标记未确定的页面；具体原因保留在 `pages` 中，
`stop_reason` 记录提前停止或扫描到边界的原因。
`vlm_calls` 仅表示页面分类调用次数（应为 0）；`extraction_calls` 表示提交的逻辑表解析任务数。
模型请求不进行隐藏重试，响应截断或本地数据校验失败会明确报错，通过响应格式校验的原始输出保存为快照。
跨页报表对外 `page` 字段仍为起始页，完整页码范围可在发现记录的 `groups` 中查看。

### `config/env/`

运行环境配置目录，用于区分不同部署环境的参数。

当前包含：

- `local.yaml`
- `dev.yaml`
- `sit.yaml`
- `uat.yaml`
- `prod.yaml`

通常会放：

- 文件下载与本地落盘路径
- OCR / Paddle 配置
- LLM 服务配置
- 业务运行参数

### `config/mappings/`

财务三表科目映射规则目录，供 `AccountCodeMapper` 使用。

按报表类型和是否合并拆分：

- `balance/`
- `profit/`
- `cashflow/`

每类下通常包含：

- `standalone/semantic.yaml`
- `standalone/view.yaml`
- `consolidated/semantic.yaml`
- `consolidated/view.yaml`

这些 YAML 用来定义：

- 规范语义字段
- 前端展示字段
- 从原始表格中提取数值的映射与回填规则

### `config/prompts/`

LLM 提示词目录，用于表格识别和抽取相关提示模板管理。

当前已包含：

- `table_detection.py`

这部分主要服务于：

- 页面表格类型识别
- 大模型表格内容提取
- 解析回退场景下的提示词复用

## 功能链路

共享核心的大致处理链路如下：

```text
输入文件
  -> 下载到本地
  -> PDF/图片解析
  -> Markdown 表格抽取
  -> Markdown 转结构化数据
  -> YAML 科目映射
  -> 三表合并
  -> 勾稽校验
  -> 输出结构化结果
```

## 其他目录

### `clients/`

外部客户端封装，当前主要是 `llm_client.py`，用于统一管理 LLM 调用。

### `utils/`

工具方法目录，包含：

- 文件传输与下载
- YAML 读取
- S3 客户端
- 日志与请求上下文
- 字符串处理

### `exceptions/`

自定义异常定义目录，供共享服务和适配层统一处理错误。

### `consts/`

常量和编码枚举定义目录。

### `tests/`

核心目录下的测试脚本，当前可见的是 `test_s3_client.py`。

## 与适配层的关系

- `apps/fin_stmts_parse_grpc`：把共享核心包装成 gRPC 服务
- `apps/fin_stmts_parse_mcp`：把共享核心包装成 MCP tools

因此，协议层问题通常看适配层目录，识别、映射、校验逻辑问题通常看这个核心目录。
