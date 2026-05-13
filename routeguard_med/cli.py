"""RouteGuard-Med command line demo.

Examples:
    python -m routeguard_med.cli route --query "What public evidence exists for UNiD Spine Analyzer?"
    python -m routeguard_med.cli eval
"""
from __future__ import annotations

import argparse
import json

from .agent import RouteGuardAgent
from .config import get_settings
from .data_layer import load_evidence_jsonl
from .retrieval.hybrid import HybridRetriever
from .routers.heuristic import HeuristicRouter
from .routers.utility import UtilityRouter
from .evaluation.evaluate import main as eval_main


def route_query(args) -> None:
    settings = get_settings()
    evidence = load_evidence_jsonl(args.corpus or settings.corpus_path)
    retriever = HybridRetriever(evidence, embedding_model=settings.embedding_model)
    router = UtilityRouter() if args.router == "utility" else HeuristicRouter()
    agent = RouteGuardAgent(router=router, retriever=retriever, top_k=args.top_k)
    result = agent.run(args.query)
    print(json.dumps(result.model_dump(), indent=2, default=str))


def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd", required=True)

    route = sub.add_parser("route")
    route.add_argument("--query", required=True)
    route.add_argument("--router", default="utility", choices=["heuristic", "utility"])
    route.add_argument("--corpus", default=None)
    route.add_argument("--top-k", type=int, default=5)
    route.set_defaults(func=route_query)

    ev = sub.add_parser("eval")
    ev.set_defaults(func=lambda args: eval_main())

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
