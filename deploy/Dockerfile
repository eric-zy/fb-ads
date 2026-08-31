# 后端镜像：FastAPI + Celery（worker/beat 复用同一镜像，由 compose 覆盖 command）
FROM python:3.12-slim

# 系统依赖：libpq5 给 psycopg2-binary 兜底，build-essential 兜底个别源码包
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential libpq5 curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 先装依赖（利用 docker 层缓存）
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

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
