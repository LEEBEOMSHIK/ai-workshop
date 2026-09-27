"""Require complete rules, reviewer outcomes and consistent proposition normalization."""

# ruff: noqa: E501
from alembic import op

revision = "0057_generative_proof_hardening"
down_revision = "0056_generative_evaluation_gate"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(r"""
    CREATE FUNCTION rag_normalize_proposition(value text) RETURNS text
    LANGUAGE sql IMMUTABLE STRICT AS $$
      SELECT btrim(regexp_replace(translate(normalize(value,NFKC),
        'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'), E'[ \t\r\n\f\v]+',' ','g'))
    $$;
""")
    op.execute(r"""
    CREATE OR REPLACE FUNCTION rag_verify_generative_candidate(run_uuid uuid, version_uuid uuid)
    RETURNS jsonb LANGUAGE plpgsql AS $$
    DECLARE
      r rag_generative_runs; p rag_generative_policies; v rag_configuration_versions;
      a rag_generative_attempts; c rag_evaluation_dataset_cases;
      component jsonb; rule jsonb; observation jsonb; group_value jsonb; evidence text;
      expected_count integer; actual_count integer:=0; positives integer:=0; negatives integer:=0;
      correct integer:=0; abstained integer:=0; covered float8:=0;
      groups integer; matched integer; content_ok boolean; judgment_status text;
      answer_text text; latencies float8[]:='{}'; p95 float8; candidate_metrics jsonb;
    BEGIN
      SELECT * INTO STRICT r FROM rag_generative_runs WHERE id=run_uuid;
      SELECT * INTO STRICT p FROM rag_generative_policies WHERE id=r.policy_id;
      SELECT * INTO STRICT v FROM rag_configuration_versions WHERE id=version_uuid;
      IF r.status<>'completed' OR r.metric_version<>'generative-v1' OR p.owner_id<>r.owner_id
        OR v.generation_profile_id IS NULL THEN
        RAISE EXCEPTION 'generative acceptance requires a complete exact run';
      END IF;
      IF (p.definition->>'version')::integer IS NULL
        OR p.definition->>'require_valid_citations' IS DISTINCT FROM 'true'
        OR p.definition->>'max_access_leaks' IS DISTINCT FROM '0'
        OR rag_evaluation_is_nonnegative_finite_float(p.definition->'min_context_coverage') IS DISTINCT FROM true
        OR rag_evaluation_is_nonnegative_finite_float(p.definition->'min_correctness') IS DISTINCT FROM true
        OR rag_evaluation_is_nonnegative_finite_float(p.definition->'min_abstention') IS DISTINCT FROM true
        OR rag_evaluation_is_nonnegative_finite_float(p.definition->'max_p95_latency_ms') IS DISTINCT FROM true
        OR (p.definition->>'min_context_coverage')::float8>1
        OR (p.definition->>'min_correctness')::float8>1
        OR (p.definition->>'min_abstention')::float8>1 THEN
        RAISE EXCEPTION 'invalid immutable generative acceptance policy';
      END IF;
      IF r.rules_digest<>encode(sha256(convert_to(rag_generative_canonical(r.expected_rules),'UTF8')),'hex') THEN
        RAISE EXCEPTION 'expected rule digest mismatch';
      END IF;
      SELECT entry->'component_snapshot' INTO component
        FROM jsonb_array_elements(r.snapshot->'candidates') entry
        WHERE entry->>'configuration_version_id'=version_uuid::text;
      IF component IS NULL OR component->'configuration'->>'version_id'<>version_uuid::text
        OR NOT EXISTS(SELECT 1 FROM jsonb_array_elements(component->'profiles') profile
          WHERE profile->>'id'=v.generation_profile_id::text AND profile->>'kind'='generation')
        OR NOT EXISTS(SELECT 1 FROM jsonb_array_elements(component->'profiles') profile
          WHERE profile->>'id'=v.indexing_profile_id::text)
        OR NOT EXISTS(SELECT 1 FROM jsonb_array_elements(component->'profiles') profile
          WHERE profile->>'id'=v.retrieval_profile_id::text)
        OR component->'answer_policy'->>'id'<>v.answer_policy_version_id::text THEN
        RAISE EXCEPTION 'generative profile binding mismatch';
      END IF;
      SELECT count(*)*r.repetition_count INTO expected_count FROM rag_evaluation_dataset_cases
        WHERE dataset_snapshot_id=r.dataset_snapshot_id;
      FOR a IN SELECT DISTINCT ON (case_id,repetition) * FROM rag_generative_attempts
        WHERE run_id=r.id AND configuration_version_id=v.id
        ORDER BY case_id,repetition,attempt_number DESC
      LOOP
        actual_count:=actual_count+1;
        SELECT * INTO STRICT c FROM rag_evaluation_dataset_cases
          WHERE dataset_snapshot_id=r.dataset_snapshot_id AND id=a.case_id;
        rule:=r.expected_rules->a.case_id::text;
        observation:=a.result->'observation';
        IF a.status<>'completed' OR rule IS NULL OR coalesce((rule->>'version')::integer,0)<1
          OR observation IS NULL OR observation->>'generation_status' IS NULL
          OR observation->>'generation_status' NOT IN ('answered','insufficient_evidence')
          OR observation->>'failure_stage' IS NOT NULL OR observation->>'error_code' IS NOT NULL
          OR observation->>'execution_id' IS DISTINCT FROM a.execution_id::text
          OR NOT EXISTS(SELECT 1 FROM rag_executions x WHERE x.id=a.execution_id
            AND x.evaluation_attempt_id=a.id AND x.actor_id=r.owner_id AND x.status='completed')
          OR jsonb_typeof(observation->'access_exposures') IS DISTINCT FROM 'array'
          OR jsonb_typeof(observation->'retrieved_evidence_ids') IS DISTINCT FROM 'array'
          OR jsonb_typeof(observation->'selected_evidence_ids') IS DISTINCT FROM 'array'
          OR jsonb_typeof(observation->'cited_evidence_ids') IS DISTINCT FROM 'array'
          OR jsonb_array_length(observation->'access_exposures')<>0
          OR rag_evaluation_is_nonnegative_finite_float(observation->'duration_ms') IS DISTINCT FROM true THEN
          RAISE EXCEPTION 'incomplete or invalid raw generative observation';
        END IF;
        IF NOT EXISTS(SELECT 1 FROM rag_generation_execution_audits audit
          WHERE audit.execution_id=a.execution_id AND audit.actor_id=r.owner_id
            AND audit.configuration_version_id=v.id AND audit.generation_profile_id=v.generation_profile_id
            AND audit.policy_allowed AND audit.status=CASE
              WHEN observation->>'generation_status'='answered' THEN 'succeeded' ELSE 'allowed' END
            AND to_jsonb(audit.evidence_ids) @> (observation->'selected_evidence_ids')
            AND (observation->'selected_evidence_ids') @> to_jsonb(audit.evidence_ids)) THEN
          RAISE EXCEPTION 'matching authorized generation audit is required';
        END IF;
        FOR evidence IN SELECT jsonb_array_elements_text(
            (observation->'retrieved_evidence_ids')||(observation->'selected_evidence_ids')||(observation->'cited_evidence_ids'))
        LOOP
          IF NOT c.authorized_source_ids::jsonb ? evidence OR c.forbidden_source_ids::jsonb ? evidence
            OR NOT EXISTS(SELECT 1 FROM jsonb_array_elements(r.snapshot->'sources') source,
                jsonb_array_elements(source->'evidence_units') unit,
                jsonb_array_elements(component->'index_builds') build
              WHERE unit->>'id'=evidence AND source->>'index_build_id'=build->>'index_build_id') THEN
            RAISE EXCEPTION 'generative evidence outside authorized snapshot';
          END IF;
        END LOOP;
        IF observation->>'generation_status'='answered' AND (
          observation->>'citation_valid' IS DISTINCT FROM 'true'
          OR jsonb_array_length(observation->'cited_evidence_ids')=0
          OR NOT (observation->'selected_evidence_ids') @> (observation->'cited_evidence_ids')) THEN
          RAISE EXCEPTION 'generative citation validation failed';
        END IF;
        IF rule->>'expected_answer_status' IS DISTINCT FROM (CASE WHEN convert_from(c.canonical_case_bytes,'UTF8')::jsonb->>'expected_answer_status'='supported' THEN 'answered' ELSE 'insufficient_evidence' END)
          OR rule->>'expected_answer_status' NOT IN ('answered','insufficient_evidence') THEN
          RAISE EXCEPTION 'unknown expected rule status';
        END IF;
          judgment_status:=NULL;
          SELECT j.status INTO judgment_status FROM rag_generative_judgments j JOIN users u ON u.id=j.reviewer_id
            WHERE j.attempt_id=a.id AND j.result_digest=a.result_digest AND j.reviewer_id=r.owner_id
              AND u.role='owner' AND j.rule_digest=encode(sha256(convert_to(
                rag_generative_canonical(rule),'UTF8')),'hex')
            ORDER BY j.created_at DESC,j.id DESC LIMIT 1;
        IF rule->>'expected_answer_status'='insufficient_evidence' THEN
          negatives:=negatives+1;
          IF observation->>'generation_status'='insufficient_evidence' THEN
            abstained:=abstained+1;
            IF judgment_status IS NULL OR judgment_status='passed' THEN correct:=correct+1;
            ELSIF judgment_status='unreviewed' THEN RAISE EXCEPTION 'unreviewed content'; END IF;
          END IF;
        ELSE
          positives:=positives+1;
          groups:=jsonb_array_length(rule->'required_evidence_groups'); matched:=0;
          IF groups IS NULL OR groups=0 THEN RAISE EXCEPTION 'positive case requires evidence'; END IF;
          FOR group_value IN SELECT * FROM jsonb_array_elements(rule->'required_evidence_groups') LOOP
            IF jsonb_array_length(group_value)=0 OR NOT c.expected_evidence_ids::jsonb @> group_value THEN
              RAISE EXCEPTION 'expected rule evidence mismatch';
            END IF;
            IF EXISTS(SELECT 1 FROM jsonb_array_elements_text(group_value) e
              WHERE observation->'selected_evidence_ids' ? e) THEN matched:=matched+1; END IF;
          END LOOP;
          covered:=covered+matched::float8/groups;
          answer_text:=rag_normalize_proposition(coalesce(a.result->>'answer',''));
          IF judgment_status IS NULL THEN
            content_ok:=jsonb_array_length(rule->'required_propositions')>0;
            FOR evidence IN SELECT jsonb_array_elements_text(rule->'required_propositions') LOOP
              content_ok:=content_ok AND position(rag_normalize_proposition(evidence) IN answer_text)>0;
            END LOOP;
            FOR evidence IN SELECT jsonb_array_elements_text(rule->'forbidden_propositions') LOOP
              content_ok:=content_ok AND position(rag_normalize_proposition(evidence) IN answer_text)=0;
            END LOOP;
            IF jsonb_array_length(rule->'required_propositions')=0 THEN
              RAISE EXCEPTION 'unreviewed generative content cannot qualify';
            END IF;
          ELSE
            IF judgment_status='unreviewed' THEN RAISE EXCEPTION 'unreviewed content'; END IF;
            content_ok:=judgment_status='passed';
          END IF;
          IF content_ok AND observation->>'generation_status'='answered' THEN correct:=correct+1; END IF;
        END IF;
        latencies:=array_append(latencies,(observation->>'duration_ms')::float8);
      END LOOP;
      IF actual_count<>expected_count OR positives=0 OR negatives=0 THEN
        RAISE EXCEPTION 'complete positive and negative repetitions are required';
      END IF;
      SELECT percentile_cont(0.95) WITHIN GROUP (ORDER BY duration) INTO p95 FROM unnest(latencies) duration;
      IF covered/positives < (p.definition->>'min_context_coverage')::float8
        OR correct::float8/actual_count < (p.definition->>'min_correctness')::float8
        OR abstained::float8/negatives < (p.definition->>'min_abstention')::float8
        OR p95 > (p.definition->>'max_p95_latency_ms')::float8 THEN
        RAISE EXCEPTION 'generative acceptance policy failed';
      END IF;
      candidate_metrics:=jsonb_build_object('metric_version','generative-v1',
        'context_coverage',covered/positives,'context_count',positives,
        'correctness',correct::float8/actual_count,'correctness_count',actual_count,
        'abstention',abstained::float8/negatives,'abstention_count',negatives,
        'p95_ms',p95,'duration_count',actual_count,'duration_missing',0,'access_leaks',0);
      RETURN candidate_metrics;
    END $$;
    """)


def downgrade() -> None:
    raise RuntimeError("Proof validation rollback requires explicit review.")
