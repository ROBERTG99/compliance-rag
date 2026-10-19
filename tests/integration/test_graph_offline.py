"""Graph end to end on real stores, offline (T-25): 10 dev questions and a Postgres-checkpointed follow-up."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

from compliance_rag.auth.personas import persona_principal
from compliance_rag.evals.metrics import norm_values
from compliance_rag.graph.build import GraphDeps, build_graph, run_graph
from compliance_rag.ingest.pipeline import DocumentMeta, IngestDeps, ingest_document, register_upload
from compliance_rag.llm.gateway import Gateway
from compliance_rag.rerank import create_reranker
from compliance_rag.retrieval.hybrid import HybridRetriever
from compliance_rag.settings import Settings
from data.generator.corpus import SEED, build_corpus
from data.generator.render import render_version
from tests.fixtures_services import Database

pytestmark = pytest.mark.integration
ROOT = Path(__file__).resolve().parents[2]


def _dev_rows(n: int) -> list[dict]:
    rows = [
        json.loads(line) for line in (ROOT / "evals/datasets/questions.v1.jsonl").read_text().splitlines()
    ]
    return [r for r in rows if r["split"] == "dev" and r["meta"]["category"] == "single_hop"][:n]


async def _ingest(deps: IngestDeps, document_ids: set[str]) -> None:
    from compliance_rag.embed.lsa import LocalLSAEmbedder

    policies = [p for p in build_corpus(SEED) if p.document_id in document_ids]
    # like `crag seed`: fit the offline embedder on the corpus being indexed
    texts = [
        a.heading + "\n" + "\n".join(a.paragraphs) for p in policies for v in p.versions for a in v.articles
    ]
    deps.embedder = LocalLSAEmbedder(dim=384, seed=2026).fit(texts)
    for policy in policies:
        if policy.document_id not in document_ids:
            continue
        for v in policy.versions:
            meta = DocumentMeta(
                policy.document_id,
                v.version,
                policy.title,
                policy.domain,
                policy.owner,
                date.fromisoformat(v.valid_from),
                v.source_format,
                policy.acl_groups,
            )
            job = await register_upload(deps, meta, render_version(policy, v), "admin")
            await ingest_document(deps, job.job_id)


async def test_ten_dev_questions_answer_offline_with_postgres_checkpointer(
    ingest_deps: IngestDeps, migrated_db: Database
) -> None:
    rows = _dev_rows(10)
    await _ingest(ingest_deps, {g["document_id"] for r in rows for g in r["meta"]["gold"]})
    settings = Settings(_env_file=None)
    retriever = HybridRetriever(ingest_deps.bm25, ingest_deps.pg, ingest_deps.embedder)
    deps = GraphDeps(
        retriever, create_reranker("feature", embedder=ingest_deps.embedder), Gateway(settings), settings
    )
    async with AsyncPostgresSaver.from_conn_string(migrated_db.url) as saver:
        await saver.setup()
        graph = build_graph(deps, saver)
        answered = 0
        failures = []
        for row in rows:
            state = await run_graph(
                graph,
                question=row["input"]["question"],
                principal=persona_principal(row["input"]["persona"]),
                as_of=row["input"]["as_of"],
            )
            if not state["abstained"] and set(row["expected"]["values"]) <= norm_values(
                state["verified"]["answer"]
            ):
                answered += 1
            else:
                from compliance_rag.rerank.feature import extract_features

                top = (state.get("reranked") or [{}])[0]
                feats = extract_features(
                    row["input"]["question"],
                    state.get("reranked", [])[:3],
                    date.fromisoformat(row["input"]["as_of"]),
                )
                failures.append(
                    (
                        row["input"]["question"],
                        state.get("abstain_reason"),
                        top.get("rerank"),
                        top.get("bm25"),
                        top.get("cosine"),
                        feats,
                        top.get("text", "")[:200],
                    )
                )
        assert answered == 10, "\n".join(map(str, failures))

        first = await run_graph(
            graph,
            question=rows[0]["input"]["question"],
            principal=persona_principal(rows[0]["input"]["persona"]),
            as_of="2026-10-16",
        )
        follow = await run_graph(
            graph,
            question="And who owns this policy?",
            principal=persona_principal(rows[0]["input"]["persona"]),
            as_of="2026-10-16",
            conversation_id=first["conversation_id"],
            follow_up_of=first["run_id"],
        )
        assert follow["standalone_question"] != "And who owns this policy?"
        assert len(follow["history"]) == 2  # reloaded from the Postgres checkpoint
