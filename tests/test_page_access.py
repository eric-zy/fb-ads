from types import SimpleNamespace

from services.meta.page_access import page_account_access_error


def _page(**overrides):
    values = {
        "connection_id": None,
        "connector_credential_id": "connector-1",
        "tasks": ["ADVERTISE"],
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _account(**overrides):
    values = {
        "connection_id": None,
        "connector_credential_id": None,
        "business": SimpleNamespace(
            connection_id=None,
            connector_credential_id="connector-1",
        ),
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_connector_page_access_does_not_use_removed_credential_relationship():
    assert page_account_access_error(_page(), _account()) is None


def test_connector_page_access_rejects_different_credentials():
    error = page_account_access_error(
        _page(connector_credential_id="connector-page"),
        _account(business=SimpleNamespace(connection_id=None, connector_credential_id="connector-account")),
    )

    assert error == "页面与广告账户不属于同一个 Connector 授权凭据"


def test_account_level_connector_credential_takes_precedence_over_business():
    account = _account(connector_credential_id="connector-account")

    assert page_account_access_error(
        _page(connector_credential_id="connector-account"),
        account,
    ) is None


def test_oauth_page_access_still_uses_connection_id():
    page = _page(connector_credential_id=None, connection_id="connection-1")
    account = _account(
        connector_credential_id=None,
        business=SimpleNamespace(connection_id="connection-1", connector_credential_id=None),
    )

    assert page_account_access_error(page, account) is None


def test_connector_page_access_rejects_expired_page_credential():
    error = page_account_access_error(_page(status="EXPIRED"), _account())

    assert error == "Facebook Page 的 Connector 凭据状态为 EXPIRED，请重新授权或同步"


def test_connector_page_access_rejects_invalid_account_credential():
    account = _account(capabilities={"connector_credential_status": "INVALID"})

    error = page_account_access_error(_page(), account)

    assert error == "广告账户的 Connector 凭据状态为 INVALID，请重新授权或同步"
