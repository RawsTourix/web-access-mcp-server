"""Redis lifecycle adapters."""

from web_access.infrastructure.redis.client import RedisDependency, create_redis_dependency

__all__ = ["RedisDependency", "create_redis_dependency"]
