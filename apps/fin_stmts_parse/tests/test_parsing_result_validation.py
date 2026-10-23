import unittest
from unittest import mock

from apps.fin_stmts_parse.src.base_financial_processor import BaseFinancialProcessor
from apps.fin_stmts_parse.src.statement_page_processor import StatementPageProcessor


class ParsingResultValidationTest(unittest.TestCase):
    def setUp(self):
        with mock.patch.object(BaseFinancialProcessor, "_initialize_openai_client"):
            self.processor = StatementPageProcessor(config={})
        self.processor.logger = mock.Mock()

    def test_profit_list_values_do_not_trigger_begin_alarm(self):
        valid = self.processor.is_parsing_result_valid(
            {"营业收入": [None, "100.00"]}, "利润表"
        )
        self.assertTrue(valid)
        warnings = [str(call.args[0]) for call in self.processor.logger.warning.call_args_list]
        self.assertFalse(any("期初列数据全部为None" in item for item in warnings))

    def test_cashflow_list_values_do_not_trigger_begin_alarm(self):
        valid = self.processor.is_parsing_result_valid(
            {"经营活动产生的现金流量净额": [None, "200.00"]}, "现金流量表"
        )
        self.assertTrue(valid)
        warnings = [str(call.args[0]) for call in self.processor.logger.warning.call_args_list]
        self.assertFalse(any("期初列数据全部为None" in item for item in warnings))

    def test_balance_list_values_still_require_begin_and_end_columns(self):
        valid = self.processor.is_parsing_result_valid(
            {"货币资金": [None, "100.00"]}, "资产负债表"
        )
        self.assertFalse(valid)
        warnings = [str(call.args[0]) for call in self.processor.logger.warning.call_args_list]
        self.assertTrue(any("期初列数据全部为None" in item for item in warnings))


if __name__ == "__main__":
    unittest.main()
