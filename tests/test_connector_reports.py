import asyncio

import pytest
from pydantic import ValidationError

from fb_connector.api.reports import InsightsRequest
from fb_connector.main import request_validation_error


def test_insights_request_accepts_domestic_connector_payload():
    payload = InsightsRequest.model_validate(
        {
            "credential_id": "a" * 32,
            "account_id": "act_123456789",
            "days": 30,
            "level": "campaign",
            "since": "2026-09-01",
            "until": "2026-09-18",
        }
    )

    assert payload.level == "campaign"
    assert payload.since == "2026-09-01"


@pytest.mark.parametrize(
    ("level", "expected"),
    [("ad_set", "adset"), ("ad-set", "adset"), ("ads", "ad")],
)
def test_insights_request_normalizes_legacy_levels(level, expected):
    payload = InsightsRequest.model_validate(
        {"credential_id": "credential-1", "account_id": 123, "level": level}
    )

    assert payload.account_id == "123"
    assert payload.level == expected


def test_insights_request_rejects_reversed_time_range():
    with pytest.raises(ValidationError, match="since 不能晚于 until"):
        InsightsRequest.model_validate(
            {
                "credential_id": "credential-1",
                "account_id": "act_123",
                "since": "2026-09-18",
                "until": "2026-09-01",
            }
        )


def test_validation_error_response_is_json_safe():
    class FakeRequest:
        state = type("State", (), {})()
        headers = {}
        url = type("URL", (), {"path": "/internal/meta/reports/insights"})()

    class FakeError:
        @staticmethod
        def errors():
            return [{
                "type": "value_error",
                "loc": (),
                "input": {},
                "ctx": {"error": ValueError("bad range")},
            }]

    response = asyncio.run(request_validation_error(FakeRequest(), FakeError()))

    assert response.status_code == 422
