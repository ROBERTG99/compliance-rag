"""Prometheus metrics."""

from __future__ import annotations

from prometheus_client import Counter, Gauge, Histogram

RETRIEVAL_SECONDS = Histogram(
    "crag_retrieval_seconds",
    "Retrieval latency per leg (bm25, vector) and in total (legs + fusion + rerank, label total)",
    ["leg"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.15, 0.2, 0.25, 0.3, 0.5, 1.0, 2.5),
)
TTFT_SECONDS = Histogram(
    "crag_ttft_seconds", "Time to first streamed claim", buckets=(0.05, 0.1, 0.2, 0.3, 0.5, 1, 2, 5, 10)
)
LLM_TOKENS = Counter("crag_llm_tokens_total", "LLM tokens", ["route", "model", "direction"])
LLM_COST = Counter("crag_llm_cost_usd_total", "LLM cost in USD", ["route", "model"])
ABSTENTIONS = Counter("crag_abstentions_total", "Abstained answers", ["reason"])
CLAIMS_REJECTED = Counter(
    "crag_claims_rejected_total", "Claims rejected by citation verification", ["reason"]
)
CLAIMS_VERIFIED = Counter("crag_claims_verified_total", "Claims that passed citation verification")
ACL_POSTCHECK_VIOLATIONS = Counter(
    "crag_acl_postcheck_violations_total",
    "Retrieval hits outside the principal's groups or validity (must stay 0)",
)
INGESTION_LAG = Gauge(
    "crag_ingestion_lag_seconds",
    "Ingestion lag (p95 of recent jobs and age of oldest pending)",
    ["stat"],
    multiprocess_mode="max",  # set by the (single-process) worker; max across processes elsewhere
)
RATELIMIT_BYPASS = Counter(
    "crag_ratelimit_bypass_total", "Requests allowed because the rate limiter was unavailable"
)
ASK_REQUESTS = Counter("crag_ask_requests_total", "Ask requests", ["mode"])
STALE_INDEX_HITS = Counter(
    "crag_stale_index_hits_total",
    "Index hits dropped because Postgres (authoritative ACL/visibility/validity) no longer allows them",
    ["leg"],
)
