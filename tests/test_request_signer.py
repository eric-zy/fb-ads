from services.request_signer import build_signature_headers, verify_request


def test_signature_round_trip():
    body = b'{"task_id":"t-1"}'
    headers = build_signature_headers(
        "test-secret",
        "saas",
        "req-1",
        "POST",
        "/internal/meta/tasks",
        body,
        "idem-1",
        timestamp=1700000000,
    )
    assert verify_request(
        "test-secret",
        headers,
        "POST",
        "/internal/meta/tasks",
        body,
        now=1700000001,
    )


def test_signature_rejects_body_or_timestamp_change():
    headers = build_signature_headers(
        "test-secret",
        "saas",
        "req-1",
        "POST",
        "/internal/meta/tasks",
        b"original",
        timestamp=1700000000,
    )
    assert not verify_request("test-secret", headers, "POST", "/internal/meta/tasks", b"changed", now=1700000001)
    assert not verify_request("test-secret", headers, "POST", "/internal/meta/tasks", b"original", now=1700000401)
