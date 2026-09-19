# syntax=docker/dockerfile:1.7
# 后端镜像：FastAPI + Celery（worker/beat 复用同一镜像，由 compose 覆盖 command）
FROM python:3.12-slim AS builder

WORKDIR /build

ARG PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple

# 先装依赖（利用 docker 层缓存）
COPY requirements.txt .
RUN python -m venv /opt/venv \
    && /opt/venv/bin/pip install --no-cache-dir --upgrade pip \
    && /opt/venv/bin/pip install --no-cache-dir --prefer-binary --index-url "$PIP_INDEX_URL" -r requirements.txt

FROM python:3.12-slim

# 国内服务器优先使用阿里云 Debian 镜像，避免 deb.debian.org 跨境/跨网抖动。
ARG DEBIAN_MIRROR=mirrors.aliyun.com
RUN if [ -f /etc/apt/sources.list.d/debian.sources ]; then \
        sed -i "s|deb.debian.org|${DEBIAN_MIRROR}|g" /etc/apt/sources.list.d/debian.sources; \
    else \
        sed -i "s|deb.debian.org|${DEBIAN_MIRROR}|g" /etc/apt/sources.list; \
    fi \
    && apt-get update \
    && apt-get install -y --no-install-recommends libpq5 curl ffmpeg \
    && rm -rf /var/lib/apt/lists/*

ENV PATH="/opt/venv/bin:$PATH"
WORKDIR /app

COPY --from=builder /opt/venv /opt/venv

# 复制项目代码
COPY . .

# 运行时目录
RUN mkdir -p /app/logs /app/uploads

ENV PYTHONPATH=/app \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

EXPOSE 8000

# 默认启动 API；celery-worker / celery-beat 由 compose 覆盖 command
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
