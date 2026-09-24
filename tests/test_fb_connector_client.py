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


def test_client_deploy_campaign_uses_deploy_endpoint(monkeypatch):
    captured = {}

    class Response:
        status_code = 202

        def json(self):
            return {"status": "QUEUED", "connector_task_id": "remote-1"}

    def fake_request(method, url, **kwargs):
        captured.update(method=method, url=url, kwargs=kwargs)
        return Response()

    monkeypatch.setattr("services.fb_connector_client.requests.request", fake_request)
    client = FBConnectorClient(base_url="https://connector.test", signing_key="secret")
    result = client.deploy_campaign(
        {
            "task_id": "task-1",
            "credential_id": "credential-1",
            "account_id": "account-1",
            "campaign": {"name": "demo"},
            "adsets": [],
        },
        idempotency_key="deploy-task-1",
    )

    assert result["status"] == "QUEUED"
    assert captured["method"] == "POST"
    assert captured["url"].endswith("/internal/meta/campaigns/deploy")


def test_client_insights_uses_report_timeout(monkeypatch):
    captured = {}

    class Response:
        status_code = 200
        headers = {}

        def json(self):
            return {"items": []}

    def fake_request(method, url, **kwargs):
        captured.update(method=method, url=url, kwargs=kwargs)
        return Response()

    monkeypatch.setattr("services.fb_connector_client.requests.request", fake_request)
    monkeypatch.setattr("services.fb_connector_client.settings.FB_CONNECTOR_REPORT_TIMEOUT", 301)
    client = FBConnectorClient(base_url="https://connector.test", signing_key="secret")

    assert client.get_insights("act_1", "credential-1") == {"items": []}
    assert captured["kwargs"]["timeout"] == 301
    assert captured["url"].endswith("/internal/meta/reports/insights")


def test_cleanup_client_can_limit_to_orphaned_objects(monkeypatch):
    captured = {}

    class Response:
        status_code = 200

        def json(self):
            return {"status": "SUCCESS"}

    def fake_request(method, url, **kwargs):
        captured.update(method=method, url=url, kwargs=kwargs)
        return Response()

    monkeypatch.setattr("services.fb_connector_client.requests.request", fake_request)
    client = FBConnectorClient(base_url="https://connector.test", signing_key="secret")

    client.cleanup_deployment("remote-1", "credential-1", orphaned_only=True)

    assert captured["url"].endswith("/internal/meta/campaigns/cleanup")
    assert '"orphaned_only":true' in captured["kwargs"]["data"].decode()


def test_client_search_targeting_uses_catalog_endpoint(monkeypatch):
    captured = {}

    class Response:
        status_code = 200

        def json(self):
            return {"data": [{"id": "6001", "name": "Movies"}]}

    def fake_request(method, url, **kwargs):
        captured.update(method=method, url=url, kwargs=kwargs)
        return Response()

    monkeypatch.setattr("services.fb_connector_client.requests.request", fake_request)
    client = FBConnectorClient(base_url="https://connector.test", signing_key="secret")
    result = client.search_targeting(
        "act_1", "credential-1", "adinterest", "movie", locale="en_US", limit=20,
    )

    assert result["data"][0]["id"] == "6001"
    assert captured["url"].endswith("/internal/meta/targeting/search")
    assert '"type":"adinterest"' in captured["kwargs"]["data"].decode()
    assert '"q":"movie"' in captured["kwargs"]["data"].decode()
