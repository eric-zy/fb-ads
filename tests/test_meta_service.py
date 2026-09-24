from services.meta.service import MetaAdsService


class FakeMetaClient:
    def __init__(self):
        self.posted = None

    @staticmethod
    def normalize_account_id(account_id):
        return account_id

    @staticmethod
    def resolve_targeting_locales(targeting):
        return targeting

    def _post(self, path, params):
        self.posted = (path, params)
        return {"id": "adset-1"}


def test_create_adset_strips_internal_audience_metadata_before_meta_request():
    client = FakeMetaClient()
    service = MetaAdsService(client, enable_rate_limit=False)
    targeting = {
        "geo_locations": {"countries": ["US"]},
        "custom_audiences": [{"id": "include-1", "ad_account_id": "local-account"}],
        "excluded_custom_audiences": [{"id": "exclude-1", "resolution": "POLICY"}],
    }

    service.create_adset(
        "act_1",
        {"campaign_id": "campaign-1", "targeting": targeting},
    )

    assert client.posted[1]["targeting"] == {
        "geo_locations": {"countries": ["US"]},
        "custom_audiences": [{"id": "include-1"}],
        "excluded_custom_audiences": [{"id": "exclude-1"}],
    }
    assert targeting["custom_audiences"][0]["ad_account_id"] == "local-account"


def test_create_adset_rejects_unresolved_audience_before_meta_request():
    client = FakeMetaClient()
    service = MetaAdsService(client, enable_rate_limit=False)

    try:
        service.create_adset(
            "act_1",
            {
                "campaign_id": "campaign-1",
                "targeting": {
                    "excluded_custom_audiences": [
                        {"id": "audience-1", "resolution": "UNRESOLVED"}
                    ]
                },
            },
        )
    except Exception as exc:
        assert "尚未解析" in str(exc)
    else:
        raise AssertionError("未解析受众必须在 Meta 请求前失败")

    assert client.posted is None
