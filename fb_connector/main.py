"""FB Connector 最小服务外壳。

T04 只提供运行边界和服务间认证；具体 Meta API 路由在 T06-T10 逐步迁入。
"""

from __future__ import annotations

import os
import uuid

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from services.request_signer import verify_request
from fb_connector.api.oauth import router as oauth_router
from fb_connector.api.assets import router as assets_router
from fb_connector.api.media import router as media_router
from fb_connector.api.campaigns import router as campaigns_router
from fb_connector.api.reports import router as reports_router


app = FastAPI(title="FB Connector", version="0.1.0")
app.include_router(oauth_router)
app.include_router(assets_router)
app.include_router(media_router)
app.include_router(campaigns_router)
app.include_router(reports_router)


def _service_secret() -> str:
    return os.getenv("SAAS_INTERNAL_SIGNING_KEY", "")


@app.middleware("http")
async def service_auth_middleware(request: Request, call_next):
    """保护 /internal 路由；健康检查允许负载均衡探针访问。"""
    if request.url.path.startswith("/internal/") and request.url.path not in {"/internal/health", "/internal/ready"}:
        body = await request.body()
        service_name = request.headers.get("X-Service-Name")
        if service_name != "saas" or not verify_request(
            _service_secret(), request.headers, request.method, request.url.path, body
        ):
            return JSONResponse(status_code=401, content={"detail": "invalid service signature"})
        request.state.request_id = request.headers.get("X-Request-Id") or uuid.uuid4().hex
    response = await call_next(request)
    response.headers["X-Request-Id"] = getattr(request.state, "request_id", uuid.uuid4().hex)
    return response


@app.get("/internal/health")
async def health():
    return {"status": "ok", "service": "fb_connector"}


@app.get("/internal/ready")
async def ready():
    required = ("FB_APP_ID", "FB_APP_SECRET", "FB_OAUTH_REDIRECT_URI", "SAAS_INTERNAL_SIGNING_KEY")
    missing = [key for key in required if not os.getenv(key)]
    if missing:
        return JSONResponse(status_code=503, content={"status": "not_ready", "missing": missing})
    return {"status": "ready", "service": "fb_connector"}


@app.get("/internal/meta/version")
async def meta_version(request: Request):
    """临时受保护探针，确认 Connector 配置已加载；不返回 Secret。"""
    return {"service": "fb_connector", "api_version": os.getenv("FB_API_VERSION", "")}
