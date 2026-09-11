# 后端镜像：FastAPI + Celery（worker/beat 复用同一镜像，由 compose 覆盖 command）
FROM python:3.12-slim AS builder

# 系统依赖：libpq5 给 psycopg2-binary 兜底，build-essential 兜底个别源码包
RUN apt-get update && apt-get install -y --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build

# 先装依赖（利用 docker 层缓存）
COPY requirements.txt .
RUN python -m venv /opt/venv \
    && /opt/venv/bin/pip install --no-cache-dir --upgrade pip \
    && /opt/venv/bin/pip install --no-cache-dir -r requirements.txt

FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends libpq5 curl ffmpeg \
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
