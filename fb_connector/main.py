"""FB Connector 最小服务外壳。

T04 只提供运行边界和服务间认证；具体 Meta API 路由在 T06-T10 逐步迁入。
"""

from __future__ import annotations

import os
import uuid
import hmac
import time

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from services.request_signer import verify_request
from core.logger import logger
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


@app.exception_handler(RequestValidationError)
async def request_validation_error(request: Request, exc: RequestValidationError):
    """Expose safe, actionable validation details for cross-service callers.

    Starlette's default 422 response is useful to an interactive browser but
    the access log only contains the status code.  Return the request ID and
    omit raw input values so malformed requests can be fixed without ever
    logging or echoing credentials/tokens.
    """
    request_id = getattr(request.state, "request_id", None) or request.headers.get("X-Request-Id") or uuid.uuid4().hex
    # Pydantic may put a ValueError instance into ``ctx`` for model-level
    # validators.  Keep only stable JSON-safe fields in the wire response.
    errors = [
        {
            "loc": error.get("loc", ()),
            "msg": error.get("msg", "请求参数校验失败"),
            "type": error.get("type", "value_error"),
        }
        for error in exc.errors()
    ]
    logger.warning(
        "[Connector] request validation failed path=%s request_id=%s errors=%s",
        request.url.path,
        request_id,
        errors,
    )
    return JSONResponse(
        status_code=422,
        content={"detail": errors, "request_id": request_id},
        headers={"X-Request-Id": request_id},
    )


def _service_secret() -> str:
    return os.getenv("SAAS_INTERNAL_SIGNING_KEY", "")


@app.middleware("http")
async def service_auth_middleware(request: Request, call_next):
    """保护 /internal 路由；健康检查允许负载均衡探针访问。"""
    started = time.monotonic()
    request_id = request.headers.get("X-Request-Id") or uuid.uuid4().hex
    request.state.request_id = request_id
    # Meta 浏览器回调不会携带内部服务签名；安全性由 OAuth state
    # 校验和授权码交换保证，因此必须允许该公开回调进入路由。
    public_internal_paths = {
        "/internal/health",
        "/internal/ready",
        "/internal/meta/oauth/callback",
    }
    if request.url.path.startswith("/internal/") and request.url.path not in public_internal_paths:
        body = await request.body()
        # Reading the body in middleware consumes the ASGI receive stream.
        # Replay it for FastAPI route handlers, otherwise valid signed POSTs
        # can hang until the caller's HTTP timeout expires.
        async def receive():
            return {"type": "http.request", "body": body, "more_body": False}
        request._receive = receive
        service_name = request.headers.get("X-Service-Name")
        expected_token = os.getenv("CONNECTOR_SERVICE_TOKEN", "")
        authorization = request.headers.get("Authorization", "")
        token_ok = bool(expected_token) and hmac.compare_digest(authorization, f"Bearer {expected_token}")
        if service_name != "saas" or not token_ok or not verify_request(
            _service_secret(), request.headers, request.method, request.url.path, body
        ):
            logger.warning(
                "[ConnectorHTTP] rejected request_id=%s method=%s path=%s reason=invalid_service_signature",
                request_id,
                request.method,
                request.url.path,
            )
            return JSONResponse(
                status_code=401,
                content={"detail": "invalid service signature", "request_id": request_id},
                headers={"X-Request-Id": request_id},
            )
    try:
        response = await call_next(request)
    except Exception:
        logger.exception(
            "[ConnectorHTTP] unhandled request_id=%s method=%s path=%s elapsed_ms=%s",
            request_id,
            request.method,
            request.url.path,
            round((time.monotonic() - started) * 1000, 1),
        )
        raise
    elapsed_ms = round((time.monotonic() - started) * 1000, 1)
    response.headers["X-Request-Id"] = request_id
    logger.info(
        "[ConnectorHTTP] completed request_id=%s method=%s path=%s status=%s elapsed_ms=%s",
        request_id,
        request.method,
        request.url.path,
        response.status_code,
        elapsed_ms,
    )
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
