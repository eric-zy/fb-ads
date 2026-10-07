"""Bound persisted idempotency keys without discarding their distinguishing suffix."""
import hashlib


def bounded_idempotency_key(value: str, max_length: int = 128) -> str:
    # Preserve existing short keys so already queued requests remain replayable.
    if len(value) <= max_length:
        return value
    return "sha256:" + hashlib.sha256(value.encode("utf-8")).hexdigest()
