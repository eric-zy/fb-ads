"""Verify that the domestic Worker consumes tasks through the configured broker."""
from __future__ import annotations

from celery.exceptions import TimeoutError as CeleryTimeoutError

from celery_app import celery_app


def main() -> int:
    # This existing task only prints its own request metadata and returns None.
    # A successful result proves queue consumption and result-backend delivery.
    for attempt in range(1, 4):
        try:
            result = celery_app.send_task("celery_app.debug_task", expires=60)
            result.get(timeout=15, propagate=False)
            if result.state == "SUCCESS":
                result.forget()
                print("celery worker task consumption: PASS")
                return 0
            print(f"celery worker task consumption: attempt {attempt}/3 failed")
        except (CeleryTimeoutError, ConnectionError, OSError) as exc:
            print(f"celery worker task consumption: attempt {attempt}/3 {type(exc).__name__}")
        except Exception as exc:
            # Do not print exception values: a broker URL can contain credentials.
            print(f"celery worker task consumption: attempt {attempt}/3 {type(exc).__name__}")
    print("celery worker task consumption: FAIL")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
