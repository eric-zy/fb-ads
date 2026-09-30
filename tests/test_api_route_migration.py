"""新接口迁移回归测试。

旧接口已删除，不保留 410/转发兼容层；此测试防止后续把旧入口误加回主应用。
"""

from main import app


LEGACY_ROUTES = {
    "/api/v1/accounts/{account_id}/sync-campaigns",
    "/api/v1/tasks/fetch-insights",
    "/api/v1/tasks/generate-report",
    "/api/v1/campaigns/batch-publish",
    "/api/v1/campaigns/{campaign_id}/pause",
    "/api/v1/campaigns/{campaign_id}/resume",
}

NEW_ROUTES = {
    "/api/v1/accounts/{account_pk}/sync",
    "/api/v1/tasks/{task_id}",
    "/api/v1/campaigns/actions",
    "/api/v1/delivery-actions",
    "/api/v1/jobs/campaign-create",
}


def test_only_new_api_contract_is_registered():
    registered = {
        route.path for route in app.routes if getattr(route, "path", None)
    }

    assert not registered.intersection(LEGACY_ROUTES)
    assert NEW_ROUTES.issubset(registered)
