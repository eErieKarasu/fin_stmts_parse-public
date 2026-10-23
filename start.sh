#!/bin/bash

set -euo pipefail

export PYTHONUNBUFFERED=1
export SKIP_RUNTIME_PIP_INSTALL="${SKIP_RUNTIME_PIP_INSTALL:-true}"
export GRPC_WORKERS="${GRPC_WORKERS:-1}"
export HTTP_WORKERS="${HTTP_WORKERS:-1}"
export GRPC_APP_PATH="${GRPC_APP_PATH:-${GRPC_APP_IMAGE_PATH:-apps/fin_stmts_parse_grpc}}"
export MCP_APP_PATH="${MCP_APP_PATH:-${MCP_APP_IMAGE_PATH:-apps/fin_stmts_parse_mcp}}"
export ENABLE_FRONTEND="${ENABLE_FRONTEND:-true}"
export FRONTEND_HOST="${FRONTEND_HOST:-0.0.0.0}"
export FRONTEND_PORT="${FRONTEND_PORT:-5173}"
export FIN_STMTS_MCP_URL="${FIN_STMTS_MCP_URL:-http://127.0.0.1:8001/mcp}"
export SW_AGENT_LOGGING_LEVEL="${SW_AGENT_LOGGING_LEVEL:-CRITICAL}"
export SW_AGENT_PROFILE_ACTIVE="${SW_AGENT_PROFILE_ACTIVE:-false}"
export SW_AGENT_METER_REPORTER_ACTIVE="${SW_AGENT_METER_REPORTER_ACTIVE:-false}"
export SW_AGENT_LOG_REPORTER_ACTIVE="${SW_AGENT_LOG_REPORTER_ACTIVE:-false}"

exec python start_all.py \
  --runner grpc,mcp \
  --grpc-app-path "${GRPC_APP_PATH}" \
  --mcp-app-path "${MCP_APP_PATH}"
