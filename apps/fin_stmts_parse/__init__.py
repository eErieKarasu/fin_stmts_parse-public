"""Shared financial statement parsing core for lwade protocol adapters."""

import sys

# Support both import styles:
# - fin_stmts_parse...
# - apps.fin_stmts_parse...
sys.modules.setdefault("fin_stmts_parse", sys.modules[__name__])
