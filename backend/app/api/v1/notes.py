import uuid
from typing import Any, List
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.database import get_db
from app.api.v1.auth import get_current_active_user
from app.models.auth import User
from app.models.metrics import UserNote
from app.models.knowledge import KnowledgeBase
from app.schemas.notes import NoteCreate, NoteUpdate, NoteResponse, SynthesisRequest

router = APIRouter()

@router.get("", response_model=List[NoteResponse])
async def list_user_notes(
    kb_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
) -> Any:
    """
    List all notes saved by the user in a specific Knowledge Base.
    """
    result = await db.execute(
        select(UserNote)
        .where(
            UserNote.kb_id == kb_id,
            UserNote.user_id == current_user.id
        )
        .order_by(UserNote.created_at.desc())
    )
    return result.scalars().all()


@router.post("", response_model=NoteResponse, status_code=status.HTTP_201_CREATED)
async def create_user_note(
    note_in: NoteCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
) -> Any:
    """
    Create a new note (either scratchpad note or pinned chunk/response).
    """
    # Verify KB exists
    kb_res = await db.execute(select(KnowledgeBase).where(KnowledgeBase.id == note_in.kb_id))
    kb = kb_res.scalar_one_or_none()
    if not kb:
        raise HTTPException(status_code=404, detail="Knowledge base not found.")

    db_note = UserNote(
        user_id=current_user.id,
        kb_id=note_in.kb_id,
        title=note_in.title,
        content=note_in.content
    )
    db.add(db_note)
    await db.commit()
    await db.refresh(db_note)
    return db_note


@router.put("/{note_id}", response_model=NoteResponse)
async def update_user_note(
    note_id: uuid.UUID,
    note_in: NoteUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
) -> Any:
    """
    Update a note's title and/or content.
    """
    result = await db.execute(
        select(UserNote).where(
            UserNote.id == note_id,
            UserNote.user_id == current_user.id
        )
    )
    db_note = result.scalar_one_or_none()
    if not db_note:
        raise HTTPException(status_code=404, detail="Note not found or access denied.")

    if note_in.title is not None:
        db_note.title = note_in.title
    if note_in.content is not None:
        db_note.content = note_in.content

    await db.commit()
    await db.refresh(db_note)
    return db_note


@router.delete("/{note_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user_note(
    note_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    """
    Delete a user note.
    """
    result = await db.execute(
        select(UserNote).where(
            UserNote.id == note_id,
            UserNote.user_id == current_user.id
        )
    )
    db_note = result.scalar_one_or_none()
    if not db_note:
        raise HTTPException(status_code=404, detail="Note not found or access denied.")

    await db.delete(db_note)
    await db.commit()
    from fastapi.responses import Response
    return Response(status_code=204)


@router.post("/synthesize")
async def synthesize_user_notes(
    req: SynthesisRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
) -> Any:
    """
    Combine selected notes and call the LLM to write a synthesized outline/report.
    """
    if not req.note_ids:
        raise HTTPException(status_code=400, detail="No note IDs provided.")

    # Fetch notes and verify ownership
    result = await db.execute(
        select(UserNote).where(
            UserNote.id.in_(req.note_ids),
            UserNote.user_id == current_user.id
        )
    )
    notes = result.scalars().all()
    if not notes:
        raise HTTPException(status_code=404, detail="None of the specified notes could be found.")

    # Format notes content
    combined_content_list = []
    for idx, note in enumerate(notes):
        combined_content_list.append(f"### Note #{idx+1}: {note.title}\n{note.content}")
    combined_content = "\n\n".join(combined_content_list)

    # Prompt details
    synth_format = req.format or "outline"
    system_prompt = (
        f"You are a professional assistant. You will be provided with several user-saved notes. "
        f"Your task is to compile and synthesize these notes into a cohesive, structured document. "
        f"Format the output as a Markdown {synth_format}. Make it detailed, clear, and well-structured, with professional headings, bullet points, and key takeaways."
    )

    import openai
    from app.core.config import settings
    from app.core.logging import logger

    synthesized_text = ""
    if settings.GEMINI_API_KEY or settings.OPENAI_API_KEY:
        try:
            if settings.GEMINI_API_KEY:
                client = openai.AsyncOpenAI(
                    api_key=settings.GEMINI_API_KEY,
                    base_url="https://generativelanguage.googleapis.com/v1beta/openai/"
                )
                model_name = settings.GEMINI_MODEL
            else:
                client = openai.AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
                model_name = "gpt-4o"

            completion = await client.chat.completions.create(
                model=model_name,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": combined_content}
                ],
                temperature=0.3
            )
            synthesized_text = completion.choices[0].message.content
        except Exception as e:
            logger.error(f"Failed to synthesize notes with LLM: {str(e)}")

    if not synthesized_text:
        # Fallback local merger
        synthesized_text = (
            f"# Synthesized Notes Summary ({synth_format.upper()})\n\n"
            f"Here is a combined summary of your selected notes:\n\n"
        )
        for note in notes:
            synthesized_text += f"## {note.title}\n{note.content}\n\n"

    return {"synthesis": synthesized_text}
