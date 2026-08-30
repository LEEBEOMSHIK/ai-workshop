import hashlib
import json
import math
from asyncio import to_thread
from pathlib import Path
from uuid import UUID, uuid4

import psycopg
import pytest
from alembic.config import Config
from psycopg import sql
from sqlalchemy import make_url

from ai_workshop.config import get_settings
from ai_workshop.labs.rag.configurations.domain import (
    BM25_BASELINE_CONFIGURATION_VERSION_ID,
)
from ai_workshop.labs.rag.evaluation.domain import EvaluationDataset, load_evaluation_dataset
from alembic import command

pytestmark = pytest.mark.integration

BACKEND_ROOT = Path(__file__).resolve().parents[2]
REVISION_0009 = "0009_rag_configurations"
REVISION_0010 = "0010_rag_evaluation"
BGE_MODEL_ID = UUID("00000000-0000-0000-0000-000000000102")
BGE_INDEXING_PROFILE_ID = UUID("00000000-0000-0000-0000-000000000204")
BGE_RETRIEVAL_PROFILE_ID = UUID("00000000-0000-0000-0000-000000000205")
FIXTURE_PATH = BACKEND_ROOT.parent / "sample-data/public/rag/evaluation/search-v1.json"


def _database_url(base_url: str, database: str) -> str:
    return make_url(base_url).set(database=database).render_as_string(hide_password=False)


def _sync_url(database_url: str) -> str:
    return database_url.replace("postgresql+psycopg://", "postgresql://", 1)


def _create_database(base_url: str, database: str) -> None:
    administrative = _database_url(base_url, "postgres")
    with psycopg.connect(_sync_url(administrative), autocommit=True) as connection:
        connection.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database)))


def _drop_database(base_url: str, database: str) -> None:
    administrative = _database_url(base_url, "postgres")
    with psycopg.connect(_sync_url(administrative), autocommit=True) as connection:
        connection.execute(
            sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(database))
        )


def _raw_observations(raw_case: dict[str, object]) -> str:
    expected = raw_case["expected"]
    assert isinstance(expected, dict)
    evidence_ids = expected["evidence_unit_ids"]
    assert isinstance(evidence_ids, list)
    answer_status = expected["answer_status"]
    answer_ids = evidence_ids if answer_status == "supported" else []
    highlight = expected["highlight"]
    highlights = []
    highlight_kind = None
    highlight_spans: list[object] = []
    highlight_bboxes: list[object] = []
    if isinstance(highlight, dict):
        highlight_kind = highlight["kind"]
        highlight_spans = highlight["spans"]  # type: ignore[assignment]
        highlight_bboxes = highlight["bboxes"]  # type: ignore[assignment]
        highlights = [highlight]
    observation = {
        "retrieved_evidence_ids": evidence_ids,
        "retrieved_ranked": [
            {"rank": rank, "evidence_id": evidence_id}
            for rank, evidence_id in enumerate(evidence_ids, start=1)
        ],
        "answer_status": answer_status,
        "answer_evidence_ids": answer_ids,
        "conflict_evidence_ids": (
            evidence_ids if answer_status == "conflicting_evidence" else []
        ),
        "related_evidence_ids": [],
        "highlight_kind": highlight_kind,
        "highlight_spans": highlight_spans,
        "highlight_bboxes": highlight_bboxes,
        "highlights": highlights,
        "exposures": [
            {"surface": "case_output", "source_id": evidence_id}
            for evidence_id in evidence_ids
        ],
        "duration_ms": 10,
        "repetition_signature_sha256": "a" * 64,
    }
    return json.dumps([observation, observation])


def _insert_incomplete_dataset(
    connection: psycopg.Connection[tuple[object, ...]], owner_id: UUID
) -> tuple[UUID, EvaluationDataset]:
    fixture = json.loads(FIXTURE_PATH.read_bytes())
    fixture["id"] = str(uuid4())
    fixture["name"] = "incomplete-direct-sql"
    fixture["version"] = 2
    fixture_bytes = json.dumps(
        fixture, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode()
    dataset = load_evaluation_dataset(fixture_bytes)
    dataset_id = uuid4()
    connection.execute(
        """
        INSERT INTO rag_evaluation_datasets (
            owner_id, name, version, fixture_bytes, fixture_sha256,
            document_snapshot, document_snapshot_bytes,
            document_snapshot_sha256, query_set_bytes,
            query_set_sha256, case_count, id
        ) VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s, %s, %s, %s)
        """,
        (
            owner_id,
            dataset.name,
            dataset.version,
            fixture_bytes,
            dataset.fixture_sha256,
            json.dumps(fixture["document_snapshot"]),
            dataset.document_snapshot_bytes,
            dataset.document_snapshot_sha256,
            dataset.query_set_bytes,
            dataset.query_set_sha256,
            len(dataset.cases),
            dataset_id,
        ),
    )
    return dataset_id, dataset


def _seed_qualifying_evidence(database_url: str) -> tuple[UUID, UUID]:
    owner_id = uuid4()
    dataset_id = uuid4()
    policy_id = uuid4()
    run_id = uuid4()
    candidate_id = uuid4()
    email = f"evaluation-{owner_id}@example.test"
    fixture_bytes = FIXTURE_PATH.read_bytes()
    dataset = load_evaluation_dataset(fixture_bytes)
    fixture = json.loads(fixture_bytes)
    with psycopg.connect(_sync_url(database_url)) as connection:
        connection.execute(
            """
            INSERT INTO users (
                display_name, email, normalized_email, password_hash,
                role, is_active, id
            ) VALUES ('Evaluation Owner', %s, %s, 'fixture-hash', 'owner', true, %s)
            """,
            (email, email, owner_id),
        )
        connection.execute(
            """
            INSERT INTO rag_evaluation_datasets (
                owner_id, name, version, fixture_bytes, fixture_sha256,
                document_snapshot, document_snapshot_bytes,
                document_snapshot_sha256, query_set_bytes,
                query_set_sha256, case_count, id
            ) VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s, %s, %s, %s)
            """,
            (
                owner_id,
                dataset.name,
                dataset.version,
                fixture_bytes,
                dataset.fixture_sha256,
                json.dumps(fixture["document_snapshot"]),
                dataset.document_snapshot_bytes,
                dataset.document_snapshot_sha256,
                dataset.query_set_bytes,
                dataset.query_set_sha256,
                len(dataset.cases),
                dataset_id,
            ),
        )
        for ordinal, raw_case in enumerate(fixture["cases"]):
            canonical = json.dumps(
                raw_case,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
            scenario = raw_case["permission_scenario"]
            expected = raw_case["expected"]
            connection.execute(
                """
                INSERT INTO rag_evaluation_dataset_cases (
                    dataset_snapshot_id, ordinal, canonical_case_bytes,
                    canonical_case_sha256, query_bytes, query_sha256,
                    permission_scenario, expected_evidence_ids,
                    authorized_source_ids, forbidden_source_ids,
                    expected_highlight, id
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb,
                    %s::jsonb, %s::jsonb, %s::jsonb, %s
                )
                """,
                (
                    dataset_id,
                    ordinal,
                    canonical,
                    hashlib.sha256(canonical).hexdigest(),
                    raw_case["query"].encode(),
                    raw_case["query_sha256"],
                    json.dumps(scenario),
                    json.dumps(expected["evidence_unit_ids"]),
                    json.dumps(scenario["authorized_source_ids"]),
                    json.dumps(scenario["forbidden_source_ids"]),
                    json.dumps(expected["highlight"]),
                    UUID(raw_case["id"]),
                ),
            )
        connection.execute(
            """
            INSERT INTO rag_evaluation_policies (
                owner_id, dataset_snapshot_id, version,
                metric_definition_version, retrieval_k,
                min_recall_at_k, min_mrr, min_ndcg,
                min_supported_precision, max_false_grounding_rate,
                min_highlight_iou, max_p50_latency_ms, max_p95_latency_ms,
                max_access_leaks, required_reproducibility, id
            ) VALUES (%s, %s, 1, 1, 10, 0.5, 0.4, 0.5, 0.8, 0.2,
                      0.6, 500, 1000, 0, 1.0, %s)
            """,
            (owner_id, dataset_id, policy_id),
        )
        connection.execute(
            """
            INSERT INTO rag_evaluation_runs (
                owner_id, dataset_snapshot_id, evaluation_policy_version_id,
                status, fixture_sha256, document_snapshot_sha256,
                query_set_sha256, execution_snapshot,
                execution_snapshot_bytes, execution_snapshot_sha256,
                runtime_environment,
                worker_runtime_environment, metric_definition_version,
                retrieval_k, repetition_count, candidate_count, finished_at, id
            ) VALUES (%s, %s, %s, 'completed', %s, %s, %s,
                      '{}'::jsonb, '{}'::bytea,
                      '44136fa355b3678a1146ad16f7e8649e'
                          || '94fb4fc21fe77e8310c060f61caaff8a',
                      '{"python":"3.13","runtime":"test"}'::jsonb,
                      '{"revision":"test-worker"}'::jsonb,
                      1, 10, 2, 1, now(), %s)
            """,
            (
                owner_id,
                dataset_id,
                policy_id,
                dataset.fixture_sha256,
                dataset.document_snapshot_sha256,
                dataset.query_set_sha256,
                run_id,
            ),
        )
        connection.execute(
            """
            INSERT INTO rag_evaluation_run_configurations (
                run_id, configuration_version_id, ordinal,
                indexing_profile_id, retrieval_profile_id,
                answer_policy_version_id, generation_profile_id,
                component_snapshot, status, failure,
                recall_at_k, mrr, ndcg, supported_precision,
                false_grounding_rate, highlight_iou,
                p50_latency_ms, p95_latency_ms,
                access_leaks, reproducibility, completed_at, id
            )
            SELECT %s, version.id, 0,
                   version.indexing_profile_id, version.retrieval_profile_id,
                   version.answer_policy_version_id, version.generation_profile_id,
                   '{"models":[],"execution_snapshot_sha256":"44136fa355b3678a1146ad16f7e8649e94fb4fc21fe77e8310c060f61caaff8a"}'::jsonb,
                   'pending', NULL,
                   NULL, NULL, NULL, NULL, NULL, NULL,
                   NULL, NULL, NULL, NULL, NULL, %s
            FROM rag_configuration_versions AS version
            WHERE version.id = %s
            """,
            (run_id, candidate_id, BM25_BASELINE_CONFIGURATION_VERSION_ID),
        )
        for ordinal, raw_case in enumerate(fixture["cases"]):
            expected = raw_case["expected"]
            supported = expected["answer_status"] == "supported"
            connection.execute(
                """
                INSERT INTO rag_evaluation_case_results (
                    run_configuration_id, dataset_snapshot_id,
                    evaluation_case_id, ordinal,
                    query_sha256, permission_scenario, expected_evidence_ids,
                    raw_observations, duration_ms, recall_at_k, reciprocal_rank,
                    ndcg, correct_supported, false_grounding, highlight_iou,
                    access_leaks, reproducible, id
                ) VALUES (
                    %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb,
                    %s::jsonb,
                    20, %s, %s, %s, %s, %s, %s, 0, true, %s
                )
                """,
                (
                    candidate_id,
                    dataset_id,
                    UUID(raw_case["id"]),
                    ordinal,
                    raw_case["query_sha256"],
                    json.dumps(raw_case["permission_scenario"]),
                    json.dumps(expected["evidence_unit_ids"]),
                    _raw_observations(raw_case),
                    1.0 if expected["evidence_unit_ids"] else None,
                    1.0 if expected["evidence_unit_ids"] else None,
                    1.0 if expected["evidence_unit_ids"] else None,
                    supported if supported else None,
                    False if supported else None,
                    1.0 if expected["highlight"] else None,
                    uuid4(),
                ),
            )
        connection.execute(
            """
            UPDATE rag_evaluation_run_configurations
               SET status = 'completed', completed_at = now()
             WHERE id = %s
            """,
            (candidate_id,),
        )
    return owner_id, policy_id


@pytest.mark.asyncio
async def test_0010_migrates_forward_and_database_promotion_is_evidence_backed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    base_settings = get_settings()
    database = f"ai_workshop_t11_migration_{uuid4().hex}"
    caller_bge_configuration_id = uuid4()
    caller_bge_policy_id = uuid4()
    caller_bge_version_id = uuid4()
    shared_bge_profile_id = uuid4()
    shared_bge_binding_id = uuid4()
    isolated_url = _database_url(base_settings.database_url, database)
    _create_database(base_settings.database_url, database)
    try:
        with monkeypatch.context() as environment:
            environment.setenv("AI_WORKSHOP_DATABASE_URL", isolated_url)
            get_settings.cache_clear()
            config = Config(str(BACKEND_ROOT / "alembic.ini"))
            await to_thread(command.upgrade, config, REVISION_0009)
            await to_thread(command.upgrade, config, REVISION_0010)

            with psycopg.connect(_sync_url(isolated_url), autocommit=True) as connection:
                with pytest.raises(psycopg.errors.RaiseException, match="qualifying"):
                    connection.execute(
                        """
                        UPDATE rag_configuration_versions
                        SET evaluation_state = 'passed', is_default = true
                        WHERE id = %s
                        """,
                        (BM25_BASELINE_CONFIGURATION_VERSION_ID,),
                    )

                inserted_configuration_id = uuid4()
                inserted_policy_id = uuid4()
                connection.execute(
                    """
                    INSERT INTO rag_configurations (name, is_system, id)
                    VALUES ('direct insert gate fixture', true, %s)
                    """,
                    (inserted_configuration_id,),
                )
                connection.execute(
                    """
                    INSERT INTO rag_answer_policy_versions (
                        configuration_id, version, mode, min_semantic_score,
                        min_keyword_coverage, require_complete_provenance,
                        conflict_mode, id
                    )
                    SELECT %s, 1, mode, min_semantic_score,
                           min_keyword_coverage, require_complete_provenance,
                           conflict_mode, %s
                      FROM rag_answer_policy_versions
                     WHERE configuration_id = (
                         SELECT configuration_id
                           FROM rag_configuration_versions
                          WHERE id = %s
                     )
                    """,
                    (
                        inserted_configuration_id,
                        inserted_policy_id,
                        BM25_BASELINE_CONFIGURATION_VERSION_ID,
                    ),
                )
                with pytest.raises(psycopg.errors.RaiseException, match="qualifying"):
                    connection.execute(
                        """
                        INSERT INTO rag_configuration_versions (
                            configuration_id, version, indexing_profile_id,
                            retrieval_profile_id, generation_profile_id,
                            answer_policy_version_id, evaluation_state,
                            is_default, id
                        )
                        SELECT %s, 1, indexing_profile_id, retrieval_profile_id,
                               NULL, %s, 'passed', true, %s
                          FROM rag_configuration_versions
                         WHERE id = %s
                        """,
                        (
                            inserted_configuration_id,
                            inserted_policy_id,
                            uuid4(),
                            BM25_BASELINE_CONFIGURATION_VERSION_ID,
                        ),
                    )
                connection.execute(
                    """
                    INSERT INTO rag_configuration_versions (
                        configuration_id, version, indexing_profile_id,
                        retrieval_profile_id, generation_profile_id,
                        answer_policy_version_id, evaluation_state,
                        is_default, id
                    )
                    SELECT %s, 1, indexing_profile_id, retrieval_profile_id,
                           NULL, %s, 'pending', false, %s
                      FROM rag_configuration_versions
                     WHERE id = %s
                    """,
                    (
                        inserted_configuration_id,
                        inserted_policy_id,
                        uuid4(),
                        BM25_BASELINE_CONFIGURATION_VERSION_ID,
                    ),
                )

                assert connection.execute(
                    "SELECT count(*) FROM rag_configurations"
                ).fetchone() == (2,)
                assert connection.execute(
                    "SELECT count(*) FROM rag_configurations WHERE name ILIKE '%bge%'"
                ).fetchone() == (0,)
                bge = connection.execute(
                    """
                    SELECT model.config, indexing.config, retrieval.config
                    FROM rag_model_definitions AS model
                    JOIN rag_profile_model_bindings AS binding
                      ON binding.model_id = model.id
                    JOIN rag_profiles AS indexing ON indexing.id = binding.profile_id
                    JOIN rag_profiles AS retrieval
                      ON retrieval.id = %s
                    WHERE model.id = %s AND indexing.id = %s
                    """,
                    (BGE_RETRIEVAL_PROFILE_ID, BGE_MODEL_ID, BGE_INDEXING_PROFILE_ID),
                ).fetchone()
                assert bge is not None
                assert bge[0]["revision"] == "5617a9f61b028005a4858fdac845db406aefb181"
                assert bge[0]["dimension"] == 1024
                assert bge[0]["max_tokens"] == 8192
                assert bge[0]["output_mode"] == "dense"
                assert bge[0]["sparse_enabled"] is False
                assert bge[0]["colbert_enabled"] is False
                assert bge[2]["indexing_profile_id"] == str(BGE_INDEXING_PROFILE_ID)

                connection.execute(
                    """
                    INSERT INTO rag_profiles (
                        kind, name, version, config, evaluation_state,
                        is_default, id
                    )
                    SELECT kind, 'caller shared BGE consumer', 1, config,
                           'draft', false, %s
                      FROM rag_profiles WHERE id = %s
                    """,
                    (shared_bge_profile_id, BGE_INDEXING_PROFILE_ID),
                )
                connection.execute(
                    """
                    INSERT INTO rag_profile_model_bindings (
                        profile_id, role, model_id, id
                    ) VALUES (%s, 'embedding', %s, %s)
                    """,
                    (shared_bge_profile_id, BGE_MODEL_ID, shared_bge_binding_id),
                )

                await to_thread(command.downgrade, config, REVISION_0009)
                with psycopg.connect(
                    _sync_url(isolated_url), autocommit=True
                ) as connection:
                    assert connection.execute(
                        "SELECT count(*) FROM rag_profiles WHERE id IN (%s, %s)",
                        (BGE_INDEXING_PROFILE_ID, BGE_RETRIEVAL_PROFILE_ID),
                    ).fetchone() == (0,)
                    assert connection.execute(
                        "SELECT count(*) FROM rag_model_definitions WHERE id = %s",
                        (BGE_MODEL_ID,),
                    ).fetchone() == (1,)
                    assert connection.execute(
                        """
                        SELECT count(*) FROM rag_profile_model_bindings
                         WHERE id = %s AND profile_id = %s AND model_id = %s
                        """,
                        (shared_bge_binding_id, shared_bge_profile_id, BGE_MODEL_ID),
                    ).fetchone() == (1,)
                    connection.execute(
                        "DELETE FROM rag_profiles WHERE id = %s",
                        (shared_bge_profile_id,),
                    )
                    connection.execute(
                        "DELETE FROM rag_model_definitions WHERE id = %s",
                        (BGE_MODEL_ID,),
                    )
                await to_thread(command.upgrade, config, REVISION_0010)
                await to_thread(command.downgrade, config, REVISION_0009)
                with psycopg.connect(
                    _sync_url(isolated_url), autocommit=True
                ) as connection:
                    assert connection.execute(
                        "SELECT count(*) FROM rag_profiles WHERE id IN (%s, %s)",
                        (BGE_INDEXING_PROFILE_ID, BGE_RETRIEVAL_PROFILE_ID),
                    ).fetchone() == (0,)
                    assert connection.execute(
                        "SELECT count(*) FROM rag_model_definitions WHERE id = %s",
                        (BGE_MODEL_ID,),
                    ).fetchone() == (0,)
                await to_thread(command.upgrade, config, REVISION_0010)

                owner_id, policy_id = _seed_qualifying_evidence(isolated_url)
            with psycopg.connect(_sync_url(isolated_url), autocommit=True) as connection:
                dataset_id = connection.execute(
                    "SELECT dataset_snapshot_id FROM rag_evaluation_policies WHERE id = %s",
                    (policy_id,),
                ).fetchone()[0]
                incomplete_id, incomplete = _insert_incomplete_dataset(
                    connection, owner_id
                )
                with pytest.raises(psycopg.errors.RaiseException, match="incomplete"):
                    connection.execute(
                        """
                        INSERT INTO rag_evaluation_runs (
                            owner_id, dataset_snapshot_id,
                            evaluation_policy_version_id, status,
                            fixture_sha256, document_snapshot_sha256,
                            query_set_sha256, execution_snapshot,
                            execution_snapshot_bytes, execution_snapshot_sha256,
                            runtime_environment,
                            metric_definition_version, retrieval_k,
                            repetition_count, candidate_count, id
                        ) VALUES (%s, %s, NULL, 'pending', %s, %s, %s,
                                  '{}'::jsonb, '{}'::bytea,
                                  '44136fa355b3678a1146ad16f7e8649e'
                                      || '94fb4fc21fe77e8310c060f61caaff8a',
                                  '{}'::jsonb, 1, 10, 2, 1, %s)
                        """,
                        (
                            owner_id,
                            incomplete_id,
                            incomplete.fixture_sha256,
                            incomplete.document_snapshot_sha256,
                            incomplete.query_set_sha256,
                            uuid4(),
                        ),
                    )
                with pytest.raises(psycopg.errors.RaiseException, match="immutable"):
                    connection.execute(
                        "UPDATE rag_evaluation_datasets SET fixture_sha256 = %s "
                        "WHERE id = %s",
                        ("0" * 64, dataset_id),
                    )
                invalid_fixture = b"not-json"
                empty_json = b"[]"
                with pytest.raises(psycopg.errors.RaiseException, match="UTF-8 JSON"):
                    connection.execute(
                        """
                        INSERT INTO rag_evaluation_datasets (
                            owner_id, name, version, fixture_bytes, fixture_sha256,
                            document_snapshot, document_snapshot_bytes,
                            document_snapshot_sha256, query_set_bytes,
                            query_set_sha256, case_count, id
                        ) VALUES (%s, 'invalid-json', 1, %s, %s, '[]'::jsonb,
                                  %s, %s, %s, %s, 1, %s)
                        """,
                        (
                            owner_id,
                            invalid_fixture,
                            hashlib.sha256(invalid_fixture).hexdigest(),
                            empty_json,
                            hashlib.sha256(empty_json).hexdigest(),
                            empty_json,
                            hashlib.sha256(empty_json).hexdigest(),
                            uuid4(),
                        ),
                    )
                with pytest.raises(psycopg.errors.CheckViolation, match="finite"):
                    connection.execute(
                        """
                        INSERT INTO rag_evaluation_policies (
                            owner_id, dataset_snapshot_id, version,
                            metric_definition_version, retrieval_k,
                            min_recall_at_k, min_mrr, min_ndcg,
                            min_supported_precision, max_false_grounding_rate,
                            min_highlight_iou, max_p50_latency_ms,
                            max_p95_latency_ms, max_access_leaks,
                            required_reproducibility, id
                        ) VALUES (%s, %s, 2, 1, 10, 0.5, 'NaN'::float8,
                                  0.5, 0.8, 0.2, 0.6, 500, 1000, 0, 1.0, %s)
                        """,
                        (owner_id, dataset_id, uuid4()),
                    )
                with pytest.raises(
                    psycopg.errors.RaiseException, match="raw observation"
                ):
                    connection.execute(
                        """
                        INSERT INTO rag_evaluation_case_results (
                            run_configuration_id, dataset_snapshot_id,
                            evaluation_case_id, ordinal, query_sha256,
                            permission_scenario, expected_evidence_ids,
                            raw_observations, duration_ms, recall_at_k,
                            reciprocal_rank, ndcg, correct_supported,
                            false_grounding, highlight_iou, access_leaks,
                            reproducible, id
                        ) SELECT run_configuration_id, dataset_snapshot_id,
                                 evaluation_case_id, ordinal, query_sha256,
                                 permission_scenario, expected_evidence_ids,
                                 '[{},{}]'::jsonb, duration_ms, recall_at_k,
                                 reciprocal_rank, ndcg, correct_supported,
                                 false_grounding, highlight_iou, access_leaks,
                                 reproducible, %s
                            FROM rag_evaluation_case_results
                           WHERE dataset_snapshot_id = %s
                           ORDER BY ordinal LIMIT 1
                        """,
                        (uuid4(), dataset_id),
                    )
                first_result = connection.execute(
                    """
                    SELECT raw_observations, expected_evidence_ids
                      FROM rag_evaluation_case_results
                     WHERE dataset_snapshot_id = %s
                       AND recall_at_k IS NOT NULL
                     ORDER BY ordinal LIMIT 1
                    """,
                    (dataset_id,),
                ).fetchone()
                assert first_result is not None
                missing_rank = json.loads(json.dumps(first_result[0]))
                missing_rank[0]["retrieved_ranked"].pop()
                extra_rank = json.loads(json.dumps(first_result[0]))
                extra_rank[0]["retrieved_ranked"].append(
                    {
                        "rank": len(extra_rank[0]["retrieved_ranked"]) + 1,
                        "evidence_id": extra_rank[0]["retrieved_evidence_ids"][0],
                    }
                )
                malformed_highlight = json.loads(json.dumps(first_result[0]))
                malformed_highlight[0]["highlights"][0]["spans"] = [[9, 1]]
                inconsistent_answer = json.loads(json.dumps(first_result[0]))
                inconsistent_answer[0]["answer_status"] = "insufficient_evidence"
                for malformed_raw in (
                    missing_rank,
                    extra_rank,
                    malformed_highlight,
                    inconsistent_answer,
                ):
                    with pytest.raises(
                        psycopg.errors.RaiseException, match="raw observation"
                    ):
                        connection.execute(
                            """
                            INSERT INTO rag_evaluation_case_results (
                                run_configuration_id, dataset_snapshot_id,
                                evaluation_case_id, ordinal, query_sha256,
                                permission_scenario, expected_evidence_ids,
                                raw_observations, duration_ms, recall_at_k,
                                reciprocal_rank, ndcg, correct_supported,
                                false_grounding, highlight_iou, access_leaks,
                                reproducible, id
                            ) SELECT run_configuration_id, dataset_snapshot_id,
                                     evaluation_case_id, ordinal, query_sha256,
                                     permission_scenario, expected_evidence_ids,
                                     %s::jsonb, duration_ms, recall_at_k,
                                     reciprocal_rank, ndcg, correct_supported,
                                     false_grounding, highlight_iou, access_leaks,
                                     reproducible, %s
                                FROM rag_evaluation_case_results
                               WHERE dataset_snapshot_id = %s
                                 AND recall_at_k IS NOT NULL
                               ORDER BY ordinal LIMIT 1
                            """,
                            (
                                json.dumps(malformed_raw),
                                uuid4(),
                                dataset_id,
                            ),
                        )
                duplicate_raw = json.loads(json.dumps(first_result[0]))
                irrelevant_id = str(uuid4())
                relevant_id = str(first_result[1][0])
                for observation in duplicate_raw:
                    observation["retrieved_evidence_ids"] = [
                        irrelevant_id,
                        irrelevant_id,
                        relevant_id,
                    ]
                    observation["retrieved_ranked"] = [
                        {"rank": 1, "evidence_id": irrelevant_id},
                        {"rank": 2, "evidence_id": irrelevant_id},
                        {"rank": 3, "evidence_id": relevant_id},
                    ]
                    observation["repetition_signature_sha256"] = "c" * 64
                expected_count = len(first_result[1])
                ideal_dcg = sum(
                    1.0 / math.log2(rank + 1)
                    for rank in range(1, min(expected_count, 10) + 1)
                )
                with pytest.raises(psycopg.errors.UniqueViolation):
                    connection.execute(
                        """
                        INSERT INTO rag_evaluation_case_results (
                            run_configuration_id, dataset_snapshot_id,
                            evaluation_case_id, ordinal, query_sha256,
                            permission_scenario, expected_evidence_ids,
                            raw_observations, duration_ms, recall_at_k,
                            reciprocal_rank, ndcg, correct_supported,
                            false_grounding, highlight_iou, access_leaks,
                            reproducible, id
                        ) SELECT run_configuration_id, dataset_snapshot_id,
                                 evaluation_case_id, ordinal, query_sha256,
                                 permission_scenario, expected_evidence_ids,
                                 %s::jsonb, duration_ms, %s, 0.5, %s,
                                 correct_supported, false_grounding,
                                 highlight_iou, access_leaks, reproducible, %s
                            FROM rag_evaluation_case_results
                           WHERE dataset_snapshot_id = %s
                             AND recall_at_k IS NOT NULL
                           ORDER BY ordinal LIMIT 1
                        """,
                        (
                            json.dumps(duplicate_raw),
                            1.0 / expected_count,
                            (1.0 / math.log2(3)) / ideal_dcg,
                            uuid4(),
                            dataset_id,
                        ),
                    )
                forged_raw = first_result[0]
                for observation in forged_raw:
                    observation["retrieved_evidence_ids"] = []
                    observation["retrieved_ranked"] = []
                    observation["repetition_signature_sha256"] = "b" * 64
                with pytest.raises(
                    psycopg.errors.RaiseException, match="derived metrics"
                ):
                    connection.execute(
                        """
                        INSERT INTO rag_evaluation_case_results (
                            run_configuration_id, dataset_snapshot_id,
                            evaluation_case_id, ordinal, query_sha256,
                            permission_scenario, expected_evidence_ids,
                            raw_observations, duration_ms, recall_at_k,
                            reciprocal_rank, ndcg, correct_supported,
                            false_grounding, highlight_iou, access_leaks,
                            reproducible, id
                        ) SELECT run_configuration_id, dataset_snapshot_id,
                                 evaluation_case_id, ordinal, query_sha256,
                                 permission_scenario, expected_evidence_ids,
                                 %s::jsonb, duration_ms, 1.0, 1.0, 1.0,
                                 correct_supported, false_grounding,
                                 highlight_iou, access_leaks, reproducible, %s
                            FROM rag_evaluation_case_results
                           WHERE dataset_snapshot_id = %s
                             AND recall_at_k IS NOT NULL
                           ORDER BY ordinal LIMIT 1
                        """,
                        (json.dumps(forged_raw), uuid4(), dataset_id),
                    )
                with pytest.raises(psycopg.errors.RaiseException, match="terminal"):
                    connection.execute(
                        """
                        UPDATE rag_evaluation_run_configurations
                        SET recall_at_k = 'Infinity'::float8
                        WHERE configuration_version_id = %s
                        """,
                        (BM25_BASELINE_CONFIGURATION_VERSION_ID,),
                    )
                with pytest.raises(psycopg.errors.UniqueViolation):
                    connection.execute(
                        """
                        INSERT INTO rag_evaluation_dataset_cases
                        SELECT * FROM rag_evaluation_dataset_cases
                         WHERE dataset_snapshot_id = %s AND ordinal = 0
                        """,
                        (dataset_id,),
                    )
                with pytest.raises(psycopg.errors.RaiseException, match="invalid"):
                    connection.execute(
                        """
                        INSERT INTO rag_evaluation_dataset_cases (
                            dataset_snapshot_id, ordinal, canonical_case_bytes,
                            canonical_case_sha256, query_bytes, query_sha256,
                            permission_scenario, expected_evidence_ids,
                            authorized_source_ids, forbidden_source_ids,
                            expected_highlight, id, created_at, updated_at
                        ) SELECT dataset_snapshot_id, 99, canonical_case_bytes,
                                 canonical_case_sha256, query_bytes, query_sha256,
                                 permission_scenario, expected_evidence_ids,
                                 authorized_source_ids, forbidden_source_ids,
                                 expected_highlight, %s, now(), now()
                            FROM rag_evaluation_dataset_cases
                           WHERE dataset_snapshot_id = %s AND ordinal = 0
                        """,
                        (uuid4(), dataset_id),
                    )
                with pytest.raises(psycopg.errors.RaiseException, match="immutable"):
                    connection.execute(
                        "DELETE FROM rag_evaluation_dataset_cases "
                        "WHERE dataset_snapshot_id = %s AND ordinal = 0",
                        (dataset_id,),
                    )
                connection.execute(
                    """
                    UPDATE rag_configuration_versions
                    SET evaluation_state = 'passed', is_default = true
                    WHERE id = %s
                    """,
                    (BM25_BASELINE_CONFIGURATION_VERSION_ID,),
                )
                connection.execute(
                    """
                    INSERT INTO rag_configurations (owner_id, name, is_system, id)
                    VALUES (%s, 'caller BGE downgrade fixture', false, %s)
                    """,
                    (owner_id, caller_bge_configuration_id),
                )
                connection.execute(
                    """
                    INSERT INTO rag_answer_policy_versions (
                        configuration_id, version, mode, min_semantic_score,
                        min_keyword_coverage, require_complete_provenance,
                        conflict_mode, id
                    ) VALUES (
                        %s, 1, 'extractive', 0.0, 0.0, true,
                        'separate_sources', %s
                    )
                    """,
                    (caller_bge_configuration_id, caller_bge_policy_id),
                )
                connection.execute(
                    """
                    INSERT INTO rag_configuration_versions (
                        configuration_id, version, indexing_profile_id,
                        retrieval_profile_id, generation_profile_id,
                        answer_policy_version_id, evaluation_state,
                        is_default, id
                    ) VALUES (%s, 1, %s, %s, NULL, %s, 'pending', false, %s)
                    """,
                    (
                        caller_bge_configuration_id,
                        BGE_INDEXING_PROFILE_ID,
                        BGE_RETRIEVAL_PROFILE_ID,
                        caller_bge_policy_id,
                        caller_bge_version_id,
                    ),
                )
                assert connection.execute(
                    """
                    SELECT evaluation_state, is_default
                    FROM rag_configuration_versions WHERE id = %s
                    """,
                    (BM25_BASELINE_CONFIGURATION_VERSION_ID,),
                ).fetchone() == ("passed", True)
                with pytest.raises(psycopg.errors.RaiseException, match="immutable"):
                    connection.execute(
                        "UPDATE rag_evaluation_policies SET min_mrr = 0 WHERE id = %s",
                        (policy_id,),
                    )
            await to_thread(command.downgrade, config, REVISION_0009)
            with psycopg.connect(_sync_url(isolated_url), autocommit=True) as connection:
                evaluation_table = connection.execute(
                    "SELECT to_regclass('rag_evaluation_runs')"
                ).fetchone()
                assert evaluation_table == (None,)
                assert connection.execute(
                    """
                    SELECT evaluation_state, is_default
                    FROM rag_configuration_versions WHERE id = %s
                    """,
                    (BM25_BASELINE_CONFIGURATION_VERSION_ID,),
                ).fetchone() == ("pending", False)
                assert connection.execute(
                    "SELECT count(*) FROM rag_profiles WHERE id IN (%s, %s)",
                    (BGE_INDEXING_PROFILE_ID, BGE_RETRIEVAL_PROFILE_ID),
                ).fetchone() == (2,)
                assert connection.execute(
                    "SELECT count(*) FROM rag_model_definitions WHERE id = %s",
                    (BGE_MODEL_ID,),
                ).fetchone() == (1,)
                assert connection.execute(
                    """
                    SELECT evaluation_state, is_default
                      FROM rag_configuration_versions WHERE id = %s
                    """,
                    (caller_bge_version_id,),
                ).fetchone() == ("pending", False)
                with pytest.raises(psycopg.errors.CheckViolation, match="no_passed"):
                    connection.execute(
                        """
                        UPDATE rag_configuration_versions
                        SET evaluation_state = 'passed'
                        WHERE id = %s
                        """,
                        (BM25_BASELINE_CONFIGURATION_VERSION_ID,),
                    )
            await to_thread(command.upgrade, config, "head")
            await to_thread(command.current, config, check_heads=True)
            await to_thread(command.check, config)
            with psycopg.connect(_sync_url(isolated_url), autocommit=True) as connection:
                assert connection.execute(
                    """
                    SELECT count(*)
                      FROM rag_profile_model_bindings
                     WHERE profile_id = %s AND model_id = %s
                    """,
                    (BGE_INDEXING_PROFILE_ID, BGE_MODEL_ID),
                ).fetchone() == (1,)
                assert connection.execute(
                    "SELECT count(*) FROM rag_configuration_versions WHERE id = %s",
                    (caller_bge_version_id,),
                ).fetchone() == (1,)
    finally:
        get_settings.cache_clear()
        _drop_database(base_settings.database_url, database)
