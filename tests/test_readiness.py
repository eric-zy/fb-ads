from unittest.mock import Mock
from sqlalchemy import create_engine
from services.readiness import dependency_readiness


def test_readiness_requires_database_and_redis():
    engine = create_engine("sqlite://")
    redis = Mock()
    redis.ping.return_value = True
    assert dependency_readiness(engine, redis)["status"] == "ready"
    redis.ping.side_effect = ConnectionError("private redis endpoint")
    result = dependency_readiness(engine, redis)
    assert result == {"status": "not_ready", "checks": {"database": "ok", "redis": "unavailable"}}
    broken = Mock()
    broken.connect.side_effect = ConnectionError("database-password")
    result = dependency_readiness(broken, redis)
    assert result["checks"]["database"] == "unavailable"
    assert "password" not in str(result)
    engine.dispose()
