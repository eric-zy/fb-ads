import asyncio

from fb_connector.api import assets


def test_connector_lists_audience_metadata_without_member_data(monkeypatch):
    class FakeClient:
        def get_custom_audiences(self, account_id):
            assert account_id == "act_123"
            return [{"id": "aud_1", "name": "Existing customers", "subtype": "CUSTOM"}]

    monkeypatch.setattr(assets, "_client", lambda credential_id: FakeClient())

    result = asyncio.run(
        assets.list_custom_audiences(
            assets.AudienceListRequest(credential_id="credential-1", account_id="act_123")
        )
    )

    assert result == {
        "account_id": "act_123",
        "audiences": [{"id": "aud_1", "name": "Existing customers", "subtype": "CUSTOM"}],
    }
