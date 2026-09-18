"""Aliyun OSS V2 adapter."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
import os
from typing import Any

from config.settings import settings


class StorageError(RuntimeError):
    pass


@dataclass
class ObjectHead:
    size: int | None
    etag: str | None
    content_type: str | None


class AliyunOSSStorage:
    def __init__(self) -> None:
        missing = [name for name, value in {
            "OSS_REGION": settings.OSS_REGION,
            "OSS_ENDPOINT": settings.OSS_ENDPOINT,
            "OSS_BUCKET": settings.OSS_BUCKET,
        }.items() if not value]
        if missing:
            raise StorageError(f"OSS 配置缺失: {', '.join(missing)}")
        try:
            import alibabacloud_oss_v2 as oss
        except ImportError as exc:
            raise StorageError("未安装 alibabacloud-oss-v2") from exc
        self.oss = oss
        if settings.OSS_STS_ROLE_ARN:
            try:
                from alibabacloud_credentials.client import Client as CredentialClient
                from alibabacloud_credentials.models import Config as CredentialConfig

                credential_config = CredentialConfig(
                    access_key_id=settings.OSS_ACCESS_KEY_ID,
                    access_key_secret=settings.OSS_ACCESS_KEY_SECRET,
                    type="ram_role_arn",
                    role_arn=settings.OSS_STS_ROLE_ARN,
                    role_session_name=os.getenv("ALIBABA_CLOUD_ROLE_SESSION_NAME", "fb-ads-oss"),
                    role_session_expiration=settings.OSS_STS_DURATION_SECONDS,
                )
                credential_client = CredentialClient(credential_config)

                def get_credentials():
                    credential = credential_client.get_credential()
                    return oss.credentials.Credentials(
                        access_key_id=credential.access_key_id,
                        access_key_secret=credential.access_key_secret,
                        security_token=credential.security_token,
                    )

                credentials_provider = oss.credentials.CredentialsProviderFunc(get_credentials)
            except ImportError as exc:
                raise StorageError("未安装 alibabacloud-credentials，无法使用 OSS RAM Role/STS") from exc
        else:
            credentials_provider = oss.credentials.StaticCredentialsProvider(
                access_key_id=settings.OSS_ACCESS_KEY_ID,
                access_key_secret=settings.OSS_ACCESS_KEY_SECRET,
            )

        cfg = oss.config.load_default()
        cfg.credentials_provider = credentials_provider
        cfg.region = settings.OSS_REGION
        cfg.endpoint = settings.OSS_ENDPOINT
        self.client = oss.Client(cfg)

    def presign_put(self, key: str, content_type: str | None = None) -> dict[str, Any]:
        request_kwargs: dict[str, Any] = {"bucket": settings.OSS_BUCKET, "key": key}
        if content_type:
            request_kwargs["content_type"] = content_type
        request = self.oss.PutObjectRequest(**request_kwargs)
        result = self.client.presign(request, expires=timedelta(seconds=settings.OSS_UPLOAD_EXPIRE_SECONDS))
        url = getattr(result, "url", None) or getattr(result, "signed_url", None)
        if not url:
            raise StorageError("OSS SDK 未返回上传签名 URL")
        return {"url": url, "method": "PUT", "headers": {"Content-Type": content_type} if content_type else {}}

    def presign_get(self, key: str) -> str:
        request = self.oss.GetObjectRequest(bucket=settings.OSS_BUCKET, key=key)
        result = self.client.presign(request, expires=timedelta(seconds=settings.OSS_DOWNLOAD_EXPIRE_SECONDS))
        url = getattr(result, "url", None) or getattr(result, "signed_url", None)
        if not url:
            raise StorageError("OSS SDK 未返回下载签名 URL")
        return url

    def head(self, key: str) -> ObjectHead:
        result = self.client.head_object(self.oss.HeadObjectRequest(bucket=settings.OSS_BUCKET, key=key))
        return ObjectHead(
            size=getattr(result, "content_length", None),
            etag=getattr(result, "etag", None),
            content_type=getattr(result, "content_type", None),
        )

    def download_url(self, key: str) -> str:
        return self.presign_get(key)

    def put_file(self, key: str, path: str, content_type: str | None = None) -> None:
        request_kwargs: dict[str, Any] = {"bucket": settings.OSS_BUCKET, "key": key}
        if content_type:
            request_kwargs["content_type"] = content_type
        self.client.put_object_from_file(self.oss.PutObjectRequest(**request_kwargs), path)

    def delete(self, key: str) -> None:
        self.client.delete_object(self.oss.DeleteObjectRequest(bucket=settings.OSS_BUCKET, key=key))
