"""Dependency probes with no credentials or exception details in responses."""
from sqlalchemy import text


def dependency_readiness(engine, redis_connection):
    checks = {}
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception:
        checks["database"] = "unavailable"
    try:
        checks["redis"] = "ok" if redis_connection.ping() else "unavailable"
    except Exception:
        checks["redis"] = "unavailable"
    return {"status": "ready" if all(value == "ok" for value in checks.values()) else "not_ready", "checks": checks}
