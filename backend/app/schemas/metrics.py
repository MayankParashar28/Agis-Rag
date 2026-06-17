import uuid
from typing import Optional
from pydantic import BaseModel, ConfigDict
from datetime import datetime

class QueryLogBase(BaseModel):
    query: str
    latency: float
    embedding_latency: Optional[float] = None
    retrieval_latency: Optional[float] = None
    hallucination_rate: Optional[float] = None
    retrieval_score: Optional[float] = None

class QueryLogResponse(QueryLogBase):
    id: uuid.UUID
    user_id: Optional[uuid.UUID] = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)

class AnalyticsDashboardResponse(BaseModel):
    total_users: int
    total_documents: int
    total_chunks: int
    total_queries: int
    average_latency: float
    average_retrieval_score: float
    average_context_precision: Optional[float] = None
    average_context_recall: Optional[float] = None
    average_answer_relevancy: Optional[float] = None
    average_hallucination_rate: Optional[float] = None
    average_faithfulness: Optional[float] = None
    user_satisfaction_rate: Optional[float] = None


class RagasEvaluationBase(BaseModel):
    kb_id: uuid.UUID

class RagasEvaluationResponse(BaseModel):
    id: uuid.UUID
    kb_id: uuid.UUID
    faithfulness: Optional[float] = None
    context_precision: Optional[float] = None
    context_recall: Optional[float] = None
    answer_relevancy: Optional[float] = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
