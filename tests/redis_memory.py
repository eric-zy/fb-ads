"""Small counter-store fixture for unit tests; no network or production keys."""
from time import monotonic


class MemoryCounterStore:
    def __init__(self):
        self.values = {}
        self.expires = {}

    def get(self, key, default=None):
        if key in self.expires and self.expires[key] <= monotonic():
            self.delete(key)
        return self.values.get(key, default)

    def incr(self, key, amount=1, ttl=None):
        self.values[key] = int(self.get(key, 0)) + amount
        if ttl and key not in self.expires:
            self.expires[key] = monotonic() + ttl
        return self.values[key]

    def delete(self, key):
        self.values.pop(key, None)
        self.expires.pop(key, None)
        return True
