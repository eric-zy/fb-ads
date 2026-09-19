from types import SimpleNamespace

from services.meta.ad_account_service import AdAccountService


def _account(*, payment_status: str = "UNKNOWN", account_status: str = "ACTIVE"):
    business = SimpleNamespace(
        status="ACTIVE",
        connector_credential_id="connector-credential-1",
    )
    return SimpleNamespace(
        system_status="ACTIVE",
        system_status_reason=None,
        business=business,
        connector_credential_id=None,
        account_status=account_status,
        payment_status=payment_status,
        payment_error_message="账单状态不应阻断投放",
    )


def test_payment_status_is_informational_only():
    service = AdAccountService(None)

    for payment_status in ("UNKNOWN", "MISSING", "PAST_DUE", "RESTRICTED"):
        available, reason = service.check_available(
            _account(payment_status=payment_status),
        )
        assert available is True
        assert reason == "ok"


def test_meta_account_status_still_blocks_deployment():
    available, reason = AdAccountService(None).check_available(
        _account(payment_status="UNKNOWN", account_status="DISABLED"),
    )

    assert available is False
    assert "Meta 侧状态" in reason
