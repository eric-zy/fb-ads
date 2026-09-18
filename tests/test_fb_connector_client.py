from services.fb_connector_client import FBConnectorClient


def test_client_builds_signed_request(monkeypatch):
    captured = {}

    class Response:
        status_code = 200

        def json(self):
            return {"ok": True}

    def fake_request(method, url, **kwargs):
        captured.update(method=method, url=url, kwargs=kwargs)
        return Response()

    monkeypatch.setattr("services.fb_connector_client.requests.request", fake_request)
    client = FBConnectorClient(base_url="https://connector.test", signing_key="secret")
    result = client.create_campaign(
        "task-1", "credential-1", "account-1", {"name": "demo"}, idempotency_key="idem-1"
    )
    assert result == {"ok": True}
    assert captured["kwargs"]["headers"]["X-Service-Name"] == "saas"
    assert captured["kwargs"]["headers"]["X-Idempotency-Key"] == "idem-1"
    assert captured["url"].endswith("/internal/meta/campaigns/create")
