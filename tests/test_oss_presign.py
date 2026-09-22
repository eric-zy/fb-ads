from types import SimpleNamespace

from services.storage.aliyun_oss import AliyunOSSStorage


def test_multipart_part_presign_includes_browser_content_type_header(monkeypatch):
    captured = {}

    class FakeUploadPartRequest:
        _attribute_map = {
            "part_number": {"tag": "input", "position": "query"},
        }

        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

    class FakeClient:
        def presign(self, request, expires):
            captured["request"] = request
            captured["expires"] = expires
            return SimpleNamespace(
                url="https://oss.example/part",
                signed_headers={"Content-Type": "application/octet-stream"},
            )

    storage = object.__new__(AliyunOSSStorage)
    storage.oss = SimpleNamespace(UploadPartRequest=FakeUploadPartRequest)
    storage.client = FakeClient()
    monkeypatch.setattr("services.storage.aliyun_oss.settings.OSS_BUCKET", "bucket")

    result = storage.presign_upload_part("video.mp4", "upload-1", 1)

    request = captured["request"]
    assert request.content_type == "application/octet-stream"
    assert request._attribute_map["content_type"] == {
        "tag": "input",
        "position": "header",
        "rename": "Content-Type",
    }
    assert result["headers"] == {"Content-Type": "application/octet-stream"}
