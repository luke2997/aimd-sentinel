"""Configuration helpers for RouteGuard-Med."""
from __future__ import annotations

import os
from pathlib import Path
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv()

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CORPUS = ROOT / "routeguard_med" / "data" / "sample_evidence.jsonl"
DEFAULT_BENCHMARK = ROOT / "routeguard_med" / "benchmarks" / "routeguard_med_300.csv"
DEFAULT_REPORT_DIR = ROOT / "routeguard_reports"


@dataclass
class Settings:
    corpus_path: Path = Path(os.getenv("ROUTEGUARD_CORPUS", str(DEFAULT_CORPUS)))
    benchmark_path: Path = Path(os.getenv("ROUTEGUARD_BENCHMARK", str(DEFAULT_BENCHMARK)))
    report_dir: Path = Path(os.getenv("ROUTEGUARD_REPORT_DIR", str(DEFAULT_REPORT_DIR)))
    embedding_model: str = os.getenv("ROUTEGUARD_EMBEDDING_MODEL", "BAAI/bge-m3")
    model_provider: str = os.getenv("ROUTEGUARD_MODEL_PROVIDER", "heuristic")
    openai_model: str = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
    openai_api_key: str = os.getenv("OPENAI_API_KEY", "")
    openai_base_url: str = os.getenv("OPENAI_BASE_URL", "")
    ollama_base_url: str = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
    ollama_model: str = os.getenv("OLLAMA_MODEL", "qwen2.5:3b")
    top_k: int = int(os.getenv("ROUTEGUARD_TOP_K", "5"))
    retrieval_weight_bm25: float = float(os.getenv("ROUTEGUARD_WEIGHT_BM25", "0.55"))
    retrieval_weight_dense: float = float(os.getenv("ROUTEGUARD_WEIGHT_DENSE", "0.45"))


def get_settings() -> Settings:
    s = Settings()
    s.report_dir.mkdir(parents=True, exist_ok=True)
    return s
