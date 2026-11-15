import sys
import types
import uuid

import pytest

sys.modules.setdefault("app.services.models", types.SimpleNamespace(get_embedding_model=lambda: None, get_reranker=lambda: None))

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.api.v1 import evaluation, retrieval  # noqa: E402
from app.api.v1.auth import get_current_active_user  # noqa: E402
from app.core.database import get_db  # noqa: E402

KB = str(uuid.uuid4())
ADMIN_ONLY = [
    ("post", "/evaluation/run", {"kb_id": KB}),
    ("post", "/evaluation/golden/run", {"kb_id": KB}),
    ("post", "/evaluation/golden/suggest", {"kb_id": KB}),
    ("get", f"/evaluation/golden/{KB}", None),
    ("get", f"/evaluation/results/{KB}", None),
    ("post", "/retrieval/debug", {"kb_id": KB, "query": "q"}),
]


def _client(role: str) -> TestClient:
    app = FastAPI()
    app.include_router(evaluation.router, prefix="/evaluation")
    app.include_router(retrieval.router, prefix="/retrieval")
    app.dependency_overrides[get_current_active_user] = lambda: types.SimpleNamespace(id=uuid.uuid4(), role=role, is_active=True)

    async def no_db():
        yield None
    app.dependency_overrides[get_db] = no_db
    return TestClient(app)


@pytest.mark.parametrize("method,path,body", ADMIN_ONLY)
def test_members_cannot_use_evaluation_or_retrieval(method, path, body):
    res = getattr(_client("member"), method)(path, **({"json": body} if body else {}))
    assert res.status_code == 403, (path, res.status_code, res.text)
