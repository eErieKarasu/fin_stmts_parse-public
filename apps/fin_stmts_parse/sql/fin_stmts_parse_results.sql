CREATE TABLE IF NOT EXISTS fin_stmts_parse_results_balance (
    session_id varchar NOT NULL,
    company_name varchar NOT NULL,
    item_name varchar NOT NULL,
    fns_cycle varchar NOT NULL,
    fns_year varchar NOT NULL,
    report_cycle_type varchar NOT NULL,
    report_type varchar NOT NULL,
    begin_amt varchar,
    end_amt varchar,
    report_status varchar NOT NULL,
    stat_date varchar NOT NULL,
    file_name varchar NOT NULL,
    extension_field varchar NOT NULL,
    stat_is_audit varchar NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_fin_stmts_parse_results_balance_session_id
    ON fin_stmts_parse_results_balance (session_id);

CREATE INDEX IF NOT EXISTS idx_fin_stmts_parse_results_balance_session_id_file_name
    ON fin_stmts_parse_results_balance (session_id, file_name);

CREATE INDEX IF NOT EXISTS idx_fin_stmts_parse_results_balance_snapshot
    ON fin_stmts_parse_results_balance (
        session_id,
        file_name,
        report_status,
        report_type
    );

WITH ranked AS (
    SELECT
        ctid,
        ROW_NUMBER() OVER (
            PARTITION BY session_id, file_name, report_status, report_type
            ORDER BY stat_date DESC, ctid DESC
        ) AS row_number
    FROM fin_stmts_parse_results_balance
    WHERE report_status = '-1'
)
DELETE FROM fin_stmts_parse_results_balance AS target
USING ranked
WHERE target.ctid = ranked.ctid
  AND ranked.row_number > 1;

CREATE UNIQUE INDEX IF NOT EXISTS ux_fin_stmts_parse_results_balance_markdown
    ON fin_stmts_parse_results_balance (
        session_id,
        file_name,
        report_status,
        report_type
    )
    WHERE report_status = '-1';

CREATE TABLE IF NOT EXISTS fin_stmts_parse_results_profit (
    session_id varchar NOT NULL,
    company_name varchar NOT NULL,
    item_name varchar NOT NULL,
    fns_cycle varchar NOT NULL,
    fns_year varchar NOT NULL,
    report_cycle_type varchar NOT NULL,
    report_type varchar NOT NULL,
    begin_amt varchar,
    end_amt varchar,
    report_status varchar NOT NULL,
    stat_date varchar NOT NULL,
    file_name varchar NOT NULL,
    extension_field varchar NOT NULL,
    stat_is_audit varchar NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_fin_stmts_parse_results_profit_session_id
    ON fin_stmts_parse_results_profit (session_id);

CREATE INDEX IF NOT EXISTS idx_fin_stmts_parse_results_profit_session_id_file_name
    ON fin_stmts_parse_results_profit (session_id, file_name);

CREATE INDEX IF NOT EXISTS idx_fin_stmts_parse_results_profit_snapshot
    ON fin_stmts_parse_results_profit (
        session_id,
        file_name,
        report_status,
        report_type
    );

WITH ranked AS (
    SELECT
        ctid,
        ROW_NUMBER() OVER (
            PARTITION BY session_id, file_name, report_status, report_type
            ORDER BY stat_date DESC, ctid DESC
        ) AS row_number
    FROM fin_stmts_parse_results_profit
    WHERE report_status = '-1'
)
DELETE FROM fin_stmts_parse_results_profit AS target
USING ranked
WHERE target.ctid = ranked.ctid
  AND ranked.row_number > 1;

CREATE UNIQUE INDEX IF NOT EXISTS ux_fin_stmts_parse_results_profit_markdown
    ON fin_stmts_parse_results_profit (
        session_id,
        file_name,
        report_status,
        report_type
    )
    WHERE report_status = '-1';

CREATE TABLE IF NOT EXISTS fin_stmts_parse_results_cashflow (
    session_id varchar NOT NULL,
    company_name varchar NOT NULL,
    item_name varchar NOT NULL,
    fns_cycle varchar NOT NULL,
    fns_year varchar NOT NULL,
    report_cycle_type varchar NOT NULL,
    report_type varchar NOT NULL,
    begin_amt varchar,
    end_amt varchar,
    report_status varchar NOT NULL,
    stat_date varchar NOT NULL,
    file_name varchar NOT NULL,
    extension_field varchar NOT NULL,
    stat_is_audit varchar NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_fin_stmts_parse_results_cashflow_session_id
    ON fin_stmts_parse_results_cashflow (session_id);

CREATE INDEX IF NOT EXISTS idx_fin_stmts_parse_results_cashflow_session_id_file_name
    ON fin_stmts_parse_results_cashflow (session_id, file_name);

CREATE INDEX IF NOT EXISTS idx_fin_stmts_parse_results_cashflow_snapshot
    ON fin_stmts_parse_results_cashflow (
        session_id,
        file_name,
        report_status,
        report_type
    );

WITH ranked AS (
    SELECT
        ctid,
        ROW_NUMBER() OVER (
            PARTITION BY session_id, file_name, report_status, report_type
            ORDER BY stat_date DESC, ctid DESC
        ) AS row_number
    FROM fin_stmts_parse_results_cashflow
    WHERE report_status = '-1'
)
DELETE FROM fin_stmts_parse_results_cashflow AS target
USING ranked
WHERE target.ctid = ranked.ctid
  AND ranked.row_number > 1;

CREATE UNIQUE INDEX IF NOT EXISTS ux_fin_stmts_parse_results_cashflow_markdown
    ON fin_stmts_parse_results_cashflow (
        session_id,
        file_name,
        report_status,
        report_type
    )
    WHERE report_status = '-1';
