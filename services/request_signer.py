"""SaaS 与 FB Connector 的服务间请求签名。

签名内容固定为：HTTP 方法、请求路径、时间戳、请求体 SHA256 摘要和幂等键。
不把 Token 或签名密钥放入 URL，也不记录完整请求头。
"""

from __future__ import annotations

import hashlib
import hmac
import time
from typing import Mapping


SIGNATURE_HEADER = "X-Signature"
TIMESTAMP_HEADER = "X-Timestamp"
REQUEST_ID_HEADER = "X-Request-Id"
IDEMPOTENCY_HEADER = "X-Idempotency-Key"
SERVICE_HEADER = "X-Service-Name"


def body_digest(body: bytes = b"") -> str:
    return hashlib.sha256(body or b"").hexdigest()


def canonical_string(
    method: str,
    path: str,
    timestamp: str,
    body: bytes = b"",
    idempotency_key: str = "",
) -> str:
    return "\n".join(
        [
            method.upper(),
            path,
            str(timestamp),
            body_digest(body),
            idempotency_key or "",
        ]
    )


def sign_request(
    secret: str,
    method: str,
    path: str,
    timestamp: str | int,
    body: bytes = b"",
    idempotency_key: str = "",
) -> str:
    if not secret:
        raise ValueError("服务间签名密钥不能为空")
    message = canonical_string(method, path, str(timestamp), body, idempotency_key)
    return hmac.new(secret.encode("utf-8"), message.encode("utf-8"), hashlib.sha256).hexdigest()


def verify_request(
    secret: str,
    headers: Mapping[str, str],
    method: str,
    path: str,
    body: bytes = b"",
    max_age_seconds: int = 300,
    now: int | None = None,
) -> bool:
    if not secret:
        return False
    timestamp = headers.get(TIMESTAMP_HEADER, "")
    signature = headers.get(SIGNATURE_HEADER, "")
    if not timestamp or not signature:
        return False
    try:
        timestamp_int = int(timestamp)
    except (TypeError, ValueError):
        return False
    current = int(time.time()) if now is None else now
    if abs(current - timestamp_int) > max_age_seconds:
        return False
    expected = sign_request(
        secret,
        method,
        path,
        timestamp,
        body,
        headers.get(IDEMPOTENCY_HEADER, ""),
    )
    return hmac.compare_digest(expected, signature)


def build_signature_headers(
    secret: str,
    service_name: str,
    request_id: str,
    method: str,
    path: str,
    body: bytes = b"",
    idempotency_key: str = "",
    timestamp: int | None = None,
) -> dict[str, str]:
    ts = int(time.time()) if timestamp is None else timestamp
    headers = {
        SERVICE_HEADER: service_name,
        REQUEST_ID_HEADER: request_id,
        TIMESTAMP_HEADER: str(ts),
        IDEMPOTENCY_HEADER: idempotency_key,
    }
    headers[SIGNATURE_HEADER] = sign_request(secret, method, path, ts, body, idempotency_key)
    return headers
