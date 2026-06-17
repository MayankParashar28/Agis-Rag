import uuid
from typing import Optional, List
from pydantic import BaseModel, ConfigDict
from datetime import datetime

class NoteBase(BaseModel):
    title: str
    content: str
    kb_id: uuid.UUID

class NoteCreate(NoteBase):
    pass

class NoteUpdate(BaseModel):
    title: Optional[str] = None
    content: Optional[str] = None

class NoteResponse(NoteBase):
    id: uuid.UUID
    user_id: uuid.UUID
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)

class SynthesisRequest(BaseModel):
    note_ids: List[uuid.UUID]
    format: Optional[str] = "outline"  # "outline", "report", or "briefing"
