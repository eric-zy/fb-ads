"""Read-only SaaS probes: reject SPA HTML 200 and incomplete dependency checks."""
from __future__ import annotations

import argparse
import json
from urllib.error import HTTPError, URLError
from urllib.request import urlopen


def check_endpoint(url: str, *, ready: bool) -> bool:
    try:
        with urlopen(url, timeout=10) as response:
            if response.status != 200 or response.headers.get_content_type() != "application/json":
                return False
            # Health responses are small; don't consume arbitrary proxy pages.
            raw = response.read(65537)
            if len(raw) > 65536:
                return False
            data = json.loads(raw)
        if not isinstance(data, dict):
            return False
        if not ready:
            return data.get("status") == "healthy"
        checks = data.get("checks")
        return (
            data.get("status") == "ready"
            and isinstance(checks, dict)
            and checks.get("database") == "ok"
            and checks.get("redis") == "ok"
            and all(value == "ok" for value in checks.values())
        )
    except (HTTPError, URLError, TimeoutError, OSError, ValueError):
        return False


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("base_url", help="SaaS API or Nginx base URL")
    args = parser.parse_args()
    passed = True
    for path, ready in (("/health", False), ("/ready", True)):
        ok = check_endpoint(args.base_url.rstrip("/") + path, ready=ready)
        print(f"{path}: {'PASS' if ok else 'FAIL (HTTP/JSON/dependency contract)'}")
        passed = passed and ok
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
