"""司南推广链展示权限回归测试。"""

import asyncio

import pytest
from fastapi import HTTPException

from core.auth import require_permission
from models import User


def test_sinan_read_permission_is_required_for_non_admin():
    dependency = require_permission("sinan:read")
    user = User(
        id="sinan-viewer",
        tenant_id="test_tenant",
        email="sinan-viewer@test.local",
        username="sinan-viewer",
        hashed_password="unused",
        role="user",
        permissions=[],
        is_active=True,
    )

    with pytest.raises(HTTPException) as error:
        asyncio.run(dependency(current_user=user))

    assert error.value.status_code == 403


def test_sinan_read_permission_allows_non_admin():
    dependency = require_permission("sinan:read")
    user = User(
        id="sinan-viewer-with-permission",
        tenant_id="test_tenant",
        email="sinan-viewer-with-permission@test.local",
        username="sinan-viewer-with-permission",
        hashed_password="unused",
        role="user",
        permissions=["sinan:read"],
        is_active=True,
    )

    assert asyncio.run(dependency(current_user=user)) is user
