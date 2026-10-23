#!/bin/bash

# 设置环境变量
export GRPC_WORKERS=1
export SW_AGENT_LOGGING_LEVEL=CRITICAL
export SW_AGENT_PROFILE_ACTIVE=false
export SW_AGENT_METER_REPORTER_ACTIVE=false
export SW_AGENT_LOG_REPORTER_ACTIVE=false
export ENABLE_SKYWALKING=false
export GRPC_VERBOSITY=ERROR
export SKIP_RUNTIME_PIP_INSTALL=true

export PIP_MIRROR_URL=https://pypi.tuna.tsinghua.edu.cn/simple/                    
export PIP_MIRROR_HOSTNAME=pypi.tuna.tsinghua.edu.cn

# 启动 Python 脚本
python start_all.py --runner grpc --grpc-app-path apps/fin_stmts_parse_grpc
