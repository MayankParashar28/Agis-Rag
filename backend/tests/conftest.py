import os
import sys

import fakeredis
import pytest

os.environ.setdefault("SECRET_KEY", "test-secret")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@pytest.fixture
def sync_redis(monkeypatch):
    """A fresh in-memory Redis behind doc_store (used by hand-off and progress)."""
    from app.services import doc_store
    client = fakeredis.FakeRedis()
    monkeypatch.setattr(doc_store, "_client", client)
    return client


@pytest.fixture
def async_redis(monkeypatch):
    """In-memory async Redis behind app.core.redis_client (used by the cache)."""
    from fakeredis import aioredis
    from app.core import redis_client
    client = aioredis.FakeRedis(decode_responses=True)
    monkeypatch.setattr(redis_client, "redis_client", client)
    return client
