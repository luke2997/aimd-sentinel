"""FastAPI backend for RouteGuard-Med."""
from __future__ import annotations

from fastapi import FastAPI
from pydantic import BaseModel

from routeguard_med.agent import RouteGuardAgent
from routeguard_med.config import get_settings
from routeguard_med.data_layer import load_evidence_jsonl
from routeguard_med.retrieval.hybrid import HybridRetriever
from routeguard_med.routers.heuristic import HeuristicRouter
from routeguard_med.routers.utility import UtilityRouter

app = FastAPI(title="RouteGuard-Med", version="0.1.0")
settings = get_settings()
corpus = load_evidence_jsonl(settings.corpus_path)
retriever = HybridRetriever(corpus, embedding_model=settings.embedding_model)
routers = {
    "heuristic": HeuristicRouter(),
    "utility": UtilityRouter(),
}


class RouteRequest(BaseModel):
    query: str
    router: str = "utility"
    top_k: int = 5


@app.get("/health")
def health():
    return {"ok": True, "corpus_size": len(corpus), "routers": list(routers)}


@app.post("/route")
def route(req: RouteRequest):
    router = routers.get(req.router, routers["utility"])
    agent = RouteGuardAgent(router=router, retriever=retriever, top_k=req.top_k)
    return agent.run(req.query).model_dump()
