"""CLI evaluation runner for RouteGuard-Med."""
from __future__ import annotations

import argparse
import random
from pathlib import Path
from typing import List, Tuple

import pandas as pd

from routeguard_med.agent import RouteGuardAgent
from routeguard_med.config import get_settings
from routeguard_med.data_layer import load_benchmark_csv, load_evidence_jsonl
from routeguard_med.evaluation.metrics import leaderboard, make_eval_row
from routeguard_med.retrieval.hybrid import HybridRetriever
from routeguard_med.routers.heuristic import HeuristicRouter
from routeguard_med.routers.learned import LearnedRouter
from routeguard_med.routers.utility import UtilityRouter


def split_examples(examples, test_fraction: float = 0.3, seed: int = 7) -> Tuple[list, list]:
    if test_fraction <= 0:
        return examples, examples
    rng = random.Random(seed)
    shuffled = list(examples)
    rng.shuffle(shuffled)
    n_test = max(1, int(len(shuffled) * test_fraction))
    test = shuffled[:n_test]
    train = shuffled[n_test:]
    return train, test


def build_routers(names: List[str], train_examples):
    routers = []
    for name in names:
        if name == "heuristic":
            routers.append(HeuristicRouter())
        elif name == "utility":
            routers.append(UtilityRouter())
        elif name == "learned":
            routers.append(LearnedRouter().fit(train_examples))
        else:
            raise ValueError(f"Unsupported router for offline evaluation: {name}")
    return routers


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--benchmark", default=None)
    parser.add_argument("--corpus", default=None)
    parser.add_argument("--routers", default="heuristic,utility,learned")
    parser.add_argument("--out-dir", default=None)
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--test-fraction", type=float, default=0.30, help="Held-out fraction for evaluation; learned router trains on the complement.")
    parser.add_argument("--seed", type=int, default=7)
    args = parser.parse_args()

    settings = get_settings()
    corpus_path = Path(args.corpus or settings.corpus_path)
    benchmark_path = Path(args.benchmark or settings.benchmark_path)
    out_dir = Path(args.out_dir or settings.report_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    evidence = load_evidence_jsonl(corpus_path)
    examples = load_benchmark_csv(benchmark_path)
    train_examples, eval_examples = split_examples(examples, test_fraction=args.test_fraction, seed=args.seed)
    retriever = HybridRetriever(evidence, embedding_model=settings.embedding_model)
    routers = build_routers([x.strip() for x in args.routers.split(",") if x.strip()], train_examples)

    rows = []
    for router in routers:
        agent = RouteGuardAgent(router=router, retriever=retriever, top_k=args.top_k)
        for ex in eval_examples:
            rows.append(make_eval_row(ex, agent.run(ex.query)))

    eval_df = pd.DataFrame([r.model_dump() for r in rows])
    lb = leaderboard(rows)
    eval_df.to_csv(out_dir / "eval_rows.csv", index=False)
    lb.to_csv(out_dir / "leaderboard.csv", index=False)

    md = [
        "# RouteGuard-Med evaluation report",
        "",
        f"Benchmark: `{benchmark_path}`",
        f"Corpus: `{corpus_path}`",
        f"Training examples: {len(train_examples)}",
        f"Held-out evaluation examples: {len(eval_examples)}",
        "",
        "## Leaderboard",
        "",
        lb.to_markdown(index=False),
        "",
    ]
    failure = eval_df.groupby(["router", "failure_mode"]).size().reset_index(name="count").sort_values(["router", "count"], ascending=[True, False])
    md += ["## Failure modes", "", failure.to_markdown(index=False), ""]
    (out_dir / "evaluation_report.md").write_text("\n".join(md), encoding="utf-8")
    print(lb.to_string(index=False))
    print(f"\nWrote reports to {out_dir}")


if __name__ == "__main__":
    main()
