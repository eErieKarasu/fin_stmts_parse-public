# db_tools

这个目录提供一个面向本仓库的 PostgreSQL CLI，用来替代“控制台一坨原始结果”的查看方式。

它复用了 `apps/fin_stmts_parse/config/env/*.yaml` 里的 `postgres.dsn` 配置，并使用 `Rich` 把输出渲染成更可读的表格。

## 适用场景

- 看当前库里有哪些表
- 查看某张表的字段结构
- 预览表里的数据
- 直接执行一段 SQL

## 用法

建议直接使用项目虚拟环境：

```bash
./.venv/bin/python db_tools/db_cli.py tables
```

### 1. 列出表

```bash
./.venv/bin/python db_tools/db_cli.py tables
./.venv/bin/python db_tools/db_cli.py tables --all-schemas
```

### 2. 查看表结构

```bash
./.venv/bin/python db_tools/db_cli.py describe fin_stmts_parse_results_balance
./.venv/bin/python db_tools/db_cli.py describe public.fin_stmts_parse_results_profit
```

### 3. 预览表数据

```bash
./.venv/bin/python db_tools/db_cli.py preview fin_stmts_parse_results_balance --limit 10
./.venv/bin/python db_tools/db_cli.py preview fin_stmts_parse_results_balance --limit 5 --vertical
```

### 4. 执行 SQL

```bash
./.venv/bin/python db_tools/db_cli.py sql -q "select * from fin_stmts_parse_results_balance limit 5"
./.venv/bin/python db_tools/db_cli.py sql -f apps/fin_stmts_parse/sql/fin_stmts_parse_results.sql
```

## 额外参数

- `--env local|dev|sit|uat|prod`
  - 切换到不同环境配置，默认读取 `RUNNING_ENV`，否则使用 `local`
- `--dsn "postgresql://..."`
  - 临时覆盖 YAML 里的数据库连接
- `--schema public`
  - 给 `describe` / `preview` 提供默认 schema
- `--max-cell-width 64`
  - 调整单元格截断宽度，避免太宽时难看

## 说明

- `preview` 会自动帮你生成 `SELECT * ... LIMIT n`
- `sql` 支持直接执行写操作，执行成功后会提交事务
- 为了避免结果太横向，列太多时会自动切到纵向展示
