# Dockerfile
FROM python:3.12-slim-bookworm@sha256:a116514e19457bcb7af7efe9c3dd0b9b71e85b317694e7882a1c52aa15a78134

ARG GRPC_APP_IMAGE_PATH=apps/fin_stmts_parse_grpc
ARG MCP_APP_IMAGE_PATH=apps/fin_stmts_parse_mcp

RUN echo "deb https://mirrors.aliyun.com/debian bookworm main contrib non-free" > /etc/apt/sources.list && \
    echo "deb https://mirrors.aliyun.com/debian-security bookworm-security main contrib non-free" >> /etc/apt/sources.list && \
    echo "deb https://mirrors.aliyun.com/debian bookworm-updates main contrib non-free" >> /etc/apt/sources.list

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libc6-dev \
    libgl1 \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender-dev \
    libgomp1 \
    libgtk-3-0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

ENV GRPC_APP_IMAGE_PATH=${GRPC_APP_IMAGE_PATH}
ENV MCP_APP_IMAGE_PATH=${MCP_APP_IMAGE_PATH}

COPY requirements.txt ./
RUN pip install --no-cache-dir -i https://pypi.tuna.tsinghua.edu.cn/simple/ -r requirements.txt

COPY . ./

RUN rm -rf /app/packages/grpc /app/packages/mcp /app/packages/sse /app/packages/a2a && \
    mkdir -p /app/packages/grpc /app/packages/mcp /app/packages/sse /app/packages/a2a && \
    if [ -f "/app/${GRPC_APP_IMAGE_PATH}/requirements.txt" ]; then \
        pip install --no-cache-dir -i https://pypi.tuna.tsinghua.edu.cn/simple/ --target /app/packages/grpc -r "/app/${GRPC_APP_IMAGE_PATH}/requirements.txt"; \
    fi && \
    if [ -f "/app/${MCP_APP_IMAGE_PATH}/requirements.txt" ]; then \
        pip install --no-cache-dir -i https://pypi.tuna.tsinghua.edu.cn/simple/ --target /app/packages/mcp -r "/app/${MCP_APP_IMAGE_PATH}/requirements.txt"; \
    fi

# --- 标记：用户自定义 Dockerfile 将插入此处 ---
RUN PYTHONPATH=/app/packages/grpc python /app/apps/fin_stmts_parse/src/lightweight_ocr.py && \
    PYTHONPATH=/app/packages/mcp python /app/apps/fin_stmts_parse/src/lightweight_ocr.py && \
    PYTHONPATH=/app/packages/grpc:/app/packages/mcp python -m pip check && \
    PYTHONPATH=/app/packages/mcp:/app/packages/grpc python -m pip check

# >>> INSERT_SUB_DOCKERFILE_HERE <<<
# ------------------------------------

RUN chmod +x /app/start.sh

EXPOSE 50051 5173 8001 8002 9000

ENTRYPOINT ["/app/start.sh"]
