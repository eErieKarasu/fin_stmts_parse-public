# 财报解析评测

评测只需要两个文件：

```text
evaluate/
├── gold.json   # 标准答案
└── run.py      # 运行评测
```

公开版不提供业务评测集。请将你有权使用的原始 PDF、图片和 Excel 放入本地 `files/`，自行准备 `evaluate/gold.json`；这些文件默认被 Git 忽略。

## 运行

先启动需要测试的服务，然后在仓库根目录执行：

```bash
# gRPC
.venv/bin/python evaluate/run.py grpc

# MCP
.venv/bin/python evaluate/run.py mcp
```

两种方式都直接读取本地文件，不使用 S3。

只检查标准答案和原文件，不调用服务：

```bash
.venv/bin/python evaluate/run.py grpc --check
```

先测试一个用例：

```bash
.venv/bin/python evaluate/run.py grpc --limit 1
```

指定服务地址：

```bash
.venv/bin/python evaluate/run.py grpc --host 127.0.0.1 --grpc-port 50051
.venv/bin/python evaluate/run.py mcp --url http://127.0.0.1:8765/
```

服务在 Docker 中时，将仓库挂载到容器，并用 `--service-root` 指定容器中的仓库根目录：

```bash
.venv/bin/python evaluate/run.py grpc --service-root /workspace/fin_stmts_parse
```

## gold.json

`gold.json` 的结构如下；标准答案及原始文件由使用者自行提供。

每个用例直接保存：

- 本地原文件路径；
- 公司、日期和 `FN191/FN192` 等请求参数；
- 三张报表的科目编码、名称和标准金额。

示例：

```json
{
  "file": "files/example-report.jpg",
  "company": "示例公司",
  "fns_no": "FN191",
  "end_date": "202503",
  "report_type": "QTR",
  "expected": {
    "balance": {
      "Z01010100": {
        "name": "货币资金",
        "begin": "100.00",
        "end": "120.00"
      }
    },
    "profit": {},
    "cashflow": {}
  }
}
```

不需要额外的 `id`；运行脚本使用 `file + fns_no` 区分用例。资产负债表使用 `begin`、`end`，利润表和现金流量表使用 `current`。金额用字符串保存，避免浮点误差。

## 报告

报告默认写入 `evaluate/reports/`，包含字段准确率和每个错误字段。缺表、缺科目、服务调用失败都会计错。`--fail-under` 也使用字段准确率判断。

完整参数见：

```bash
.venv/bin/python evaluate/run.py --help
```

## 测试

```bash
.venv/bin/python -m unittest discover -s evaluate/tests -v
```
