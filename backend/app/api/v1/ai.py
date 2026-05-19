from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import List, Optional

from app.api.deps import get_current_user
from app.models.utenti import Utente
from app.services.ai_engine import ai_engine

router = APIRouter()

class ChatMessage(BaseModel):
    role: str
    content: str

class ChatRequest(BaseModel):
    message: str
    history: Optional[List[ChatMessage]] = None

class ChatResponse(BaseModel):
    reply: str

@router.post("/chat", response_model=ChatResponse, summary="Invia un messaggio a Sentinel Copilot")
async def chat_with_copilot(
    req: ChatRequest,
    current_user: Utente = Depends(get_current_user)
):
    """
    Riceve un messaggio testuale dall'utente e lo inoltra al motore AI,
    mantenendo il contesto della conversazione.
    """
    history_dicts = []
    if req.history:
        history_dicts = [{"role": msg.role, "content": msg.content} for msg in req.history]
        
    reply = await ai_engine.chat(req.message, chat_history=history_dicts)
    return ChatResponse(reply=reply)
