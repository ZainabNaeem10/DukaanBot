"""
DukaanBot AI service.

The request/response models below are the contract with the backend (docs/contract.md).
The pipeline itself lives in pipeline.py:
normalize -> escalation rules -> retrieval (RAG) -> LLM (Groq or Gemini) -> grounding check.
"""
from typing import List, Optional

from fastapi import FastAPI
from pydantic import BaseModel

from . import config, llm, pipeline

app = FastAPI(title="DukaanBot AI service")


class HistoryItem(BaseModel):
    role: str  # "customer" or "bot"
    text: str


class RespondRequest(BaseModel):
    store_id: str
    conversation_id: str
    message: str
    history: List[HistoryItem] = []


class OrderItem(BaseModel):
    sku: str
    size: Optional[str] = None
    color: Optional[str] = None
    qty: int = 1


class Order(BaseModel):
    items: List[OrderItem]
    name: Optional[str] = None
    address: Optional[str] = None
    phone: Optional[str] = None


class RespondResponse(BaseModel):
    reply: str
    language: str  # "en", "ur", "roman_urdu" or "mixed"
    intent: str  # e.g. "product_question", "order", "complaint", "policy", "other"
    escalate: bool
    escalate_reason: Optional[str] = None
    order: Optional[Order] = None
    grounded: bool
    trace: Optional[dict] = None  # how the answer was made (for the evaluation report; backend ignores it)


@app.get("/health")
def health():
    return {"status": "ok", "llm_key_set": llm.available(), "provider": config.LLM_PROVIDER, "model": config.LLM_MODEL,
            "embed_model": config.EMBED_MODEL, "rag_default": config.RAG_DEFAULT,
            "grounding_default": config.GROUNDING_DEFAULT, "last_llm_error": llm.LAST_ERROR}


@app.get("/llm/test")
def llm_test():
    """Makes one tiny live call to the LLM and the embedding API, and reports errors."""
    return llm.check()


@app.post("/respond", response_model=RespondResponse)
def respond(req: RespondRequest, rag: Optional[bool] = None, grounding: Optional[bool] = None):
    """rag=false: plain-LLM baseline (no catalog records). grounding=false: skip the fact check."""
    result = pipeline.respond(
        req.store_id, req.conversation_id, req.message,
        [h.model_dump() for h in req.history], rag=rag, grounding_on=grounding,
    )
    return RespondResponse(**result)


@app.post("/reindex")
def reindex():
    """Reload the catalog files and rebuild the retrieval index (and embeddings)."""
    return pipeline.reindex()
